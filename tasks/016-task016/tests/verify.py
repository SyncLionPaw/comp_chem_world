#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability.
# L2 Execution: Check execution evidence through bounded replay or independent recomputation where implemented.
# L3 Science: Diagnose equilibration and statistical reliability in native molecular-dynamics trajectories.
"""Terminal-state science verification with private references and isolated replay."""
from __future__ import annotations
import hashlib,json,importlib,sys,traceback
from pathlib import Path
_REFS_BYTES=Path(__file__).with_name('refs.json').read_bytes()
if hashlib.sha256(_REFS_BYTES).hexdigest()!='76370a929feeb7d19062fce36dae2b82ebc1edd2d0fbd145c1d730b18af57929':
    raise RuntimeError('Private reference integrity mismatch')
REFS=json.loads(_REFS_BYTES)
"""Linux replay isolation: public inputs/source only, immutable runtime, private scratch.

Landlock is enforced even against root; replay also drops to nobody so it cannot
inspect/control the root verifier. No /proc process paths, scorer, final artifacts,
SSH material, inherited descriptors or application environment are exposed.
"""
import ctypes
import errno
import os
from pathlib import Path
import selectors
import signal
import shutil
import stat
import subprocess
import sys
import tempfile
import time

READ = (1 << 0) | (1 << 2) | (1 << 3)  # execute, read file, read directory
WRITE = (1 << 1) | sum(1 << i for i in range(4, 15))
MAX_CAPTURE_BYTES = 64 * 1024


class ReplayInfrastructureError(RuntimeError):
    """The evaluator could not provision or launch an isolated replay."""


def run_bounded(command, timeout, env, pass_fds=()):
    """Run one submitted program with bounded diagnostics and process cleanup."""
    try:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   close_fds=True, pass_fds=pass_fds, start_new_session=True, env=env)
    except OSError as error:
        raise ReplayInfrastructureError('Cannot launch isolated replay: ' + str(error)) from error
    output = bytearray()
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    deadline = time.monotonic() + timeout
    timed_out = False
    while selector.get_map() or process.poll() is None:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            timed_out = True
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
            # Drain only the bounded tail after killing the whole replay group.
            remaining = 1.0
        events = selector.select(min(max(remaining, 0), 0.1))
        for key, _ in events:
            try:
                chunk = os.read(key.fileobj.fileno(), 16384)
            except OSError as error:
                raise ReplayInfrastructureError('Cannot capture isolated replay output: ' + str(error)) from error
            if not chunk:
                selector.unregister(key.fileobj)
                continue
            output.extend(chunk)
            if len(output) > MAX_CAPTURE_BYTES:
                del output[:-MAX_CAPTURE_BYTES]
        if timed_out:
            # Children that inherited stdout are in the same session and have
            # been killed; do not wait forever on a leaked pipe descriptor.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            break
    selector.close()
    if process.poll() is None:
        process.wait()
    text = output.decode('utf-8', errors='replace')
    if timed_out:
        raise subprocess.TimeoutExpired(command, timeout, output=text, stderr=None)
    # Existing scientific verifiers include ``stderr`` in failed replay
    # diagnostics; keep that field as a bounded combined stream.
    return subprocess.CompletedProcess(command, process.returncode, '', text)


def copy_python_sources(source_root, destination_root):
    """Stage submitted Python helpers only; never stage precomputed outputs."""
    source_root = Path(source_root).resolve()
    for source in sorted(source_root.rglob('*.py')):
        if '__pycache__' in source.parts:
            continue
        mode = source.lstat().st_mode
        if not stat.S_ISREG(mode):
            raise ValueError('Submitted Python helper must be a regular file: ' + str(source.relative_to(source_root)))
        relative = source.relative_to(source_root)
        target = Path(destination_root) / relative
        try:
            data = source.read_bytes()
        except OSError as error:
            raise ValueError('Submitted Python helper cannot be read: ' + str(relative)) from error
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            target.chmod(0o444)
        except OSError as error:
            raise ReplayInfrastructureError('Cannot stage submitted Python helper: ' + str(error)) from error


def copy_resp_config(source_root, destination_root):
    """Stage only case-01's explicitly contracted, independently validated config."""
    source = Path(source_root) / 'fit-input.json'
    try:
        mode = source.lstat().st_mode
    except FileNotFoundError:
        return
    except OSError as error:
        raise ValueError('Submitted fit-input.json cannot be inspected') from error
    if not stat.S_ISREG(mode):
        raise ValueError('Submitted fit-input.json must be a regular file')
    try:
        import json
        data = json.loads(source.read_text())
    except (OSError, ValueError) as error:
        raise ValueError('Submitted fit-input.json is not valid readable JSON') from error
    if (not isinstance(data, dict) or not {'method','a','b','restrained_atoms','charge_constraint','convergence_rule'}.issubset(data)
            or not isinstance(data.get('method'), str) or not isinstance(data.get('convergence_rule'), str)
            or type(data.get('a')) not in (int,float) or type(data.get('b')) not in (int,float)
            or type(data.get('charge_constraint')) not in (int, float)
            or not isinstance(data.get('restrained_atoms'),list)
            or any(type(value) is not int for value in data['restrained_atoms'])):
        raise ValueError('Submitted fit-input.json has invalid contracted types')
    target = Path(destination_root) / 'fit-input.json'
    try:
        allowed = ('method','a','b','restrained_atoms','charge_constraint','convergence_rule')
        target.write_text(json.dumps({key: data[key] for key in allowed}, separators=(',', ':')) + '\n')
        target.chmod(0o444)
    except OSError as error:
        raise ReplayInfrastructureError('Cannot stage declared RESP config: ' + str(error)) from error


def restrict(root):
    libc = ctypes.CDLL(None, use_errno=True)
    abi = libc.syscall(444, 0, 0, 1)
    if abi < 3:
        raise RuntimeError('Replay requires Linux Landlock ABI >= 3')
    handled = READ | WRITE
    if abi < 3:
        handled &= ~(1 << 14)
    attr = ctypes.c_uint64(handled)
    fd = libc.syscall(444, ctypes.byref(attr), ctypes.sizeof(attr), 0)
    if fd < 0:
        raise OSError(ctypes.get_errno(), 'landlock_create_ruleset')
    class Rule(ctypes.Structure):
        _pack_ = 1
        _fields_ = [('access', ctypes.c_uint64), ('parent', ctypes.c_int32)]
    def allow(path, rights):
        if not Path(path).exists():
            return
        parent = os.open(path, os.O_PATH | os.O_CLOEXEC)
        try:
            rule = Rule(rights, parent)
            if libc.syscall(445, fd, 1, ctypes.byref(rule), 0):
                raise OSError(ctypes.get_errno(), 'landlock_add_rule: ' + str(path))
        finally:
            os.close(parent)
    try:
        for path in ['/opt/autosolvate', '/usr', '/bin', '/lib', '/lib64']:
            allow(path, READ)
        for path in ['/etc/ld.so.cache', '/etc/localtime', '/proc/cpuinfo', '/proc/meminfo', '/dev/urandom', '/dev/random']:
            allow(path, 1 << 2)
        allow('/dev/null', (1 << 1) | (1 << 2))
        allow(root / 'inputs', READ)
        allow(root / 'sources', READ)
        allow(root / 'work', handled)
        if libc.prctl(38, 1, 0, 0, 0):  # PR_SET_NO_NEW_PRIVS
            raise OSError(ctypes.get_errno(), 'no_new_privs')
        if libc.syscall(446, fd, 0):
            raise OSError(ctypes.get_errno(), 'landlock_restrict_self')
    finally:
        os.close(fd)


def launch(root, probe=False, script_name="script.py", status_fd=None):
    root = Path(root).resolve()
    try:
        if os.getuid() == 0:
            os.setgroups([])
            os.setgid(65534)
            os.setuid(65534)
        restrict(root)
    except Exception as error:
        if status_fd is not None:
            try: os.write(status_fd, b'X')
            except OSError: pass
        raise SystemExit(125)
    if probe:
        # Probe in the same privilege/filesystem state used by actual replays.
        for forbidden in ['/app/final', '/tests', '/root/.ssh', '/proc/1/root']:
            try:
                os.listdir(forbidden)
            except (PermissionError, FileNotFoundError):
                continue
            raise RuntimeError('Replay isolation probe could read ' + forbidden)
        return
    source = root / 'sources' / script_name
    os.chdir(root / 'work')
    env = {'PATH': '/opt/autosolvate/bin:/usr/local/bin:/usr/bin:/bin',
           'AMBERHOME': '/opt/autosolvate', 'HOME': str(root / 'work'),
           'TMPDIR': str(root / 'work'), 'OPENMM_CPU_THREADS': '4',
           'OPENBLAS_NUM_THREADS': '1', 'OMP_NUM_THREADS': '4', 'LANG': 'C.UTF-8'}
    if status_fd is not None:
        os.set_inheritable(status_fd, False)
        os.write(status_fd, b'S')
    try:
        os.execve(sys.executable, [sys.executable, '-B', str(source),
                   '--input-dir', str(root / 'inputs'), '--output-dir', str(root / 'work/outputs')], env)
    except OSError:
        if status_fd is not None:
            try: os.write(status_fd, b'E')
            except OSError: pass
        raise SystemExit(125)


def prepare(root):
    root.chmod(0o755)
    (root / 'sources').mkdir(mode=0o755)
    (root / 'work').mkdir(mode=0o777)
    (root / 'work').chmod(0o777)
    (root / 'inputs').mkdir(mode=0o755)


def preflight():
    with tempfile.TemporaryDirectory(prefix='replay-probe-') as directory:
        root = Path(directory)
        prepare(root)
        result = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--probe', str(root)],
                                capture_output=True, text=True, timeout=15, close_fds=True)
        if result.returncode:
            raise RuntimeError('Replay isolation unavailable: ' + result.stderr[-1000:])


def run_replay(script, input_dir, output_dir, timeout):
    try:
        temporary = tempfile.TemporaryDirectory(prefix='isolated-replay-')
    except OSError as error:
        raise ReplayInfrastructureError('Cannot create private replay directory: ' + str(error)) from error
    with temporary as directory:
        root = Path(directory)
        try:
            prepare(root)
        except OSError as error:
            raise ReplayInfrastructureError('Cannot provision isolated replay directories: ' + str(error)) from error
        script = Path(script).resolve()
        source_root = script.parent
        copy_python_sources(source_root, root / 'sources')
        if script.name == 'fit.py':
            copy_resp_config(source_root, root / 'sources')
        # Preserve __file__/argv basename for programs that copy their own source.
        script_name=Path(script).name
        try:
            shutil.copytree(input_dir, root / 'inputs', dirs_exist_ok=True)
            for path in (root / 'inputs').rglob('*'):
                if path.is_symlink():
                    raise ReplayInfrastructureError('Public replay input contains a symlink')
                path.chmod(0o555 if path.is_dir() else 0o444)
        except ReplayInfrastructureError:
            raise
        except OSError as error:
            raise ReplayInfrastructureError('Cannot stage public replay inputs: ' + str(error)) from error
        out = root / 'work/outputs'
        try:
            out.mkdir(mode=0o777)
            out.chmod(0o777)
        except OSError as error:
            raise ReplayInfrastructureError('Cannot provision private replay output: ' + str(error)) from error
        status_read, status_write = os.pipe()
        try:
            command = [sys.executable, str(Path(__file__).resolve()), '--launch', str(root),
                       script_name, '--status-fd', str(status_write)]
            try:
                result = run_bounded(command, timeout=timeout, env={'PATH': os.environ.get('PATH', '')},
                                     pass_fds=(status_write,))
            except subprocess.TimeoutExpired:
                os.close(status_read)
                raise
        finally:
            os.close(status_write)
        try:
            trusted_status = bytearray()
            while True:
                chunk = os.read(status_read, 64)
                if not chunk: break
                trusted_status.extend(chunk)
        finally:
            os.close(status_read)
        if trusted_status == b'X':
            raise ReplayInfrastructureError('Isolated replay could not establish sandbox restrictions')
        if trusted_status == b'E':
            raise ReplayInfrastructureError('Isolated replay could not exec submitted program')
        if trusted_status != b'S':
            raise ReplayInfrastructureError('Isolated replay launcher exited before its trusted start marker')
        if result.returncode == 125:
            # A candidate can choose both its stderr text and exit status; neither
            # changes the trusted launch marker or upgrades FAIL to ENV_INVALID.
            pass
        # Never follow submitted output symlinks into scoring/reference material.
        try:
            for path in out.rglob('*'):
                mode=path.lstat().st_mode
                if not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
                    raise ValueError('Replay output must be regular file/directory: ' + str(path.relative_to(out)))
        except OSError as error:
            raise ReplayInfrastructureError('Cannot inspect isolated replay output: ' + str(error)) from error
        output_dir = Path(output_dir)
        if output_dir.is_symlink() or not output_dir.is_dir():
            raise ValueError('Replay destination must be a real directory')
        if any(output_dir.iterdir()):
            raise ValueError('Replay destination must be empty; refusing to merge stale files')
        try:
            output_dir.rmdir()
            shutil.copytree(out, output_dir)
        except OSError as error:
            raise ReplayInfrastructureError('Cannot collect isolated replay output: ' + str(error)) from error
        return result


if __name__ == '__main__' and len(sys.argv)>1 and sys.argv[1] in ('--probe','--launch'):
    args=sys.argv[1:]
    launch(args[1], probe=args[0]=='--probe',
           script_name=args[2] if len(args)>2 and args[2]!='--status-fd' else 'script.py',
           status_fd=int(args[4]) if len(args)>4 and args[3]=='--status-fd' else None)
    raise SystemExit(0)

"""Independent native trajectory/statistical audit, no reference result import."""
from pathlib import Path
import csv
import numpy as np,parmed
from scipy.io import netcdf_file

def statistical_inefficiency(x):
 x=np.asarray(x,dtype=float);n=len(x)
 if np.ptp(x)<REFS['tolerances']['constant_series_abs_threshold_native_units']:return None
 x=x-x.mean();v=np.mean(x*x);total=0.
 for lag in range(1,n):
  rho=float(np.dot(x[:-lag],x[lag:])/((n-lag)*v))
  if rho<=0:break
  total+=(1-lag/n)*rho
 return min(float(n),max(1.,1+2*total))

def calculate(input_dir):
 top=parmed.load_file(str(input_dir/'neutral.prmtop'));mass=sum(a.mass for a in top.atoms);result={}
 for name,file in [('legacy','legacy-qmmm.nc'),('short_npt','short-npt.nc')]:
  with netcdf_file(str(input_dir/file),mmap=False) as f:
   if f.variables['time'].units!=b'picosecond' or f.variables['coordinates'].units!=b'angstrom':raise ValueError('Native units changed')
   t=f.variables['time'][:].copy();cell=f.variables['cell_lengths'][:].copy();angles=f.variables['cell_angles'][:].copy();shape=f.variables['coordinates'].shape
   if not np.allclose(angles,90,atol=REFS['tolerances']['orthorhombic_angle_atol_degree'],rtol=REFS['tolerances']['orthorhombic_angle_rtol']) or not (np.diff(t)>0).all():raise ValueError('Invalid cell/time metadata')
  if shape[1:]!=(24003,3):raise ValueError('Wrong topology association')
  volume=cell.prod(axis=1);density=mass*1.66053906660/volume;g=statistical_inefficiency(density);neff=1. if g is None else len(t)/g
  codes=['observation_too_short_for_independent_equilibrium_ensemble']
  if np.ptp(density)<REFS['tolerances']['constant_series_abs_threshold_native_units']:codes.append('constant_density_does_not_establish_uncorrelated_frames')
  if neff<10:codes.append('fewer_than_ten_effective_density_observations')
  if len(t)<5:codes.append('too_few_frames_for_stationarity_and_uncertainty')
  result[name]={'frames':len(t),'atoms':shape[1],'start_time_ps':float(t[0]),'end_time_ps':float(t[-1]),'duration_ps':float(t[-1]-t[0]),'interval_ps':float(np.diff(t).mean()),'box_source':'trajectory_cell_lengths','volumes_A3':volume.tolist(),'densities_g_ml':density.tolist(),'density_statistical_inefficiency':g,'effective_density_samples':neff,'density_relative_change':float((density[-1]-density[0])/density[0]),'supports_ten_independent_equilibrium_clusters':False,'reason_codes':codes}
 records=list(csv.DictReader((input_dir/'short-npt-diagnostics.csv').open()))
 b=result['short_npt'];assert len(records)==b['frames']
 temperatures=[]
 for i,row in enumerate(records):
  assert abs(float(row['time_ps'])-(b['start_time_ps']+i*b['interval_ps']))<REFS['tolerances']['native_and_statistical_comparison']
  assert abs(float(row['density_g_ml'])-b['densities_g_ml'][i])<REFS['tolerances']['native_and_statistical_comparison']
  assert abs(float(row['volume_A3'])-b['volumes_A3'][i])<REFS['tolerances']['volume_A3']
  temperatures.append(float(row['temperature_K']))
 b['temperature_mean_K']=float(np.mean(temperatures));b['temperature_sd_K']=float(np.std(temperatures,ddof=1))
 return {'datasets':result,'diagnostic_controls':controls(input_dir),'duration_ratio_short_to_legacy':b['duration_ps']/result['legacy']['duration_ps'],'recommendation':{'extend_sampling':True,'location':'remote','reason':'Statistical adequacy cannot be inferred from frame count or successful execution.'}}

def controls(input_dir):
 import json
 index=json.loads((input_dir/'controls/index.json').read_text());policy=index['policy'];result={}
 for item in index['datasets']:
  records=list(csv.DictReader((input_dir/'controls'/item['file']).open()));n=len(records)
  times=np.array([float(row['time']) for row in records])*{'ps':1,'ns':1000}[item['time_unit']]
  consistent=bool(np.isfinite(times).all() and (np.diff(times)>0).all())
  if item.get('native_time_reference'):
   with netcdf_file(str(input_dir/item['native_time_reference']),mmap=False) as f:native=f.variables['time'][:].copy()
   consistent=consistent and len(times)==len(native) and bool(np.allclose(times,native,atol=REFS['tolerances']['native_and_statistical_comparison'],rtol=0))
  metrics={};reasons=[]
  if not consistent:reasons.append('time_metadata_disagrees_with_native_reference')
  if n<policy['minimum_frames']:reasons.append('too_few_observations_for_declared_audit')
  for observable in item['observables']:
   x=np.array([float(row[observable]) for row in records]);assert np.isfinite(x).all()
   g=statistical_inefficiency(x);neff=1. if g is None else n/g
   blocks=np.array_split(x,policy['stationarity_blocks']);sd=np.std(x,ddof=1)
   spread=None if sd<REFS['tolerances']['constant_series_abs_threshold_native_units'] or n<policy['stationarity_blocks'] else float(np.ptp([np.mean(block) for block in blocks])/sd)
   stable=spread is not None and n>=policy['minimum_frames'] and spread<=policy['maximum_block_mean_range_in_sample_sd']
   metrics[observable]={'statistical_inefficiency':g,'effective_observations':neff,'block_mean_range_in_sample_sd':spread,'passes_declared_stationarity_screen':bool(stable)}
   if neff<policy['minimum_effective_observations']:reasons.append('insufficient_effective_observations:'+observable)
   if not stable:reasons.append('stationarity_not_supported:'+observable)
  eligible=consistent and n>=policy['minimum_frames'] and all(m['effective_observations']>=policy['minimum_effective_observations'] and m['passes_declared_stationarity_screen'] for m in metrics.values())
  if eligible:reasons.append('declared_observable_summary_requirements_met')
  result[item['dataset_id']]={'observations':n,'declared_duration_ps':float(times[-1]-times[0]),'metadata_consistent':bool(consistent),'observables':metrics,'eligible_for_declared_observable_summary':bool(eligible),'establishes_molecular_equilibrium':False,'verdict':'metadata_inconsistent' if not consistent else ('eligible_observable_summary' if eligible else 'insufficient_sampling_evidence'),'reason_codes':reasons}
 return result

#!/usr/bin/env python3
import argparse,json,subprocess,sys,tempfile,hashlib,shutil
from pathlib import Path
import numpy as np
PACKAGE=Path(__file__).resolve().parents[1]
def check_result(output,expected,require_delivery=True):
 required=['audit.json']
 if require_delivery:required += ['analysis.py','analysis.md']
 for name in required:
  assert (output/name).is_file() and (output/name).stat().st_size>0,'Missing '+name
 a=json.loads((output/'audit.json').read_text())
 def json_types(actual,reference,path):
  if type(reference) is bool:
   assert type(actual) is bool,f'{path}: expected boolean'
  elif reference is None:
   assert actual is None,f'{path}: expected null'
  elif isinstance(reference,(int,float)):
   assert type(actual) in (int,float),f'{path}: expected number, not boolean/string'
  elif isinstance(reference,list):
   assert isinstance(actual,list) and len(actual)==len(reference),f'{path}: expected array shape'
   for i,(value,want) in enumerate(zip(actual,reference)):json_types(value,want,f'{path}[{i}]')
  elif isinstance(reference,dict):
   assert isinstance(actual,dict),f'{path}: expected object'
   for key,want in reference.items():
    if key in actual:json_types(actual[key],want,f'{path}.{key}')
  else:
   assert type(actual) is type(reference),f'{path}: wrong JSON type'
 def alias_value(record,canonical,aliases,path):
  present=[key for key in (canonical,*aliases) if key in record]
  assert present,f'{path}: missing contracted value'
  value=record[present[0]]
  for key in present[1:]:
   other=record[key]
   if isinstance(value,(int,float,list,np.ndarray)) and not isinstance(value,bool):
    assert np.allclose(value,other,atol=REFS['tolerances']['native_and_statistical_comparison'],rtol=REFS['tolerances']['native_and_statistical_comparison']),f'{path}: conflicting alias values'
   else: assert value==other,f'{path}: conflicting alias values'
  return value
 def check_reasons(name,actual,want):
  assert isinstance(actual,list) and all(isinstance(code,str) and code for code in actual) and len(actual)==len(set(actual)) and set(want)==set(actual),name+': incomplete or unsupported reason codes'
 assert set(a['datasets'])==set(expected['datasets']),'Unknown or missing native dataset'
 # Control reason codes are an explicit public obligation. Check all controls
 # before the native datasets, whose detailed reason-code vocabulary was added
 # only in the later contract revision.
 raw_controls=a['diagnostic_controls']
 if isinstance(raw_controls,list):
  controls={}
  for row in raw_controls:
   assert isinstance(row,dict) and isinstance(row.get('dataset_id'),str),'Malformed diagnostic-control record'
   key=row['dataset_id'];assert key not in controls,'Duplicate diagnostic-control id'
   controls[key]=row
  assert set(controls)==set(expected['diagnostic_controls']),'Unknown or missing diagnostic-control id'
 elif isinstance(raw_controls,dict):
  controls=raw_controls
  assert set(controls)==set(expected['diagnostic_controls']),'Unknown or missing diagnostic-control id'
  for key,row in controls.items():
   assert isinstance(row,dict),'Malformed diagnostic-control record'
   if 'dataset_id' in row:assert row['dataset_id']==key,'Conflicting diagnostic-control id'
 else:raise AssertionError('diagnostic_controls must be a list or object')
 for name,e in expected['diagnostic_controls'].items():
  r=controls[name]
  assert isinstance(r,dict),'Diagnostic-control entry must be an object'
  check_reasons(name,r.get('reason_codes'),e['reason_codes'])
 # Validate every public-reason obligation before any observable numeric check.
 # This prevents an earlier, contract-ambiguous rho estimate from masking a
 # later, independently missing explanation in another dataset.
 for name,e in expected['datasets'].items():
  r=a['datasets'][name]
  assert isinstance(r,dict),'Dataset record must be an object'
  check_reasons(name,r.get('reason_codes'),e['reason_codes'])
 for name,e in expected['datasets'].items():
  r=a['datasets'][name]
  assert isinstance(r,dict),'Dataset record must be an object'
  rtype=dict(r);rtype.pop('reason_codes',None)
  native_times=r.get('native_time_ps')
  if native_times is not None:
   assert isinstance(native_times,list) and len(native_times)==r.get('frames') and all(type(value) in (int,float) for value in native_times),'Invalid native time vector'
   t=np.asarray(native_times,dtype=float)
   assert np.isfinite(t).all() and np.all(np.diff(t)>0),'Invalid native time vector'
   time_aliases={'start_time_ps':float(t[0]),'end_time_ps':float(t[-1]),'duration_ps':float(t[-1]-t[0]),
                 'interval_ps':float(np.diff(t).mean()) if len(t)>1 else 0.0}
   for canonical,value in time_aliases.items():
    aliases={'start_time_ps':['native_start_time_ps'],'end_time_ps':['native_end_time_ps'],
       'duration_ps':['time_span_ps'],'interval_ps':['time_interval_ps']}[canonical]
    rtype[canonical]=alias_value(r,canonical,aliases,'datasets.'+name+'.'+canonical) if canonical in r or any(k in r for k in aliases) else value
    assert np.isclose(rtype[canonical],value,atol=REFS['tolerances']['native_and_statistical_comparison'],rtol=REFS['tolerances']['native_and_statistical_comparison']),f'{name}: contradictory native time summary'
  else:
   for canonical,aliases in [('start_time_ps',['native_start_time_ps']),('end_time_ps',['native_end_time_ps']),('duration_ps',['time_span_ps']),('interval_ps',['time_interval_ps'])]:
    rtype[canonical]=alias_value(r,canonical,aliases,'datasets.'+name+'.'+canonical)
  for canonical,aliases in [('volumes_A3',['frame_volumes_A3']),('densities_g_ml',['density_g_ml'])]:
   rtype[canonical]=alias_value(r,canonical,aliases,'datasets.'+name+'.'+canonical)
  json_types(rtype,e,'datasets.'+name)
  for k in ['frames','atoms']:
   assert r[k]==e[k],f'{name}: wrong {k}'
  for k in ['start_time_ps','end_time_ps','duration_ps','interval_ps','volumes_A3','densities_g_ml','effective_density_samples','density_relative_change']:
   assert np.allclose(rtype[k],e[k],atol=REFS['tolerances']['native_and_statistical_comparison'],rtol=REFS['tolerances']['native_and_statistical_comparison']),f'{name}: incorrect {k}'
  if e['density_statistical_inefficiency'] is None:assert r['density_statistical_inefficiency'] is None,'Constant observable has unidentifiable inefficiency'
  else:assert abs(r['density_statistical_inefficiency']-e['density_statistical_inefficiency'])<REFS['tolerances']['native_and_statistical_comparison']
  support=r.get('supports_ten_independent_equilibrium_clusters')
  if support is not None:assert type(support) is bool,f'{name}: support flag must be boolean'
  verdict=None
  if 'verdict' in r:
   verdicts={'insufficient_sampling_evidence':False,'eligible_observable_summary':True}
   assert isinstance(r['verdict'],str) and r['verdict'] in verdicts,f'{name}: unknown native sampling verdict'
   verdict=verdicts[r['verdict']]
  assert support is not None or verdict is not None,f'{name}: missing native sampling conclusion'
  if support is not None and verdict is not None:assert support is verdict,f'{name}: conflicting native conclusion fields'
  actual_support=support if support is not None else verdict
  assert actual_support is e['supports_ten_independent_equilibrium_clusters'],f'{name}: unsupported sampling claim'
  if name=='short_npt':
   for k in ['temperature_mean_K','temperature_sd_K']:assert abs(r[k]-e[k])<REFS['tolerances']['native_and_statistical_comparison']
 if 'duration_ratio_short_to_legacy' in a:
  value=a['duration_ratio_short_to_legacy'];assert type(value) in (int,float) and np.isclose(value,expected['duration_ratio_short_to_legacy'],rtol=REFS['tolerances']['native_and_statistical_comparison']),'Incorrect short/legacy duration ratio'
 assert a['recommendation']['extend_sampling'] is True,'Unsupported sampling-extension recommendation'
 location=a['recommendation']['location']
 assert isinstance(location,str) and location.strip(),'Sampling location must be a nonempty description'
 for name,e in expected['diagnostic_controls'].items():
  r=controls[name]
  assert isinstance(r,dict),'Diagnostic-control entry must be an object'
  rtype=dict(r);rtype.pop('reason_codes',None)
  def normalize_observables(mapping):
   assert isinstance(mapping,dict),'Observable metrics must be an object'
   normalized={}
   for observable,metrics in mapping.items():
    assert observable not in normalized,'Duplicate observable'
    assert isinstance(metrics,dict),'Malformed observable metrics'
    m=dict(metrics)
    for canonical,alias in [('block_mean_range_in_sample_sd','four_block_mean_range_over_sample_sd'),('passes_declared_stationarity_screen','stationarity_screen_pass')]:
     if canonical in m and alias in m:
      left,right=m[canonical],m[alias]
      same=bool(np.isclose(left,right,rtol=REFS['tolerances']['native_and_statistical_comparison'],atol=REFS['tolerances']['native_and_statistical_comparison'])) if type(left) in (int,float) and type(right) in (int,float) else left==right
      assert same,f'{name}/{observable}: conflicting metric aliases'
     elif canonical not in m and alias in m:m[canonical]=m[alias]
    normalized[observable]=m
   return normalized
  if 'observables' in rtype and 'per_observable' in rtype:
   assert normalize_observables(r['observables'])==normalize_observables(r['per_observable']),f'{name}: conflicting observable mappings'
  if 'observables' not in rtype and 'per_observable' in rtype:rtype['observables']=r['per_observable']
  if 'observables' in rtype:
   normalized=normalize_observables(rtype['observables'])
   rtype['observables']=normalized
  json_types(rtype,e,'diagnostic_controls.'+name)
  for k in ['observations','metadata_consistent','eligible_for_declared_observable_summary','establishes_molecular_equilibrium']:assert r[k]==e[k],f'{name}: wrong {k}'
  verdicts={e['verdict']}
  if e['verdict']=='metadata_inconsistent' and not e['metadata_consistent']:
   verdicts.add('insufficient_sampling_evidence')
  assert r['verdict'] in verdicts,f'{name}: wrong verdict'
  assert abs(r['declared_duration_ps']-e['declared_duration_ps'])<REFS['tolerances']['native_and_statistical_comparison']
  assert set(rtype['observables'])==set(e['observables'])
  for observable,m in e['observables'].items():
   for key,value in m.items():
    if value is None:assert rtype['observables'][observable][key] is None
    elif isinstance(value,bool):assert rtype['observables'][observable][key] is value
    else:assert np.isclose(rtype['observables'][observable][key],value,rtol=REFS['tolerances']['native_and_statistical_comparison'],atol=REFS['tolerances']['native_and_statistical_comparison']),name+': incorrect '+observable+'/'+key
def verify(output,replay=True):
 expected=calculate(PACKAGE/'inputs');check_result(output,expected)
 if replay:
  with tempfile.TemporaryDirectory(prefix='audit-replay-') as d:
   out=Path(d)/'outputs';out.mkdir()
   r=run_replay(output/'analysis.py',PACKAGE/'inputs',out,timeout=90)
   assert r.returncode==0,'Audit replay failed: '+r.stderr[-1000:]
   check_result(out,expected,require_delivery=False)
  # Dataset identifiers and file order cannot substitute for numerical/statistical analysis.
  with tempfile.TemporaryDirectory(prefix='audit-renamed-replay-') as d:
   inp=Path(d)/'inputs';shutil.copytree(PACKAGE/'inputs',inp);out=Path(d)/'outputs';out.mkdir()
   p=inp/'controls/index.json';index=json.loads(p.read_text());index['datasets'].reverse()
   for i,item in enumerate(index['datasets']):
    item['dataset_id']='anonymous-'+str(i);old=inp/'controls'/item['file'];item['file']='trace-'+str(i)+'.csv';old.rename(inp/'controls'/item['file'])
   p.write_text(json.dumps(index));r=run_replay(output/'analysis.py',inp,out,timeout=90)
   assert r.returncode==0,'Renamed control audit failed: '+r.stderr[-1000:]
   check_result(out,calculate(inp),require_delivery=False)
 return {'status':'PASS','layers':['L1','L2','L3'],'replayed':replay,'legacy_duration_ps':expected['datasets']['legacy']['duration_ps'],'real_short_npt_duration_ps':expected['datasets']['short_npt']['duration_ps']}
def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def emit(logs, status, reason=None, result=None):
    report = {"status": status}
    if reason is not None:
        report["reason"] = reason
    if result is not None:
        report["science"] = result
    if status in {"PASS", "FAIL"}:
        report["reward"] = int(status == "PASS")
        (logs / "reward.txt").write_text(str(report["reward"]) + "\n")
    else:
        (logs / "reward.txt").unlink(missing_ok=True)
    (logs / "verification.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))
    return {"PASS": 0, "FAIL": 1, "ENV_INVALID": 2}[status]


def main():
    app = Path(os.environ.get("APP", "/app")).resolve()
    tests = Path(os.environ.get("TESTS", Path(__file__).parent)).resolve()
    logs = Path(os.environ.get("LOGS", "/logs/verifier")).resolve()
    logs.mkdir(parents=True, exist_ok=True)
    for name in ("reward.txt", "verification.json"):
        (logs / name).unlink(missing_ok=True)
    try:
        contract = REFS["runtime"]
        for item in contract["inputs"]:
            path = app / item["path"]
            if not path.is_file() or path.is_symlink() or digest(path) != item["sha256"]:
                raise RuntimeError("Public input integrity: " + item["path"])
        for module in contract["python_modules"]:
            importlib.import_module(module)
        verifier = sys.modules[__name__]
        if contract["case_id"] != "case-02":
            preflight()
    except Exception as error:
        (logs / "preflight-error.log").write_text(traceback.format_exc())
        return emit(logs, "ENV_INVALID", str(error))

    output = app / "final"
    # Preserve the original PACKAGE-relative input/reference interface without
    # exposing evaluator materials during the answer phase.
    with tempfile.TemporaryDirectory(prefix="case-verifier-") as directory:
        package = Path(directory)
        (package / "inputs").symlink_to(app / "inputs", target_is_directory=True)
        (package / "tests").symlink_to(tests, target_is_directory=True)
        verifier.PACKAGE = package
        try:
            # Reference-only calculations run before inspecting submissions.
            if contract["case_id"] == "case-03-audit":
                verifier.calculate(package / "inputs")
            if contract["case_id"] == "case-02":
                verifier.check_reference()
            if contract["case_id"] == "case-01":
                verifier.system(package / "inputs")
        except Exception as error:
            return emit(logs, "ENV_INVALID", "Reference preflight: " + str(error))
        try:
            if not output.is_dir():
                return emit(logs, "FAIL", "Missing final/ submission directory")
            if (output / ".invalid-submission-artifact").exists():
                raise ValueError("Submission tree contains symlink or special-file artifacts")
            for path in output.rglob("*"):
                mode = path.lstat().st_mode
                if not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
                    raise ValueError("Submission tree contains a symlink or special file: " + str(path.relative_to(output)))
            for name in contract["output_paths"]:
                path = output / name
                if not path.resolve().is_relative_to(output.resolve()):
                    raise ValueError("Submission path escapes final/: " + name)
                if not path.exists():
                    raise AssertionError("Missing output: " + name)
                mode = path.lstat().st_mode
                kind = contract["output_types"][name]
                if ((kind == "file" and not stat.S_ISREG(mode))
                        or (kind == "directory" and not stat.S_ISDIR(mode))
                        or kind not in {"file", "directory"}):
                    raise ValueError("Required submission artifact has the wrong filesystem type: " + name)
            if contract["case_id"] == "case-01":
                result = verifier.verify(output, package / "inputs", replay=True)
            else:
                result = verifier.verify(output)
            if result.get("status") != "PASS":
                raise RuntimeError("Unexpected scientific verifier result")
        except ReplayInfrastructureError as error:
            return emit(logs, "ENV_INVALID", str(error))
        except (AssertionError, ValueError, KeyError, TypeError, IndexError,
                OSError, subprocess.TimeoutExpired) as error:
            return emit(logs, "FAIL", str(error) or type(error).__name__)
        except Exception as error:
            (logs / "verifier-error.log").write_text(traceback.format_exc())
            return emit(logs, "ENV_INVALID", str(error))
        return emit(logs, "PASS", result=result)


if __name__ == "__main__":
    sys.exit(main())
