FROM compchembench-connectivity:hpc

WORKDIR /app

# Keep the task grader on its existing NumPy 1.26 ABI. Calphy 2.1.2 runs in a
# separate interpreter because it requires NumPy >= 2.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       build-essential cmake ninja-build python3.12-dev python3.12-venv \
    && rm -rf /var/lib/apt/lists/* \
    && python3.12 -m venv /opt/si-ox-runtime \
    && python3.12 -m venv /opt/si-ox-author-runtime

COPY assets/runtime-source/ /tmp/runtime-source/

# Verify all frozen software sources before installing the wheel or building.
RUN printf '%s\n' \
        '75a9fb55d3c10f44cbc7b30313351ce9b12ab3003c1400147fa3590b6d651c73  /tmp/runtime-source/lammps-stable_29Aug2024_update3.tar.gz' \
        'edeb6017b9076460a0badebeff5695a533b795a4028d019f764e57ca9eff88fa  /tmp/runtime-source/lammps-user-pace-v.2023.11.25.fix.tar.gz' \
        '778558c99d29c8299c987efd61d004f67a016f96f520879ae82429519e2e86bb  /tmp/runtime-source/calphy-2.1.2-py3-none-any.whl' \
        'f4b784e53374ab92a128e66c778be5732daf0f08d1c02923540da618cb6d50de  /tmp/runtime-source/calphy-requirements.txt' \
        '36466d6b78da6bf5bc2a25a282582b45decd8b1b626e468e55d13b759b4a4111  /tmp/runtime-source/pyscal3-3.3.2.tar.gz' \
        | sha256sum -c -

RUN /opt/si-ox-runtime/bin/python -m pip install --no-cache-dir \
        pip==24.3.1 setuptools==75.6.0 wheel==0.45.1 \
    && /opt/si-ox-runtime/bin/python -m pip install --no-cache-dir \
        numpy==1.26.4 scipy==1.14.1 PyYAML==6.0.2 \
    && /opt/si-ox-runtime/bin/python -c 'import numpy, scipy, yaml; assert numpy.__version__ == "1.26.4"; print("grader runtime", numpy.__version__, scipy.__version__, yaml.__version__)' \
    && /opt/si-ox-author-runtime/bin/python -m pip install --no-cache-dir \
        pip==24.3.1 setuptools==75.6.0 wheel==0.45.1 \
    && /opt/si-ox-author-runtime/bin/python -m pip install --no-cache-dir \
        -r /tmp/runtime-source/calphy-requirements.txt \
    && /opt/si-ox-author-runtime/bin/python -m pip install --no-cache-dir --no-deps \
        /tmp/runtime-source/calphy-2.1.2-py3-none-any.whl \
    && /opt/si-ox-author-runtime/bin/python -m pip install --no-cache-dir --no-build-isolation \
        /tmp/runtime-source/pyscal3-3.3.2.tar.gz \
    && /opt/si-ox-author-runtime/bin/python -m pip check

RUN mkdir -p /tmp/lammps-source /tmp/libpace-source \
    && tar -xzf /tmp/runtime-source/lammps-stable_29Aug2024_update3.tar.gz -C /tmp/lammps-source --strip-components=1 \
    && tar -xzf /tmp/runtime-source/lammps-user-pace-v.2023.11.25.fix.tar.gz -C /tmp/libpace-source --strip-components=1 \
    && cmake -S /tmp/lammps-source/cmake -B /tmp/lammps-build -G Ninja \
        -D CMAKE_BUILD_TYPE=Release \
        -D CMAKE_CXX_STANDARD=17 \
        -D CMAKE_INSTALL_PREFIX=/opt/lammps-29Aug2024-update3 \
        -D LAMMPS_INSTALL_RPATH=ON \
        -D BUILD_MPI=OFF \
        -D BUILD_OMP=OFF \
        -D PKG_KOKKOS=ON \
        -D Kokkos_ENABLE_SERIAL=ON \
        -D Kokkos_ENABLE_OPENMP=OFF \
        -D PKG_ML-PACE=ON \
        -D PKG_EXTRA-FIX=ON \
        -D LOCAL_ML-PACE=/tmp/libpace-source \
    && cmake --build /tmp/lammps-build --parallel 2 \
    && cmake --install /tmp/lammps-build \
    && rm -rf /tmp/lammps-source /tmp/libpace-source /tmp/lammps-build

ENV PATH="/opt/lammps-29Aug2024-update3/bin:/opt/si-ox-runtime/bin:${PATH}"
ENV CASE159_AUTHOR_PYTHON=/opt/si-ox-author-runtime/bin/python
ENV CASE159_CALPHY=/opt/si-ox-author-runtime/bin/calphy
ENV CALPHY_LAMMPS_EXECUTABLE=/opt/lammps-29Aug2024-update3/bin/lmp

# Keep only the task's public runtime inputs in the grader-visible input tree.
COPY assets/candidate-runtime/ /app/inputs/candidate-runtime/
COPY assets/phase_diagram/ /app/inputs/phase_diagram/
COPY assets/potential-ded3972eed38/ /app/inputs/potential-ded3972eed38/

# Build-time checks are software/import/capability checks only; they do not run
# any LAMMPS input, MD, or scientific calculation.
RUN /opt/si-ox-author-runtime/bin/python - <<'PY'
import subprocess
import numpy
import scipy
import yaml
import calphy
from calphy.input import Calculation
from calphy.solid import Solid
from pyscal3 import System
from pyscal3.core import _make_crystal, element_dict, structure_dict
from pyscal3.trajectory import Trajectory

assert calphy.__version__ == "2.1.2", calphy.__version__
assert numpy.__version__ == "2.2.6", numpy.__version__
help_text = subprocess.run(
    ["/opt/lammps-29Aug2024-update3/bin/lmp", "-h"],
    check=True, capture_output=True, text=True,
).stdout
tokens = set(help_text.split())
required = {"pace/kk", "ti/spring"}
missing = sorted(required - tokens)
if missing:
    raise SystemExit(f"LAMMPS capability check missing styles: {missing}")
print({
    "calphy": calphy.__version__,
    "calphy_imports": [Calculation.__name__, Solid.__name__],
    "pyscal3_imports": [System.__name__, Trajectory.__name__, len(element_dict), len(structure_dict), _make_crystal.__name__],
    "numpy": numpy.__version__,
    "scipy": scipy.__version__,
    "pyyaml": yaml.__version__,
    "lammps_version": next((line.strip() for line in help_text.splitlines() if "LAMMPS" in line), "unknown"),
    "required_styles": sorted(required),
})
PY

# Preserve a root-owned record of the author-only CPU build and installed
# runtime. The verifier checks this against refs.json and the live executables.
RUN /opt/si-ox-author-runtime/bin/python - <<'PY'
import hashlib, importlib.metadata, json, os, sys
from pathlib import Path
import calphy

source_root = Path('/tmp/runtime-source')
lock_path = source_root / 'source-locks.json'
lock = json.loads(lock_path.read_text())
sources = {row['path']: row['sha256'] for row in lock['sources']}
sources[lock['calphy_python_dependencies']['path']] = lock['calphy_python_dependencies']['sha256']
flags = [
    'CMAKE_BUILD_TYPE=Release', 'CMAKE_CXX_STANDARD=17',
    'CMAKE_INSTALL_PREFIX=/opt/lammps-29Aug2024-update3', 'LAMMPS_INSTALL_RPATH=ON',
    'BUILD_MPI=OFF', 'BUILD_OMP=OFF', 'PKG_KOKKOS=ON', 'Kokkos_ENABLE_SERIAL=ON',
    'Kokkos_ENABLE_OPENMP=OFF', 'PKG_ML-PACE=ON', 'PKG_EXTRA-FIX=ON',
    'LOCAL_ML-PACE=/tmp/libpace-source',
]
buildspec = {
    'schema': 'case06-author-cpu-build-spec/v1',
    'source_locks_sha256': hashlib.sha256(lock_path.read_bytes()).hexdigest(),
    'sources': sources,
    'cmake_flags': flags,
}
def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
calphy_root = Path(calphy.__file__).resolve().parent
calphy_sources = {
    path.relative_to(calphy_root.parent).as_posix(): sha(path)
    for path in sorted(calphy_root.rglob('*.py'))
}
lmp = Path('/opt/lammps-29Aug2024-update3/bin/lmp')
author_python = Path('/opt/si-ox-author-runtime/bin/python')
python_real = author_python.resolve(strict=True)
manifest = {
    'schema': 'case06-author-runtime-manifest/v1',
    'buildspec': buildspec,
    'actual': {
        'lmp_path': str(lmp), 'lmp_sha256': sha(lmp),
        'author_python_path': str(author_python), 'author_python_realpath': str(python_real),
        'author_python_sha256': sha(python_real), 'author_python_version': sys.version.split()[0],
        'author_python_prefix': sys.prefix, 'calphy_version': importlib.metadata.version('calphy'),
        'calphy_python_sources': calphy_sources,
    },
}
target = Path('/opt/bench24-159/author-runtime-manifest.json')
target.parent.mkdir(parents=True, exist_ok=True)
target.write_text(json.dumps(manifest, sort_keys=True, separators=(',', ':')) + '\n')
os.chown(target, 0, 0); os.chmod(target, 0o444)
print({'schema': manifest['schema'], 'source_count': len(sources),
       'calphy_source_count': len(calphy_sources), 'lmp_sha256': manifest['actual']['lmp_sha256'],
       'python_version': manifest['actual']['author_python_version']})
PY

RUN /opt/si-ox-runtime/bin/python - <<'PY'
import numpy, scipy, yaml
assert numpy.__version__ == "1.26.4", numpy.__version__
print("grader ABI retained", numpy.__version__, scipy.__version__, yaml.__version__)
PY

# Verify that the image helper interpreter can import its CLI without
# probing a host, reading SSH configuration, or submitting any work.
RUN /opt/si-ox-runtime/bin/python - <<'PY'
from pathlib import Path
import subprocess
items = sorted(Path('/opt/skills').glob('*/scripts/submit.py'))
assert len(items) == 1, items
subprocess.run(['/opt/si-ox-runtime/bin/python', '-B', '-I', str(items[0]), '--help'],
               check=True, stdout=subprocess.DEVNULL)
PY

# Install a small public client for the root-owned Unix-socket broker. It has
# no SSH or scheduler credentials and only forwards the existing broker API.
RUN cat > /usr/local/bin/task-compute <<'PY'
#!/usr/bin/python3
import argparse, json, os, re, socket, struct, sys, uuid
from pathlib import Path

SOCKET_PATH = Path('/run/bench24-159/hpc.sock')
PUBLIC_ATTEMPT = Path('/run/bench24-159/public-attempt.json')
MAX_MESSAGE = 1_000_000
TRIAL_RE = re.compile(r'bench24-task159-[a-z0-9-]{8,100}')

def read_exact(sock, n):
    chunks=[]
    while n:
        block=sock.recv(n)
        if not block: raise RuntimeError('root broker closed the IPC connection')
        chunks.append(block);n-=len(block)
    return b''.join(chunks)

def request(doc, timeout=600):
    raw=json.dumps(doc,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
    if len(raw)>MAX_MESSAGE: raise RuntimeError('broker request exceeds the IPC limit')
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        sock.connect(str(SOCKET_PATH))
        sock.sendall(struct.pack('!I',len(raw))+raw)
        size=struct.unpack('!I',read_exact(sock,4))[0]
        if size<=0 or size>MAX_MESSAGE: raise RuntimeError('root broker response size is invalid')
        response=json.loads(read_exact(sock,size))
    if not isinstance(response,dict): raise RuntimeError('root broker response is malformed')
    return response

def attempt():
    if PUBLIC_ATTEMPT.is_symlink() or not PUBLIC_ATTEMPT.is_file():
        raise RuntimeError('root-published attempt context is unavailable')
    doc=json.loads(PUBLIC_ATTEMPT.read_text())
    if doc.get('schema')!='case06-native-main-clock-public/v1' or not re.fullmatch(r'[0-9a-f]{32}',str(doc.get('attempt_id',''))):
        raise RuntimeError('root-published attempt context is unsupported')
    return doc

def trial_name(value):
    value=value or ('bench24-task159-'+uuid.uuid4().hex)
    if not TRIAL_RE.fullmatch(value): raise RuntimeError('trial name must use the bench24-task159-<token> form')
    return value

def state_path(name, create=False):
    home=Path.home()
    if home.is_symlink() or not home.is_dir(): raise RuntimeError('candidate home directory is unavailable')
    root=home/'.cache'/'task-compute'
    if root.is_symlink(): raise RuntimeError('client state directory cannot be a symlink')
    if create: root.mkdir(mode=0o700,parents=True,exist_ok=True)
    if not root.is_dir(): raise RuntimeError('client state directory is unavailable')
    return root/(name+'.json')

def resources_command(args):
    public=attempt()
    if args.resource_id:
        name=trial_name(args.trial)
        doc={'schema':'case06-hpc-broker-request/v1','attempt_id':public['attempt_id'],
            'trial_name':name,'args':['resources','--resource-id',args.resource_id]}
        response=request(doc,timeout=90)
        if response.get('returncode')!=0:
            print(json.dumps(response,sort_keys=True),file=sys.stderr)
            return int(response.get('returncode') or 2)
        try: discovered=json.loads(response.get('stdout',''))
        except Exception as exc: raise RuntimeError('root resource discovery response is malformed') from exc
        print(json.dumps(discovered,sort_keys=True))
        return 0
    ids=public.get('resource_ids')
    if not isinstance(ids,list) or any(not isinstance(x,str) for x in ids):
        raise RuntimeError('root-published resource alias list is malformed')
    print(json.dumps({'resource_ids':sorted(set(ids)),'status':'AVAILABLE' if ids else 'NO_AUTHORIZED_RESOURCE'},
        sort_keys=True))
    return 0

def probe_command(args):
    public=attempt();name=trial_name(args.trial);path=state_path(name,create=True)
    if path.exists() or path.is_symlink(): raise RuntimeError('trial client state already exists; choose a fresh trial name')
    runtime={}
    if args.python: runtime['python']=args.python
    if args.lmp: runtime['lmp']=args.lmp
    if args.module: runtime['modules']=args.module
    selection={'resource_id':args.resource_id,'backend':'slurm','partition':args.partition,
        'runtime':runtime,'resources':{'nodes':1,'ntasks':1,'cpus':args.cpus,
        'memory_mb':args.memory_mb,'gpus':args.gpus,'wall_seconds':args.wall_seconds}}
    if args.remote_base: selection['remote_base']=args.remote_base
    doc={'schema':'case06-hpc-broker-request/v1','attempt_id':public['attempt_id'],
        'trial_name':name,'args':['probe','--host',args.resource_id,'--partition',args.partition,'--json','--detail'],
        'selection':selection}
    response=request(doc)
    if response.get('returncode')!=0:
        print(json.dumps(response,sort_keys=True),file=sys.stderr);return int(response.get('returncode') or 2)
    selected=response.get('selection');admission=response.get('admission_id')
    if not isinstance(selected,dict) or not isinstance(admission,str) or selected.get('admission_id')!=admission:
        raise RuntimeError('root broker did not return a bound resource admission')
    probe_bytes=response.get('stdout','').encode()
    output=Path('/app/outputs')
    if output.is_symlink() or not output.is_dir(): raise RuntimeError('candidate output directory is unavailable')
    directory=output/'.task-compute'
    if directory.is_symlink(): raise RuntimeError('probe output directory cannot be a symlink')
    directory.mkdir(mode=0o700,exist_ok=True)
    probe_path=directory/(name+'.probe.json')
    if probe_path.exists() or probe_path.is_symlink(): raise RuntimeError('probe snapshot output already exists')
    fd=os.open(probe_path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
    with os.fdopen(fd,'wb') as stream: stream.write(probe_bytes);stream.flush();os.fsync(stream.fileno())
    local={'schema':'case06-task-compute-client-state/v1','attempt_id':public['attempt_id'],
        'trial_name':name,'selection':selected,'admission_id':admission,
        'probe_snapshot_path':str(probe_path)}
    state_bytes=(json.dumps(local,sort_keys=True,separators=(',',':'))+'\n').encode()
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
    with os.fdopen(fd,'wb') as stream: stream.write(state_bytes);stream.flush();os.fsync(stream.fileno())
    response['trial_name']=name;response['probe_snapshot_path']=str(probe_path)
    print(json.dumps(response,sort_keys=True))
    return 0

def lifecycle_command(args):
    if not args.trial: raise RuntimeError('--trial is required for lifecycle actions')
    public=attempt();name=trial_name(args.trial);path=state_path(name)
    if path.is_symlink() or not path.is_file(): raise RuntimeError('no saved root admission for this trial')
    state=json.loads(path.read_text())
    if (state.get('schema')!='case06-task-compute-client-state/v1'
            or state.get('attempt_id')!=public['attempt_id'] or state.get('trial_name')!=name):
        raise RuntimeError('saved client state belongs to another attempt')
    helper_args=list(args.helper_args)
    if helper_args and helper_args[0]=='--': helper_args=helper_args[1:]
    if not helper_args: raise RuntimeError('pass the existing helper action arguments after --')
    doc={'schema':'case06-hpc-broker-request/v1','attempt_id':public['attempt_id'],
        'trial_name':name,'args':[args.action,*helper_args],
        'selection':state['selection'],'admission_id':state['admission_id']}
    timeout=600
    if args.action=='wait':
        try:
            timeout_arg=int(helper_args[helper_args.index('--timeout')+1])
            timeout=min(604800,timeout_arg+120)
        except (ValueError,IndexError):
            raise RuntimeError('wait requires an integer --timeout helper argument')
    elif args.action=='collect': timeout=3700
    elif args.action=='submit': timeout=420
    response=request(doc,timeout=timeout)
    if response.get('helper_job_name'):
        state['helper_job_name']=response['helper_job_name']
        raw=(json.dumps(state,sort_keys=True,separators=(',',':'))+'\n').encode()
        tmp=path.with_name(path.name+'.tmp')
        fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
        with os.fdopen(fd,'wb') as stream: stream.write(raw);stream.flush();os.fsync(stream.fileno())
        os.replace(tmp,path)
    print(json.dumps(response,sort_keys=True))
    rc=response.get('returncode')
    if type(rc) is not int: raise RuntimeError('root broker response has no integer return code')
    return rc

def main():
    parser=argparse.ArgumentParser(prog='task-compute',
        description='Select an authorized task resource and use the root-owned task IPC broker.')
    parser.add_argument('--trial',help='trial namespace; generated automatically by probe when omitted')
    subs=parser.add_subparsers(dest='action',required=True)
    resources=subs.add_parser('resources',help="list authorized aliases or discover one alias's partitions and default tool paths")
    resources.add_argument('--resource-id',help='authorized alias to inspect through the root broker')
    probe=subs.add_parser('probe',help='probe and admit a selected resource')
    probe.add_argument('--resource-id',required=True);probe.add_argument('--partition',required=True)
    probe.add_argument('--remote-base');probe.add_argument('--python');probe.add_argument('--lmp')
    probe.add_argument('--module',action='append');probe.add_argument('--cpus',type=int,default=1)
    probe.add_argument('--memory-mb',type=int,default=8192);probe.add_argument('--gpus',type=int,choices=(0,1),default=1)
    probe.add_argument('--wall-seconds',type=int,default=43200)
    lifecycle_help={
        'submit':('submit the admitted job',
            'Required helper arguments: --target TARGET --name NAME --cmd COMMAND '
            '--reason-file FILE --probe-snapshot FILE --snapshot-sha256 SHA256 '
            '--src DIR --workdir ABSOLUTE_DIR --partition PARTITION --nodes N '
            '--ntasks N --ntasks-per-node N --cpus N --mem SIZE --gpus N --time HH:MM:SS. '
            'Optional: --dry-run.'),
        'status':('read the admitted job status','Required helper argument: --job JOB_NAME.'),
        'wait':('wait for the admitted job','Required: --job JOB_NAME --poll SECONDS --timeout SECONDS.'),
        'collect':('collect the admitted job outputs','Required: --job JOB_NAME --dest NEW_DIRECTORY. '
            'Optional: --allow-unsuccessful for diagnostic collection.'),
        'cancel':('cancel the admitted job','Required helper argument: --job JOB_NAME.'),
    }
    for action in ('submit','status','wait','collect','cancel'):
        short,details=lifecycle_help[action]
        command=subs.add_parser(action,help=short,description=short,epilog=details,
            formatter_class=argparse.RawDescriptionHelpFormatter)
        command.add_argument('helper_args',nargs=argparse.REMAINDER,
            help='existing helper arguments, optionally after --')
    args=parser.parse_args()
    try:
        if args.action=='resources': return resources_command(args)
        if args.action=='probe': return probe_command(args)
        return lifecycle_command(args)
    except Exception as exc:
        print(json.dumps({'status':'ERROR','error_type':type(exc).__name__,'error':str(exc)},sort_keys=True),file=sys.stderr)
        return 2

if __name__=='__main__': raise SystemExit(main())
PY
RUN chmod 0555 /usr/local/bin/task-compute

# Harbor-native root capture. The agent runs as an unprivileged researcher;
# only the root collector may freeze its outputs and publish the attempt seal.
RUN install -d -o root -g root -m 0755 /opt/bench24-159 \
    && cat > /opt/bench24-159/root-capture.py <<'PY'
#!/usr/bin/python3
import base64, grp, hashlib, hmac, json, os, pwd, re, select, shlex, shutil, signal, socket, stat, struct, subprocess, sys, threading, time, uuid
from datetime import datetime, timezone
from pathlib import Path

STATE = Path('/run/bench24-159')
ARTIFACTS = Path('/app/bench24-artifacts')
LIMIT = 43200
HELPER_ROOT = Path('/opt/skills')
HELPER_PYTHON = Path('/opt/si-ox-runtime/bin/python')
HPC_SOCKET = STATE / 'hpc.sock'
OUTPUT_ROOT = Path('/app/outputs')
HPC_LOCK = threading.RLock()
HPC_SUBMIT_LOCK = threading.Lock()
HPC_COND = threading.Condition(HPC_LOCK)
HPC_CLIENT = threading.local()
HPC_STOPPING = False
HPC_ACTIVE = 0

def _helper_root():
    candidates=sorted(path.parent.parent for path in HELPER_ROOT.glob('*/scripts/submit.py'))
    if len(candidates)!=1: raise RuntimeError('image must provide exactly one supported HPC submission helper')
    return candidates[0]

def utc():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()

def atomic(path, data, mode=0o400):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp-' + uuid.uuid4().hex)
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), mode)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(data); stream.flush(); os.fsync(stream.fileno())
    os.chmod(tmp, mode); os.replace(tmp, path)

def tree_inventory(root):
    rows = []
    for base, dirs, files in os.walk(root, followlinks=False):
        dirs.sort()
        for name in sorted(dirs + files):
            path = Path(base) / name
            st = path.lstat()
            if stat.S_ISLNK(st.st_mode) or not (stat.S_ISDIR(st.st_mode) or stat.S_ISREG(st.st_mode)):
                raise RuntimeError('unsafe task/output filesystem entry')
            if stat.S_ISREG(st.st_mode):
                if st.st_nlink != 1: raise RuntimeError('hardlinked task/output file rejected')
                rel = path.relative_to(root).as_posix(); raw = path.read_bytes()
                rows.append({'path': rel, 'size_bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()})
    rows.sort(key=lambda row: row['path'])
    return rows

def task_inputs():
    root = Path('/app/inputs')
    return {'schema':'case06-root-captured-inputs/v1', 'files':tree_inventory(root)}

def kill_researcher():
    uid = pwd.getpwnam('researcher').pw_uid
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        victims = set()
        for entry in Path('/proc').iterdir():
            if not entry.name.isdigit(): continue
            try:
                status = (entry / 'status').read_text()
                line = next(x for x in status.splitlines() if x.startswith('Uid:'))
                if int(line.split()[1]) == uid: victims.add(int(entry.name))
            except (OSError, StopIteration, ValueError): pass
        if not victims: return
        for pid in victims:
            try: os.kill(pid, signal.SIGTERM)
            except ProcessLookupError: pass
        time.sleep(.2)
        for pid in victims:
            try:
                status=(Path(f'/proc/{pid}/status')).read_text()
                if int(next(x for x in status.splitlines() if x.startswith('Uid:')).split()[1]) == uid:
                    os.kill(pid, signal.SIGKILL)
            except (OSError, StopIteration, ValueError, ProcessLookupError): pass
    raise RuntimeError('researcher processes remain after root freeze cleanup')

def _hpc_read_exact(stream, size):
    chunks=[]
    while size:
        block=stream.recv(size)
        if not block: raise RuntimeError('truncated broker request')
        chunks.append(block); size-=len(block)
    return b''.join(chunks)

def _hpc_safe_tree(source, dest):
    root=OUTPUT_ROOT.resolve(strict=True)
    source=Path(source)
    if source.is_symlink(): raise RuntimeError('HPC payload source cannot be a symlink')
    source=source.resolve(strict=True)
    source.relative_to(root)
    if not source.is_dir(): raise RuntimeError('HPC payload source must be a directory under /app/outputs')
    rows=[]
    for base,dirs,files in os.walk(source,topdown=True,followlinks=False):
        dirs.sort();files.sort()
        for name in dirs+files:
            path=Path(base)/name;st=path.lstat()
            if stat.S_ISLNK(st.st_mode) or not (stat.S_ISDIR(st.st_mode) or stat.S_ISREG(st.st_mode)):
                raise RuntimeError('HPC payload contains a symlink or special file')
            if stat.S_ISREG(st.st_mode):
                if st.st_nlink!=1: raise RuntimeError('HPC payload contains a hardlink')
                rows.append({'path':path.relative_to(source).as_posix(),'size_bytes':st.st_size,
                    'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
    rows.sort(key=lambda x:x['path'])
    if not rows: raise RuntimeError('HPC payload is empty')
    dest=Path(dest);shutil.copytree(source,dest,symlinks=True)
    if tree_inventory(source)!=tree_inventory(dest): raise RuntimeError('HPC payload changed during root copy')
    return rows

def _hpc_args_map(args, valued, flags):
    values={};seen=set();i=0
    while i<len(args):
        token=args[i]
        if token in flags:
            if token in seen: raise RuntimeError('duplicate helper flag')
            seen.add(token);values[token]=True;i+=1;continue
        if token not in valued or token in seen or i+1>=len(args):
            raise RuntimeError('unsupported or duplicate helper argument')
        seen.add(token);values[token]=args[i+1];i+=2
    if seen != set(valued)|set(flags):
        if seen != set(valued) and seen != set(valued)|set(flags):
            raise RuntimeError('required helper arguments are missing')
    return values

def _authorized_resource_ids():
    config=Path('/root/.ssh/config')
    if config.is_symlink() or not config.is_file() or config.stat().st_uid!=0 or config.stat().st_mode&0o022:
        return set()
    aliases=set()
    for line in config.read_text(encoding='utf-8').splitlines():
        parts=line.strip().split()
        if len(parts)<2 or parts[0].lower()!='host': continue
        for value in parts[1:]:
            if re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,62}',value): aliases.add(value)
    return aliases

def _valid_remote_path(value):
    return (isinstance(value,str) and value.startswith('/') and '\\' not in value
        and not any(part in ('','..') for part in value.split('/')[1:])
        and bool(re.fullmatch(r'/[A-Za-z0-9._/-]{1,240}',value)))

def _root_ssh(resource_id, command, timeout=45):
    if resource_id not in _authorized_resource_ids(): raise RuntimeError('resource id is not an authorized SSH alias')
    env={'HOME':'/root','PATH':'/usr/bin:/bin','LANG':'C','LC_ALL':'C','TZ':'UTC'}
    if os.environ.get('SSH_AUTH_SOCK'): env['SSH_AUTH_SOCK']=os.environ['SSH_AUTH_SOCK']
    return subprocess.run(['/usr/bin/ssh','-oBatchMode=yes','-oConnectTimeout=8',resource_id,command],
        env=env,capture_output=True,text=True,timeout=timeout,check=False)

def _resolve_selection(value, start_doc, trial):
    if not isinstance(value,dict): raise RuntimeError('a runtime resource selection is required')
    allowed={'resource_id','backend','partition','remote_base','runtime','resources'}
    if set(value)-allowed: raise RuntimeError('resource selection has unsupported fields')
    resource_id=value.get('resource_id');partition=value.get('partition')
    if not isinstance(resource_id,str) or resource_id not in _authorized_resource_ids():
        raise RuntimeError('resource id is not in the root-authorized SSH alias set')
    if value.get('backend','slurm')!='slurm' or not isinstance(partition,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}',partition):
        raise RuntimeError('resource backend or partition is malformed')
    resources=value.get('resources') or {}
    if not isinstance(resources,dict) or set(resources)-{'nodes','ntasks','cpus','memory_mb','gpus','wall_seconds'}:
        raise RuntimeError('resource limits are malformed')
    remaining=max(0,(int(json.loads((STATE/'public-attempt.json').read_text())['deadline_monotonic_ns'])-time.monotonic_ns())//1_000_000_000-300)
    requested_wall=resources.get('wall_seconds',43200)
    if type(requested_wall) is not int or requested_wall<1: raise RuntimeError('requested allocation time is malformed')
    resources={'nodes':resources.get('nodes',1),'ntasks':resources.get('ntasks',1),
        'cpus':resources.get('cpus',1),'memory_mb':resources.get('memory_mb',8192),
        'gpus':resources.get('gpus',1),'wall_seconds':min(requested_wall,remaining)}
    if (type(resources['nodes']) is not int or resources['nodes']!=1 or type(resources['ntasks']) is not int or resources['ntasks']!=1 or type(resources['cpus']) is not int or not 1<=resources['cpus']<=4
            or type(resources['memory_mb']) is not int or not 1024<=resources['memory_mb']<=8192
            or type(resources['gpus']) is not int or resources['gpus'] not in (0,1)
            or type(resources['wall_seconds']) is not int or not 1<=resources['wall_seconds']<=43200):
        raise RuntimeError('requested resources exceed task limits or remaining time')
    runtime=value.get('runtime') or {}
    if not isinstance(runtime,dict) or set(runtime)-{'python','lmp','modules'}:
        raise RuntimeError('runtime selection is malformed')
    modules=runtime.get('modules',[])
    if not isinstance(modules,list) or len(modules)>8 or any(not isinstance(m,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._+/-]{0,79}',m) for m in modules):
        raise RuntimeError('runtime module selection is malformed')
    py=runtime.get('python');lmp=runtime.get('lmp')
    for path in (py,lmp):
        if path is not None and not _valid_remote_path(path): raise RuntimeError('selected runtime path is not normalized absolute')
    module_lines=''
    if modules:
        module_lines='if [ -d "$HOME/modulefiles" ]; then module use "$HOME/modulefiles"; fi; '
        module_lines+=''.join('module load '+shlex.quote(m)+'; ' for m in modules)
    py_expr=shlex.quote(py) if py else '$(command -v python3)'
    lmp_expr=shlex.quote(lmp) if lmp else '$(command -v lmp || command -v lmp_mpi)'
    python_check=shlex.quote('import calphy,sys; print("PYTHON_VERSION="+sys.version.split()[0]); print("CALPHY_VERSION="+calphy.__version__)')
    script=('set -eu; '+module_lines+
        'p='+py_expr+' || exit 61; l='+lmp_expr+' || exit 62; test -x "$p" || exit 61; test -x "$l" || exit 62; '
        'digest=$(sha256sum -- "$l"); digest=${digest%% *}; '
        'printf "HOME=%s\nPYTHON=%s\nLAMMPS=%s\nLAMMPS_SHA256=%s\n" "$HOME" "$p" "$l" "$digest"; '
        '"$p" -c '+python_check+' || exit 63; '
        'if h=$("$l" -h 2>&1); then '
        'printf "%s" "$h" | grep -Fq pace/kk || exit 65; '
        'printf "%s" "$h" | grep -Fq ti/spring || exit 66; '
        'echo LAMMPS_CAPABILITY_CHECK=login; '
        'elif printf "%s" "$h" | grep -Fq "libcuda.so.1: cannot open shared object file"; then '
        'echo LAMMPS_CAPABILITY_CHECK=compute_node; else exit 64; fi')
    runtime_probe=_root_ssh(resource_id,'bash -lc '+shlex.quote(script),90)
    if runtime_probe.returncode:
        failures={61:'Python executable not found',62:'LAMMPS executable not found',
                  63:'selected Python could not import Calphy',64:'LAMMPS -h failed',
                  65:'LAMMPS lacks pace/kk',66:'LAMMPS lacks ti/spring'}
        reason=failures.get(runtime_probe.returncode,'SSH or module setup failed')
        raise RuntimeError('selected endpoint runtime check failed: '+reason)
    lines=runtime_probe.stdout.splitlines(); observed={}
    for line in lines:
        if '=' in line:
            k,v=line.split('=',1);observed[k]=v
    home=observed.get('HOME')
    if not _valid_remote_path(home): raise RuntimeError('selected endpoint did not report a normalized home directory')
    remote_base=value.get('remote_base')
    if remote_base is None: remote_base=home+'/.cache/bench24-task159'
    if not _valid_remote_path(remote_base) or not remote_base.startswith(home.rstrip('/')+'/'):
        raise RuntimeError('remote work base must remain under the selected account home')
    python_path=observed.get('PYTHON');lmp_path=observed.get('LAMMPS')
    if not _valid_remote_path(python_path) or not _valid_remote_path(lmp_path):
        raise RuntimeError('selected endpoint runtime paths were not resolved')
    lmp_sha=observed.get('LAMMPS_SHA256')
    if not re.fullmatch(r'[0-9a-f]{64}',lmp_sha or ''): raise RuntimeError('selected LAMMPS binary SHA is unavailable')
    if observed.get('CALPHY_VERSION')!='2.1.2': raise RuntimeError('selected endpoint Calphy version is not source-qualified')
    capability_check=observed.get('LAMMPS_CAPABILITY_CHECK')
    if capability_check not in {'login','compute_node'} or (capability_check=='compute_node' and not resources['gpus']):
        raise RuntimeError('LAMMPS capability check requires a GPU allocation when the login node has no CUDA driver')
    target='bench24-task159-'+start_doc['attempt_id'][:8]+'-'+hashlib.sha256(trial.encode()).hexdigest()[:6]
    resolved={'schema':'case06-resource-selection/v1','resource_id':resource_id,'backend':'slurm','partition':partition,'remote_base':remote_base,
        'runtime':{'python':python_path,'lmp':lmp_path,'modules':modules,'lmp_sha256':lmp_sha,'capability_check':capability_check},
        'resources':resources,'target_name':target,'runtime_probe_sha256':hashlib.sha256(runtime_probe.stdout.encode()).hexdigest()}
    return resolved

def _hpc_config(selection):
    resource=selection['resources'];part=selection['partition'];target=selection['target_name'];host=selection['resource_id']
    mem=f"{resource['memory_mb']}M";gpus=resource['gpus'];cpus=resource['cpus']
    klass='gpu' if gpus else 'cpu'
    limits={'enabled':True,'max_nodes':1,'max_ntasks':1,'max_ntasks_per_node':1,
        'max_cpus_per_task':cpus,'max_total_cpus':cpus,'max_gpus_per_node':gpus,
        'max_total_gpus':gpus,'max_memory_per_node':mem,'max_total_memory':mem,
        'max_walltime':'12:00:00'}
    return {'targets':{target:{'backend':'slurm','host':host,'resource_class':klass,
        'partition':part,'allowed_partitions':[part],'base_dir':selection['remote_base'],
        'snapshot_max_age_seconds':900,'transfer_timeout':300,'partition_limits':{part:limits}}}}

def _hpc_next_job_name(attempt_id):
    path=STATE/'job-sequence.json'
    try: state=json.loads(path.read_text())
    except FileNotFoundError: state={'next':0}
    value=state.get('next')
    if type(value) is not int or value<0: raise RuntimeError('root job sequence is corrupt')
    value+=1
    atomic(path,canonical({'next':value})+b'\n',0o400)
    return f'bench24-task159-{attempt_id[:12]}-{value:02d}'

def _hpc_root(trial, selection=None):
    if not re.fullmatch(r'bench24-task159-[a-z0-9-]{8,100}',trial):
        raise RuntimeError('HPC logical name is outside the task namespace')
    hpc_root=STATE/'hpc'
    hpc_root.mkdir(mode=0o700,exist_ok=True)
    if not (hpc_root/trial).exists() and sum(1 for p in hpc_root.iterdir() if p.is_dir())>=8:
        raise RuntimeError('root broker per-attempt trial namespace limit reached')
    base=hpc_root/trial
    if base.is_symlink(): raise RuntimeError('HPC private state cannot be a symlink')
    base.mkdir(mode=0o700,parents=True,exist_ok=True)
    st=base.stat()
    if st.st_uid!=0 or st.st_mode&0o077: raise RuntimeError('HPC private state permissions are invalid')
    helper=base/'helper-root'
    if not helper.exists():
        shutil.copytree(_helper_root(),helper,ignore=shutil.ignore_patterns('submit-job.json','.submit-job','__pycache__','.git'))
        os.chown(helper,0,0)
    cfg=helper/'submit-job.json'
    if cfg.is_symlink(): raise RuntimeError('HPC config cannot be a symlink')
    if selection is None:
        if not cfg.exists(): raise RuntimeError('root admission selection is missing before HPC lifecycle')
        return base,helper
    selection_path=base/'selection.json'
    selection_raw=canonical(selection)+b'\n'
    if selection_path.exists() and selection_path.read_bytes()!=selection_raw: raise RuntimeError('resource selection changed after probe admission')
    if not selection_path.exists(): atomic(selection_path,selection_raw,0o400)
    raw=json.dumps(_hpc_config(selection),sort_keys=True,separators=(',',':')).encode()+b'\n'
    if cfg.exists() and cfg.read_bytes()!=raw: raise RuntimeError('HPC fixed config changed during attempt')
    if not cfg.exists():
        fd=os.open(cfg,os.O_CREAT|os.O_EXCL|os.O_WRONLY|getattr(os,'O_NOFOLLOW',0),0o400)
        with os.fdopen(fd,'wb') as f: f.write(raw);f.flush();os.fsync(f.fileno())
    return base,helper

def _hpc_run(helper,args,timeout,monitor_base=None,monitor_job=None):
    script=helper/'scripts'/'submit.py'
    if not script.is_file() or not HELPER_PYTHON.is_file(): raise RuntimeError('fixed HPC helper runtime is unavailable')
    env=dict(os.environ);env.update({'HOME':'/root','PATH':'/opt/si-ox-runtime/bin:/usr/bin:/bin'})
    process=subprocess.Popen([str(HELPER_PYTHON),'-B','-I',str(script),*args],cwd=helper,
        env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True)
    deadline=time.monotonic()+timeout
    reason='ROOT_BROKER_TIMEOUT';next_scheduler_poll=time.monotonic()
    while True:
        remaining=deadline-time.monotonic()
        if remaining<=0: break
        if monitor_base is not None and monitor_job is not None and time.monotonic()>=next_scheduler_poll:
            try: _persist_scheduler_observation(monitor_base,monitor_job)
            except Exception: pass
            next_scheduler_poll=time.monotonic()+10.0
        try:
            stdout,stderr=process.communicate(timeout=min(1.0,remaining))
            return subprocess.CompletedProcess(args,process.returncode,stdout or '',stderr or '')
        except subprocess.TimeoutExpired:
            client=getattr(HPC_CLIENT,'socket',None)
            if client is not None:
                try:
                    extra=client.recv(1,socket.MSG_PEEK|socket.MSG_DONTWAIT)
                    if extra==b'': reason='ROOT_BROKER_CLIENT_DISCONNECTED';break
                    if extra: reason='ROOT_BROKER_UNEXPECTED_CLIENT_BYTES';break
                except BlockingIOError: pass
                except OSError: reason='ROOT_BROKER_CLIENT_DISCONNECTED';break
    try: os.killpg(process.pid,signal.SIGTERM)
    except ProcessLookupError: pass
    try: stdout,stderr=process.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        try: os.killpg(process.pid,signal.SIGKILL)
        except ProcessLookupError: pass
        stdout,stderr=process.communicate(timeout=10)
    return subprocess.CompletedProcess(args,124,stdout or '',(stderr or '')+'\n'+reason)

def _hpc_find_terminal_receipt(value):
    if isinstance(value,dict):
        if str(value.get('schema',value.get('receipt_schema',''))).endswith('slurm-sacct-receipt/v1') and isinstance(value.get('sacct_rows_base64'),str):
            return value
        for key in ('receipt','sacct_receipt','scheduler_receipt','terminal_receipt','result','state'):
            found=_hpc_find_terminal_receipt(value.get(key))
            if found: return found
        for key in ('results','records'):
            rows=value.get(key)
            if isinstance(rows,list):
                for row in rows:
                    found=_hpc_find_terminal_receipt(row)
                    if found: return found
    return None

def _broker_scheduler_times(job_id, resource_id):
    if not re.fullmatch(r"[0-9]+", str(job_id)):
        raise RuntimeError('scheduler query requires a root-bound numeric job ID')
    if resource_id not in _authorized_resource_ids(): raise RuntimeError('scheduler resource is no longer an authorized SSH alias')
    remote_cmd="env TZ=UTC SLURM_TIME_FORMAT='%Y-%m-%dT%H:%M:%S%z' sacct -n -P -j "+str(job_id)+" --format=JobIDRaw,State,Submit,Start,End,ElapsedRaw,Restarts"
    argv=['/usr/bin/ssh','-oBatchMode=yes','-oConnectTimeout=8',resource_id,remote_cmd]
    env={'HOME':'/root','PATH':'/usr/bin:/bin','LC_ALL':'C',
        'LANG':'C','SSH_AUTH_SOCK':os.environ.get('SSH_AUTH_SOCK','')}
    try:
        proc=subprocess.run(argv,env=env,capture_output=True,timeout=20,check=False)
        raw=proc.stdout or b''
        captured=utc()
        lines=[line for line in raw.decode('utf-8','strict').splitlines() if line.strip()]
        matched=[line for line in lines if line.split('|',1)[0].strip()==str(job_id)]
        if proc.returncode!=0 or len(matched)!=1:
            return {'schema':'case06-root-scheduler-times/v1','job_id':str(job_id),
                'status':'UNKNOWN','captured_utc':captured,'raw_base64':base64.b64encode(raw).decode('ascii'),
                'raw_sha256':hashlib.sha256(raw).hexdigest(),
                'stderr_sha256':hashlib.sha256(proc.stderr or b'').hexdigest(),
                'returncode':proc.returncode,'row_count':len(matched)}
        columns=matched[0].rstrip('|').split('|')
        if len(columns)!=7: raise RuntimeError('scheduler raw row has unexpected column count')
        job,state,submitted,started,ended,elapsed,restarts=columns
        def parse_time(value):
            if not value.strip() or value.strip() in ('Unknown','N/A','None'):
                return None
            normalized=value.strip().replace('Z','+00:00')
            if re.search(r'[+-][0-9]{4}$',normalized): normalized=normalized[:-2]+':'+normalized[-2:]
            parsed=datetime.fromisoformat(normalized)
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                raise ValueError('raw scheduler timestamp lacks an explicit timezone offset')
            return parsed.astimezone(timezone.utc).isoformat().replace('+00:00','Z')
        try: restart_count=int(restarts) if restarts not in ('','Unknown','N/A') else None
        except ValueError: restart_count=None
        return {'schema':'case06-root-scheduler-times/v1','job_id':job,'status':'OBSERVED',
            'state':state.split('+')[0].split()[0],'submit_utc':parse_time(submitted),
            'start_utc':parse_time(started),'end_utc':parse_time(ended),
            'elapsed_raw':elapsed,'restart_count':restart_count,'captured_utc':captured,
            'raw_base64':base64.b64encode(raw).decode('ascii'),
            'raw_sha256':hashlib.sha256(raw).hexdigest(),'returncode':proc.returncode,
            'row_count':len(matched)}
    except Exception as exc:
        raw=(type(exc).__name__+':'+str(exc)).encode('utf-8','replace')
        return {'schema':'case06-root-scheduler-times/v1','job_id':str(job_id),
            'status':'UNKNOWN','captured_utc':utc(),'raw_base64':base64.b64encode(raw).decode('ascii'),
            'raw_sha256':hashlib.sha256(raw).hexdigest(),'returncode':None,'row_count':0}

def _queue_credit_set(records, active_intervals, capture_start, now):
    def stamp(value):
        parsed=datetime.fromisoformat(str(value).replace('Z','+00:00'))
        if parsed.tzinfo is None: raise ValueError('scheduler timestamp has no timezone')
        return parsed.astimezone(timezone.utc).timestamp()
    start=stamp(capture_start);end=stamp(now);by_job={};spans=[];unknown=[]
    for row in records:
        if not isinstance(row,dict) or row.get('schema')!='case06-root-scheduler-times/v1':
            unknown.append('unsupported scheduler source');continue
        job=str(row.get('job_id',''))
        try: raw=base64.b64decode(row.get('raw_base64',''),validate=True)
        except Exception:
            unknown.append('scheduler source base64 is invalid');continue
        if hashlib.sha256(raw).hexdigest()!=row.get('raw_sha256'):
            unknown.append('scheduler source SHA mismatch');continue
        if not job.isdigit():
            unknown.append('malformed scheduler job');continue
        try:
            raw_lines=[line.rstrip('|').split('|') for line in raw.decode('utf-8','strict').splitlines()
                if line.strip() and line.split('|',1)[0].strip()==job]
            if len(raw_lines)!=1 or len(raw_lines[0])!=7: raise ValueError('raw scheduler row is absent or ambiguous')
            fields=raw_lines[0]
            def raw_stamp(value):
                value=value.strip()
                if not value or value in ('Unknown','N/A','None'): return None
                normalized=value.replace('Z','+00:00')
                if re.search(r'[+-][0-9]{4}$',normalized): normalized=normalized[:-2]+':'+normalized[-2:]
                parsed=datetime.fromisoformat(normalized)
                if parsed.tzinfo is None or parsed.utcoffset() is None: raise ValueError('raw scheduler timestamp lacks an explicit timezone offset')
                return parsed.astimezone(timezone.utc).timestamp()
            normalized_state=fields[1].split('+')[0].split()[0]
            raw_restart=int(fields[6]) if fields[6].strip() not in ('','Unknown','N/A') else None
            if normalized_state!=row.get('state') or fields[5]!=row.get('elapsed_raw') or raw_restart!=row.get('restart_count'):
                raise ValueError('parsed scheduler state/count differs from raw row')
            for raw_value,key in ((fields[2],'submit_utc'),(fields[3],'start_utc'),(fields[4],'end_utc')):
                parsed_epoch=raw_stamp(raw_value); declared=row.get(key)
                if (parsed_epoch is None)!=(declared is None): raise ValueError('parsed scheduler timestamp sentinel differs from raw row')
                if parsed_epoch is not None and abs(parsed_epoch-stamp(declared))>1.0:
                    raise ValueError('parsed scheduler timestamp differs from raw row')
        except Exception as exc:
            unknown.append(f'scheduler source cannot be replayed: {type(exc).__name__}');continue
        previous=by_job.get(job)
        if previous is None or stamp(row.get('captured_utc'))>stamp(previous.get('captured_utc')):
            by_job[job]=row
    for job,row in by_job.items():
        if row.get('status')!='OBSERVED':
            unknown.append('latest scheduler source is unavailable');continue
        if row.get('restart_count')!=0:
            unknown.append('job restart count is missing or nonzero');continue
        submitted=row.get('submit_utc');allocated=row.get('start_utc')
        if not submitted:
            unknown.append('scheduler submit time is unavailable');continue
        qs=stamp(submitted)
        state=str(row.get('state','')).upper()
        if allocated:
            qe=stamp(allocated)
        elif state in ('PENDING','CONFIGURING'):
            qe=stamp(row.get('captured_utc'))
        else:
            unknown.append('scheduler allocation start is unavailable');continue
        if qs<start-1 or qe<qs or qe>end+1:
            unknown.append('scheduler queue interval is outside captured attempt');continue
        spans.append((qs,qe,job))
    ordered=sorted((a,b) for a,b,_ in spans);union=[]
    for a,b in ordered:
        if b<=a: continue
        if not union or a>union[-1][1]: union.append([a,b])
        elif b>union[-1][1]: union[-1][1]=b
    for a,b in union:
        if any(a<ee and b>ss for ss,ee in active_intervals):
            unknown.append('scheduler queue interval overlaps active work')
    credit=sum(max(0,b-a) for a,b in union) if not unknown else 0.0
    return {'status':'UNKNOWN' if unknown else 'VALIDATED','queue_credit_seconds':credit,
        'intervals':[{'start_utc':datetime.fromtimestamp(a,timezone.utc).isoformat().replace('+00:00','Z'),
                      'end_utc':datetime.fromtimestamp(b,timezone.utc).isoformat().replace('+00:00','Z')}
                     for a,b in union], 'reasons':unknown}

def _hpc_scheduler_sources():
    entries=[];records=[];missing=False
    root=STATE/'hpc'
    if root.is_dir():
        for base in sorted(root.iterdir()):
            state_path=base/'broker-state.json'
            if not base.is_dir() or base.is_symlink() or not state_path.is_file(): continue
            try: state=json.loads(state_path.read_text())
            except Exception: missing=True;continue
            if state.get('submit_called') is not True: continue
            path=base/'scheduler-times.json'
            digest=None
            if path.is_file() and not path.is_symlink():
                try:
                    rows=json.loads(path.read_text())
                    if not isinstance(rows,list): raise ValueError('scheduler source is not a list')
                    records.extend(rows);digest=hashlib.sha256(path.read_bytes()).hexdigest()
                except Exception: missing=True
            else: missing=True
            entries.append({'trial_name':base.name,'sha256':digest})
    entries.sort(key=lambda row:row['trial_name'])
    return entries,records,missing

def _persist_scheduler_observation(base, job_id):
    selection_path=base/'selection.json'
    if selection_path.is_symlink() or not selection_path.is_file(): raise RuntimeError('root-frozen resource selection is missing for scheduler query')
    selection=json.loads(selection_path.read_text())
    record=_broker_scheduler_times(job_id,selection['resource_id'])
    path=base/'scheduler-times.json'
    records=json.loads(path.read_text()) if path.is_file() and not path.is_symlink() else []
    if not isinstance(records,list): raise RuntimeError('root scheduler observations are malformed')
    records.append(record)
    if len(records)>2048: records=records[-2048:]
    raw=canonical(records)+b'\n';atomic(path,raw,0o400)
    start_doc=json.loads((STATE/'start.json').read_text())
    source_entries,all_records,source_missing=_hpc_scheduler_sources()
    result=_queue_credit_set(all_records,[],start_doc['start_utc'],utc())
    if source_missing:
        result['status']='UNKNOWN';result['queue_credit_seconds']=0.0
    public=json.loads((STATE/'public-attempt.json').read_text())
    credit=int(result['queue_credit_seconds']) if result['status']=='VALIDATED' else 0
    start_ns=int(start_doc['start_monotonic_ns'])
    start_epoch=int(datetime.fromisoformat(start_doc['start_utc'].replace('Z','+00:00')).timestamp())
    public.update({'queue_credit_status':result['status'],'queue_credit_seconds':credit,
        'queue_credit_intervals':result['intervals'],'queue_credit_source_sha256':hashlib.sha256(canonical(source_entries)).hexdigest(),
        'deadline_monotonic_ns':start_ns+(LIMIT+credit)*1_000_000_000,
        'deadline_epoch':start_epoch+LIMIT+credit})
    atomic(STATE/'public-attempt.json',canonical(public)+b'\n',0o444)
    return record

def _hpc_cancel_owned_jobs():
    results=[];root=STATE/'hpc'
    if not root.is_dir(): return results
    for base in sorted(root.iterdir()):
        if not base.is_dir() or base.is_symlink(): continue
        state_path=base/'broker-state.json'
        if not state_path.is_file(): continue
        state=json.loads(state_path.read_text())
        if state.get('submit_called') is not True: continue
        trial=state.get('trial_name');helper_job=state.get('helper_job_name');helper=base/'helper-root';helper_state=helper/'.submit-job'/f'{helper_job}.json'
        if (not isinstance(trial,str) or base.name!=trial or not isinstance(helper_job,str)
                or not helper_state.is_file() or helper_state.is_symlink()):
            raise RuntimeError('cannot safely resolve an owned helper job before freezing candidate outputs')
        helper_doc=json.loads(helper_state.read_text())
        job_id=str(state.get('job_id') or helper_doc.get('job_id') or '')
        if not job_id or helper_doc.get('name')!=helper_job or str(helper_doc.get('job_id'))!=job_id:
            raise RuntimeError('owned helper job has no matching logical/numeric identity; freeze refused')
        receipt=_hpc_find_terminal_receipt(helper_doc)
        if receipt is None:
            cancel=_hpc_run(helper,['cancel','--job',helper_job],120)
            if cancel.returncode!=0:
                raise RuntimeError('root broker could not cancel its still-active owned job')
            status=_hpc_run(helper,['wait','--job',helper_job,'--poll','2','--timeout','30'],90)
            helper_doc=json.loads(helper_state.read_text())
            receipt=_hpc_find_terminal_receipt(helper_doc)
            if receipt is None:
                receipt=_hpc_find_terminal_receipt(json.loads(status.stdout)) if status.stdout.strip().startswith('{') else None
            if receipt is None:
                raise RuntimeError('owned job cancellation did not yield a hash-bound terminal scheduler receipt')
        rows=__import__('base64').b64decode(receipt.get('sacct_rows_base64',''),validate=True)
        if hashlib.sha256(rows).hexdigest()!=receipt.get('sacct_rows_sha256'):
            raise RuntimeError('owned job terminal receipt failed its raw sacct SHA check')
        lines=[line for line in rows.decode('utf-8').splitlines() if line.strip()]
        if len(lines)!=1 or lines[0].split('|')[0].strip()!=job_id:
            raise RuntimeError('owned job terminal receipt does not bind exactly one expected job')
        try: _persist_scheduler_observation(base,job_id)
        except Exception: pass
        result={'trial_name':trial,'job_id':job_id,'terminal_state':receipt.get('State'),
            'helper_state_sha256':hashlib.sha256(helper_state.read_bytes()).hexdigest(),
            'helper_state_path':str(helper_state)}
        results.append(result)
    return results

def _hpc_export_trusted(results):
    trusted=ARTIFACTS/'trusted';trusted.mkdir(mode=0o700,parents=True,exist_ok=True);os.chmod(trusted,0o700)
    dest=trusted/'hpc'
    if dest.exists(): raise RuntimeError('trusted root broker artifact already exists')
    dest.mkdir(mode=0o700,parents=True)
    jobs=[]
    for item in results:
        trial=item['trial_name'];base=STATE/'hpc'/trial
        target=dest/trial;target.mkdir(mode=0o700)
        names=['broker-state.json','probe.json','scheduler-times.json','selection.json']
        for name in names:
            source=base/name
            if source.is_file() and not source.is_symlink(): shutil.copy2(source,target/name)
        source=Path(item['helper_state_path'])
        shutil.copy2(source,target/'helper-state.json')
        state_raw=(target/'broker-state.json').read_bytes() if (target/'broker-state.json').is_file() else b''
        helper_raw=(target/'helper-state.json').read_bytes()
        scheduler_raw=(target/'scheduler-times.json').read_bytes() if (target/'scheduler-times.json').is_file() else b''
        state=json.loads((base/'broker-state.json').read_text())
        selection_doc=json.loads((target/'selection.json').read_text())
        selection_sha=hashlib.sha256(canonical(selection_doc)).hexdigest()
        if state.get('submit_called') is not True or state.get('submit_exit_code')!=0:
            raise RuntimeError('root capture cannot export a job without a successful owned submission')
        if selection_doc.get('admission_id')!=state.get('admission_id'):
            raise RuntimeError('root capture resource selection is not bound to its admission')
        probe_doc=json.loads((target/'probe.json').read_text())
        if (probe_doc.get('host')!=selection_doc.get('resource_id')
                or probe_doc.get('request_partition')!=selection_doc.get('partition')):
            raise RuntimeError('root capture probe differs from its frozen resource selection')
        jobs.append({'trial_name':trial,'helper_job_name':state.get('helper_job_name'),'job_id':item['job_id'],'terminal_state':item['terminal_state'],
            'broker_state_sha256':hashlib.sha256(state_raw).hexdigest() if state_raw else None,
            'helper_state_sha256':hashlib.sha256(helper_raw).hexdigest(),
            'scheduler_times_sha256':hashlib.sha256(scheduler_raw).hexdigest() if scheduler_raw else None,
            'selection_sha256':selection_sha})
    files=tree_inventory(dest)
    return {'schema':'case06-root-hpc-broker-capture/v1','jobs':jobs,'files':files,
        'tree_sha256':hashlib.sha256(canonical(files)).hexdigest()}

def _hpc_dispatch(req):
    if not isinstance(req,dict) or req.get('schema')!='case06-hpc-broker-request/v1':
        raise RuntimeError('unsupported broker request schema')
    start_doc=json.loads((STATE/'start.json').read_text())
    if req.get('attempt_id')!=start_doc.get('attempt_id'): raise RuntimeError('broker request attempt binding failed')
    trial=req.get('trial_name');args=req.get('args')
    if not isinstance(trial,str) or not isinstance(args,list) or not all(isinstance(x,str) for x in args):
        raise RuntimeError('broker request fields are malformed')
    action=args[0] if args else ''
    if action not in {'resources','probe','submit','status','wait','collect','cancel'}: raise RuntimeError('broker action is not allowed')
    if action=='resources':
        values=_hpc_args_map(args[1:],{'--resource-id'},set())
        resource_id=values['--resource-id']
        if resource_id not in _authorized_resource_ids(): raise RuntimeError('resource id is not in the root-authorized SSH alias set')
        if req.get('selection') is not None or req.get('admission_id') is not None:
            raise RuntimeError('resource discovery does not accept an admission or candidate selection')
        script=(
            "set +e; printf '__PARTITIONS_BEGIN__\\n'; "
            "sinfo --noheader --format='%P|%a|%l|%G'; sinfo_rc=$?; "
            "printf '\\n__PARTITIONS_END__\\n__SINFO_RC__=%s\\n' \"$sinfo_rc\"; "
            "printf '\\n__LMP__='; command -v lmp || command -v lmp_mpi || true; "
            "printf '\\n__MODULES_BEGIN__\\n'; "
            "if type module >/dev/null 2>&1; then "
            "if [ -d \"$HOME/modulefiles\" ]; then module use \"$HOME/modulefiles\"; fi; "
            "module -t avail 2>&1; fi; printf '\\n__MODULES_END__\\n'")
        remote=_root_ssh(resource_id,'bash -lc '+shlex.quote(script),60)
        text=remote.stdout
        begin='__PARTITIONS_BEGIN__\n';end='\n__PARTITIONS_END__\n'
        partitions=[];sinfo_rc=None;python_path=None;lmp_path=None
        if begin in text and end in text:
            body=text.split(begin,1)[1].split(end,1)[0]
            for line in body.splitlines():
                fields=line.split('|',3)
                if len(fields)!=4: continue
                name=fields[0].rstrip('*')
                if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}',name): continue
                partitions.append({'name':name,'default':fields[0].endswith('*'),'availability':fields[1],
                    'time_limit':fields[2],'gres':fields[3]})
            for line in text.splitlines():
                if line.startswith('__SINFO_RC__='):
                    try: sinfo_rc=int(line.split('=',1)[1])
                    except ValueError: pass
                elif line.startswith('__PYTHON__='):
                    candidate=line.split('=',1)[1].strip()
                    python_path=candidate if _valid_remote_path(candidate) else None
                elif line.startswith('__LMP__='):
                    candidate=line.split('=',1)[1].strip()
                    lmp_path=candidate if _valid_remote_path(candidate) else None
        module_block=text.partition('__MODULES_BEGIN__\n')[2].partition('\n__MODULES_END__')[0]
        available_modules=sorted({m for m in re.findall(r'[A-Za-z0-9][A-Za-z0-9._+/-]*',module_block)
            if re.search(r'(?:^|/)(?:lammps|calphy)(?:[/_-]|$)',m,re.I)})
        result={'status':'DISCOVERED_UNQUALIFIED','resource_id':resource_id,'partitions':partitions,
            'default_runtime_paths':{'python3':python_path,'lmp':lmp_path},
            'available_runtime_modules':available_modules,
            'partition_query_status':'OK' if remote.returncode==0 and sinfo_rc==0 and partitions else 'UNAVAILABLE',
            'runtime_qualification':'NOT_QUALIFIED'}
        return {'returncode':0 if remote.returncode==0 else 2,
            'stdout':json.dumps(result,sort_keys=True,separators=(',',':'))+'\n',
            'stderr':remote.stderr[-4000:]}

    selection=None;admission_id=None
    if action=='probe':
        selection=_resolve_selection(req.get('selection'),start_doc,trial)
        selection['admission_id']=uuid.uuid4().hex
        with HPC_LOCK: base,helper=_hpc_root(trial,selection)
        expected=['probe','--host',selection['resource_id'],'--partition',selection['partition'],'--json','--detail']
        if args!=expected: raise RuntimeError('probe arguments differ from the root-validated selection')
    else:
        with HPC_LOCK: base,helper=_hpc_root(trial)
        selection_path=base/'selection.json'
        if selection_path.is_symlink() or not selection_path.is_file(): raise RuntimeError('root admission is missing')
        selection=json.loads(selection_path.read_text())
        admission_id=selection.get('admission_id')
        if req.get('admission_id')!=admission_id: raise RuntimeError('resource admission id is not bound to this attempt')
        if req.get('selection') is not None and req.get('selection')!=selection: raise RuntimeError('resource selection changed after admission')
    result=None;helper_state_path=None;helper_job=None
    if action=='probe':
        result=_hpc_run(helper,args,240)
        if result.returncode==0:
            try: snapshot=json.loads(result.stdout)
            except Exception as exc: raise RuntimeError('selected resource probe did not return valid JSON') from exc
            digest=snapshot.get('snapshot_sha256')
            if (snapshot.get('host')!=selection['resource_id'] or snapshot.get('request_partition')!=selection['partition']
                    or not isinstance(digest,str) or not re.fullmatch(r'[0-9a-f]{64}',digest)):
                raise RuntimeError('resource probe snapshot does not bind the selected endpoint and partition')
            probe=base/'probe.json';probe.write_text(result.stdout,encoding='utf-8');os.chmod(probe,0o400)
            atomic(base/'selection.json',canonical(selection)+b'\n',0o400)
            admission_id=selection['admission_id']
    elif action=='submit':
        value_names={'--target','--name','--cmd','--reason-file','--probe-snapshot','--snapshot-sha256','--src','--workdir','--partition','--nodes','--ntasks','--ntasks-per-node','--cpus','--mem','--gpus','--time'}
        values=_hpc_args_map(args[1:],value_names,{'--dry-run'})
        target=selection['target_name'];resource=selection['resources'];part=selection['partition']
        attempt_base=selection['remote_base']+'/'+start_doc['attempt_id']
        if (values['--target']!=target or values['--name']!=trial or values['--partition']!=part
                or values['--workdir']!=attempt_base+'/'+trial): raise RuntimeError('submit differs from the root-frozen resource admission')
        expected_values=(('--nodes',str(resource['nodes'])),('--ntasks',str(resource['ntasks'])),
            ('--ntasks-per-node',str(resource['ntasks'])),('--cpus',str(resource['cpus'])),
            ('--mem',f"{resource['memory_mb']}M"),('--gpus',str(resource['gpus'])))
        if any(values[k]!=v for k,v in expected_values): raise RuntimeError('submit resources differ from the root-frozen admission')
        try: hours,minutes,seconds=map(int,values['--time'].split(':'))
        except Exception as exc: raise RuntimeError('submit walltime is malformed') from exc
        wall=hours*3600+minutes*60+seconds
        remaining=int(json.loads((STATE/'public-attempt.json').read_text())['deadline_monotonic_ns']-time.monotonic_ns())//1_000_000_000
        if (wall<=0 or wall>43200 or wall>remaining-300 or wall>int(selection['resources']['wall_seconds'])): raise RuntimeError('submit walltime exceeds the frozen selection or remaining attempt allowance')
        probe_path=base/'probe.json'
        if not probe_path.is_file(): raise RuntimeError('fresh root broker probe is required before submit')
        probe=json.loads(probe_path.read_text())
        if values['--snapshot-sha256']!=probe.get('snapshot_sha256'): raise RuntimeError('submit does not bind the fresh broker probe')
        candidate_probe=Path(values['--probe-snapshot'])
        if candidate_probe.is_symlink() or not candidate_probe.is_file(): raise RuntimeError('candidate probe source is not a regular file')
        candidate_probe=candidate_probe.resolve(strict=True);candidate_probe.relative_to(OUTPUT_ROOT.resolve(strict=True))
        candidate_probe_stat=candidate_probe.stat()
        if candidate_probe_stat.st_uid!=pwd.getpwnam('researcher').pw_uid or candidate_probe_stat.st_nlink!=1: raise RuntimeError('candidate probe source owner/link count is invalid')
        if candidate_probe.read_bytes()!=probe_path.read_bytes(): raise RuntimeError('candidate probe bytes differ from the root broker snapshot')
        payload=base/'payload'
        if payload.exists():
            if payload.is_symlink() or tree_inventory(payload)!=tree_inventory(Path(values['--src']).resolve()): raise RuntimeError('candidate payload changed after root copy')
        else: _hpc_safe_tree(values['--src'],payload)
        runtime=selection['runtime']
        if runtime.get('capability_check')=='compute_node':
            lmp=shlex.quote(runtime['lmp'])
            modules=runtime['modules']
            prepare=['if [ -d "$HOME/modulefiles" ]; then module use "$HOME/modulefiles"; fi'] if modules else []
            prepare.extend('module load '+shlex.quote(m) for m in modules)
            prepare.extend([
                f'digest=$(sha256sum -- {lmp})',
                'test "${digest%% *}" = '+shlex.quote(runtime['lmp_sha256']),
                f'help=$({lmp} -h 2>&1)',
                'printf "%s" "$help" | grep -Fq pace/kk',
                'printf "%s" "$help" | grep -Fq ti/spring',
            ])
            values['--cmd']='bash -lc '+shlex.quote('set -e; '+'; '.join(prepare)+'\n'+values['--cmd'])
        reason=base/'reason.txt'
        reason_bytes=b'Task 159 candidate campaign through root-owned helper broker.\n'
        if reason.is_symlink(): raise RuntimeError('root helper reason file cannot be a symlink')
        if reason.exists():
            if not reason.is_file() or reason.read_bytes()!=reason_bytes: raise RuntimeError('root helper reason bytes changed')
        else:
            atomic(reason,reason_bytes,0o400)
        remote_base=values['--workdir'].rsplit('/',1)[0]
        src_sha=hashlib.sha256(json.dumps(tree_inventory(payload),sort_keys=True,separators=(',',':')).encode()).hexdigest()
        plan={'target':target,'selection_sha256':hashlib.sha256(canonical(selection)).hexdigest(),'name':trial,'cmd':values['--cmd'],'workdir':values['--workdir'],
            'snapshot_sha256':values['--snapshot-sha256'],'payload_sha256':src_sha,'walltime':values['--time']}
        plan_sha=hashlib.sha256(json.dumps(plan,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        state_path=base/'broker-state.json';state=json.loads(state_path.read_text()) if state_path.is_file() else {}
        if state.get('submit_called') is True: raise RuntimeError('this logical candidate job already submitted')
        helper_job=state.get('helper_job_name')
        if not isinstance(helper_job,str):
            helper_job=_hpc_next_job_name(start_doc['attempt_id'])
        plan={'target':target,'selection_sha256':hashlib.sha256(canonical(selection)).hexdigest(),'name':helper_job,'alias':trial,'cmd':values['--cmd'],'workdir':values['--workdir'],
            'snapshot_sha256':values['--snapshot-sha256'],'payload_sha256':src_sha,'walltime':values['--time']}
        plan_sha=hashlib.sha256(json.dumps(plan,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        if '--dry-run' in values:
            if state.get('plan_sha256') not in (None,plan_sha): raise RuntimeError('candidate dry-run plan changed for this logical job')
            result=_hpc_run(helper,['submit','--target',target,'--name',helper_job,'--cmd',values['--cmd'],
                '--reason-file',str(reason),'--probe-snapshot',str(probe_path),'--snapshot-sha256',values['--snapshot-sha256'],
                '--src',str(payload),'--workdir',values['--workdir'],'--partition',part,'--nodes',str(resource['nodes']),'--ntasks',str(resource['ntasks']),
                '--ntasks-per-node',str(resource['ntasks']),'--cpus',str(resource['cpus']),'--mem',f"{resource['memory_mb']}M",'--gpus',str(resource['gpus']),'--time',values['--time'],'--dry-run'],300)
            state.update({'trial_name':trial,'helper_job_name':helper_job,'plan_sha256':plan_sha,
                'admission_id':selection.get('admission_id'),
                'selection_sha256':hashlib.sha256(canonical(selection)).hexdigest(),
                'dry_run_exit_code':result.returncode,'submit_called':False})
            atomic(state_path,json.dumps(state,sort_keys=True).encode()+b'\n',0o400)
        else:
            if state.get('plan_sha256')!=plan_sha or state.get('dry_run_exit_code')!=0:
                raise RuntimeError('matching successful root broker dry-run is required')
            with HPC_SUBMIT_LOCK:
                if state.get('submit_called') is True: raise RuntimeError('this logical candidate job already submitted')
                for other in sorted((STATE/'hpc').iterdir()):
                    if other.name==trial or not other.is_dir(): continue
                    other_path=other/'broker-state.json'
                    if not other_path.is_file(): continue
                    other_state=json.loads(other_path.read_text())
                    if other_state.get('submit_called') is not True: continue
                    other_job=str(other_state.get('job_id') or '')
                    if other_state.get('submit_exit_code')!=0 or not other_job:
                        raise RuntimeError('previous root allocation is active or has unknown identity')
                    observed=_persist_scheduler_observation(other,other_job)
                    terminal={'COMPLETED','FAILED','CANCELLED','CANCELLED_BY_0','TIMEOUT','OUT_OF_MEMORY','NODE_FAIL','PREEMPTED','BOOT_FAIL','DEADLINE','REVOKED','SPECIAL_EXIT'}
                    if (observed.get('status')!='OBSERVED' or observed.get('restart_count')!=0
                            or str(observed.get('state','')).upper() not in terminal):
                        raise RuntimeError('previous root allocation is active or its terminal source is unknown')
                with HPC_LOCK:
                    state.update({'trial_name':trial,'helper_job_name':helper_job,'plan_sha256':plan_sha,
                        'admission_id':selection.get('admission_id'),
                        'selection_sha256':hashlib.sha256(canonical(selection)).hexdigest(),
                        'submit_called':True,'submit_exit_code':None})
                    atomic(state_path,json.dumps(state,sort_keys=True).encode()+b'\n',0o400)
            result=_hpc_run(helper,['submit','--target',target,'--name',helper_job,'--cmd',values['--cmd'],
                '--reason-file',str(reason),'--probe-snapshot',str(probe_path),'--snapshot-sha256',values['--snapshot-sha256'],
                '--src',str(payload),'--workdir',values['--workdir'],'--partition',part,'--nodes',str(resource['nodes']),'--ntasks',str(resource['ntasks']),
                '--ntasks-per-node',str(resource['ntasks']),'--cpus',str(resource['cpus']),'--mem',f"{resource['memory_mb']}M",'--gpus',str(resource['gpus']),'--time',values['--time']],300)
            try: submitted=json.loads(result.stdout)
            except Exception: submitted={}
            job_id=submitted.get('job_id') or submitted.get('jobid') or submitted.get('id')
            with HPC_LOCK:
                state.update({'trial_name':trial,'helper_job_name':helper_job,'plan_sha256':plan_sha,
                    'admission_id':selection.get('admission_id'),
                    'selection_sha256':hashlib.sha256(canonical(selection)).hexdigest(),
                    'submit_called':True,'job_id':str(job_id) if job_id else None,'submit_exit_code':result.returncode})
                atomic(state_path,json.dumps(state,sort_keys=True).encode()+b'\n',0o400)
            helper_state_path=helper/'.submit-job'/f'{helper_job}.json'
            if result.returncode==0 and state.get('job_id'):
                try: _persist_scheduler_observation(base,str(state['job_id']))
                except Exception: pass
    else:
        if action in ('status','wait','cancel','collect'):
            names={'status':{'--job'},'wait':{'--job','--poll','--timeout'},'cancel':{'--job'},'collect':{'--job','--dest','--allow-unsuccessful'}}[action]
            flags={'--allow-unsuccessful'} if action=='collect' else set()
            values=_hpc_args_map(args[1:],names,flags)
            state_path=base/'broker-state.json'
            if not state_path.is_file(): raise RuntimeError('no root-owned submission exists for this logical name')
            state=json.loads(state_path.read_text())
            helper_job=state.get('helper_job_name')
            if (state.get('trial_name')!=trial or state.get('submit_called') is not True
                    or state.get('submit_exit_code')!=0 or not state.get('job_id')
                    or not isinstance(helper_job,str) or values['--job']!=helper_job):
                raise RuntimeError('lifecycle job identity is not bound to this root-owned attempt')
            helper_state=helper/'.submit-job'/f'{helper_job}.json'
            if not helper_state.is_file(): raise RuntimeError('root helper state is missing')
            helper_state_path=helper_state
            saved=json.loads(helper_state.read_text())
            if saved.get('name')!=helper_job or str(saved.get('job_id'))!=state['job_id']:
                raise RuntimeError('helper state differs from root-owned logical/numeric job binding')
            if action=='collect':
                requested=Path(values['--dest'])
                output_root=OUTPUT_ROOT.resolve(strict=True)
                if requested.is_symlink(): raise RuntimeError('collect destination cannot be a symlink')
                requested=requested.resolve(strict=False);requested.relative_to(output_root)
                if requested.exists(): raise RuntimeError('collect destination already exists')
                actual=base/'collected';
                if actual.exists(): raise RuntimeError('root collect destination already used')
                call=['collect','--job',helper_job,'--dest',str(actual),'--allow-unsuccessful']
            elif action=='wait':
                try: timeout=int(values['--timeout']);poll=int(values['--poll'])
                except Exception as exc: raise RuntimeError('wait budget is malformed') from exc
                remaining=(int(json.loads((STATE/'public-attempt.json').read_text())['deadline_monotonic_ns'])-time.monotonic_ns())//1_000_000_000
                if timeout<1 or timeout>604800 or poll<1 or poll>60: raise RuntimeError('wait budget exceeds the seven-day root-captured wall safety cap')
                call=['wait','--job',helper_job,'--poll',str(poll),'--timeout',str(timeout)]
            else: call=[action,'--job',helper_job]
            result=_hpc_run(helper,call,timeout+60 if action=='wait' else 3600 if action=='collect' else 300,
                monitor_base=base if action=='wait' else None,monitor_job=state['job_id'] if action=='wait' else None)
            if action in ('status','wait','collect'):
                try: _persist_scheduler_observation(base,str(state['job_id']))
                except Exception: pass
            if action=='collect' and result.returncode==0:
                tree_inventory(actual)
                shutil.copytree(actual,requested,symlinks=False)
                agent=pwd.getpwnam('researcher')
                os.chown(requested,agent.pw_uid,agent.pw_gid);os.chmod(requested,0o700)
                for path in requested.rglob('*'):
                    if path.is_symlink(): raise RuntimeError('collected HPC output contains a symlink')
                    if path.is_file(): os.chown(path,agent.pw_uid,agent.pw_gid)
                    elif path.is_dir(): os.chown(path,agent.pw_uid,agent.pw_gid)
    if result is None: raise RuntimeError('broker did not produce a helper result')
    raw={'action':action,'trial_name':trial,'returncode':result.returncode,
         'stdout_sha256':hashlib.sha256(result.stdout.encode()).hexdigest(),
         'stderr_sha256':hashlib.sha256(result.stderr.encode()).hexdigest(),
         'recorded_utc':utc()}
    log=base/('rpc-'+str(time.time_ns())+'.json')
    log.write_text(json.dumps(raw,sort_keys=True)+'\n');os.chmod(log,0o400)
    response={'returncode':result.returncode,'stdout':result.stdout,'stderr':result.stderr[-4000:],
        'helper_job_name':helper_job or (state.get('helper_job_name') if isinstance(locals().get('state'),dict) else None)}
    if action=='probe' and result.returncode==0:
        response.update({'selection':selection,'admission_id':admission_id})
    if helper_state_path is not None and helper_state_path.is_file() and not helper_state_path.is_symlink():
        response['helper_state_base64']=base64.b64encode(helper_state_path.read_bytes()).decode('ascii')
    return response

def _hpc_connection(conn):
    global HPC_ACTIVE
    counted=False
    try:
        peer=conn.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,struct.calcsize('3i'))
        _pid,uid,_gid=struct.unpack('3i',peer)
        if uid!=pwd.getpwnam('researcher').pw_uid: raise RuntimeError('broker peer UID is not researcher')
        size=struct.unpack('!I',_hpc_read_exact(conn,4))[0]
        if size<=0 or size>1_000_000: raise RuntimeError('broker request size is outside bounds')
        req=json.loads(_hpc_read_exact(conn,size))
        with HPC_COND:
            if HPC_STOPPING: raise RuntimeError('root broker is sealing this Harbor attempt')
            HPC_ACTIVE+=1;counted=True
        HPC_CLIENT.socket=conn
        response=_hpc_dispatch(req)
    except BaseException as exc:
        response={'returncode':2,'stdout':'','stderr':f'root broker rejected request: {type(exc).__name__}: {exc}'}
    finally:
        if counted:
            with HPC_COND:
                HPC_ACTIVE-=1;HPC_COND.notify_all()
        if hasattr(HPC_CLIENT,'socket'): del HPC_CLIENT.socket
    raw=json.dumps(response,sort_keys=True,separators=(',',':')).encode()
    try: conn.sendall(struct.pack('!I',len(raw))+raw)
    except OSError: pass
    conn.close()

def _hpc_stop_and_drain():
    global HPC_STOPPING
    deadline=time.monotonic()+60
    with HPC_COND:
        HPC_STOPPING=True
        while HPC_ACTIVE and time.monotonic()<deadline:
            HPC_COND.wait(min(.25,deadline-time.monotonic()))
        if HPC_ACTIVE: raise RuntimeError('root broker RPCs did not drain before output freeze')

def _hpc_server():
    if not HELPER_PYTHON.is_file() or not (_helper_root()/'scripts'/'submit.py').is_file():
        raise RuntimeError('fixed HPC helper runtime is missing')
    help_run=subprocess.run([str(HELPER_PYTHON),'-B','-I',str(_helper_root()/'scripts'/'submit.py'),'--help'],
        env={**os.environ,'HOME':'/root','PATH':'/opt/si-ox-runtime/bin:/usr/bin:/bin'},capture_output=True,text=True,timeout=30)
    if help_run.returncode!=0: raise RuntimeError('fixed HPC helper --help import check failed')
    HPC_SOCKET.unlink(missing_ok=True)
    listener=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
    listener.bind(str(HPC_SOCKET));os.chown(HPC_SOCKET,0,grp.getgrnam('case159agent').gr_gid);os.chmod(HPC_SOCKET,0o660);listener.listen(8);listener.setblocking(False)
    while True:
        ready,_,_=select.select([listener],[],[],1.0)
        if not ready: continue
        conn,_=listener.accept()
        threading.Thread(target=_hpc_connection,args=(conn,),daemon=True).start()

def start():
    if os.geteuid() != 0: raise SystemExit('root capture must run as root')
    if STATE.is_symlink(): raise RuntimeError('runtime capture directory cannot be a symlink')
    STATE.mkdir(mode=0o710, parents=True, exist_ok=True)
    if any(STATE.iterdir()): raise RuntimeError('runtime capture directory is not fresh')
    os.chown(STATE, 0, grp.getgrnam('case159agent').gr_gid); os.chmod(STATE, 0o710)
    key = os.urandom(32)
    atomic(STATE / 'signing.key', key, 0o400)
    doc = {'schema':'case06-native-main-clock/v1', 'status':'RUNNING',
        'attempt_id':uuid.uuid4().hex, 'nonce':os.urandom(32).hex(),
        'start_utc':utc(), 'start_monotonic_ns':time.monotonic_ns(),
        'limit_seconds':LIMIT, 'input_identity':task_inputs()}
    atomic(STATE / 'start.json', canonical(doc) + b'\n', 0o400)
    deadline = doc['start_monotonic_ns'] + LIMIT * 1_000_000_000
    wall_deadline = doc['start_monotonic_ns'] + 604800 * 1_000_000_000
    public = {'schema':'case06-native-main-clock-public/v1','attempt_id':doc['attempt_id'],
        'deadline_monotonic_ns':deadline,
        'deadline_epoch':int(datetime.fromisoformat(doc['start_utc'].replace('Z','+00:00')).timestamp()) + LIMIT,
        'resource_ids':sorted(_authorized_resource_ids()),
        'queue_credit_status':'VALIDATED','queue_credit_seconds':0,'queue_credit_intervals':[],
        'queue_credit_source_sha256':hashlib.sha256(canonical([])).hexdigest()}
    atomic(STATE / 'public-attempt.json', canonical(public) + b'\n', 0o444)
    os.chown(STATE, 0, grp.getgrnam('case159agent').gr_gid); os.chmod(STATE, 0o711)
    broker=threading.Thread(target=_hpc_server,daemon=True);broker.start()
    until=time.monotonic()+30
    while not HPC_SOCKET.exists() and broker.is_alive() and time.monotonic()<until: time.sleep(.05)
    if not HPC_SOCKET.exists(): raise RuntimeError('fixed root HPC broker did not become ready')
    while True:
        try: deadline=int(json.loads((STATE/'public-attempt.json').read_text())['deadline_monotonic_ns'])
        except Exception: deadline=doc['start_monotonic_ns']+LIMIT*1_000_000_000
        if time.monotonic_ns() >= wall_deadline:
            kill_researcher();atomic(STATE/'wall-cap-expired.json',canonical({'attempt_id':doc['attempt_id'],'expired_utc':utc()})+b'\n');time.sleep(3600)
        if time.monotonic_ns() >= deadline:
            kill_researcher()
            atomic(STATE / 'expired.json', canonical({'attempt_id':doc['attempt_id'], 'expired_utc':utc()}) + b'\n')
            time.sleep(3600)
        time.sleep(min(1.0, max(.01, (deadline - time.monotonic_ns()) / 1e9)))

def collect():
    if os.geteuid() != 0: raise SystemExit('collector must run as root')
    if not (STATE / 'start.json').is_file() or not (STATE / 'signing.key').is_file():
        raise RuntimeError('root attempt capture is missing')
    start_doc = json.loads((STATE / 'start.json').read_text())
    if start_doc.get('status') != 'RUNNING': raise RuntimeError('attempt capture already collected')
    kill_researcher()
    _hpc_stop_and_drain()
    owned_jobs=_hpc_cancel_owned_jobs()
    end_ns, end_utc = time.monotonic_ns(), utc()
    elapsed = (end_ns - int(start_doc['start_monotonic_ns'])) / 1e9
    public=json.loads((STATE/'public-attempt.json').read_text())
    queue_credit=float(public.get('queue_credit_seconds',0.0)) if public.get('queue_credit_status')=='VALIDATED' else 0.0
    active_upper=max(0.0,elapsed-queue_credit)
    if elapsed > 604800 + 1: raise RuntimeError('root-captured attempt exceeded its seven-day wall safety cap')
    if active_upper > LIMIT + 1: raise RuntimeError('root-captured active attempt exceeded its 12-hour budget')
    source = Path('/app/outputs')
    target = ARTIFACTS / 'app' / 'outputs'
    if target.exists(): raise RuntimeError('root output snapshot already exists')
    ARTIFACTS.mkdir(mode=0o700, parents=True, exist_ok=True); os.chmod(ARTIFACTS, 0o700)
    target.parent.mkdir(mode=0o700)
    target.mkdir(mode=0o700)
    if source.exists():
        inventory = tree_inventory(source)
        for item in source.iterdir():
            dest = target / item.name
            if item.is_dir(): shutil.copytree(item, dest, symlinks=False)
            elif item.is_file(): shutil.copy2(item, dest, follow_symlinks=False)
        for item in target.rglob('*'):
            if item.is_symlink(): raise RuntimeError('frozen output contains a symlink')
            if item.is_file(): os.chown(item, 0, 0); os.chmod(item, 0o400)
            elif item.is_dir(): os.chown(item, 0, 0); os.chmod(item, 0o700)
    else: inventory = []
    frozen = tree_inventory(target)
    if frozen != inventory: raise RuntimeError('root output snapshot differs from candidate source at freeze')
    doc = {**start_doc, 'status':'FROZEN', 'end_utc':end_utc,
        'end_monotonic_ns':end_ns, 'wall_elapsed_seconds':elapsed,
        'queue_credit_status':public.get('queue_credit_status','UNKNOWN'),
        'queue_credit_seconds':queue_credit,
        'queue_credit_intervals':public.get('queue_credit_intervals',[]),
        'queue_credit_source_sha256':public.get('queue_credit_source_sha256'),
        'candidate_active_upper_seconds':active_upper,
        'candidate_outputs':{'path':'app/outputs', 'files':frozen,
            'tree_sha256':hashlib.sha256(canonical(frozen)).hexdigest()}}
    doc['hpc_broker_capture']=_hpc_export_trusted(owned_jobs)
    key = (STATE / 'signing.key').read_bytes()
    doc['hmac_sha256'] = hmac.new(key, canonical(doc), hashlib.sha256).hexdigest()
    trusted = ARTIFACTS / 'trusted'; trusted.mkdir(mode=0o700,exist_ok=True); os.chmod(trusted,0o700)
    atomic(trusted / 'attempt.json', canonical(doc) + b'\n', 0o400)
    atomic(trusted / 'capture.key', key, 0o400)
    print(json.dumps({'status':'FROZEN','attempt_id':doc['attempt_id'],
        'wall_elapsed_seconds':elapsed,'output_file_count':len(frozen)}, sort_keys=True))

role = os.environ.get('CCB_BENCH24_159_ROLE')
if len(sys.argv) > 1 and sys.argv[1] == 'collect': collect()
elif role == 'verifier':
    while True: time.sleep(60)
elif role == 'agent': start()
else: raise SystemExit('CCB_BENCH24_159_ROLE must be agent or verifier')
PY

RUN chmod 0555 /opt/bench24-159/root-capture.py \
    && groupadd --gid 10001 case159agent \
    && useradd --uid 10001 --gid 10001 --create-home --shell /bin/bash researcher \
    && install -d -o researcher -g case159agent -m 0750 /app/outputs /app/workspace \
    && install -d -o root -g root -m 0700 /trusted /app/bench24-artifacts \
    && (rm -f /usr/bin/sudo /usr/sbin/sudo /bin/su /usr/bin/su /usr/bin/pkexec /etc/sudoers.d/* || true)

ENTRYPOINT ["/usr/bin/python3", "-B", "-I", "/opt/bench24-159/root-capture.py"]
