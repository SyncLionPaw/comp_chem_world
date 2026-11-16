#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability.
# L2 Execution: Check execution evidence through bounded replay or independent recomputation where implemented.
# L3 Science: Construct a consistent periodic solvent model using the supplied six-site acetonitrile parameters.
"""Terminal-state science verification with private references and isolated replay."""
from __future__ import annotations
import hashlib,json,importlib,sys,traceback
from pathlib import Path
_REFS_BYTES=Path(__file__).with_name('refs.json').read_bytes()
if hashlib.sha256(_REFS_BYTES).hexdigest()!='949a3e548d1a9ffeb29ee2a8a7e2f783e871aabfdfa78660c06a0c70138ca864':
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
"""Whole-model science validation, chemistry/parameter checks and native build evidence."""
import argparse,hashlib,json,re,sys
from pathlib import Path
import numpy as np,parmed
from scipy.spatial import cKDTree
import openmm as mm
from openmm import app,unit
PACKAGE=Path(__file__).resolve().parents[1]

def check_inputs():
 import tomllib
 for i in tomllib.loads((PACKAGE/'task.toml').read_text())['requirements']['inputs']:
  p=PACKAGE/i['path']
  if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=i['sha256']:raise RuntimeError('Preflight input integrity: '+i['path'])

def load_candidate(path, **kwargs):
 try:return parmed.load_file(str(path), **kwargs)
 except parmed.exceptions.ParmedError as error:
  raise ValueError('Invalid submitted molecular file: '+str(error)) from error

def bonded_terms(top):
 """Per-residue atom-name graph and all GAFF/six-site bonded coefficients."""
 result=[{} for _ in top.residues]
 for kind,terms,fields in [('bond',top.bonds,('k','req')),('angle',top.angles,('k','theteq')),('torsion',top.dihedrals,('phi_k','per','phase','scee','scnb'))]:
  for term in terms:
   atoms=[getattr(term,'atom'+str(i)) for i in range(1, {'bond':2,'angle':3,'torsion':4}[kind]+1)]
   assert all(a.residue is atoms[0].residue for a in atoms),'Intermolecular bonded term'
   assert term.type is not None,'Missing force-field term'
   # Atom labels are user-facing names, not chemical identity. Preserve
   # topology identity by using each atom's position inside its residue.
   indices=tuple(a.idx-a.residue.atoms[0].idx for a in atoms);indices=min(indices,indices[::-1])
   key=(kind,indices,getattr(term,'improper',False),getattr(term,'ignore_end',False))
   types=list(term.type) if isinstance(term.type,parmed.DihedralTypeList) else [term.type]
   for typ in types:
    values=tuple(float(getattr(typ,f)) for f in fields)
    assert np.isfinite(values).all(),'Nonfinite bonded parameter'
    result[atoms[0].residue.idx].setdefault(key,[]).append(values)
 return result

def graph_mapping(candidate,reference,charge_tolerance,compare_lj=True,compare_mass=True,
                  candidate_terms=None,reference_terms=None,terminal_match=None):
 """Map renamed/reordered atoms by labelled molecular graph, one-to-one."""
 ca=list(candidate.atoms);ra=list(reference.atoms)
 if len(ca)!=len(ra):raise ValueError('Molecular atom count differs from reference')
 def adjacency(res):
  local={atom.idx:i for i,atom in enumerate(res.atoms)}
  graph=[set() for _ in res.atoms]
  for atom in res.atoms:
   i=local[atom.idx]
   for partner in atom.bond_partners:
    if partner.idx not in local:raise ValueError('Intermolecular bonded term')
    graph[i].add(local[partner.idx])
  return graph
 cg,rg=adjacency(candidate),adjacency(reference)
 def compatible(ci,ri):
  a,b=ca[ci],ra[ri]
  if a.atomic_number!=b.atomic_number or a.type!=b.type or len(cg[ci])!=len(rg[ri]):return False
  if abs(a.charge-b.charge)>charge_tolerance:return False
  if terminal_match is not None and not terminal_match(a,b):return False
  if compare_mass and abs(a.mass-b.mass)>=REFS['tolerances']['mass_dalton']:return False
  if compare_lj and (abs(a.sigma-b.sigma)>=REFS['tolerances']['sigma_angstrom'] or abs(a.epsilon-b.epsilon)>=REFS['tolerances']['epsilon_kcal_mol']):return False
  return True
 options=[[j for j in range(len(ra)) if compatible(i,j)] for i in range(len(ca))]
 if any(not values for values in options):raise ValueError('No element/type/parameter-preserving atom mapping exists')
 order=sorted(range(len(ca)),key=lambda i:(len(options[i]),-len(cg[i])))
 mapping={};used=set()
 def bonded_match():
  if candidate_terms is None:return True
  actual=remap_bonded_terms(candidate_terms,mapping)
  if actual.keys()!=reference_terms.keys():return False
  return all(len(actual[key])==len(reference_terms[key]) and
             np.allclose(sorted(actual[key]),sorted(reference_terms[key]),rtol=REFS['tolerances']['bonded_rtol'],atol=REFS['tolerances']['bonded_atol'])
             for key in reference_terms)
 def search(depth):
  if depth==len(order):return bonded_match()
  ci=order[depth]
  for ri in options[ci]:
   if ri in used:continue
   if any(((cj in cg[ci]) != (rj in rg[ri])) for cj,rj in mapping.items()):continue
   mapping[ci]=ri;used.add(ri)
   if search(depth+1):return True
   del mapping[ci];used.remove(ri)
  return False
 if not search(0):raise ValueError('Molecular connectivity has no one-to-one reference mapping')
 return mapping

def remap_bonded_terms(terms,atom_map):
 result={}
 for (kind,indices,improper,ignore_end),values in terms.items():
  mapped=tuple(atom_map[i] for i in indices);mapped=min(mapped,mapped[::-1])
  result[(kind,mapped,improper,ignore_end)]=values
 return result

def check_reference():
 import base64,zlib,tempfile
 native=zlib.decompress(base64.b64decode(REFS['native_topology']['data'],validate=True))
 if hashlib.sha256(native).hexdigest()!=REFS['native_topology']['sha256']:raise RuntimeError('Corrupt private native topology reference')
 with tempfile.TemporaryDirectory(prefix='native-reference-') as directory:
  p=Path(directory)/'reference.prmtop';p.write_bytes(native);reference=parmed.load_file(str(p))
 # Archived backend topology uses C/C1...H/H1...; public solute uses C1...H11... .
 # Translate by its documented native atom order, then compare by public names.
 for i,atom in enumerate(reference.residues[0].atoms):atom.name=('C' if i<10 else 'H')+str(i+1)
 bonded_terms(reference)
 return reference

def verify(output):
 for f in ['system.prmtop','system.inpcrd','system.pdb','model.json','analysis.md']:
  assert (output/f).is_file() and (output/f).stat().st_size>0,'Missing '+f
 for folder in ['parameters','logs']:assert (output/folder).is_dir() and list((output/folder).iterdir()),'Missing '+folder
 top=load_candidate(output/'system.prmtop',xyz=str(output/'system.inpcrd'))
 assert len(top.atoms)==10098 and len(top.residues)==1681,'Wrong chemical composition'
 assert np.isfinite(top.coordinates).all() and np.allclose(top.box,[56,56,56,90,90,90],atol=REFS['tolerances']['box_angstrom']),'Wrong periodic box'
 solutes=[r for r in top.residues if len(r.atoms)==18];assert len(solutes)==1,'Exactly one solute required';solute=solutes[0]
 assert sorted(a.atomic_number for a in solute.atoms)==[1]*8+[6]*10,'Solute is not C10H8'
 solvent=[r for r in top.residues if r is not solute];assert len(solvent)==1680
 expected=check_reference()
 reference_terms=bonded_terms(expected);submitted_terms=bonded_terms(top);atom_maps={}
 for res,actual in zip(top.residues,submitted_terms):
  refres=expected.residues[0 if res is solute else 1]
  charge_tol=REFS['tolerances']['solute_am1bcc_charge_e'] if res is solute else REFS['tolerances']['solvent_charge_e']
  atom_map=graph_mapping(res,refres,charge_tol,candidate_terms=actual,reference_terms=reference_terms[refres.idx])
  atom_maps[res.idx]=atom_map
  actual=remap_bonded_terms(actual,atom_map);target=reference_terms[refres.idx]
  assert actual.keys()==target.keys(),'Incorrect molecular bonded graph/1-4 exclusions'
  for key in target:
   assert len(actual[key])==len(target[key]) and np.allclose(sorted(actual[key]),sorted(target[key]),rtol=REFS['tolerances']['bonded_rtol'],atol=REFS['tolerances']['bonded_atol']),'Incorrect GAFF/six-site bonded coefficients'
  refatoms=refres.atoms
  assert len({a.name for a in res.atoms})==len(res.atoms),'Molecular atom names must be unique within each residue'
  for index,atom in enumerate(res.atoms):
   ref=refatoms[atom_map[index]]
   assert atom.type==ref.type and abs(atom.mass-ref.mass)<REFS['tolerances']['mass_dalton'] and abs(atom.sigma-ref.sigma)<REFS['tolerances']['sigma_angstrom'] and abs(atom.epsilon-ref.epsilon)<REFS['tolerances']['epsilon_kcal_mol'],'Incorrect GAFF/six-site atom parameters'
 refsolv=expected.residues[1]
 for res in solvent:
  atom_map=atom_maps[res.idx]
  assert len(res.atoms)==6 and sorted(a.atomic_number for a in res.atoms)==[1]*3+[6]*2+[7],'Wrong acetonitrile molecule'
  for index,atom in enumerate(res.atoms):
   ref=refsolv.atoms[atom_map[index]]
   assert abs(atom.charge-ref.charge)<REFS['tolerances']['solvent_charge_e'] and abs(atom.mass-ref.mass)<REFS['tolerances']['mass_dalton'],'Wrong six-site solvent charge/mass'
   assert abs(atom.sigma-ref.sigma)<REFS['tolerances']['sigma_angstrom'] and abs(atom.epsilon-ref.epsilon)<REFS['tolerances']['epsilon_kcal_mol'],'Wrong solvent LJ parameter'
 charge=sum(a.charge for a in top.atoms);assert abs(charge)<=REFS['tolerances']['net_charge_e'],'Wrong charge balance'
 # Every molecule must be connected internally and disconnected from all other molecules.
 for res in top.residues:
  ids={a.idx for a in res.atoms};seen={res.atoms[0].idx};todo=[res.atoms[0]]
  while todo:
   atom=todo.pop()
   for partner in atom.bond_partners:
    assert partner.idx in ids,'Spurious intermolecular bond'
    if partner.idx not in seen:seen.add(partner.idx);todo.append(partner)
  assert seen==ids,'Disconnected/incomplete molecule'
 for group in [top.bonds,top.angles,top.dihedrals]:
  for term in group:assert term.type is not None,'Missing force-field term'
 assert len([b for b in top.bonds if b.atom1.residue is solute])==19,'Incorrect naphthalene connectivity'
 assert all(a.type=='ca' for a in solute.atoms if a.atomic_number==6),'Not aromatic GAFF carbon'
 assert all(a.type=='ha' for a in solute.atoms if a.atomic_number==1),'Not GAFF aromatic hydrogen'
 paramfiles=list((output/'parameters').glob('*.mol2'));assert paramfiles,'No solute charge artifact'
 parameter=None
 for path in sorted(paramfiles):
  candidate=load_candidate(path)
  if len(candidate.atoms)!=18:continue
  try:
   candidate_map=graph_mapping(candidate,solute,REFS['tolerances']['parameter_topology_charge_e'],compare_lj=False,compare_mass=False)
  except ValueError:continue
  parameter,parameter_map=candidate,candidate_map
  break
 assert parameter is not None,'No matching solute parameter artifact'
 for index,a in enumerate(parameter.atoms):assert abs(a.charge-solute.atoms[parameter_map[index]].charge)<REFS['tolerances']['parameter_topology_charge_e'],'Parameter/topology charge mismatch'
 # Charge distribution against independent real AM1-BCC calculation; mapping by native atom name.
 reference=REFS['am1bcc_reference']
 reference_residue=expected.residues[0]
 solute_map=graph_mapping(solute,reference_residue,REFS['tolerances']['solute_am1bcc_charge_e'],
                          terminal_match=lambda atom,ref: abs(atom.charge-reference['charges_by_name'][ref.name])<=REFS['tolerances']['solute_am1bcc_charge_e'])
 for index,a in enumerate(solute.atoms):
  ref=reference_residue.atoms[solute_map[index]]
  assert abs(a.charge-reference['charges_by_name'][ref.name])<=REFS['tolerances']['solute_am1bcc_charge_e'],'Not supported AM1-BCC charge distribution'
 pairs=cKDTree(np.mod(top.coordinates,56),boxsize=56).query_pairs(REFS['tolerances']['nonbonded_clash_distance_angstrom'])
 bonded={tuple(sorted([b.atom1.idx,b.atom2.idx])) for b in top.bonds}
 assert not (set(pairs)-bonded),'Coincident nonbonded atoms'
 pdb=load_candidate(output/'system.pdb');assert len(pdb.atoms)==10098,'PDB atom count mismatch'
 assert [a.name for a in pdb.atoms]==[a.name for a in top.atoms],'PDB/topology atom order mismatch'
 dx=pdb.coordinates-top.coordinates;dx-=dx[0].copy();dx-=56*np.rint(dx/56);assert np.max(np.abs(dx))<REFS['tolerances']['pdb_coordinates_angstrom'],'PDB/coordinate mismatch'
 logfiles=[p for p in (output/'logs').glob('*') if p.is_file()]
 text='\n'.join(p.read_text(errors='replace') for p in logfiles)
 assert re.search(r'antechamber|sqm|AM1',text,re.I) and re.search(r'packmol|packing',text,re.I),'No native parameterization/packing evidence'
 for logfile in logfiles:
  logtext=logfile.read_text(errors='replace')
  failures=list(re.finditer(r'FATAL ERROR|ABORTING|Illegal seek',logtext,re.I))
  recoveries=list(re.finditer(r'Exiting LEaP:\s*Errors\s*=\s*0\b|Calculation Completed|Running time:',logtext,re.I))
  if failures and (not recoveries or recoveries[-1].start()<failures[-1].start()):
   raise AssertionError('Unresolved native build failure in final log '+logfile.name)
 model=json.loads((output/'model.json').read_text())
 for k in ['charge','multiplicity','solute_atoms','solvent_molecules','box_angstrom','net_charge','force_fields','parameter_warnings']:assert k in model,'Missing model field '+k
 for k in ['charge','multiplicity','solute_atoms','solvent_molecules']:
  assert type(model[k]) is int,'Model count/state fields must be JSON integers, not booleans'
 assert type(model['net_charge']) in (int,float) and isinstance(model['box_angstrom'],list) and all(type(v) in (int,float) for v in model['box_angstrom']),'Model physical values must be JSON numbers, not booleans'
 assert model['charge']==0 and model['multiplicity']==1 and model['solute_atoms']==18 and model['solvent_molecules']==1680
 assert abs(float(model['net_charge'])-charge)<REFS['tolerances']['model_net_charge_e'] and np.allclose(model['box_angstrom'],[56]*3,atol=REFS['tolerances']['box_angstrom']),'Incorrect model summary'
 # Independently instantiate the returned force field; file presence cannot prove valid physics.
 crd=app.AmberInpcrdFile(str(output/'system.inpcrd'));pt=app.AmberPrmtopFile(str(output/'system.prmtop'),periodicBoxVectors=crd.boxVectors)
 try:system=pt.createSystem(nonbondedMethod=app.PME,nonbondedCutoff=1*unit.nanometer,constraints=app.HBonds)
 except mm.OpenMMException as error:raise ValueError('Invalid submitted force field: '+str(error)) from error
 integrator=mm.VerletIntegrator(.001*unit.picosecond);context=mm.Context(system,integrator,mm.Platform.getPlatformByName('CPU'),{'Threads':'2'});context.setPositions(crd.positions)
 state=context.getState(getEnergy=True,getForces=True);energy=state.getPotentialEnergy().value_in_unit(unit.kilocalorie_per_mole);forces=state.getForces(asNumpy=True).value_in_unit(unit.kilojoule_per_mole/unit.nanometer)
 assert np.isfinite(energy) and np.isfinite(forces).all(),'Invalid physical model'
 return {'status':'PASS','layers':['L1','L2','L3'],'atoms':10098,'solvent_molecules':1680,'total_charge_e':charge,'initial_energy_kcal_mol':energy}

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
