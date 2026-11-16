"""Harbor 0.25 lifecycle bridge to this bench's self-contained HPC support."""
from __future__ import annotations
import asyncio
import json
from pathlib import Path
import re
import shlex
import subprocess
import threading
import time
import tomllib
from types import SimpleNamespace
import uuid

from harbor.environments.docker.docker import DockerEnvironment
from harbor.models.job.plugin import BaseJobPlugin
from harbor.trial.hooks import TrialEvent
from bench03_hpc import collector as core
from bench03_hpc.artifacts import export_declared_artifacts

_STATES = {}
_LOCK = threading.RLock()


def support_hashes():
    return {p.name: core.digest(p) for p in sorted((Path(__file__).parent / 'bench03_hpc').glob('*.py'))}


def active(path):
    path = Path(path).resolve()
    if path != Path(__file__).resolve().parents[2]:
        return False
    meta = tomllib.loads((path / 'task.toml').read_text())
    identity = meta.get('metadata', {})
    return identity.get('case_id') == 'case-05' and identity.get('revision') == 5


def tree_hashes(root):
    if root.is_symlink() or not root.is_dir():
        raise RuntimeError('Candidate artifact directory is absent or redirected')
    result = {}
    for path in root.rglob('*'):
        if path.is_symlink() or not (path.is_dir() or path.is_file()):
            raise RuntimeError('Candidate artifacts contain a link or special file')
        if path.is_file():
            result[path.relative_to(root).as_posix()] = core.digest(path)
    return result


class TrustedTransport:
    """Runner-owned SSH transport bound to one immutable-image helper."""
    def __init__(self, container_id: str, image_id: str):
        if not re.fullmatch(r'[0-9a-f]{64}', image_id.removeprefix('sha256:')):
            raise RuntimeError('Trusted helper image is not immutable')
        self.container_id = container_id
        self.image_id = image_id

    def command(self, remote_argv):
        return ['docker', 'exec', '-i', self.container_id, 'ssh', '-o', 'BatchMode=yes',
                '-o', 'ConnectTimeout=15', 'ikkem', shlex.join(remote_argv)]


def start_trusted_helper(image_id: str, name: str):
    if not re.fullmatch(r'sha256:[0-9a-f]{64}', image_id):
        raise RuntimeError('Candidate image is not immutable')
    try:
        result = subprocess.run(
            ['docker', 'run', '-d', '--name', name, '--entrypoint', 'sleep', image_id, 'infinity'],
            capture_output=True, text=True, check=True, timeout=30)
    except BaseException as exc:
        try:
            remove_trusted_helper(name, check=True)
        except BaseException as cleanup_error:
            exc.add_note('Trusted SSH helper startup cleanup failed: ' + type(cleanup_error).__name__)
        raise
    container_id = result.stdout.strip()
    if not container_id:
        exc = RuntimeError('Trusted SSH helper did not return a container ID')
        try:
            remove_trusted_helper(name, check=True)
        except BaseException as cleanup_error:
            exc.add_note('Trusted SSH helper startup cleanup failed: ' + type(cleanup_error).__name__)
        raise exc
    return TrustedTransport(container_id, image_id)


def remove_trusted_helper(container_id: str | None, *, check=False):
    if not container_id:
        return
    result = subprocess.run(['docker', 'rm', '-f', container_id], capture_output=True,
                            text=True, timeout=30)
    if check and result.returncode:
        raise RuntimeError('Trusted SSH helper cleanup failed')


def quiesce_program(baseline):
    # Preserve both Harbor's PID1 shell and its original keepalive child. Match
    # kernel start times too, so PID reuse cannot exempt a new candidate process.
    return ("import os,signal,time,json\nkeep=json.loads(" + repr(json.dumps(baseline)) + ")\nme=os.getpid()\n"
            "for _ in range(3):\n for p in os.listdir('/proc'):\n"
            "  if not p.isdigit() or int(p)==me: continue\n"
            "  try:\n   started=open('/proc/'+p+'/stat').read().rsplit(') ',1)[1].split()[19]\n"
            "   if keep.get(p)==started: continue\n   os.kill(int(p),signal.SIGKILL)\n"
            "  except ProcessLookupError: pass\n  except FileNotFoundError: pass\n time.sleep(.1)\n")


class Bench03DockerEnvironment(DockerEnvironment):
    def __init__(self, *args, **kwargs):
        if kwargs.get('task_env_config') is not None:
            kwargs['task_env_config'] = kwargs['task_env_config'].model_copy(deep=True)
        super().__init__(*args, **kwargs)
        self.task_path = self.environment_dir.resolve().parent
        self.case05 = active(self.task_path)
        self.key = str(self.trial_paths.trial_dir.resolve())
        self.is_verifier = '__verifier__' in self.session_id
        self.cid = None
        self.helper_id = None
        self.transport = None
        if self.case05:
            with _LOCK:
                self.state = _STATES.setdefault(self.key, {})
                self.state['verifier_env' if self.is_verifier else 'agent_env'] = self

    def mounts(self, rows):
        for source, destination in rows:
            source = Path(source)
            if source.is_symlink() or not source.exists():
                raise RuntimeError('Trusted runtime mount missing or redirected')
            self._host_mounts.append({'type': 'bind', 'source': str(source.resolve()),
                                      'target': destination, 'read_only': True})

    async def main_container(self):
        if self._uses_compose:
            result = await self._run_docker_compose_command(['ps', '-q', 'main'])
            ids = result.stdout.strip().splitlines()
        else:
            from harbor.environments.docker.docker import _sanitize_docker_compose_project_name
            result = await asyncio.to_thread(subprocess.run,
                [*type(self)._engine_cmd('ps', '--filter', 'label=com.docker.compose.project='
                  + _sanitize_docker_compose_project_name(self.session_id), '--filter',
                  'label=com.docker.compose.service=main', '--format', '{{.ID}}')],
                capture_output=True, text=True, check=True, timeout=20)
            ids = result.stdout.strip().splitlines()
        if len(ids) != 1:
            raise RuntimeError('Expected exactly one owned Harbor main container')
        return ids[0]

    async def start(self, force_build=False):
        if not self.case05:
            return await super().start(force_build)
        state = self.state
        if state.get('mode') not in ('agent', 'oracle'):
            raise RuntimeError('Bench03 Harbor lifecycle plugin was not loaded')
        if self.is_verifier:
            if not state.get('sealed'):
                raise RuntimeError('Independent HPC evidence was not sealed before verification')
            if state.get('blockage'):
                raise RuntimeError('HPC infrastructure prevents scoring: ' + state['blockage'])
            if any(core.digest(self.task_path / name) != value for name, value in state['contract'].items()):
                raise RuntimeError('Scientific contract changed after evidence sealing')
            if core.digest(self.task_path / 'task.toml') != state['binding']['task_config_sha256']:
                raise RuntimeError('Task definition changed after evidence sealing')
            self.mounts([(state['context'], '/trusted/runner-context.json'),
                         (state['evidence'], '/trusted/remote-evidence')])
            # Candidate SSH mounts are never carried into the separate verifier.
            return await super().start(force_build)
        attempt = uuid.uuid4().hex
        helper_name = 'ccb05-trusted-' + attempt[:12]
        state['contract'] = {name: core.digest(self.task_path / name) for name in ('task.toml', 'instruction.md', 'tests/test.sh', 'tests/verify.py', 'tests/refs.json', 'tests/Dockerfile', 'environment/Dockerfile')}
        state.update(runtime_sha=core.digest(Path(__file__)), core_sha=core.digest(Path(core.__file__)), support_sha=support_hashes(), attempt=attempt,
                     source_task_sha256=core.digest(self.task_path / 'task.toml'))
        try:
            await super().start(force_build)
            self.cid = await self.main_container()
            observed = await asyncio.to_thread(subprocess.run,
                ['docker', 'inspect', '--format', '{{.Image}}', self.cid],
                capture_output=True, text=True, check=True, timeout=20)
            image_id = observed.stdout.strip()
            if not re.fullmatch(r'sha256:[0-9a-f]{64}', image_id):
                raise RuntimeError('Candidate image is not immutable')
            self.transport = await asyncio.to_thread(start_trusted_helper, image_id, helper_name)
            self.helper_id = self.transport.container_id
            site = json.loads(await asyncio.to_thread(core.remote, core.SITE_SCRIPT, transport=self.transport))
            remote_root = site['home'] + '/compchembench/bench03/task18/runs/' + attempt
            prefix = 'ccb05-' + attempt[:12] + '-'
            await asyncio.to_thread(core.remote,
                "from pathlib import Path\nimport sys\np=Path(sys.argv[1])\nfor q in [p,*p.parents]:\n if q.is_symlink(): raise RuntimeError('symlink in attempt root')\np.mkdir(parents=True,exist_ok=False)\n", (remote_root,), transport=self.transport)
            state.update(image=image_id, site=site, root=remote_root, prefix=prefix)
            self._persistent_env.update(CCB_HPC_SSH_TARGET='ikkem', CCB_HPC_REMOTE_ATTEMPT_ROOT=remote_root,
                CCB_HPC_JOB_NAME_PREFIX=prefix, CCB_HPC_ACCOUNT=site['account'], CCB_HPC_PARTITION=site['partition'],
                SSH_AUTH_SOCK='', SSH_AGENT_PID='')
            connected = await self.exec('ssh ikkem true', timeout_sec=45)
            if connected.return_code:
                raise RuntimeError('Candidate image SSH preflight failed; no agent should be charged')
            prepared = await self.exec('mkdir -p /app/final && chmod 1777 /app/final', timeout_sec=15)
            if prepared.return_code:
                raise RuntimeError('Cannot prepare candidate artifact directory')
            baseline_code = "import os,json\nme=os.getpid();rows={}\nfor p in os.listdir('/proc'):\n if p.isdigit() and int(p)!=me:\n  try: rows[p]=open('/proc/'+p+'/stat').read().rsplit(') ',1)[1].split()[19]\n  except FileNotFoundError: pass\nprint(json.dumps(rows))\n"
            baseline = await asyncio.to_thread(subprocess.run,
                ['docker', 'exec', self.cid, 'python3', '-I', '-B', '-c', baseline_code],
                capture_output=True, text=True, timeout=20, check=True)
            state['baseline_pids'] = json.loads(baseline.stdout)
            core.write_json(self.trial_paths.trial_dir / 'bench03-baseline-pids.json', state['baseline_pids'])
            state['begin'] = time.time()
        except BaseException as exc:
            helper_start_cleanup_failed = any('Trusted SSH helper startup cleanup failed:' in note
                                              for note in getattr(exc, '__notes__', ()))
            if self.helper_id or helper_start_cleanup_failed:
                try:
                    await asyncio.to_thread(remove_trusted_helper, self.helper_id or helper_name, check=True)
                except BaseException as cleanup_error:
                    self.helper_id = self.helper_id or helper_name
                    exc.add_note('Trusted SSH helper startup cleanup failed: ' + type(cleanup_error).__name__)
                else:
                    self.helper_id = None
                    self.transport = None
            try:
                await super().stop(delete=True)
            except BaseException as cleanup_error:
                exc.add_note('Candidate container startup cleanup failed: ' + type(cleanup_error).__name__)
            raise

    async def agent_ended(self):
        if not self.case05 or self.is_verifier or self.state.get('ended'):
            return
        if self.cid is None or 'begin' not in self.state:
            raise RuntimeError('Agent-end hook lacks candidate container/start binding')
        self.state['end'] = time.time()
        # Freeze candidate descendants in this owned PID namespace before exporting artifacts.
        quiesce = quiesce_program(self.state['baseline_pids'])
        result = await asyncio.to_thread(subprocess.run,
            ['docker', 'exec', self.cid, 'python3', '-c', quiesce],
            capture_output=True, timeout=20)
        if result.returncode:
            raise RuntimeError('Could not quiesce the owned candidate container')
        self.state['ended'] = True

    def seal(self):
        state = self.state
        if state.get('sealed'):
            return
        if (core.digest(Path(__file__)) != state['runtime_sha'] or core.digest(Path(core.__file__)) != state['core_sha']
                or support_hashes() != state['support_sha']):
            raise RuntimeError('Host evidence collector code changed during this attempt')
        if any(core.digest(self.task_path / name) != value for name, value in state.get('contract', {}).items()):
            raise RuntimeError('Scientific task/verifier contract changed during this attempt')
        if core.digest(self.task_path / 'task.toml') != state['source_task_sha256']:
            raise RuntimeError('Task changed during the candidate attempt')
        run = self.trial_paths.trial_dir
        workspace = run / 'bench03-workspace'
        rows = export_declared_artifacts(self.cid, [('/app/final', 'final')], workspace,
                    max_file_bytes=core.LIMIT, max_total_bytes=core.LIMIT, timeout=120)
        exported = tree_hashes(workspace / 'final')
        copied = tree_hashes(self.trial_paths.artifacts_dir / 'app/final')
        if exported != copied:
            raise RuntimeError('Harbor artifact copy differs from independently frozen candidate output')
        core.write_json(run / 'bench03-artifact-manifest.json', rows)
        core.write_json(run / 'bench03-runtime-binding.json', {'driver_sha256': state['runtime_sha'], 'core_sha256': state['core_sha'], 'support_sha256': state['support_sha'], 'contract': state.get('contract', {})})
        context, evidence, binding = core.seal(SimpleNamespace(path=self.task_path), run,
            state['image'], state['attempt'], state['root'], state['prefix'], state['site'],
            state['begin'], state['end'], rows, transport=self.transport)
        snapshot = json.loads((run / 'bench03-host/scheduler-before-cleanup.json').read_text())
        manifest = json.loads((evidence / 'manifest.json').read_text())
        state.update(context=context, evidence=evidence, binding=binding, sealed=True,
                     blockage=core.environment_blockage(snapshot, manifest))

    async def stop(self, delete=False):
        if not self.case05 or self.is_verifier:
            return await super().stop(delete)
        failure = None
        try:
            if self.cid and 'begin' in self.state:
                await self.agent_ended()
                await asyncio.to_thread(self.seal)
        except BaseException as exc:
            failure = exc
            if ('begin' in self.state and not self.state.get('sealed')
                    and self.transport is not None and 'site' in self.state):
                host = self.trial_paths.trial_dir / 'bench03-host'; host.mkdir(exist_ok=True)
                try:
                    await asyncio.to_thread(core.close_jobs, self.state['root'], self.state['prefix'],
                        self.state['site'], self.state['begin'], self.state.get('end', time.time()), host,
                        transport=self.transport)
                except Exception as cleanup_error:
                    failure.add_note('Owned HPC namespace cleanup failed: ' + type(cleanup_error).__name__)
        finally:
            try:
                await asyncio.to_thread(remove_trusted_helper, self.helper_id, check=True)
            except BaseException as exc:
                if failure is None: failure = exc
                else: failure.add_note('Trusted SSH helper cleanup failed: ' + type(exc).__name__)
            else:
                self.helper_id = None
                self.transport = None
        try:
            await super().stop(delete)
        except BaseException as exc:
            if failure is None: failure = exc
            else: failure.add_note('Harbor container cleanup also failed: ' + type(exc).__name__)
        if failure is not None:
            raise failure


class Bench03SlurmPlugin(BaseJobPlugin):
    async def on_job_start(self, job):
        def state(event):
            key = str((Path(event.config.trials_dir) / event.config.trial_name).resolve())
            with _LOCK: return _STATES.get(key)
        async def environment_start(event):
            current = state(event)
            if current is not None:
                name = getattr(event.config.agent.name, 'value', event.config.agent.name)
                current['mode'] = 'oracle' if name == 'oracle' else 'agent'
        async def agent_end(event):
            current = state(event)
            if current is not None:
                await current['agent_env'].agent_ended()
        job.add_hook(TrialEvent.ENVIRONMENT_START, environment_start)
        job.add_hook(TrialEvent.AGENT_END, agent_end)

    async def on_job_end(self, job_result):
        return None
