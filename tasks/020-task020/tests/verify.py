#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability.
# L2 Execution: Check execution evidence through bounded replay or independent recomputation where implemented.
# L3 Science: Diagnose and recover a failed propagation without changing the underlying physical model.
"""Terminal-state science verification with private references and isolated replay."""
from __future__ import annotations
import hashlib,json,importlib,sys,traceback
from pathlib import Path
_REFS_BYTES=Path(__file__).with_name('refs.json').read_bytes()
if hashlib.sha256(_REFS_BYTES).hexdigest()!='01fa8ff1cb78d54c818956264d9c14c21add49e6915b5fb6b65a7d0f06330a9c':
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

#!/usr/bin/env python3
"""Recovery must preserve native checkpoint state, force field and actual scientific execution."""
import argparse,csv,hashlib,json,subprocess,sys,tempfile,ctypes,ctypes.util,math
import math,re
from pathlib import Path
import numpy as np,openmm as mm
from openmm import app,unit
from scipy.io import netcdf_file
PACKAGE=Path(__file__).resolve().parents[1]
def _text_alias(value,aliases,message):
 assert isinstance(value,str) and value.strip(),'Expected a nonempty descriptive string: '+message
 key=value.strip().casefold()
 assert key in aliases,'Unknown '+message+': '+value
 return aliases[key]
def _constraints_preserved(value):
 if isinstance(value,str):
  return _text_alias(value,{'none':'none','no constraints':'none','unconstrained':'none'},'constraint setting')=='none'
 assert isinstance(value,dict) and set(value)=={'model_constraint_setting','preserved','constraint_tolerance'},'Malformed constraint record'
 setting=_text_alias(value['model_constraint_setting'],{'none':'none','no constraints':'none','unconstrained':'none'},'constraint setting')
 assert value['preserved'] is True,'Constraint model was not preserved'
 tolerance=value['constraint_tolerance']
 assert type(tolerance) in (int,float) and math.isfinite(tolerance) and tolerance>=0,'Invalid constraint tolerance'
 return setting=='none'
def _change_name(value):
 aliases={'timestep_fs':'timestep_fs','random_seed':'random_seed',
          'integrator step size':'timestep_fs','integrator timestep':'timestep_fs',
          'time step':'timestep_fs','timestep':'timestep_fs',
          'random seed':'random_seed','integrator random seed':'random_seed','stochastic random seed':'random_seed'}
 assert isinstance(value,str) and value.strip(),'Malformed changed-parameter name'
 key=value.strip().casefold()
 assert key in aliases,'Unknown changed numerical parameter: '+value
 return aliases[key]
def _time_fs(value):
 assert isinstance(value,str) and value.strip(),'Timestep values must include explicit units'
 matches=re.findall(r'(?<![A-Za-z0-9_.])([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*(fs|femtoseconds?|ps|picoseconds?)\b',value.strip(),flags=re.I)
 assert matches,'Timestep value has unknown or missing units'
 vals=[]
 for number,unit_name in matches:
  v=float(number); assert math.isfinite(v)
  vals.append(v*1000 if unit_name.casefold().startswith('p') else v)
 assert all(math.isclose(v,vals[0],rel_tol=REFS['tolerances']['timestep_unit_consistency_rel'],abs_tol=REFS['tolerances']['timestep_unit_consistency_abs_fs']) for v in vals),'Contradictory timestep units'
 return vals[0]
def _integer_json_number(value):
 return type(value) is int or (type(value) is float and math.isfinite(value) and value.is_integer())
def _model_constraints_assessment(value):
 return value is True or (isinstance(value,str) and bool(value.strip()))
def _constraints_assessment_value(diagnosis):
 canonical='model_constraints_assessment';legacy='unconstrained_hydrogen_motion'
 has_canonical=canonical in diagnosis;has_legacy=legacy in diagnosis
 assert has_canonical or has_legacy,'Missing model-constraints assessment'
 if has_canonical and has_legacy:
  assert type(diagnosis[canonical]) is type(diagnosis[legacy]) and diagnosis[canonical]==diagnosis[legacy],'Conflicting model-constraints assessment aliases'
 return diagnosis[canonical] if has_canonical else diagnosis[legacy]
def _seed_integer(value):
 if type(value) is int:return value
 assert isinstance(value,str) and re.fullmatch(r'[+-]?\d+',value.strip()),'Random-seed values must be integer seeds'
 return int(value)
def _allowed_changes(records,old_dt_fs,new_dt_fs,old_seed,new_seed):
 assert isinstance(records,list),'allowed_changes must be a list'
 names=[]
 for item in records:
  if isinstance(item,str):
   name=_change_name(item)
  else:
   assert isinstance(item,dict) and set(item)=={'parameter','from','to','reason'},'Malformed allowed_changes record'
   name=_change_name(item['parameter'])
   assert isinstance(item['reason'],str) and item['reason'].strip(),'Changed-parameter record needs a reason'
   if name=='timestep_fs':
    assert math.isclose(_time_fs(item['from']),old_dt_fs,rel_tol=0,abs_tol=REFS['tolerances']['time_and_integrator']),'Reported original timestep disagrees with native integrator'
    assert math.isclose(_time_fs(item['to']),new_dt_fs,rel_tol=0,abs_tol=REFS['tolerances']['time_and_integrator']),'Reported corrected timestep disagrees with submitted integrator'
   else:
    assert _seed_integer(item['from'])==old_seed and _seed_integer(item['to'])==new_seed,'Reported random seeds disagree with native integrators'
  assert name not in names,'Duplicate allowed_changes parameter'
  names.append(name)
 assert 'timestep_fs' in names and ('random_seed' in names)==(new_seed!=old_seed),'Numerical changes are missing or inaccurately reported'
 assert set(names)<={'timestep_fs','random_seed'}
 return set(names)
def _failure_class(value):
 return _text_alias(value,{'numerical_integration':'numerical_integration','numerical integration':'numerical_integration','numerical integration divergence':'numerical_integration'},'failure class')
def _unstable_parameter(value):
 return _text_alias(value,{'timestep_fs':'timestep_fs','timestep':'timestep_fs','integrator step size':'timestep_fs','20 fs langevinmiddleintegrator stepsize with unconstrained hydrogens':'timestep_fs'},'unstable parameter')
def _alternative_categories(rows):
 aliases={'parameterization':'parameterization','force-field or parameterization error':'parameterization',
          'electronic_structure':'electronic_structure','electronic-structure or charge-state failure':'electronic_structure',
          'thermostat':'thermostat','thermostat or target-temperature pathology':'thermostat',
          'restart':'restart','bad restart or periodic-box corruption':'restart'}
 assert isinstance(rows,list),'rejected_alternatives must be a list'
 result={}
 for row in rows:
  assert isinstance(row,dict) and set(row)=={'category','evidence'},'Malformed rejected alternative'
  category=_text_alias(row['category'],aliases,'alternative category')
  assert category not in result,'Duplicate rejected-alternative category'
  assert isinstance(row['evidence'],str) and row['evidence'].strip(),'Alternative evidence must be nonempty'
  result[category]=row['evidence']
 assert {'parameterization','electronic_structure'}<=set(result),'Required competing explanations are missing'
 return result
def canonical_xml(obj,ignored=()):
 import xml.etree.ElementTree as ET
 node=ET.fromstring(mm.XmlSerializer.serialize(obj))
 for child in node.iter():
  for key in ['name','openmmVersion',*ignored]:child.attrib.pop(key,None)
 return ET.tostring(node,encoding='unicode')
def load_candidate_xml(path,expected_type):
 try: obj=mm.XmlSerializer.deserialize(Path(path).read_text())
 except Exception as error: raise ValueError('Invalid submitted XML '+Path(path).name+': '+str(error)) from error
 if not isinstance(obj,expected_type): raise ValueError('Wrong submitted XML object type: '+Path(path).name)
 return obj
def canonical_units(name,value):
 if name in ('coordinates','cell_lengths') and value in (b'angstrom',b'angstroms','Å'.encode('utf-8')):return 'angstrom'
 if name=='time' and value in (b'ps',b'picosecond',b'picoseconds'):return 'picosecond'
 return None
def read_native_trajectory(path):
 """Read classic NetCDF and NetCDF4 through the image's libnetcdf C API."""
 library=ctypes.util.find_library('netcdf')
 assert library,'Native NetCDF reader is unavailable'
 nc=ctypes.CDLL(library)
 nc.nc_open.argtypes=[ctypes.c_char_p,ctypes.c_int,ctypes.POINTER(ctypes.c_int)];nc.nc_open.restype=ctypes.c_int
 nc.nc_close.argtypes=[ctypes.c_int];nc.nc_close.restype=ctypes.c_int
 nc.nc_inq_varid.argtypes=[ctypes.c_int,ctypes.c_char_p,ctypes.POINTER(ctypes.c_int)];nc.nc_inq_varid.restype=ctypes.c_int
 nc.nc_inq_varndims.argtypes=[ctypes.c_int,ctypes.c_int,ctypes.POINTER(ctypes.c_int)];nc.nc_inq_varndims.restype=ctypes.c_int
 nc.nc_inq_vardimid.argtypes=[ctypes.c_int,ctypes.c_int,ctypes.POINTER(ctypes.c_int)];nc.nc_inq_vardimid.restype=ctypes.c_int
 nc.nc_inq_dimlen.argtypes=[ctypes.c_int,ctypes.c_int,ctypes.POINTER(ctypes.c_size_t)];nc.nc_inq_dimlen.restype=ctypes.c_int
 nc.nc_get_var_double.argtypes=[ctypes.c_int,ctypes.c_int,ctypes.POINTER(ctypes.c_double)];nc.nc_get_var_double.restype=ctypes.c_int
 nc.nc_inq_attlen.argtypes=[ctypes.c_int,ctypes.c_int,ctypes.c_char_p,ctypes.POINTER(ctypes.c_size_t)];nc.nc_inq_attlen.restype=ctypes.c_int
 nc.nc_get_att_text.argtypes=[ctypes.c_int,ctypes.c_int,ctypes.c_char_p,ctypes.c_char_p];nc.nc_get_att_text.restype=ctypes.c_int
 nc.nc_strerror.argtypes=[ctypes.c_int];nc.nc_strerror.restype=ctypes.c_char_p
 def check(status,what):
  if status:raise ValueError('Invalid submitted NetCDF '+what+': '+nc.nc_strerror(status).decode(errors='replace'))
 def variable_shape(varid,name):
  ndim=ctypes.c_int();check(nc.nc_inq_varndims(ncid.value,varid,ctypes.byref(ndim)),name+' rank')
  assert 1<=ndim.value<=4,'Invalid submitted NetCDF variable rank'
  dimids=(ctypes.c_int*ndim.value)();check(nc.nc_inq_vardimid(ncid.value,varid,dimids),name+' dimensions')
  shape=[]
  for dimid in dimids:
   length=ctypes.c_size_t();check(nc.nc_inq_dimlen(ncid.value,dimid,ctypes.byref(length)),name+' dimension length')
   shape.append(length.value)
  return shape
 def variable_units(varid,name):
  size=ctypes.c_size_t();check(nc.nc_inq_attlen(ncid.value,varid,b'units',ctypes.byref(size)),name+' units attribute')
  assert size.value<=128,'Invalid submitted NetCDF units attribute'
  attr=ctypes.create_string_buffer(max(1,size.value));check(nc.nc_get_att_text(ncid.value,varid,b'units',attr),name+' units')
  return attr.raw[:size.value]
 ncid=ctypes.c_int();check(nc.nc_open(str(path).encode(),0,ctypes.byref(ncid)),'open')
 try:
  result={};frame_count=None;numeric_bytes=0;budget=5*1024**3
  aliases={'coordinates':['coordinates','positions'],'time':['time','time_ps'],'cell_lengths':['cell_lengths']}
  for name,candidates in aliases.items():
   varids=[]
   for candidate in candidates:
    candidate_id=ctypes.c_int()
    if nc.nc_inq_varid(ncid.value,candidate.encode(),ctypes.byref(candidate_id))==0:varids.append(candidate_id.value)
   if not varids:raise ValueError('Invalid submitted NetCDF '+name+' variable: expected one of '+', '.join(candidates))
   varid=ctypes.c_int(varids[0])
   shape=variable_shape(varid.value,name)
   count=math.prod(shape);assert 0<count,'Empty submitted NetCDF variable'
   if name=='coordinates':
    assert len(shape)==3 and shape[1:]==[24003,3] and shape[0]>=11,'Invalid submitted coordinate dimensions'
    frame_count=shape[0]
    assert count*8<=budget,'Submitted trajectory exceeds the scorer memory budget'
   elif name=='time':assert shape==[frame_count],'Invalid submitted time dimensions'
   else:assert shape==[frame_count,3],'Invalid submitted box dimensions'
   assert numeric_bytes+count*8<=budget,'Submitted trajectory exceeds the scorer memory budget'
   result[name]=np.empty(shape,dtype=np.float64)
   check(nc.nc_get_var_double(ncid.value,varid.value,result[name].ctypes.data_as(ctypes.POINTER(ctypes.c_double))),name+' values')
   result[name+'_units']=variable_units(varid.value,name);numeric_bytes+=count*8
   for duplicate_id in varids[1:]:
    duplicate_shape=variable_shape(duplicate_id,name);assert duplicate_shape==shape,'Conflicting semantic NetCDF variable shapes'
    assert numeric_bytes+count*8<=budget,'Submitted trajectory exceeds the scorer memory budget'
    duplicate=np.empty(shape,dtype=np.float64)
    check(nc.nc_get_var_double(ncid.value,duplicate_id,duplicate.ctypes.data_as(ctypes.POINTER(ctypes.c_double))),name+' alias values')
    assert canonical_units(name,variable_units(duplicate_id,name))==canonical_units(name,result[name+'_units']),'Conflicting semantic NetCDF variable units'
    assert np.array_equal(duplicate,result[name]),'Conflicting semantic NetCDF variable values'
    del duplicate
  return result
 finally:nc.nc_close(ncid.value)
def force_signature(force):
 # Energy functions/parameters rather than XML file timestamps or cosmetic force names.
 if isinstance(force,mm.NonbondedForce):
  particles=[tuple(float(q.value_in_unit(unit.elementary_charge)) if j==0 else float(q.value_in_unit(unit.nanometer)) if j==1 else float(q.value_in_unit(unit.kilojoule_per_mole)) for j,q in enumerate(force.getParticleParameters(i))) for i in range(force.getNumParticles())]
  exceptions=[]
  for i in range(force.getNumExceptions()):
   a,b,q,s,e=force.getExceptionParameters(i);exceptions.append([a,b,q.value_in_unit(unit.elementary_charge**2),s.value_in_unit(unit.nanometer),e.value_in_unit(unit.kilojoule_per_mole)])
  return ['NonbondedForce',particles,exceptions,int(force.getNonbondedMethod()),force.getCutoffDistance().value_in_unit(unit.nanometer)]
 if isinstance(force,mm.HarmonicBondForce):return ['HarmonicBondForce',[tuple(map(str,force.getBondParameters(i))) for i in range(force.getNumBonds())]]
 if isinstance(force,mm.HarmonicAngleForce):return ['HarmonicAngleForce',[tuple(map(str,force.getAngleParameters(i))) for i in range(force.getNumAngles())]]
 if isinstance(force,mm.PeriodicTorsionForce):return ['PeriodicTorsionForce',[tuple(map(str,force.getTorsionParameters(i))) for i in range(force.getNumTorsions())]]
 if isinstance(force,mm.CMMotionRemover):return ['CMMotionRemover',force.getFrequency()]
 raise ValueError('Unexpected force; explicit scientific review required')
def verify(output,replay=True,report_reference=None,source_reference=None):
 native_outputs=['system.xml','integrator.xml','restart-before.xml','final-state.xml','recovered.nc','native.csv','repair.log']
 submitted_outputs=['repair.json',*native_outputs,'repair.py','analysis.md']
 for name in (submitted_outputs if replay else native_outputs):
  assert (output/name).is_file() and (output/name).stat().st_size>0,'Missing '+name
 if replay:
  report=json.loads((output/'repair.json').read_text())
 else:
  assert isinstance(report_reference,dict),'Missing submitted recovery report for native replay'
  report=report_reference
  # A replay may emit an updated report (for example, if it selects a new
  # stochastic seed). Validate that report against the replay's own native
  # objects instead of requiring document or source-code self-copies.
  replay_report=output/'repair.json'
  if replay_report.is_file():report=json.loads(replay_report.read_text())
  replay_source=output/'repair.py'
  if replay_source.is_file() and source_reference is not None:
   assert hashlib.sha256(replay_source.read_bytes()).digest()==hashlib.sha256(Path(source_reference).read_bytes()).digest(),'Replay source copy differs from submitted program'
 for key in ['original_timestep_fs','corrected_timestep_fs','resume_time_ps','production_ps']:
  assert type(report[key]) in (int,float),'Recovery metrics must be JSON numbers, not booleans'
 assert type(report['equilibrium_claim']) is bool and isinstance(report['allowed_changes'],list),'Recovery flags have invalid JSON types'
 assert report['equilibrium_claim'] is False and report['validation_scope']=='numerical_recovery_only','2 ps recovery cannot grant equilibrium sampling'
 assert isinstance(report['root_causes'],list) and report['root_causes'],'Missing scientific diagnosis'
 diagnosis=report['diagnosis'];assert _failure_class(diagnosis['failure_class'])=='numerical_integration' and _unstable_parameter(diagnosis['unstable_parameter'])=='timestep_fs','Wrong scientific cause'
 assert _integer_json_number(diagnosis['failure_step']),'Failure step must be a finite integer-valued JSON number, not boolean or fractional'
 for key in ['failure_time_ps','failure_potential_kcal_mol','last_good_potential_kcal_mol']:
  assert type(diagnosis[key]) in (int,float),'Diagnosis metrics must be JSON numbers, not booleans'
 trace=json.loads((PACKAGE/'inputs/failed-trace.json').read_text())['records'][-1]
 assert diagnosis['failure_step']==trace['step'] and abs(diagnosis['failure_time_ps']-trace['time_ps'])<REFS['tolerances']['time_and_integrator'],'Diagnosis not tied to native failed propagation'
 assert np.isclose(diagnosis['failure_potential_kcal_mol'],trace['potential_kcal_mol'],rtol=REFS['tolerances']['native_energy_relative']),'Wrong native divergence evidence'
 alternatives=_alternative_categories(diagnosis['rejected_alternatives'])
 assert report['original_timestep_fs']==20 and 0<float(report['corrected_timestep_fs'])<=1,'Unsafe flexible-H timestep'
 assert _constraints_preserved(report['constraints']),'This minimal repair must retain the unconstrained model'
 # Prespecified minimal repair: no force-field reparameterization, deleting atoms or zeroing velocities.
 original=mm.XmlSerializer.deserialize((PACKAGE/'inputs/faulty-system.xml').read_text());system=load_candidate_xml(output/'system.xml',mm.System)
 assert system.getNumParticles()==original.getNumParticles()==REFS['reference']['particles'] and system.getNumConstraints()==original.getNumConstraints()==0
 assert [force_signature(f) for f in system.getForces()]==[force_signature(f) for f in original.getForces()],'Force-field alteration masks instability'
 assert [canonical_xml(f) for f in system.getForces()]==[canonical_xml(f) for f in original.getForces()],'Force settings changed'
 assert [str(system.getParticleMass(i)) for i in range(24003)]==[str(original.getParticleMass(i)) for i in range(24003)],'Mass altered'
 assert system.getDefaultPeriodicBoxVectors()==original.getDefaultPeriodicBoxVectors(),'Default periodic box changed'
 integrator=load_candidate_xml(output/'integrator.xml',mm.Integrator);dt=integrator.getStepSize().value_in_unit(unit.femtosecond)
 old_integrator=mm.XmlSerializer.deserialize((PACKAGE/'inputs/faulty-integrator.xml').read_text())
 assert canonical_xml(integrator,('stepSize','randomSeed'))==canonical_xml(old_integrator,('stepSize','randomSeed')),'Thermostat/integrator settings changed beyond timestep/random seed'
 old_seed=old_integrator.getRandomNumberSeed();new_seed=integrator.getRandomNumberSeed()
 changed=_allowed_changes(report['allowed_changes'],old_integrator.getStepSize().value_in_unit(unit.femtosecond),dt,old_seed,new_seed)
 assert abs(dt-report['corrected_timestep_fs'])<REFS['tolerances']['time_and_integrator'] and abs(integrator.getTemperature().value_in_unit(unit.kelvin)-298)<REFS['tolerances']['native_report']
 good=mm.XmlSerializer.deserialize((PACKAGE/'inputs/last-good-state.xml').read_text());before=load_candidate_xml(output/'restart-before.xml',mm.State);final=load_candidate_xml(output/'final-state.xml',mm.State)
 assert np.isclose(diagnosis['last_good_potential_kcal_mol'],good.getPotentialEnergy().value_in_unit(unit.kilocalorie_per_mole),rtol=REFS['tolerances']['native_energy_relative']),'No last-good energy evidence'
 assert _model_constraints_assessment(_constraints_assessment_value(diagnosis)),'Missing model-constraints assessment'
 for getter,u in [('getPositions',unit.angstrom),('getVelocities',unit.angstrom/unit.picosecond)]:
  x=getattr(before,getter)(asNumpy=True).value_in_unit(u);y=getattr(good,getter)(asNumpy=True).value_in_unit(u);assert np.max(np.abs(x-y))<REFS['tolerances']['restart_coordinates_angstrom'],'Did not resume native positions/velocities'
 assert np.allclose(before.getPeriodicBoxVectors().value_in_unit(unit.angstrom),good.getPeriodicBoxVectors().value_in_unit(unit.angstrom),atol=REFS['tolerances']['restart_box_angstrom']),'Restart box changed'
 assert abs(before.getTime().value_in_unit(unit.picosecond)-good.getTime().value_in_unit(unit.picosecond))<REFS['tolerances']['time_and_integrator']
 assert abs(final.getTime().value_in_unit(unit.picosecond)-2)<REFS['tolerances']['clock_ps'],'Final native clock mismatch'
 assert report['resume_time_ps']==0 and report['production_ps']==2,'Incorrect recovery duration report'
 traj=read_native_trajectory(output/'recovered.nc')
 times=traj['time'];xyz=traj['coordinates'];cells=traj['cell_lengths']
 assert canonical_units('cell_lengths',traj['cell_lengths_units'])=='angstrom','Wrong cell units'
 assert canonical_units('coordinates',traj['coordinates_units'])=='angstrom' and canonical_units('time',traj['time_units'])=='picosecond','Wrong trajectory units'
 assert xyz.shape[1:]==(24003,3) and len(times)>=11 and np.isfinite(xyz).all() and np.isfinite(cells).all()
 assert cells.shape==(len(times),3) and np.all(cells>0),'Invalid per-frame periodic box'
 native_box=np.asarray(good.getPeriodicBoxVectors().value_in_unit(unit.angstrom));assert np.allclose(native_box,np.diag(np.diag(native_box)),atol=REFS['tolerances']['orthogonal_box_angstrom']),'Expected orthogonal native box'
 assert np.allclose(cells,np.diag(native_box),atol=REFS['tolerances']['trajectory_box_angstrom'],rtol=REFS['tolerances']['trajectory_box_relative']),'Trajectory box differs from preserved native box'
 assert np.allclose(final.getPeriodicBoxVectors().value_in_unit(unit.angstrom),native_box,atol=REFS['tolerances']['restart_box_angstrom']),'Final box changed'
 assert times.shape==(len(xyz),) and np.isfinite(times).all(),'Invalid trajectory time array'
 assert times[0]==0 and abs(times[-1]-2)<REFS['tolerances']['clock_ps'] and np.all(np.diff(times)>0)
 assert np.max(np.abs(xyz[0]-good.getPositions(asNumpy=True).value_in_unit(unit.angstrom)))<REFS['tolerances']['trajectory_coordinates_angstrom'],'Trajectory does not start from good state'
 assert np.max(np.abs(xyz[-1]-final.getPositions(asNumpy=True).value_in_unit(unit.angstrom)))<REFS['tolerances']['trajectory_coordinates_angstrom'],'Native final state mismatch'
 rows=list(csv.DictReader((output/'native.csv').open()));assert len(rows)==len(times)
 dof=3*system.getNumParticles()-system.getNumConstraints()-3
 for row,t in zip(rows,times):
  assert abs(float(row['time_ps'])-t)<REFS['tolerances']['clock_ps'] and abs(float(row['step'])*dt/1000-t)<REFS['tolerances']['clock_ps']
  potential,kinetic,temperature=[float(row[k]) for k in ['potential_kcal_mol','kinetic_kcal_mol','temperature_K']]
  assert np.isfinite([potential,kinetic,temperature]).all() and kinetic>=0,'Invalid recovered dynamics'
  assert np.isclose(temperature,2*kinetic/(dof*.00198720425864083),rtol=REFS['tolerances']['temperature_relative'],atol=REFS['tolerances']['temperature_absolute_k']),'Native kinetic energy/temperature mismatch'
 for state,row in [(before,rows[0]),(final,rows[-1])]:
  velocities=state.getVelocities(asNumpy=True).value_in_unit(unit.nanometer/unit.picosecond)
  assert np.isfinite(velocities).all(),'Nonfinite native velocities'
  masses=np.array([system.getParticleMass(i).value_in_unit(unit.dalton) for i in range(system.getNumParticles())])
  kinetic_from_velocities=float(np.sum(masses[:,None]*velocities**2)/2/4.184)
  assert np.isclose(kinetic_from_velocities,float(row['kinetic_kcal_mol']),rtol=REFS['tolerances']['native_energy_relative'],atol=REFS['tolerances']['endpoint_energy_kcal_mol']),'Native velocity/kinetic energy mismatch'
  for getter,field in [('getPotentialEnergy','potential_kcal_mol'),('getKineticEnergy','kinetic_kcal_mol')]:
   assert np.isclose(getattr(state,getter)().value_in_unit(unit.kilocalorie_per_mole),float(row[field]),rtol=REFS['tolerances']['native_energy_relative'],atol=REFS['tolerances']['endpoint_energy_kcal_mol']),'Native endpoint energy/log mismatch'
 if replay:
  with tempfile.TemporaryDirectory(prefix='recovery-replay-') as d:
   out=Path(d)/'outputs';out.mkdir();r=run_replay(output/'repair.py',PACKAGE/'inputs',out,timeout=600)
   assert r.returncode==0,'Actual recovery replay failed: '+r.stderr[-1000:]
   verify(out,replay=False,report_reference=report,source_reference=output/'repair.py')
 energy_integrator=mm.VerletIntegrator(.001*unit.picosecond)
 energy_context=mm.Context(system,energy_integrator,mm.Platform.getPlatformByName('CPU'),{'Threads':'2'})
 energy_context.setPeriodicBoxVectors(*good.getPeriodicBoxVectors())
 for row,positions in zip(rows,xyz):
  potential=float(row['potential_kcal_mol'])
  energy_context.setPositions(positions*unit.angstrom)
  energy=energy_context.getState(getEnergy=True).getPotentialEnergy().value_in_unit(unit.kilocalorie_per_mole)
  assert np.isfinite(energy) and np.isclose(energy,potential,rtol=REFS['tolerances']['frame_energy_relative'],atol=REFS['tolerances']['frame_energy_kcal_mol']),'Trajectory frame/native potential mismatch'
 del energy_context,energy_integrator
 return {'status':'PASS','layers':['L1','L2','L3'],'replayed':replay,'recovered_duration_ps':2,'timestep_fs':dt,'preserved_force_field':True}
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
