import asyncio,json,tempfile,tomllib,unittest,sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import harbor_runtime as r
from harbor.models.task.config import TaskConfig
from harbor.models.trial.paths import TrialPaths
from harbor.trial.hooks import TrialEvent
ROOT=Path(__file__).resolve().parents[4]
class LifecycleTests(unittest.TestCase):
 def environment(self,base,verifier=False):
  task=ROOT/'task 18';cfg=TaskConfig.model_validate_toml((task/'task.toml').read_text())
  return r.Bench03DockerEnvironment(environment_dir=task/('tests' if verifier else 'environment'),environment_name='offline-case05',session_id='offline__verifier__fixture' if verifier else 'offline__env__fixture',trial_paths=TrialPaths(trial_dir=base),task_env_config=cfg.verifier.environment if verifier else cfg.environment)
 def test_case_identity(self):
  self.assertTrue(r.active(ROOT/'task 18'));self.assertFalse(r.active(ROOT/'task 14'))
 def test_no_archive_reference(self):
  text=Path(r.__file__).read_text();self.assertNotIn('.release-work',text);self.assertNotIn('/provenance',text)
 def test_lifecycle_mode(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);env=self.environment(p);hooks={}
   job=SimpleNamespace(add_hook=lambda event,callback:hooks.__setitem__(event,callback))
   asyncio.run(r.Bench03SlurmPlugin().on_job_start(job))
   event=SimpleNamespace(config=SimpleNamespace(trials_dir=p.parent,trial_name=p.name,agent=SimpleNamespace(name='nop')))
   asyncio.run(hooks[TrialEvent.ENVIRONMENT_START](event));self.assertEqual(env.state['mode'],'agent')
 def test_verifier_receives_no_candidate_environment(self):
  with tempfile.TemporaryDirectory() as d:
   candidate=self.environment(Path(d));candidate._persistent_env['SSH_AUTH_SOCK']='candidate-only'
   verifier=self.environment(Path(d),True)
   self.assertNotIn('SSH_AUTH_SOCK',verifier._persistent_env);self.assertEqual(verifier._host_mounts,[])
 def test_missing_seal_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   env=self.environment(Path(d),True);env.state['mode']='agent'
   with self.assertRaisesRegex(RuntimeError,'not sealed'):asyncio.run(env.start())
 def test_blocked_queue_is_infrastructure(self):
  with tempfile.TemporaryDirectory() as d:
   env=self.environment(Path(d),True);env.state.update(mode='agent',sealed=True,blockage='HPC_QUEUE_BLOCKED')
   with self.assertRaisesRegex(RuntimeError,'infrastructure'):asyncio.run(env.start())
 def test_redirection_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);(p/'link').symlink_to('/tmp')
   with self.assertRaises(RuntimeError):r.tree_hashes(p)
 def test_artifact_transfer_mismatch_rejected_before_seal(self):
  with tempfile.TemporaryDirectory() as d:
   base=Path(d);env=self.environment(base);env.cid='unit-test-no-container'
   env.state.update(support_sha=r.support_hashes(),runtime_sha=r.core.digest(Path(r.__file__)),core_sha=r.core.digest(Path(r.core.__file__)),source_task_sha256=r.core.digest(ROOT/'task 18/task.toml'))
   (base/'artifacts/app/final').mkdir(parents=True);(base/'artifacts/app/final/data').write_text('changed copy')
   def export(cid,artifacts,dest,**kwargs):
    (dest/'final').mkdir(parents=True);(dest/'final/data').write_text('original');return []
   with patch.object(r,'export_declared_artifacts',side_effect=export),patch.object(r.core,'seal') as seal:
    with self.assertRaisesRegex(RuntimeError,'artifact copy differs'):env.seal()
    seal.assert_not_called()


class TrustedTransportTests(unittest.TestCase):
 def test_transport_is_attempt_scoped_and_preserves_bytes_and_timeout(self):
  import subprocess
  first=r.TrustedTransport('helper-one','sha256:'+'a'*64)
  second=r.TrustedTransport('helper-two','sha256:'+'b'*64)
  self.assertNotEqual(first.command(['python3','-']),second.command(['python3','-']))
  with patch.object(r.core.subprocess,'run',return_value=subprocess.CompletedProcess([],0,b'\x00payload',b'')) as call:
   self.assertEqual(r.core.remote('print(1)',transport=first,timeout=123),b'\x00payload')
   self.assertEqual(call.call_args.args[0],['docker','exec','-i','helper-one','ssh','-o','BatchMode=yes','-o','ConnectTimeout=15','ikkem',"python3 -"])
   self.assertNotIn('StrictHostKeyChecking=yes',call.call_args.args[0])
   self.assertEqual(call.call_args.kwargs['input'],b'print(1)')
   self.assertEqual(call.call_args.kwargs['timeout'],123)
 def test_helper_uses_immutable_image_without_candidate_mounts(self):
  import subprocess
  image='sha256:'+'c'*64
  with patch.object(r.subprocess,'run',return_value=subprocess.CompletedProcess([],0,'helper-cid\n','')) as call:
   transport=r.start_trusted_helper(image,'ccb05-trusted-attempt')
  argv=call.call_args.args[0]
  self.assertEqual(argv,['docker','run','-d','--name','ccb05-trusted-attempt','--entrypoint','sleep',image,'infinity'])
  self.assertNotIn('-v',argv);self.assertNotIn('--mount',argv)
  self.assertEqual(transport.image_id,image)
 def test_start_failure_removes_helper_and_stops_candidate(self):
  async def ok_start(self,*args,**kwargs): return None
  async def get_container(self): return 'candidate-cid'
  async def stop_base(self,delete=False): stopped.append(delete)
  with tempfile.TemporaryDirectory() as d:
   stopped=[];env=LifecycleTests().environment(Path(d));env.state['mode']='agent'
   def fail_site(*args,**kwargs): raise RuntimeError('site probe failed')
   helper=r.TrustedTransport('helper-cid','sha256:'+'d'*64)
   with patch.object(r.DockerEnvironment,'start',new=ok_start),patch.object(r.Bench03DockerEnvironment,'main_container',new=get_container),patch.object(r.subprocess,'run',return_value=SimpleNamespace(stdout=helper.image_id+'\n')),patch.object(r,'start_trusted_helper',return_value=helper),patch.object(r.core,'remote',new=fail_site),patch.object(r,'remove_trusted_helper') as remove,patch.object(r.DockerEnvironment,'stop',new=stop_base):
    with self.assertRaisesRegex(RuntimeError,'site probe'):
     asyncio.run(env.start())
    remove.assert_called_once_with('helper-cid',check=True)
   self.assertEqual(stopped,[True])
   self.assertIsNone(env.transport);self.assertIsNone(env.helper_id)
 def test_start_failure_preserves_helper_for_stop_retry(self):
  async def ok_start(self,*args,**kwargs): return None
  async def get_container(self): return 'candidate-cid'
  async def stop_base(self,delete=False): return None
  with tempfile.TemporaryDirectory() as d:
   env=LifecycleTests().environment(Path(d));env.state['mode']='agent'
   def fail_site(*args,**kwargs): raise RuntimeError('site probe failed')
   helper=r.TrustedTransport('helper-cid','sha256:'+'f'*64)
   with patch.object(r.DockerEnvironment,'start',new=ok_start),patch.object(r.Bench03DockerEnvironment,'main_container',new=get_container),patch.object(r.subprocess,'run',return_value=SimpleNamespace(stdout=helper.image_id+'\n')),patch.object(r,'start_trusted_helper',return_value=helper),patch.object(r.core,'remote',new=fail_site),patch.object(r,'remove_trusted_helper',side_effect=[RuntimeError('rm timeout'),None]) as remove,patch.object(r.DockerEnvironment,'stop',new=stop_base):
    with self.assertRaisesRegex(RuntimeError,'site probe') as raised:
     asyncio.run(env.start())
    self.assertTrue(any('startup cleanup failed' in note for note in raised.exception.__notes__))
    self.assertEqual(env.helper_id,'helper-cid');self.assertIs(env.transport,helper)
    asyncio.run(env.stop())
    self.assertEqual(remove.call_count,2)
   self.assertIsNone(env.helper_id);self.assertIsNone(env.transport)
 def test_helper_launch_cleanup_failure_preserves_original_error(self):
  image='sha256:'+'a'*64
  with patch.object(r.subprocess,'run',side_effect=[TimeoutError('docker run timeout'),OSError('docker rm failed')]):
   with self.assertRaisesRegex(TimeoutError,'docker run timeout') as raised:
    r.start_trusted_helper(image,'ccb05-trusted-failed')
  self.assertTrue(any('startup cleanup failed' in note for note in raised.exception.__notes__))
 def test_stop_failure_closes_owned_jobs_then_removes_helper(self):
  async def stop_base(self,delete=False): return None
  async def ended(): return None
  with tempfile.TemporaryDirectory() as d:
   env=LifecycleTests().environment(Path(d));env.cid='candidate-cid';env.helper_id='helper-cid'
   env.transport=r.TrustedTransport('helper-cid','sha256:'+'e'*64);transport=env.transport
   env.state.update(begin=1.0,site={'user':'u'},root='/home/u/run',prefix='ccb05-test-')
   with patch.object(env,'agent_ended',new=ended),patch.object(env,'seal',side_effect=RuntimeError('seal failed')),patch.object(r.core,'close_jobs') as close_jobs,patch.object(r,'remove_trusted_helper') as remove,patch.object(r.DockerEnvironment,'stop',new=stop_base):
    with self.assertRaisesRegex(RuntimeError,'seal failed'):
     asyncio.run(env.stop())
    close_jobs.assert_called_once()
    self.assertEqual(close_jobs.call_args.kwargs['transport'],transport)
    remove.assert_called_once_with('helper-cid',check=True)
   self.assertIsNone(env.helper_id);self.assertIsNone(env.transport)
 def test_startup_probe_does_not_preflight_scientific_modules(self):
  self.assertNotIn('module load',r.core.SITE_SCRIPT)
  self.assertIn("sacctmgr",r.core.SITE_SCRIPT)


 def test_other_support_code_change_blocks_evidence_sealing(self):
  with tempfile.TemporaryDirectory() as d:
   env=LifecycleTests().environment(Path(d));env.cid='no-container'
   env.state.update(runtime_sha=r.core.digest(Path(r.__file__)),core_sha=r.core.digest(Path(r.core.__file__)),support_sha={'changed':'different'})
   with self.assertRaisesRegex(RuntimeError,'collector code changed'):env.seal()
 def test_artifact_root_traversal_rejected_before_docker(self):
  from bench03_hpc.artifacts import export_declared_artifacts
  with tempfile.TemporaryDirectory() as d:
   for roots in [('/app/../secret',),('/tmp/secret',),('/app/final','/app/final/sub')]:
    with self.assertRaises(ValueError):export_declared_artifacts('not-a-container',roots,Path(d))
 def test_archive_validation_is_atomic_and_rejects_links(self):
  import io,tarfile
  from bench03_hpc.artifacts import _safe_materialize_export
  with tempfile.TemporaryDirectory() as d:
   base=Path(d);archive=base/'bad.tar';dest=base/'out'
   with tarfile.open(archive,'w') as tf:
    m=tarfile.TarInfo('final/link');m.type=tarfile.SYMTYPE;m.linkname='/etc/passwd';tf.addfile(m)
   with self.assertRaisesRegex(RuntimeError,'link or special'):
    _safe_materialize_export(archive,dest,['final'],max_entries=20,max_file_bytes=1000,max_total_bytes=1000)
   self.assertEqual(list(dest.iterdir()),[])
 def test_safe_archive_content_and_manifest(self):
  import io,tarfile,hashlib
  from bench03_hpc.artifacts import _safe_materialize_export
  with tempfile.TemporaryDirectory() as d:
   base=Path(d);data=b'complete';rows=[dict(path='final',type='directory',bytes=0,sha256=None),dict(path='final/data',type='file',bytes=len(data),sha256=hashlib.sha256(data).hexdigest())]
   with tarfile.open(base/'ok.tar','w') as tf:
    m=tarfile.TarInfo('final');m.type=tarfile.DIRTYPE;tf.addfile(m)
    for name,content in [('final/data',data),('__ccb_manifest__.json',json.dumps(rows).encode())]:
     m=tarfile.TarInfo(name);m.size=len(content);tf.addfile(m,io.BytesIO(content))
   observed=_safe_materialize_export(base/'ok.tar',base/'out',['final'],max_entries=20,max_file_bytes=1000,max_total_bytes=1000)
   self.assertEqual(observed,rows);self.assertEqual((base/'out/final/data').read_bytes(),data)

if __name__=='__main__':unittest.main()
