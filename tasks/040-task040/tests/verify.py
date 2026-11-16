# L1 Deliverables: Check required deliverables for completeness and parseability.
# L2 Execution: Check execution evidence through bounded replay or independent recomputation where implemented.
# L3 Science: Analyse local Au–C force responses and numerical consistency in fixed water/potassium environments.
from __future__ import annotations
'Translate the scientific verifier protocol to the CompChemBench grader contract.'
import json
import math
import os
from pathlib import Path
import subprocess
import sys

def _grade_entry():
    app = Path(os.environ.get('APP', '/app'))
    tests = Path(os.environ.get('TESTS', Path(__file__).resolve().parent))
    logs = Path(os.environ.get('LOGS', '/logs/verifier'))
    logs.mkdir(parents=True, exist_ok=True)
    reward_file = logs / 'reward.txt'
    reward_file.unlink(missing_ok=True)
    report_file = logs / 'verification.json'
    report_file.unlink(missing_ok=True)
    try:
        proc = subprocess.run([sys.executable, str(tests / 'verify.py'), str(app / 'final')], capture_output=True, text=True, timeout=540)
        (logs / 'verify.stdout.log').write_text(proc.stdout)
        (logs / 'verify.stderr.log').write_text(proc.stderr)
        result = json.loads(proc.stdout)
        if not isinstance(result, dict):
            raise ValueError('verifier result must be an object')
        status = result.get('status')
        reward = result.get('reward')
        if status in {'PASS', 'FAIL'}:
            expected = int(status == 'PASS')
            if type(reward) not in {int, float} or not math.isfinite(reward) or reward != expected or (proc.returncode != (0 if expected else 1)):
                raise ValueError('inconsistent scientific status/reward/exit code')
            report_file.write_text(json.dumps(result, ensure_ascii=False) + '\n')
            reward_file.write_text(str(expected) + '\n')
            print(json.dumps(result, ensure_ascii=False))
            return proc.returncode
        if status == 'REVIEW_REQUIRED' and proc.returncode == 2 and ('reward' not in result):
            report_file.write_text(json.dumps(result, ensure_ascii=False) + '\n')
            print(json.dumps(result, ensure_ascii=False))
            return 0
        elif status == 'ENVIRONMENT_ERROR' and proc.returncode == 2 and ('reward' not in result):
            result = {**result, 'scientific_status': status, 'status': 'ENV_INVALID'}
        else:
            raise ValueError('unknown/inconsistent verifier status or exit code')
    except Exception as exc:
        result = {'status': 'ENV_INVALID', 'error': type(exc).__name__ + ': ' + str(exc)}
    report_file.write_text(json.dumps(result, ensure_ascii=False) + '\n')
    print(json.dumps(result, ensure_ascii=False))
    return 2
if __name__ == '__main__' and sys.argv[1:] == ['--grade']:
    raise SystemExit(_grade_entry())
'Strict scientific verifier for Case 05 frozen-native response deliverables.'
import csv
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
'Recompute Case 05 revision-3 local-response diagnostics from frozen VASP evidence.'
import csv as _bench40_0_csv
import hashlib as _bench40_0_hashlib
import json as _bench40_0_json
import math as _bench40_0_math
import os as _bench40_0_os
import re as _bench40_0_re
import sys as _bench40_0_sys
import tarfile as _bench40_0_tarfile
import tempfile as _bench40_0_tempfile
import xml.etree.ElementTree as _bench40_0_ET
from pathlib import Path as _bench40_0_Path, PurePosixPath as _bench40_0_PurePosixPath
_bench40_0_REQUIRED_POINTS = 13
_bench40_0_MAX_HISTORICAL_FORCE_EVALUATIONS = 24
_bench40_0_SHIFT_A = 0.02
_bench40_0_ABS_TOL = 0.05
_bench40_0_REL_TOL = 0.05
_bench40_0_TRIPLES = ('water-r26', 'water-r30', '2K-r26', '2K-r30')
_bench40_0_POINT_IDS = ('water-r26-minus', 'water-r26-center', 'water-r26-plus', 'water-r30-minus', 'water-r30-center', 'water-r30-plus', '2K-r26-minus', '2K-r26-center', '2K-r26-plus', '2K-r30-minus', '2K-r30-center', '2K-r30-plus', '2K-r26-alt-center')

def _bench40_0_sha256(path):
    h = _bench40_0_hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()

def _bench40_0_json_read(path):
    with open(path, encoding='utf-8') as f:
        return _bench40_0_json.load(f)

def _bench40_0_read_native(asset_dir):
    """Read an unpacked fixture or a path-safe tar archive, never following archive links."""
    asset_dir = _bench40_0_Path(asset_dir)
    archive = asset_dir / 'IS_native.tar.gz'
    if archive.is_file():
        members = {}
        manifest_path = asset_dir / 'IS_native_manifest.json'
        manifest = _bench40_0_json_read(manifest_path) if manifest_path.is_file() else {}
        archive_digest = _bench40_0_sha256(archive)
        if manifest.get('archive_sha256') and archive_digest != manifest['archive_sha256'].removeprefix('sha256:'):
            raise ValueError('native archive SHA-256 mismatch')
        with _bench40_0_tarfile.open(archive, 'r:gz') as tf:
            for m in tf.getmembers():
                p = _bench40_0_PurePosixPath(m.name)
                if p.is_absolute() or '..' in p.parts or (not p.parts):
                    raise ValueError('unsafe native archive member path')
                if m.issym() or m.islnk() or (not (m.isfile() or m.isdir())):
                    raise ValueError('native archive contains a non-regular member')
                if m.isfile():
                    src = tf.extractfile(m)
                    if src is None:
                        raise ValueError('native archive member unreadable')
                    members[p.as_posix()] = src.read()
        if manifest:
            expected = manifest.get('files', manifest.get('sha256', {}))
            if isinstance(expected, dict):
                for name, value in expected.items():
                    digest = value.get('sha256') if isinstance(value, dict) else value
                    digest = str(digest).removeprefix('sha256:')
                    if name in members and _bench40_0_hashlib.sha256(members[name]).hexdigest() != digest:
                        raise ValueError('native archive source hash mismatch: ' + name)
                    if name not in members:
                        raise ValueError('manifest native source missing from archive: ' + name)
        with _bench40_0_tempfile.TemporaryDirectory(prefix='case05-native-') as td:
            root = _bench40_0_Path(td)
            for name, data in members.items():
                dest = root.joinpath(*_bench40_0_PurePosixPath(name).parts)
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(data)
            yield_root = root
            return _bench40_0_analyze_native(yield_root, asset_dir)
    if (asset_dir / 'native').is_dir():
        return _bench40_0_analyze_native(asset_dir, asset_dir)
    raise ValueError('ASSET_DIR must contain IS_native.tar.gz and IS_native_manifest.json')

def _bench40_0_parse_poscar(path):
    lines = _bench40_0_Path(path).read_text().splitlines()
    scale = float(lines[1].split()[0])
    cell = [[float(x) * scale for x in lines[i].split()[:3]] for i in range(2, 5)]
    symbols = lines[5].split()
    counts = [int(x) for x in lines[6].split()]
    if len(symbols) != len(counts):
        raise ValueError('POSCAR species/count mismatch')
    i = 7
    if lines[i].strip().lower().startswith('s'):
        i += 1
    mode = lines[i].strip().lower()
    i += 1
    species = [s for s, n in zip(symbols, counts) for _ in range(n)]
    coords = [[float(x) for x in lines[i + j].split()[:3]] for j in range(len(species))]
    if mode.startswith('d'):
        coords = [[sum((coords[k] * cell[k][j] for k in range(3))) for j in range(3)] for coords in coords]
    elif not mode.startswith(('c', 'k')):
        raise ValueError('unknown POSCAR coordinate mode')
    return {'cell': cell, 'species': species, 'cart': coords}

def _bench40_0_dot(a, b):
    return sum((x * y for x, y in zip(a, b)))

def _bench40_0_norm(a):
    return _bench40_0_math.sqrt(_bench40_0_dot(a, a))

def _bench40_0_delta(a, b):
    return [x - y for x, y in zip(a, b)]

def _bench40_0_periodic_vector(pos, i, j):
    d = _bench40_0_delta(pos['cart'][i], pos['cart'][j])
    images = [[d[k] - a * pos['cell'][0][k] - b * pos['cell'][1][k] - c * pos['cell'][2][k] for k in range(3)] for a in (-1, 0, 1) for b in (-1, 0, 1) for c in (-1, 0, 1)]
    return min(images, key=_bench40_0_norm)

def _bench40_0_periodic_distance(pos, i, j):
    return _bench40_0_norm(_bench40_0_periodic_vector(pos, i, j))

def _bench40_0_extxyz_frame(path, requested_id):
    lines = _bench40_0_Path(path).read_text().splitlines()
    offset = 0
    while offset < len(lines):
        count = int(lines[offset].strip())
        header = lines[offset + 1]
        seed_match = _bench40_0_re.search('(?:^|\\s)seed_id=([^\\s]+)', header)
        if seed_match and seed_match.group(1) == requested_id:
            match = _bench40_0_re.search('Lattice="([^"]+)"', header)
            if not match:
                raise ValueError('seed geometry lacks cell matrix')
            system_match = _bench40_0_re.search('(?:^|\\s)system=([^\\s]+)', header)
            frame_match = _bench40_0_re.search('(?:^|\\s)source_frame=(\\d+)', header)
            if not system_match or not frame_match:
                raise ValueError('seed geometry lacks system or source-frame identity')
            values = [float(x) for x in match.group(1).split()]
            cell = [values[3 * i:3 * i + 3] for i in range(3)]
            atoms = [lines[offset + 2 + i].split() for i in range(count)]
            raw_frame = '\n'.join(lines[offset:offset + count + 2])
            raw_frame_sha256 = _bench40_0_hashlib.sha256(raw_frame.encode('utf-8')).hexdigest()
            return {'cell': cell, 'species': [a[0] for a in atoms], 'system': system_match.group(1), 'frame_zero_based': int(frame_match.group(1)), 'cart': [[float(x) for x in a[1:4]] for a in atoms], 'raw_frame_sha256': raw_frame_sha256}
        offset += count + 2
    raise ValueError('seed candidate not found in public geometry panel: ' + requested_id)

def _bench40_0_public_seed_comparison(reference, asset_dir, seed_id, selected_point_id):
    """Recompute a candidate seed/center comparison from public input assets."""
    asset_dir = _bench40_0_Path(asset_dir)
    if not isinstance(seed_id, str) or not seed_id.strip():
        raise ValueError('unselected seed identity is missing')
    if not isinstance(selected_point_id, str) or not selected_point_id.strip():
        raise ValueError('selected point identity is missing')
    provenance_path = asset_dir / 'IS_seed_provenance.json'
    panel_path = asset_dir / 'IS_seed_panel.extxyz'
    provenance = _bench40_0_json_read(provenance_path)
    panel_sha = _bench40_0_sha256(panel_path)
    if provenance.get('panel_sha256') != panel_sha:
        raise ValueError('public seed panel SHA-256 differs from provenance')
    records = provenance.get('records')
    if not isinstance(records, list):
        raise ValueError('public seed provenance records are missing')
    record = next((row for row in records if isinstance(row, dict) and row.get('seed_id') == seed_id), None)
    if record is None:
        raise ValueError('unselected seed is absent from the public seed panel')
    seed = _bench40_0_extxyz_frame(panel_path, seed_id)
    cidx = record.get('carbon_index_zero_based')
    auidx = record.get('nearest_Au_index_zero_based')
    if type(cidx) is not int or type(auidx) is not int or cidx < 0 or (auidx < 0) or (cidx >= len(seed['species'])) or (auidx >= len(seed['species'])):
        raise ValueError('public seed atom mapping is invalid')
    source = record.get('source_path', '')
    expected_system = '2K' if '2K_CO2_' in source else 'water' if 'water_CO2_' in source else None
    if expected_system is None or seed['system'] != expected_system:
        raise ValueError('public seed system identity differs from its provenance')
    if seed['frame_zero_based'] != record.get('frame_zero_based') or len(seed['species']) != record.get('atoms'):
        raise ValueError('public seed frame or atom count differs from provenance')
    if seed['species'][cidx] != 'C' or seed['species'][auidx] != 'Au':
        raise ValueError('public seed carbon/Au source mapping is invalid')
    center_row = next((row for row in reference.get('inputs', []) if isinstance(row, dict) and isinstance(row.get('point'), dict) and (row['point'].get('point_id') == selected_point_id) and (row['point'].get('shift_A') == 0.0) and str(row['point'].get('point_id', '')).endswith('-center')), None)
    if center_row is None:
        raise ValueError('selected point is not a measured center')
    point = center_row['point']
    seed_center = next((row for row in reference.get('inputs', []) if isinstance(row, dict) and isinstance(row.get('point'), dict) and (row['point'].get('system') == seed['system']) and (row['point'].get('shift_A') == 0.0) and str(row['point'].get('point_id', '')).endswith('-center')), None)
    if seed_center is None:
        raise ValueError('public seed system has no measured center atom mapping')
    seed_co2 = seed_center['point'].get('CO2_indices_zero_based')
    if not isinstance(seed_co2, list) or len(seed_co2) != 3 or seed_co2[0] != cidx or any((type(i) is not int or i < 0 or i >= len(seed['species']) for i in seed_co2)) or ([seed['species'][i] for i in seed_co2] != ['C', 'O', 'O']):
        raise ValueError('public seed CO2 atom mapping disagrees with its system source point')
    center_id = point.get('center_id')
    selected_geometry = center_row.get('poscar')
    if not isinstance(selected_geometry, dict):
        raise ValueError('selected center geometry is unavailable')
    selected_co2 = point.get('CO2_indices_zero_based')
    selected_pair = point.get('C_Au_indices_zero_based')
    if not isinstance(selected_co2, list) or len(selected_co2) != 3 or (not isinstance(selected_pair, list)) or (len(selected_pair) != 2):
        raise ValueError('selected center CO2/C-Au mapping is invalid')

    def metrics(pos, co2, carbon_index, gold_index):
        potassium = [i for i, symbol in enumerate(pos['species']) if symbol == 'K']
        water_oxygen = [i for i, symbol in enumerate(pos['species']) if symbol == 'O' and i not in co2]
        return {'C_Au_distance_A': _bench40_0_periodic_distance(pos, carbon_index, gold_index), 'CO_bond_lengths_A': [_bench40_0_periodic_distance(pos, co2[0], co2[1]), _bench40_0_periodic_distance(pos, co2[0], co2[2])], 'OCO_angle_deg': _bench40_0_co_angle(pos, co2), 'nearest_K_to_C_A': min((_bench40_0_periodic_distance(pos, carbon_index, i) for i in potassium), default=None), 'nearest_non_CO2_oxygen_to_C_A': min((_bench40_0_periodic_distance(pos, carbon_index, i) for i in water_oxygen), default=None)}
    seed_metrics = metrics(seed, seed_co2, cidx, auidx)
    selected_metrics = metrics(selected_geometry, selected_co2, selected_pair[0], selected_pair[1])
    recorded_cv = record.get('nearest_C_Au_distance_A')
    if not isinstance(recorded_cv, (int, float)) or isinstance(recorded_cv, bool) or (not _bench40_0_math.isfinite(recorded_cv)) or (abs(seed_metrics['C_Au_distance_A'] - recorded_cv) > 1e-05):
        raise ValueError('public seed C-Au geometry disagrees with its source provenance')
    canonical = ['cell ' + ' '.join('%.8f' % float(x) for row in seed['cell'] for x in row)]
    canonical.extend('%s %.8f %.8f %.8f' % (s, *p) for s, p in zip(seed['species'], seed['cart']))
    frame_sha = _bench40_0_hashlib.sha256(('\n'.join(canonical) + '\n').encode('utf-8')).hexdigest()
    _, selected_xml = _xml_poscar_variants(asset_dir, selected_point_id)
    selected_metrics_xml = metrics(selected_xml, selected_co2, selected_pair[0], selected_pair[1])
    return {'seed_id': seed_id, 'source_frame_zero_based': seed['frame_zero_based'], 'source_geometry_sha256': panel_sha, 'source_geometry_sha256_options': [panel_sha, frame_sha, seed['raw_frame_sha256']], 'comparison_selected_point': selected_point_id, 'metrics': seed_metrics, 'selected_metrics': selected_metrics, 'selected_metrics_xml': selected_metrics_xml}

def _bench40_0_co_angle(pos, co2):
    v1 = _bench40_0_periodic_vector(pos, co2[1], co2[0])
    v2 = _bench40_0_periodic_vector(pos, co2[2], co2[0])
    cosine = max(-1.0, min(1.0, _bench40_0_dot(v1, v2) / (_bench40_0_norm(v1) * _bench40_0_norm(v2))))
    return _bench40_0_math.degrees(_bench40_0_math.acos(cosine))

def _bench40_0_xml_point(attempt_dir, point):
    tree = _bench40_0_ET.parse(attempt_dir / 'vasprun.xml')
    root = tree.getroot()
    calcs = root.findall('calculation')
    if not calcs:
        raise ValueError('vasprun.xml has no calculations')
    calc = calcs[-1]
    e = calc.find('./energy/i[@name="e_fr_energy"]')
    fv = calc.find('./varray[@name="forces"]')
    if e is None or fv is None:
        raise ValueError('final XML calculation missing free energy or forces')
    forces = [[float(v) for v in row.text.split()[:3]] for row in fv.findall('v')]
    inds = point['CO2_indices_zero_based']
    direction = point['direction_Au_to_C']
    if max(inds) >= len(forces):
        raise ValueError('CO2 force index exceeds XML atom count')
    gradient = -sum((_bench40_0_dot(forces[i], direction) for i in inds))
    scf = len(root.findall('.//scstep'))
    return (float(e.text), gradient, scf, len(forces))

def _bench40_0_analyze_native(root, asset_dir=None):
    root = _bench40_0_Path(root)
    points = _bench40_0_json_read(root / 'points.json')
    if isinstance(points, dict):
        points = points.get('points')
    ledger = [_bench40_0_json.loads(line) for line in (root / 'native/force-budget.jsonl').read_text().splitlines() if line.strip()]
    by_id = {p['point_id']: p for p in points}
    potcar_provenance = _bench40_0_json_read(root / 'potcar-provenance.json')
    potcar_hashes = {p['point_id']: p['sha256'] for p in potcar_provenance['points']}
    if len(points) != _bench40_0_REQUIRED_POINTS or set(by_id) != set(_bench40_0_POINT_IDS):
        raise ValueError('native point set/count does not match frozen revision-3 reference')
    if len(ledger) != _bench40_0_REQUIRED_POINTS or len({x.get('point_id') for x in ledger}) != _bench40_0_REQUIRED_POINTS:
        raise ValueError('historical force budget ledger does not account for 13 unique calls')
    rows = []
    geometry = {}
    source_hashes = {}
    for n, pid in enumerate(_bench40_0_POINT_IDS, 1):
        p = by_id[pid]
        attempt = root / 'native' / f'attempt-{n:03d}'
        inp = _bench40_0_json_read(attempt / 'input.json')
        if inp.get('point_id') != pid or inp.get('point') != p:
            raise ValueError('native input-to-point mapping mismatch: ' + pid)
        for name in ('POSCAR', 'INCAR', 'KPOINTS'):
            expected = inp.get('input_sha256', {}).get(name)
            if not expected or _bench40_0_sha256(attempt / name) != expected:
                raise ValueError('native input hash mismatch: ' + pid + '/' + name)
        if inp.get('point', {}).get('POTCAR_sha256') != potcar_hashes.get(pid) or inp.get('input_sha256', {}).get('POTCAR') != potcar_hashes.get(pid):
            raise ValueError('native POTCAR source-provenance mismatch: ' + pid)
        for name in ('vasprun.xml', 'OUTCAR', 'POSCAR', 'INCAR', 'KPOINTS', 'OSZICAR', 'input.json'):
            source_hashes[f'native/attempt-{n:03d}/{name}'] = _bench40_0_sha256(attempt / name)
        energy, gradient, scf, natoms = _bench40_0_xml_point(attempt, p)
        pos = _bench40_0_parse_poscar(attempt / 'POSCAR')
        if natoms != len(pos['species']):
            raise ValueError('XML/POSCAR atom-count mismatch: ' + pid)
        incar = (attempt / 'INCAR').read_text()
        outcar = (attempt / 'OUTCAR').read_text(errors='replace')
        oszicar_text = (attempt / 'OSZICAR').read_text()
        oszicar_steps = len(_bench40_0_re.findall('^(?:DAV|RMM|CG|DMP):\\s*\\d+', oszicar_text, _bench40_0_re.M))

        def incar_value(name):
            match = _bench40_0_re.search('^\\s*' + _bench40_0_re.escape(name) + '\\s*=\\s*([^!#\\n]+)', incar, _bench40_0_re.I | _bench40_0_re.M)
            return match.group(1).strip().lower() if match else None
        expected_controls = {'ENCUT': '400', 'GGA': 'pe', 'IVDW': '11', 'NSW': '0', 'IBRION': '-1', 'ISMEAR': '1', 'SIGMA': '0.20', 'EDIFF': '1e-5'}
        controls_ok = all((incar_value(k) is not None and float(incar_value(k)) == float(v) if k in {'ENCUT', 'SIGMA', 'EDIFF'} else incar_value(k) == v for k, v in expected_controls.items()))
        kpoints_ok = _bench40_0_re.search('^\\s*3\\s+3\\s+1\\s*$', (attempt / 'KPOINTS').read_text(), _bench40_0_re.M) is not None
        direction_norm = _bench40_0_norm(p['direction_Au_to_C'])
        static_ok = controls_ok and kpoints_ok
        scf_ok = 'aborting loop because EDIFF is reached' in outcar and oszicar_steps == scf
        if not static_ok or not scf_ok or abs(direction_norm - 1.0) > 1e-08:
            raise ValueError('native point did not satisfy static/SCF convergence audit: ' + pid)
        result = {'point_id': pid, 'system': p['system'], 'kind': p['kind'], 'center_id': p['center_id'], 'q_center_A': p['q_center_A'], 'shift_A': p['shift_A'], 'point': p, 'poscar': pos, 'energy': energy, 'gradient': gradient, 'scf': scf, 'scf_converged': scf_ok, 'static_input': static_ok, 'method_controls': {'required_controls_match': controls_ok, 'kpoints_3x3x1': kpoints_ok, 'CO2_direction_norm': direction_norm}, 'native_id': f'native/attempt-{n:03d}', 'attempt': attempt}
        rows.append(result)
        geometry[pid] = result
    by_center = {}
    for row in rows:
        by_center.setdefault(row['center_id'], []).append(row)
    center_stats = {}
    for center in _bench40_0_TRIPLES:
        group = sorted(by_center.get(center, []), key=lambda r: r['shift_A'])
        if len(group) != 3 or [r['shift_A'] for r in group] != [-_bench40_0_SHIFT_A, 0.0, _bench40_0_SHIFT_A]:
            raise ValueError('incomplete or incorrectly spaced three-point path: ' + center)
        minus, middle, plus = group
        fd = (plus['energy'] - minus['energy']) / (2 * _bench40_0_SHIFT_A)
        diff = abs(middle['gradient'] - fd)
        threshold = _bench40_0_ABS_TOL + _bench40_0_REL_TOL * max(abs(middle['gradient']), abs(fd))
        center_stats[center] = {'finite_difference_gradient_eV_per_A': fd, 'force_gradient_eV_per_A': middle['gradient'], 'deviation_eV_per_A': diff, 'threshold_eV_per_A': threshold, 'consistent': diff <= threshold, 'local_zero_energy_eV': middle['energy'], 'system': middle['point']['system'], 'q_center_A': middle['point']['q_center_A']}
    path_checks = {}
    for center in _bench40_0_TRIPLES:
        group = [r for r in rows if r['center_id'] == center]
        center_row = next((r for r in group if r['shift_A'] == 0))
        base = center_row['poscar']
        co2 = center_row['point']['CO2_indices_zero_based']
        u = center_row['point']['direction_Au_to_C']
        checks = []
        for row in group:
            pos = row['poscar']
            same_env = pos['species'] == base['species'] and all((abs(pos['cell'][i][j] - base['cell'][i][j]) < 1e-08 for i in range(3) for j in range(3)))
            cind, auind = row['point']['C_Au_indices_zero_based']
            observed_cv = _bench40_0_periodic_distance(pos, cind, auind)
            expected_cv = row['q_center_A'] + row['shift_A']
            actual_au_to_c = _bench40_0_periodic_vector(pos, cind, auind)
            actual_unit = [x / observed_cv for x in actual_au_to_c]
            direction_error = _bench40_0_norm(_bench40_0_delta(actual_unit, u))
            max_co2_error = 0.0
            max_env_move = 0.0
            for i, (actual, origin) in enumerate(zip(pos['cart'], base['cart'])):
                d = _bench40_0_delta(actual, origin)
                d = _bench40_0_periodic_vector({'cell': pos['cell'], 'cart': [actual, origin]}, 0, 1)
                if i in co2:
                    max_co2_error = max(max_co2_error, _bench40_0_norm(_bench40_0_delta(d, [row['shift_A'] * x for x in u])))
                else:
                    max_env_move = max(max_env_move, _bench40_0_norm(d))
            checks.append({'point_id': row['point_id'], 'cell_species_match': same_env, 'observed_C_Au_distance_A': observed_cv, 'expected_C_Au_distance_A': expected_cv, 'C_Au_distance_error_A': abs(observed_cv - expected_cv), 'Au_to_C_direction_error': direction_error, 'max_CO2_translation_error_A': max_co2_error, 'max_environment_displacement_A': max_env_move})
        path_checks[center] = {'points': checks, 'pass': all((c['cell_species_match'] and c['C_Au_distance_error_A'] < 2e-05 and (c['Au_to_C_direction_error'] < 1e-08) and (c['max_CO2_translation_error_A'] < 2e-05) and (c['max_environment_displacement_A'] < 2e-05) for c in checks))}
    center = geometry['2K-r26-center']['poscar']
    alt = geometry['2K-r26-alt-center']['poscar']
    cv_indices = geometry['2K-r26-center']['point']['C_Au_indices_zero_based']
    cind, auind = cv_indices
    cv_main, cv_alt = (_bench40_0_periodic_distance(center, cind, auind), _bench40_0_periodic_distance(alt, cind, auind))
    alt_direction = geometry['2K-r26-alt-center']['point']['direction_Au_to_C']
    alt_vector = _bench40_0_periodic_vector(alt, cind, auind)
    alt_direction_error = _bench40_0_norm(_bench40_0_delta([x / cv_alt for x in alt_vector], alt_direction))
    co2i = geometry['2K-r26-center']['point']['CO2_indices_zero_based']

    def co_bond(pos):
        return (_bench40_0_periodic_distance(pos, co2i[0], co2i[1]), _bench40_0_periodic_distance(pos, co2i[0], co2i[2]))
    main_bond, alt_bond = (co_bond(center), co_bond(alt))
    init_sensitivity = geometry['2K-r26-alt-center']['gradient'] - geometry['2K-r26-center']['gradient']
    sys_effects = {}
    for q in (2.6, 3.0):
        w = center_stats[f'water-r{int(10 * q)}']['force_gradient_eV_per_A']
        k = center_stats[f'2K-r{int(10 * q)}']['force_gradient_eV_per_A']
        sys_effects[str(q)] = {'water_gradient_eV_per_A': w, '2K_gradient_eV_per_A': k, '2K_minus_water_eV_per_A': k - w}
    method_checks = {r['point_id']: r['method_controls'] for r in rows}
    source_hashes['points.json'] = _bench40_0_sha256(root / 'points.json')
    source_hashes['native/force-budget.jsonl'] = _bench40_0_sha256(root / 'native/force-budget.jsonl')
    source_hashes['potcar-provenance.json'] = _bench40_0_sha256(root / 'potcar-provenance.json')
    unselected = None
    if asset_dir is not None:
        asset_dir = _bench40_0_Path(asset_dir)
        seed_records = _bench40_0_json_read(asset_dir / 'IS_seed_provenance.json')['records']
        source_hashes['IS_seed_panel.extxyz'] = _bench40_0_sha256(asset_dir / 'IS_seed_panel.extxyz')
        source_hashes['IS_seed_provenance.json'] = _bench40_0_sha256(asset_dir / 'IS_seed_provenance.json')
        record = next((r for r in seed_records if r['seed_id'] == '2K-SG-1713'))
        seed = _bench40_0_extxyz_frame(asset_dir / 'IS_seed_panel.extxyz', record['seed_id'])
        seed_co2 = geometry['2K-r30-center']['point']['CO2_indices_zero_based']
        seed_c, seed_au = (record['carbon_index_zero_based'], record['nearest_Au_index_zero_based'])
        target = geometry['2K-r30-center']['poscar']

        def seed_metrics(pos, co2, cidx, auidx):
            nearest_k = min((_bench40_0_periodic_distance(pos, cidx, i) for i, s in enumerate(pos['species']) if s == 'K'))
            non_co2_oxygen = [i for i, s in enumerate(pos['species']) if s == 'O' and i not in co2]
            nearest_water_o = min((_bench40_0_periodic_distance(pos, cidx, i) for i in non_co2_oxygen))
            return {'C_Au_distance_A': _bench40_0_periodic_distance(pos, cidx, auidx), 'CO_bond_lengths_A': [_bench40_0_periodic_distance(pos, co2[0], co2[1]), _bench40_0_periodic_distance(pos, co2[0], co2[2])], 'OCO_angle_deg': _bench40_0_co_angle(pos, co2), 'nearest_K_to_C_A': nearest_k, 'nearest_non_CO2_oxygen_to_C_A': nearest_water_o}
        unselected = {'seed_id': record['seed_id'], 'source_frame_zero_based': record['frame_zero_based'], 'source_geometry_sha256': _bench40_0_json_read(asset_dir / 'IS_seed_provenance.json')['panel_sha256'], 'metrics': seed_metrics(seed, seed_co2, seed_c, seed_au), 'comparison_selected_point': '2K-r30-center', 'selected_metrics': seed_metrics(target, seed_co2, seed_c, seed_au), 'selection_status': 'not selected for the frozen force-gradient comparison; no paired +/-h energies exist for this distinct seed', 'information_tradeoff': 'Adds a distinct independently sourced interface snapshot in the nearby 3.0 A C-Au range, but comparing one seed geometry to the chosen static center without a matched displacement triplet cannot estimate a local gradient.'}
    response = []
    for r in rows:
        stat = center_stats.get(r['center_id'])
        response.append({'point_id': r['point_id'], 'system': r['point']['system'], 'center_id': r['center_id'], 'kind': r['kind'], 'shift_A': r['shift_A'], 'electronic_free_energy_eV': r['energy'], 'local_zero_energy_eV': stat['local_zero_energy_eV'] if stat else None, 'local_zeroed_energy_eV': r['energy'] - stat['local_zero_energy_eV'] if stat else None, 'rigid_CO2_gradient_eV_per_A': r['gradient'], 'finite_difference_gradient_eV_per_A': stat['finite_difference_gradient_eV_per_A'] if stat else None, 'deviation_eV_per_A': stat['deviation_eV_per_A'] if stat else None, 'threshold_eV_per_A': stat['threshold_eV_per_A'] if stat else None, 'finite_difference_consistent': stat['consistent'] if stat else None, 'SCF_iterations': r['scf'], 'native_id': r['native_id']})
    calculations = sum((int(x.get('reserved_force_evaluations', 0)) for x in ledger))
    return {'rows': response, 'center_stats': center_stats, 'path_checks': path_checks, 'method_checks': method_checks, 'unselected_geometry': unselected, 'geometry': {'2K_r26_center_C_Au_A': cv_main, '2K_r26_alt_C_Au_A': cv_alt, '2K_r26_alt_Au_to_C_direction_error': alt_direction_error, '2K_r26_center_CO_A_A': main_bond[0], '2K_r26_center_CO_B_A': main_bond[1], '2K_r26_alt_CO_A_A': alt_bond[0], '2K_r26_alt_CO_B_A': alt_bond[1]}, 'initial_state_gradient_difference_eV_per_A': init_sensitivity, 'system_effects': sys_effects, 'historical_force_evaluations': calculations, 'source_hashes': source_hashes, 'native_ids': [r['native_id'] for r in rows], 'inputs': rows}



REQUIRED = ['selection.json', 'hypotheses.json', 'response.csv', 'path_audit.json', 'decision_log.json', 'next_calculation.json', 'native/manifest.json', 'analysis.py', 'report.md']
CENTERS = list(_bench40_0_TRIPLES)

class ScientificFailure(Exception):
    pass

def require(ok, message):
    if not ok:
        raise ScientificFailure(message)

def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))

def finite_number(value):
    return type(value) in (int, float) and math.isfinite(value)

def near(actual, expected, tol=1e-07):
    return finite_number(actual) and abs(actual - expected) <= tol

def center_values(value, label):
    if isinstance(value, list):
        require(len(value) == len(CENTERS), label + ' must contain four center values')
        value = dict(zip(CENTERS, value))
    require(isinstance(value, dict) and set(value) == set(CENTERS), label + ' must identify exactly the four centers')
    require(all(finite_number(value[c]) for c in CENTERS), label + ' values must be finite numbers')
    return value

def center_mapping(value, label):
    if isinstance(value, list):
        require(len(value) == len(CENTERS), label + ' must contain four center values')
        value = dict(zip(CENTERS, value))
    require(isinstance(value, dict) and set(value) == set(CENTERS), label + ' must identify exactly the four centers')
    return value

def deviation_equal(actual, force, fd, expected, tol=1e-07):
    return near(actual, expected, tol) or near(actual, force - fd, tol)

def numeric_tree_equal(actual, expected, tol=1e-07):
    if isinstance(expected, dict):
        return isinstance(actual, dict) and set(actual) == set(expected) and all((numeric_tree_equal(actual[k], expected[k], tol) for k in expected))
    if isinstance(expected, list):
        return isinstance(actual, list) and len(actual) == len(expected) and all((numeric_tree_equal(a, b, tol) for a, b in zip(actual, expected)))
    if isinstance(expected, bool) or expected is None or isinstance(expected, str):
        return actual == expected
    if isinstance(expected, (int, float)):
        return type(actual) in (int, float) and (not isinstance(actual, bool)) and math.isfinite(actual) and (abs(actual - expected) <= tol)
    return actual == expected

def nested(obj, pointer):
    value = obj
    if pointer.startswith('/'):
        for key in pointer.strip('/').split('/'):
            key = key.replace('~1', '/').replace('~0', '~')
            value = value[int(key)] if isinstance(value, list) else value[key]
    else:
        for key in pointer.split('.'):
            value = value[key]
    return value

def comparison_facts(value):
    require(isinstance(value, dict), 'seed comparison must be a JSON object')
    metrics = value.get('metrics')
    selected_metrics = value.get('selected_metrics')
    require(isinstance(metrics, dict) and isinstance(selected_metrics, dict), 'seed comparison must include seed and selected-center geometry metrics')
    metric_keys = ('C_Au_distance_A', 'CO_bond_lengths_A', 'OCO_angle_deg', 'nearest_K_to_C_A', 'nearest_non_CO2_oxygen_to_C_A')
    require(all((key in metrics and key in selected_metrics for key in metric_keys)), 'seed comparison is missing a required geometry metric')
    for group in (metrics, selected_metrics):
        require(isinstance(group.get('CO_bond_lengths_A'), list) and len(group['CO_bond_lengths_A']) == 2 and all((finite_number(x) for x in group['CO_bond_lengths_A'])), 'seed comparison CO bond metrics must be two finite lengths')
        for key in ('C_Au_distance_A', 'OCO_angle_deg', 'nearest_non_CO2_oxygen_to_C_A'):
            require(finite_number(group.get(key)), 'seed comparison geometry metric is missing or nonfinite: ' + key)
        require(group.get('nearest_K_to_C_A') is None or finite_number(group.get('nearest_K_to_C_A')), 'nearest_K_to_C_A must be finite or null')
    frame = value.get('source_frame_zero_based')
    require(type(frame) is int and frame >= 0, 'seed source frame must be a non-negative integer')
    seed_id = value.get('seed_id')
    selected_point = value.get('comparison_selected_point')
    panel_hash = value.get('source_geometry_sha256')
    require(isinstance(seed_id, str) and seed_id.strip(), 'seed identity is missing')
    require(isinstance(selected_point, str) and selected_point.strip(), 'selected center identity is missing')
    require(isinstance(panel_hash, str) and len(panel_hash) == 64 and all((ch in '0123456789abcdef' for ch in panel_hash)), 'seed panel source hash is invalid')
    metrics_facts = {key: metrics[key] for key in metric_keys}
    selected_facts = {key: selected_metrics[key] for key in metric_keys}
    metrics_facts['CO_bond_lengths_A'] = sorted(metrics_facts['CO_bond_lengths_A'])
    selected_facts['CO_bond_lengths_A'] = sorted(selected_facts['CO_bond_lengths_A'])
    return {'seed_id': seed_id, 'source_frame_zero_based': frame, 'source_geometry_sha256': panel_hash, 'comparison_selected_point': selected_point, 'metrics': metrics_facts, 'selected_metrics': selected_facts}

def _xml_poscar_variants(asset_dir, point_id):
    asset_dir = _bench40_0_Path(asset_dir)
    order = list(_bench40_0_POINT_IDS)
    attempt = order.index(point_id) + 1
    with _bench40_0_tarfile.open(asset_dir / 'IS_native.tar.gz', 'r:gz') as tf:
        poscar_data = tf.extractfile(f'native/attempt-{attempt:03d}/POSCAR').read()
        xml_data = tf.extractfile(f'native/attempt-{attempt:03d}/vasprun.xml').read()
    with _bench40_0_tempfile.TemporaryDirectory(prefix='case05-xml-geometry-') as td:
        pp = _bench40_0_Path(td) / 'POSCAR'
        pp.write_bytes(poscar_data)
        pos = _bench40_0_parse_poscar(pp)
    root = _bench40_0_ET.fromstring(xml_data)
    structure = root.findall('calculation')[-1].find('structure')
    basis = structure.find('./crystal/varray[@name="basis"]')
    positions = structure.find('./varray[@name="positions"]')
    cell = [[float(x) for x in row.text.split()[:3]] for row in basis.findall('v')]
    frac = [[float(x) for x in row.text.split()[:3]] for row in positions.findall('v')]
    if len(frac) != len(pos['species']): raise ValueError('XML/POSCAR atom-count mismatch')
    cart = [[sum(frac[i][k] * cell[k][j] for k in range(3)) for j in range(3)] for i in range(len(frac))]
    return pos, {'cell': cell, 'species': pos['species'], 'cart': cart}

def _geometry_summary(reference, asset_dir, xml_variant):
    def measure(pos, point):
        c, au = point['C_Au_indices_zero_based']
        a, b, d = point['CO2_indices_zero_based']
        return (_bench40_0_periodic_distance(pos, c, au), _bench40_0_periodic_distance(pos, a, b), _bench40_0_periodic_distance(pos, a, d), _bench40_0_periodic_distance(pos, c, au))
    rows = {x['point_id']: x for x in reference['inputs']}
    main_id, alt_id = '2K-r26-center', '2K-r26-alt-center'
    mainpos, mainxml = _xml_poscar_variants(asset_dir, main_id)
    altpos, altxml = _xml_poscar_variants(asset_dir, alt_id)
    m = measure(mainxml if xml_variant else mainpos, rows[main_id]['point'])
    a = measure(altxml if xml_variant else altpos, rows[alt_id]['point'])
    c, au = rows[alt_id]['point']['C_Au_indices_zero_based']
    altvec = _bench40_0_periodic_vector(altxml if xml_variant else altpos, c, au)
    cenvec = _bench40_0_periodic_vector(mainxml if xml_variant else mainpos, c, au)
    altunit = [x / _bench40_0_norm(altvec) for x in altvec]
    cenunit = [x / _bench40_0_norm(cenvec) for x in cenvec]
    err = _bench40_0_norm(_bench40_0_delta(altunit, cenunit))
    return {'2K_r26_center_C_Au_A':m[0], '2K_r26_alt_C_Au_A':a[0], '2K_r26_alt_Au_to_C_direction_error':err, '2K_r26_center_CO_A_A':m[1], '2K_r26_center_CO_B_A':m[2], '2K_r26_alt_CO_A_A':a[1], '2K_r26_alt_CO_B_A':a[2]}

def _xml_path_summary(reference, asset_dir):
    rows = {x['point_id']: x for x in reference['inputs']}
    geoms = {pid: _xml_poscar_variants(asset_dir, pid)[1] for pid in _bench40_0_POINT_IDS}
    out = {}
    for cid in CENTERS:
        group = [r['point_id'] for r in reference['inputs'] if r['point']['center_id'] == cid]
        center_id = next(pid for pid in group if rows[pid]['point']['shift_A'] == 0.0)
        base = geoms[center_id]
        checks = []
        for pid in group:
            point = rows[pid]['point']; pos = geoms[pid]
            cind, auind = point['C_Au_indices_zero_based']
            distance = _bench40_0_periodic_distance(pos, cind, auind)
            expected = point['q_center_A'] + point['shift_A']
            vector = _bench40_0_periodic_vector(pos, cind, auind)
            unit = [x / distance for x in vector]
            direction_error = _bench40_0_norm(_bench40_0_delta(unit, point['direction_Au_to_C']))
            co2 = point['CO2_indices_zero_based']
            translation_error = 0.0; env_displacement = 0.0
            for i in range(len(pos['species'])):
                d = _bench40_0_periodic_vector({'cell':pos['cell'],'cart':[pos['cart'][i],base['cart'][i]]},0,1)
                if i in co2:
                    translation_error=max(translation_error,_bench40_0_norm(_bench40_0_delta(d,[point['shift_A']*x for x in point['direction_Au_to_C']])))
                else:
                    env_displacement=max(env_displacement,max(abs(x) for x in d))
            cell_match = pos['species'] == base['species'] and all(abs(pos['cell'][i][j]-base['cell'][i][j]) <= 1e-7 for i in range(3) for j in range(3))
            err = distance - expected
            checks.append({'point_id':pid,'expected_C_Au_distance_A':expected,'observed_C_Au_distance_A':distance,'C_Au_distance_error_A':err,'Au_to_C_direction_error':direction_error,'max_CO2_translation_error_A':translation_error,'max_environment_displacement_A':env_displacement,'cell_species_match':cell_match})
        out[cid]={'points':checks,'pass':reference['path_checks'][cid]['pass']}
    return out

def _report_claim_json(block):
    block=block.strip()
    fenced=re.fullmatch(r'```(?:json)?\s*\n(.*?)\n```',block,re.S)
    return json.loads(fenced.group(1) if fenced else block)

def verify(reference, out_dir, asset_dir):
    out = Path(out_dir)
    missing = [name for name in REQUIRED if not (out / name).is_file() or (out / name).stat().st_size == 0]
    require(not missing, 'missing required artifact(s): ' + ', '.join(missing))
    expected_rows = {r['point_id']: r for r in reference['rows']}
    expected_inputs = {r['point_id']: r for r in reference['inputs']}
    selection = read_json(out / 'selection.json')
    hypotheses = read_json(out / 'hypotheses.json')
    path = read_json(out / 'path_audit.json')
    decision = read_json(out / 'decision_log.json')
    next_calc = read_json(out / 'next_calculation.json')
    native_manifest = read_json(out / 'native/manifest.json')
    for name, value in (('selection.json', selection), ('hypotheses.json', hypotheses), ('path_audit.json', path), ('decision_log.json', decision), ('next_calculation.json', next_calc), ('native/manifest.json', native_manifest)):
        require(type(value) is dict, name + ' must contain a JSON object')
    require(selection.get('interpretation_timing') == 'retrospective', 'historical selection/hypotheses must be labeled retrospective')
    require(hypotheses.get('preregistration_status') == 'RETROSPECTIVE_NOT_PRE_REGISTERED', 'cannot claim these explanations were preregistered')
    require(isinstance(decision.get('timing'), str) and 'retrospective' in decision['timing'].lower(), 'decision log misstates historical timing')
    with (out / 'response.csv').open(newline='', encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    require(len(rows) == len(expected_rows), 'response.csv must contain exactly 13 unique native points')
    require(len({r.get('point_id') for r in rows}) == len(rows), 'duplicate response point_id')
    require(set((r.get('point_id') for r in rows)) == set(expected_rows), 'response.csv point identity set mismatch')
    needed = {'point_id', 'system', 'center_id', 'kind', 'shift_A', 'electronic_free_energy_eV', 'local_zero_energy_eV', 'local_zeroed_energy_eV', 'rigid_CO2_gradient_eV_per_A', 'finite_difference_gradient_eV_per_A', 'deviation_eV_per_A', 'threshold_eV_per_A', 'finite_difference_consistent', 'SCF_iterations', 'native_id'}
    require(needed <= set(rows[0]), 'response.csv missing required scientific columns')
    for row in rows:
        ref = expected_rows[row['point_id']]
        point = expected_inputs[row['point_id']]['point']
        expected_kind = point['kind']
        submitted_kind = row['kind']
        if expected_kind == 'base' and row['point_id'] in {'water-r26-minus', 'water-r26-center', 'water-r26-plus', 'water-r30-minus', 'water-r30-center', 'water-r30-plus', '2K-r26-minus', '2K-r26-center', '2K-r26-plus', '2K-r30-minus', '2K-r30-center', '2K-r30-plus'}:
            role_by_point = {'minus': 'minus', 'center': 'center', 'plus': 'plus'}
            submitted_kind_ok = submitted_kind == 'base' or submitted_kind == role_by_point[row['point_id'].rsplit('-', 1)[-1]]
        elif expected_kind == 'orthogonal_initialization' and row['point_id'] == '2K-r26-alt-center':
            submitted_kind_ok = submitted_kind in {'orthogonal_initialization', 'alternate'}
        else:
            submitted_kind_ok = submitted_kind == expected_kind
        require(row['system'] == point['system'] and row['center_id'] == point['center_id'] and submitted_kind_ok, 'response identity/context mismatch: ' + row['point_id'])
        for field, value in (('shift_A', point['shift_A']), ('electronic_free_energy_eV', ref['electronic_free_energy_eV']), ('rigid_CO2_gradient_eV_per_A', ref['rigid_CO2_gradient_eV_per_A'])):
            try:
                actual = float(row[field])
            except Exception:
                actual = None
            require(near(actual, value), f"{row['point_id']} {field} does not match native recomputation")
        require(row['native_id'] == ref['native_id'], 'native source pointer mismatch: ' + row['point_id'])
        require(int(row['SCF_iterations']) == ref['SCF_iterations'], 'SCF count mismatch: ' + row['point_id'])
        if ref['center_id'] in reference['center_stats']:
            stat = reference['center_stats'][ref['center_id']]
            require(near(float(row['local_zero_energy_eV']), stat['local_zero_energy_eV']), 'wrong center energy zero')
            require(near(float(row['local_zeroed_energy_eV']), ref['electronic_free_energy_eV'] - stat['local_zero_energy_eV']), 'cross-center/environment energy zero or incorrect local energy')
            group_diagnostic_fields = ('finite_difference_gradient_eV_per_A', 'deviation_eV_per_A', 'threshold_eV_per_A', 'finite_difference_consistent')
            diagnostic_values = [row[field] for field in group_diagnostic_fields]
            if point['shift_A'] == 0.0:
                require(all(value != '' for value in diagnostic_values), 'center row must report all finite-difference diagnostics: ' + row['point_id'])
            else:
                require(all(value == '' for value in diagnostic_values) or all(value != '' for value in diagnostic_values), 'endpoint group diagnostics must be omitted together or reported together: ' + row['point_id'])
            if all(value != '' for value in diagnostic_values):
                require(near(float(row['finite_difference_gradient_eV_per_A']), stat['finite_difference_gradient_eV_per_A']), 'wrong finite-difference diagnostic: ' + row['point_id'] + '/finite_difference_gradient_eV_per_A')
                require(deviation_equal(float(row['deviation_eV_per_A']), stat['force_gradient_eV_per_A'], stat['finite_difference_gradient_eV_per_A'], stat['deviation_eV_per_A']), 'wrong finite-difference diagnostic: ' + row['point_id'] + '/deviation_eV_per_A')
                require(near(float(row['threshold_eV_per_A']), stat['threshold_eV_per_A']), 'wrong finite-difference diagnostic: ' + row['point_id'] + '/threshold_eV_per_A')
                require(row['finite_difference_consistent'].lower() == str(stat['consistent']).lower(), 'wrong consistency flag')
        else:
            require(row['finite_difference_gradient_eV_per_A'] == '' and row['local_zero_energy_eV'] == '', 'unpaired alternate center must not be assigned a fabricated finite difference')
    require(path.get('historical_native_points') == 13 and path.get('historical_force_evaluations') == 13, 'historical native point/force-call count mismatch')
    require(path.get('historical_budget_limit') == 24 and path.get('new_scientific_calls_during_analysis') == 0, 'budget or replay call accounting mismatch')
    require(path.get('new_calculation_authorized') is False, 'analysis must not claim authorization for another calculation')
    require(path.get('equilibrium_deltaA_eV') is None and path.get('equilibrium_CI') is None, 'static scans cannot report equilibrium free-energy estimates')
    def valid_source_hashes(hashes):
        if not isinstance(hashes, dict): return False
        required = {k: v for k, v in reference['source_hashes'].items() if k.startswith('native/') or k in {'points.json', 'native/force-budget.jsonl', 'potcar-provenance.json'}}
        if any(hashes.get(k) != v for k, v in required.items()): return False
        allowed = {'IS_seed_panel.extxyz', 'IS_seed_provenance.json'}
        return set(hashes) <= set(required) | allowed and all(hashes.get(k) == reference['source_hashes'].get(k) for k in set(hashes) - set(required))
    require(valid_source_hashes(path.get('source_hashes')), 'path audit source fingerprints mismatch')
    static_checks = center_mapping(path.get('static_path_checks'), 'static path checks')
    require(all(reference['path_checks'][c].get('pass') is True for c in CENTERS), 'reference POSCAR path geometry/environment audit failed')
    require(numeric_tree_equal(static_checks, reference['path_checks']) or numeric_tree_equal(static_checks, _xml_path_summary(reference, asset_dir)), 'rigid path geometry/environment audit mismatch')
    require(numeric_tree_equal(path.get('method_control_checks'), reference['method_checks']), 'INCAR/KPOINTS method-control audit mismatch')
    require(all((x.get('pass') is True for x in static_checks.values())), 'one or more rigid-path geometry checks failed')
    centered = center_mapping(path.get('centered_difference_checks'), 'centered difference checks')
    for c in CENTERS:
        got, want = centered[c], reference['center_stats'][c]
        require(isinstance(got, dict), 'force/energy derivative audit fields mismatch: ' + c)
        if 'center_id' in got:
            require(got['center_id'] == c, 'centered-difference center_id does not match its mapping key: ' + c)
            got = {key: value for key, value in got.items() if key != 'center_id'}
        require(set(got) == set(want), 'force/energy derivative audit fields mismatch: ' + c)
        for key, val in want.items():
            if key == 'deviation_eV_per_A':
                require(deviation_equal(got[key], got['force_gradient_eV_per_A'], got['finite_difference_gradient_eV_per_A'], val), 'force/energy derivative deviation mismatch: ' + c)
            elif isinstance(val, (int, float)) and not isinstance(val, bool):
                require(near(got[key], val), 'force/energy derivative audit mismatch: ' + c + '/' + key)
            else:
                require(got[key] == val, 'force/energy derivative audit mismatch: ' + c + '/' + key)
    attempt = path.get('attempt_validation', {})
    require(attempt.get('all_status_converged') is True and attempt.get('all_inputs_static') is True and (attempt.get('within_historical_24_call_budget') is True), 'static convergence or budget audit failed')
    require(native_manifest.get('source_job_id') == '3887390' and native_manifest.get('copied_native_outputs') is False, 'native/ must identify the historical source without misrepresenting copied evidence')
    require(valid_source_hashes(native_manifest.get('source_hashes')), 'native manifest does not fingerprint frozen inputs')
    require(native_manifest.get('reference_native_ids') == reference['native_ids'], 'native source pointer set mismatch')
    selected = selection.get('selected_centers')
    require(isinstance(selected, list) and [x.get('center_id') for x in selected] == CENTERS, 'selection must enumerate the four measured three-point centers in canonical order')
    for c in selected:
        refstats = reference['center_stats'][c['center_id']]
        require(near(c.get('C_Au_distance_A'), refstats['q_center_A']), 'selection CV does not match native setup')
        want_ids = [r['point_id'] for r in reference['rows'] if r['center_id'] == c['center_id']]
        require(c.get('point_ids') == want_ids, 'selection point mapping mismatch')
    alt = selection.get('same_CV_alternate_initial_state', {})
    require(alt.get('point_id') == '2K-r26-alt-center' and alt.get('paired_center') in {'2K-r26-center', '2K-r26'}, 'alternate structure must be compared with the actual same-CV center')
    alt_ref = expected_inputs['2K-r26-alt-center']['point']
    require(near(alt.get('nominal_C_Au_distance_A'), alt_ref['q_center_A']) and near(alt_ref['q_center_A'], reference['center_stats']['2K-r26']['q_center_A']), 'alternate structure is not at the selected same-CV center')
    alt_metrics = alt.get('input_geometry_metrics')
    require(numeric_tree_equal(alt_metrics, reference['geometry']) or numeric_tree_equal(alt_metrics, _geometry_summary(reference, asset_dir, True)), 'same-CV geometry metrics mismatch')
    require('retrospective' in selection.get('alternative_comparison', {}).get('timing', '').lower(), 'candidate comparison cannot be reported as historically predeclared')
    unselected = selection.get('unselected_geometry_comparison', {})
    try:
        expected_comparison = _bench40_0_public_seed_comparison(reference, asset_dir, unselected.get('seed_id'), unselected.get('comparison_selected_point'))
        expected_comparison_poscar = comparison_facts(expected_comparison)
        expected_xml = dict(expected_comparison)
        expected_xml['selected_metrics'] = expected_xml.pop('selected_metrics_xml')
        expected_comparison_xml = comparison_facts(expected_xml)
    except (ValueError, KeyError, TypeError, IndexError) as exc:
        raise ScientificFailure('unselected seed comparison is not grounded in a valid public seed and measured center') from exc
    unselected_facts = comparison_facts(unselected)
    require(unselected_facts['source_geometry_sha256'] in expected_comparison['source_geometry_sha256_options'], 'seed source hash is not a public panel or canonical frame hash')
    unselected_facts['source_geometry_sha256'] = expected_comparison_poscar['source_geometry_sha256']
    require(numeric_tree_equal({k:v for k,v in unselected_facts.items() if k != 'selected_metrics'}, {k:v for k,v in expected_comparison_poscar.items() if k != 'selected_metrics'}) and (numeric_tree_equal(unselected_facts['selected_metrics'], expected_comparison_poscar['selected_metrics']) or numeric_tree_equal(unselected_facts['selected_metrics'], expected_comparison_xml['selected_metrics'])), 'unselected source geometry/CV comparison differs from public seed inputs')
    require_text = lambda x: isinstance(x, str) and bool(x.strip())
    require(require_text(unselected.get('selection_status')), 'unselected seed selection status is missing')
    require(require_text(unselected.get('information_tradeoff')), 'unselected seed information tradeoff is missing')
    alternative = selection.get('alternative_comparison', {})
    alternative_facts = comparison_facts(alternative.get('measured_comparison'))
    require(alternative_facts['source_geometry_sha256'] in expected_comparison['source_geometry_sha256_options'], 'alternative comparison source hash is not a public panel or canonical frame hash')
    alternative_facts['source_geometry_sha256'] = expected_comparison_poscar['source_geometry_sha256']
    require(numeric_tree_equal({k:v for k,v in alternative_facts.items() if k != 'selected_metrics'}, {k:v for k,v in expected_comparison_poscar.items() if k != 'selected_metrics'}) and (numeric_tree_equal(alternative_facts['selected_metrics'], expected_comparison_poscar['selected_metrics']) or numeric_tree_equal(alternative_facts['selected_metrics'], expected_comparison_xml['selected_metrics'])), 'alternative selection comparison does not resolve to the declared public seed geometry')
    require(all((require_text(alternative.get(key)) for key in ('candidate', 'basis', 'rejection_reason', 'information_gain', 'opportunity_cost'))), 'alternative geometry must state rejection basis, information gain, and opportunity cost')
    explanations = hypotheses.get('explanations')
    require(isinstance(explanations, list) and {x.get('id') for x in explanations} == {'local_fixed_environment_response', 'initial_state_and_path_confounding', 'numerical_estimation_error'}, 'hypotheses must expose the three required competing explanations')
    hmap = {x['id']: x for x in explanations}
    for h in explanations:
        require(isinstance(h.get('observable_predictions'), list) and len(h['observable_predictions']) >= 1, 'hypothesis missing observable prediction')
        require(isinstance(h.get('falsifier'), str) and h['falsifier'].strip(), 'hypothesis missing falsifier')
        require(isinstance(h.get('remaining_confounders'), list) and h['remaining_confounders'], 'hypothesis missing limitations')
    observed = hmap['initial_state_and_path_confounding'].get('observed', {})
    require(near(observed.get('gradient_difference_alt_minus_center_eV_per_A'), reference['initial_state_gradient_difference_eV_per_A']), 'alternate initialization response difference is incorrect')
    require(hmap['initial_state_and_path_confounding'].get('support_code') == 'OBSERVED_PAIR_DIFFERENCE' and hmap['initial_state_and_path_confounding'].get('support'), 'same-CV pair cannot support a single-variable causal claim')
    require(hmap['local_fixed_environment_response'].get('support_code') == 'OBSERVED_LOCAL_RESPONSE', 'local-response support code missing')
    expected_error_code = 'WITHIN_DIAGNOSTIC_THRESHOLD' if all((reference['center_stats'][c]['consistent'] for c in CENTERS)) else 'THRESHOLD_EXCEEDED'
    require(hmap['numerical_estimation_error'].get('support_code') == expected_error_code, 'numerical-error support code disagrees with the frozen threshold result')
    nerr = hmap['numerical_estimation_error'].get('observed', {})
    got_devs = center_values(nerr.get('deviations_eV_per_A'), 'hypothesis deviations')
    got_thresholds = center_values(nerr.get('diagnostic_thresholds_eV_per_A'), 'hypothesis thresholds')
    got_by_center = center_values(nerr['deviations_by_center_eV_per_A'], 'hypothesis center deviations') if 'deviations_by_center_eV_per_A' in nerr else None
    got_thresholds_by_center = center_values(nerr['thresholds_by_center_eV_per_A'], 'hypothesis center thresholds') if 'thresholds_by_center_eV_per_A' in nerr else None
    for c in CENTERS:
        want = reference['center_stats'][c]
        for value in ([got_devs[c]] + ([got_by_center[c]] if got_by_center is not None else [])):
            require(deviation_equal(value, want['force_gradient_eV_per_A'], want['finite_difference_gradient_eV_per_A'], want['deviation_eV_per_A']), 'hypothesis error magnitudes mismatch: ' + c)
        require(near(got_thresholds[c], want['threshold_eV_per_A']), 'hypothesis diagnostic threshold mismatch: ' + c)
        if got_thresholds_by_center is not None:
            require(near(got_thresholds_by_center[c], want['threshold_eV_per_A']), 'hypothesis diagnostic threshold mismatch: ' + c)
    require(near(nerr.get('maximum_deviation_eV_per_A'), max(reference['center_stats'][c]['deviation_eV_per_A'] for c in CENTERS)), 'hypothesis maximum deviation mismatch')
    scope = hypotheses.get('scope_flags', {})
    required_scope = {'retrospective': True, 'equilibrium_mean_force': False, 'equilibrium_free_energy': False, 'transition_state_or_barrier': False, 'global_adsorption_stability': False, 'constant_potential_cation_effect': False, 'single_variable_causal_attribution': False, 'statistical_confidence_interval': False}
    require(scope == required_scope, 'scope flags overstate what the frozen static evidence establishes')
    require(hypotheses.get('expert_extensions', {}).get('status') == 'REVIEW_REQUIRED', 'nonstandard expert extrapolations must remain outside automated reward')
    require(decision.get('new_calls_in_this_replay') == 0 and decision.get('historical_calls') == 13 and (decision.get('historical_remaining_calls') == 11) and (decision.get('no_calculation_authorized') is True), 'decision log budget/action semantics mismatch')
    received = decision.get('evidence_received')
    require(isinstance(received, list) and len(received) >= 2, 'decision log must identify evidence already received')
    for item in received:
        pointer = item.get('pointer', '')
        require(':/' in pointer, 'received evidence must use an artifact JSON pointer')
        file, keypath = pointer.split(':', 1)
        mapping = {'native/manifest.json': native_manifest, 'path_audit.json': path, 'hypotheses.json': hypotheses, 'selection.json': selection}
        require(file in mapping and nested(mapping[file], keypath) is not None, 'received-evidence pointer does not resolve')
    options = decision.get('options')
    require(isinstance(options, list) and len(options) >= 2, 'decision log must compare at least two actionable alternatives')
    for option in options:
        require('action' in option and type(option.get('cost_force_evaluations')) is int and ('evidence_pointer' in option), 'decision alternative must identify action, cost, and evidence')
        require(0 <= option['cost_force_evaluations'] <= 11, 'decision alternative exceeds remaining historical reserve')
        branches = option.get('outcome_branches')
        require(isinstance(branches, list) and len(branches) >= 2 and all((isinstance(branch, str) and branch.strip() for branch in branches)), 'decision alternative needs at least two nonempty prospective outcome branches')
        pointers = option['evidence_pointer'].split('; ')
        require(pointers, 'decision evidence pointer missing')
        for pointer in pointers:
            require(':/' in pointer, 'decision evidence pointer must use a resolvable artifact JSON pointer')
            file, keypath = pointer.split(':', 1)
            require(file in {'path_audit.json', 'hypotheses.json', 'selection.json'}, 'decision pointer is outside required artifacts')
            require(nested({'path_audit.json': path, 'hypotheses.json': hypotheses, 'selection.json': selection}[file], keypath) is not None, 'decision evidence pointer resolves to null')
    candidates = next_calc.get('candidates')
    require(next_calc.get('recommendation') == 'NO_NEW_CALCULATION_IN_THIS_REPLAY' and next_calc.get('new_calculation_authorized') is False and (next_calc.get('new_scientific_calls') == 0), 'next-calculation file must not authorize or conduct new work')
    require(isinstance(candidates, list) and len(candidates) >= 2, 'next calculation must retain two or more concrete candidate actions')
    require(all((isinstance(x, dict) for x in candidates)), 'next candidates must be JSON objects')
    require([x.get('priority') for x in candidates] == list(range(1, len(candidates) + 1)), 'next candidates must be explicitly ranked')
    actions = [x.get('action') for x in candidates if isinstance(x, dict)]
    require(len(actions) == len(candidates) and all((isinstance(a, str) and a.strip() for a in actions)) and (len(set(actions)) == len(actions)), 'candidate action names must be nonempty and unique')
    for cand in candidates:
        require(isinstance(cand, dict) and cand.get('action') and (type(cand.get('cost_force_evaluations')) is int) and cand.get('evidence_pointer'), 'next candidate needs an action, cost, and evidence pointer')
        require(1 <= cand['cost_force_evaluations'] <= 11, 'next candidate cost must be within historical reserve')
        require(cand.get('opportunity_cost'), 'next candidate must explain its opportunity cost')
        branches = cand.get('outcome_branches')
        require(isinstance(branches, list) and len(branches) >= 2 and all((isinstance(branch, str) and branch.strip() for branch in branches)), 'next candidate needs two nonempty possible result branches')
        require(cand.get('trigger_rule'), 'next candidate must include a trigger/selection rule')
    require(next_calc.get('preferred_priority') == 1 and next_calc.get('preferred_action') == candidates[0].get('action'), 'next calculation must identify a preferred action and explain its ranking')
    plan = next_calc['sequential_plan_if_later_authorized']
    require(isinstance(next_calc.get('preferred_reason'), str) and next_calc['preferred_reason'].strip() and isinstance(plan, dict), 'preferred-action rationale or sequential plan is missing')
    require(plan.get('within_historical_reserve') is True, 'proposed sequential plan exceeds the historical reserve')
    plan_actions = plan.get('actions')
    require(isinstance(plan_actions, list) and all((isinstance(a, str) for a in plan_actions)) and (len(set(plan_actions)) == len(plan_actions)) and (set(plan_actions) <= set(actions)), 'sequential plan must reference a unique subset of known candidate actions')
    total = plan.get('estimated_total_calls')
    require(type(total) is int and 0 <= total <= 11, 'sequential plan total must be an integer within the remaining reserve')
    selected_cost = sum((x['cost_force_evaluations'] for x in candidates if x['action'] in set(plan_actions)))
    require(selected_cost == total, 'sequential next-step cost does not equal sum of planned action costs')
    raw_report = (out / 'report.md').read_text(encoding='utf-8')
    start, end = ('<!-- scientific-claims:start -->', '<!-- scientific-claims:end -->')
    require(raw_report.count(start) == 1 and raw_report.count(end) == 1, 'report must contain one canonical scientific-claims block')
    block = raw_report.split(start, 1)[1].split(end, 1)[0].strip()
    claims = _report_claim_json(block)
    required_numerics = {'force_gradients_eV_per_A': {c: reference['center_stats'][c]['force_gradient_eV_per_A'] for c in CENTERS}, 'finite_difference_gradients_eV_per_A': {c: reference['center_stats'][c]['finite_difference_gradient_eV_per_A'] for c in CENTERS}, 'deviations_eV_per_A': {c: reference['center_stats'][c]['deviation_eV_per_A'] for c in CENTERS}, 'thresholds_eV_per_A': {c: reference['center_stats'][c]['threshold_eV_per_A'] for c in CENTERS}, 'same_CV_alt_minus_center_gradient_eV_per_A': reference['initial_state_gradient_difference_eV_per_A'], 'water_vs_2K_gradient_differences_eV_per_A': reference['system_effects']}
    claim_nums = claims.get('numerical_claims', {})
    require(isinstance(claim_nums, dict), 'report numerical claims must be an object')
    require(set(claim_nums) == set(required_numerics), 'report numerical claims contain missing or unexpected keys')
    for key in ('force_gradients_eV_per_A', 'finite_difference_gradients_eV_per_A', 'deviations_eV_per_A', 'thresholds_eV_per_A'):
        vals = center_values(claim_nums.get(key), 'report ' + key)
        expected_vals = required_numerics[key]
        for c in CENTERS:
            if key == 'deviations_eV_per_A':
                require(deviation_equal(vals[c], required_numerics['force_gradients_eV_per_A'][c], required_numerics['finite_difference_gradients_eV_per_A'][c], expected_vals[c]), 'report deviation claim mismatch: ' + c)
            else:
                require(near(vals[c], expected_vals[c]), 'report numerical claim mismatch: ' + key + '/' + c)
    for key in ('same_CV_alt_minus_center_gradient_eV_per_A', 'water_vs_2K_gradient_differences_eV_per_A'):
        require(numeric_tree_equal(claim_nums.get(key), required_numerics[key]), 'report numerical claim mismatch: ' + key)
    require(claims.get('scope_flags') == scope, 'report canonical scientific claims conflict with independently recomputed evidence/scope')
    require(claims.get('interpretation_status') == {x['id']: x['support_code'] for x in explanations} and claims.get('expert_extensions') == 'REVIEW_REQUIRED', 'report interpretation statuses disagree with scored hypotheses')
    return {'status': 'PASS', 'reward': 1, 'verification_coverage': 'case05-static-response-v1', 'historical_points': 13, 'new_scientific_calls': 0}

def replay_candidate(asset_dir, out_dir, reference):
    """Run submitted analysis in a temporary isolated directory and compare every contract artifact."""
    out = Path(out_dir)
    submitted_analysis = out / 'analysis.py'
    frozen_analysis = submitted_analysis.read_bytes()
    with tempfile.TemporaryDirectory(prefix='case05-analysis-replay-') as td:
        work = Path(td)
        generated = work / 'generated'
        generated.mkdir()
        env = {'PATH': os.defpath, 'LANG': 'C.UTF-8', 'PYTHONHASHSEED': '0', 'OPENBLAS_NUM_THREADS': '1', 'OMP_NUM_THREADS': '1'}
        try:
            run = subprocess.run([sys.executable, str((out / 'analysis.py').resolve()), str(Path(asset_dir).resolve()), str(generated)], cwd=work, env=env, capture_output=True, text=True, timeout=240)
        except subprocess.TimeoutExpired:
            raise ScientificFailure('analysis.py replay exceeded 240 seconds')
        except OSError as exc:
            raise ScientificFailure('cannot execute submitted analysis.py: ' + str(exc))
        if run.returncode:
            missing = re.search("ModuleNotFoundError: No module named '([A-Za-z0-9_.]+)'", run.stderr)
            if missing:
                raise EnvironmentFailure('analysis replay dependency unavailable: ' + missing.group(1))
            raise ScientificFailure('analysis.py replay failed with exit ' + str(run.returncode))
        if submitted_analysis.read_bytes() != frozen_analysis:
            raise ScientificFailure('analysis.py source changed during isolated replay')
        generated_analysis = generated / 'analysis.py'
        if generated_analysis.exists():
            if generated_analysis.read_bytes() != frozen_analysis:
                raise ScientificFailure('analysis replay produced a different analysis.py source')
        else:
            generated_analysis.write_bytes(frozen_analysis)
        verify(reference, generated, asset_dir)
        for name in REQUIRED:
            if name == 'analysis.py':
                continue
            generated_file, submitted_file = (generated / name, out / name)
            if not generated_file.is_file() or not generated_file.stat().st_size:
                raise ScientificFailure('replayed analysis did not create ' + name)
            if name.endswith('.json'):
                if not numeric_tree_equal(read_json(generated_file), read_json(submitted_file), 1e-06):
                    raise ScientificFailure('submitted artifact differs from isolated analysis replay: ' + name)
            elif name.endswith('.csv'):
                with generated_file.open(newline='', encoding='utf-8') as f:
                    left = list(csv.DictReader(f))
                with submitted_file.open(newline='', encoding='utf-8') as f:
                    right = list(csv.DictReader(f))
                if len(left) != len(right) or (left and set(left[0]) != set(right[0])):
                    raise ScientificFailure('submitted table shape differs from replay: ' + name)
                for a, b in zip(left, right):
                    if set(a) != set(b):
                        raise ScientificFailure('submitted table fields differ from replay: ' + name)
                    for field in a:
                        try:
                            same = near(float(a[field]), float(b[field]), 1e-06)
                        except (TypeError, ValueError):
                            same = a[field] == b[field]
                        if not same:
                            raise ScientificFailure('submitted table differs from replay: ' + name + '/' + field)
            elif name == 'report.md':

                def claim_payload(p):
                    text = p.read_text(encoding='utf-8')
                    start, end = ('<!-- scientific-claims:start -->', '<!-- scientific-claims:end -->')
                    if text.count(start) != 1 or text.count(end) != 1:
                        return None
                    return _report_claim_json(text.split(start, 1)[1].split(end, 1)[0])
                if not numeric_tree_equal(claim_payload(generated_file), claim_payload(submitted_file), 1e-06):
                    raise ScientificFailure('canonical report claims differ from replay')

class EnvironmentFailure(Exception):
    pass

def verify_evaluation_assets(asset_dir, tests_dir):
    tests_dir = Path(tests_dir)
    refs_path = tests_dir / 'refs.json'
    if not refs_path.is_file():
        raise EnvironmentFailure('missing private evaluation references')
    try:
        refs = read_json(refs_path)
    except Exception as exc:
        raise EnvironmentFailure('private evaluation references are unreadable: ' + str(exc))
    asset_dir = Path(asset_dir)
    for rel, expected in refs.get('asset_hashes', {}).items():
        rel = rel.removeprefix('assets/')
        path = asset_dir / rel
        if not path.is_file() or _bench40_0_sha256(path) != str(expected).removeprefix('sha256:'):
            raise EnvironmentFailure('public evaluation asset missing or corrupt: ' + rel)
    helper_hash = refs.get('science_helper_sha256')
    if refs.get('science_helper') != 'consolidated' or not helper_hash:
        raise EnvironmentFailure('private consolidated verifier fingerprint missing')
    if _bench40_0_sha256(Path(__file__).resolve()) != str(helper_hash).removeprefix('sha256:'):
        raise EnvironmentFailure('consolidated verifier missing or corrupt')

def main():
    if len(sys.argv) < 2:
        print(json.dumps({'status': 'ENVIRONMENT_ERROR', 'error': 'usage: verify.py OUTPUT_DIR [ASSET_DIR]'}))
        return 2
    out = Path(sys.argv[1])
    replay_result = '--replay-result' in sys.argv
    if len(sys.argv) >= 3 and sys.argv[2] != '--replay-result':
        asset_dir = Path(sys.argv[2])
    else:
        asset_dir = Path(os.environ.get('ASSET_DIR', Path(os.environ.get('APP', '.')) / 'environment/assets'))
    if len(sys.argv) >= 3 and sys.argv[2] == '--replay-result':
        pass
    tests_dir = Path(os.environ.get('TESTS', Path(__file__).resolve().parent))
    try:
        verify_evaluation_assets(asset_dir, tests_dir)
    except EnvironmentFailure as exc:
        print(json.dumps({'status': 'ENVIRONMENT_ERROR', 'error': str(exc)}, ensure_ascii=False))
        return 2
    try:
        reference = _bench40_0_read_native(asset_dir)
    except Exception as exc:
        print(json.dumps({'status': 'ENVIRONMENT_ERROR', 'error': 'invalid/missing frozen evaluation assets: ' + type(exc).__name__ + ': ' + str(exc)}, ensure_ascii=False))
        return 2
    try:
        result = verify(reference, out, asset_dir)
        if not replay_result:
            replay_candidate(asset_dir, out, reference)
    except ScientificFailure as exc:
        print(json.dumps({'status': 'FAIL', 'reward': 0, 'verification_coverage': 'case05-static-response-v1', 'errors': [str(exc)]}, ensure_ascii=False))
        return 1
    except EnvironmentFailure as exc:
        print(json.dumps({'status': 'ENVIRONMENT_ERROR', 'error': str(exc)}, ensure_ascii=False))
        return 2
    except (KeyError, TypeError, ValueError, IndexError, OverflowError) as exc:
        print(json.dumps({'status': 'FAIL', 'reward': 0, 'verification_coverage': 'case05-static-response-v1', 'errors': [type(exc).__name__ + ': ' + str(exc)]}, ensure_ascii=False))
        return 1
    except Exception as exc:
        print(json.dumps({'status': 'ENVIRONMENT_ERROR', 'error': type(exc).__name__ + ': ' + str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0
if __name__ == '__main__':
    raise SystemExit(main())
