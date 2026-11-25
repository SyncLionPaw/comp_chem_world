#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability.
# L2 Execution: Check native records, run evidence and their linkage where required by this task.
# L3 Science: Hydrogen site preference and magnetic sensitivity in CoCrFeNi.
"""Strict evidence scorer for the frozen case-01 CoCrFeNi-H study."""
from __future__ import annotations

# native scientific verification
"""Read native VASP results without executing scientific software. Python stdlib only."""
import gzip as _native_gzip
import io as _native_io
import math as _native_math
import re as _native_re
import xml.etree.ElementTree as _native_ET
from pathlib import Path as _native_Path

def _native_read_poscar(path):
    lines = _native_Path(path).read_text().splitlines()
    scale = float(lines[1])
    assert scale > 0, 'Negative-volume POSCAR scale unsupported'
    cell = [[float(v) * scale for v in line.split()[:3]] for line in lines[2:5]]
    species = lines[5].split()
    counts = list(map(int, lines[6].split()))
    index = 7
    if lines[index].lower().startswith('s'):
        index += 1
    direct = lines[index].lower().startswith('d')
    index += 1
    positions = []
    for line in lines[index:index + sum(counts)]:
        coord = list(map(float, line.split()[:3]))
        positions.append([sum((coord[k] * cell[k][j] for k in range(3))) for j in range(3)] if direct else [x * scale for x in coord])
    assert len(positions) == sum(counts)
    return (cell, species, counts, positions)

def _native_parameters(path):
    result = {}
    for line in _native_Path(path).read_text().splitlines():
        line = line.split('!', 1)[0].split('#', 1)[0]
        for entry in line.split(';'):
            if '=' in entry:
                key, value = entry.split('=', 1)
                result[key.strip().upper()] = value.strip()
    return result
_native__ITERATION_LABELS = {'DAV', 'RMM', 'CG', 'DMP', 'SDA', 'CGA'}
_native__NUMBER_PATTERN = '[+-]?(?:\\d+\\.\\d*|\\.\\d+)(?:[EeDd][+-]\\d{2})?'
_native__ITERATION_RECORD = _native_re.compile('^\\s*(DAV|RMM|CG|DMP|SDA|CGA)\\s*:\\s*(\\d+)\\s+' + '(' + _native__NUMBER_PATTERN + ')\\s+(' + _native__NUMBER_PATTERN + ')\\s+(' + _native__NUMBER_PATTERN + ')' + '(?:\\s+\\d+|(?<=[EeDd][+-]\\d{2})\\d{6}(?=\\s|$))(?:\\s+|$)')

def _native_electronic_iteration_records(text):
    """Parse complete supported electronic rows; fail closed on unknown tags."""
    rows = []
    for line_number, line in enumerate(text.splitlines(), 1):
        prefix = _native_re.match('^\\s*([A-Z][A-Z0-9_]*)\\s*:', line)
        if not prefix:
            continue
        label = prefix.group(1)
        if label not in _native__ITERATION_LABELS:
            raise ValueError(f'Unsupported OSZICAR electronic label {label!r} on line {line_number}')
        match = _native__ITERATION_RECORD.match(line)
        if not match:
            raise ValueError(f'Malformed/truncated {label} electronic iteration on OSZICAR line {line_number}')
        rows.append(match)
    return rows

def _native_electronic_stop(run, expected_iterations, energy_sigma0):
    """Verify both native OSZICAR changes, not just a sub-NELM count."""
    path = _native_Path(run) / 'OSZICAR'
    if not path.is_file():
        raise ValueError('Missing OSZICAR electronic convergence evidence')
    text = path.read_text(errors='replace')
    rows = _native_electronic_iteration_records(text)
    if not rows:
        raise ValueError('No supported native electronic iteration records in OSZICAR')
    last = rows[-1]
    iteration_lines = [i for i, line in enumerate(text.splitlines()) if _native_re.match('^\\s*[A-Z][A-Z0-9_]*\\s*:', line)]
    convert = lambda value: float(value.replace('D', 'E').replace('d', 'e'))
    delta_free = convert(last.group(4))
    delta_bands = convert(last.group(5))
    ediff = float(_native_parameters(_native_Path(run) / 'INCAR').get('EDIFF', '1e-4'))
    if not all((_native_math.isfinite(v) for v in (delta_free, delta_bands, ediff))) or ediff <= 0:
        raise ValueError('Nonfinite/invalid electronic convergence values')
    if int(last.group(2)) != expected_iterations:
        raise ValueError('OSZICAR and completed XML final SCF iteration counts disagree')
    if abs(delta_free) >= ediff or abs(delta_bands) >= ediff:
        raise ValueError(f'Final SCF energy changes exceed EDIFF: dE={delta_free}, d_eps={delta_bands}, EDIFF={ediff}')
    summaries = list(_native_re.finditer('^\\s*\\d+\\s+.*?\\bF=\\s*(' + _native__NUMBER_PATTERN + ').*?\\bE0=\\s*(' + _native__NUMBER_PATTERN + ')', text, _native_re.M))
    summary_lines = [text.count('\n', 0, m.start()) for m in summaries]
    if not summaries or summary_lines[-1] <= iteration_lines[-1]:
        raise ValueError('No completed ionic/static summary after final electronic loop')
    e0 = convert(summaries[-1].group(2))
    if not _native_math.isfinite(e0) or abs(e0 - energy_sigma0) > 0.0005:
        raise ValueError('Final OSZICAR E0 and OUTCAR sigma0 energy disagree')
    return dict(final_delta_free_energy_eV=delta_free, final_delta_band_energy_eV=delta_bands, EDIFF_eV=ediff, electronic_energy_changes_valid=True)

def _native_read_native(run):
    run = _native_Path(run)
    missing = [name for name in ('OUTCAR', 'CONTCAR', 'execution-exit-code.txt') if not (run / name).is_file()]
    xml_path = run / 'vasprun.xml'
    if not xml_path.is_file():
        xml_path = run / 'vasprun.xml.gz'
    if not xml_path.is_file():
        missing.append('vasprun.xml[.gz]')
    if missing:
        raise ValueError('Missing native files: ' + ', '.join(missing))
    if (run / 'execution-exit-code.txt').read_text().strip() != '0':
        raise ValueError('Nonzero engine/launcher exit')
    if (run / 'STOPCAR').exists():
        raise ValueError('STOPCAR termination requires manual review')
    incar = _native_parameters(run / 'INCAR')
    nelm = int(incar.get('NELM', 60))
    threshold = float(incar.get('EDIFFG', -0.01))
    expected_ions = sum(_native_read_poscar(run / 'CONTCAR')[2])
    last = None
    ionic_steps = 0
    top_band_occupation = None
    discarded_depth = 0
    opener = _native_gzip.open if xml_path.suffix == '.gz' else open
    with opener(xml_path, 'rb') as raw_xml_stream:
        xml_stream = _native_BoundedReader(raw_xml_stream, 256 * 1024 * 1024)
        for event, element in _native_ET.iterparse(xml_stream, events=('start', 'end')):
            if event == 'start':
                if discarded_depth or element.tag in ('projected', 'dos'):
                    discarded_depth += 1
                continue
            if discarded_depth:
                element.clear()
                discarded_depth -= 1
                continue
            if element.tag == 'eigenvalues':
                occupations = []
                for band_set in element.findall('.//set'):
                    rows = band_set.findall('r')
                    if rows:
                        occupations.append(abs(float(rows[-1].text.split()[1])))
                if any((not _native_math.isfinite(v) for v in occupations)):
                    raise ValueError('Nonfinite highest-band occupations')
                if occupations:
                    top_band_occupation = max(occupations)
                element.clear()
            elif element.tag == 'calculation':
                steps = element.findall('scstep')
                forces = [[float(v) for v in row.text.split()] for row in element.findall("./varray[@name='forces']/v")]
                if len(forces) != expected_ions or any((not _native_math.isfinite(v) for row in forces for v in row)):
                    raise ValueError('Missing, mismatched or nonfinite native forces')
                energies = {row.attrib['name']: float(row.text) for row in element.findall('./energy/i')}
                if any((not _native_math.isfinite(v) for v in energies.values())):
                    raise ValueError('Nonfinite XML energies')
                last = dict(scf_iterations=len(steps), max_force_eV_A=max((_native_math.sqrt(sum((v * v for v in f))) for f in forces), default=float('inf')), xml_energies=energies)
                ionic_steps += 1
                element.clear()
    if last is None:
        raise ValueError('No completed XML ionic calculation')
    outcar = (run / 'OUTCAR').read_text(errors='replace')
    if 'General timing and accounting informations for this job' not in outcar:
        raise ValueError('Missing native normal-termination timing footer')
    records = _native_re.findall('energy\\(\\s*sigma\\s*->\\s*0\\s*\\)\\s*=\\s*([-+0-9.EeDd]+)', outcar)
    if not records:
        raise ValueError('No native energy(sigma->0) record')
    energy = float(records[-1].replace('D', 'E').replace('d', 'e'))
    if not _native_math.isfinite(energy):
        raise ValueError('Nonfinite energy')
    scf_valid = 0 < last['scf_iterations'] < nelm
    if not scf_valid:
        raise ValueError('Final electronic loop reached NELM or has no iterations')
    stop = _native_electronic_stop(run, last['scf_iterations'], energy)
    force_valid = last['max_force_eV_A'] <= abs(threshold if threshold < 0 else -0.01)
    bands_valid = top_band_occupation is not None and top_band_occupation < 0.001
    return dict(energy_sigma0_eV=energy, ionic_steps=ionic_steps, electronic_iteration_termination_valid=scf_valid, force_valid=force_valid, top_band_occupation=top_band_occupation, empty_band_check_valid=bands_valid, convergence_basis='completed native XML, normal OUTCAR footer, matching OSZICAR final iteration and energy, both energy changes below EDIFF, engine exit 0, force and highest-band occupancy', magnetic_ground_state_proven=False, **stop, **last)

class _native_BoundedReader(_native_io.RawIOBase):
    """Incremental decompressed-byte guard for XML iterparse inputs."""

    def __init__(self, stream, limit_bytes: int):
        self._stream = stream
        self._limit = limit_bytes
        self._read = 0

    def readable(self):
        return True

    def read(self, size=-1):
        remaining_plus_one = self._limit - self._read + 1
        request = remaining_plus_one if size is None or size < 0 else min(size, remaining_plus_one)
        data = self._stream.read(request)
        self._read += len(data)
        if self._read > self._limit:
            raise ValueError(f'XML input exceeds {self._limit} byte decompression limit')
        return data

# scientific_claims scientific verification
"""Machine-checkable scientific claim contract for Case 01."""
import json as _claims_json
import math as _claims_math
from pathlib import Path as _claims_Path
from decimal import Decimal as _claims_Decimal
from typing import Any as _claims_Any
_claims_SCHEMA = 'case01-scientific-claims/v1'
_claims_RULE_ID = 'case01-exploratory-8p2mev/v1'
_claims_EXPLORATORY_SCALE_EV = 0.0082
_claims_CONDITIONS = ('baseline', 'numerical_sensitivity', 'magnetic_sensitivity')
_claims_ELEMENTS = ('Co', 'Cr', 'Fe', 'Ni')

class _claims_ClaimError(ValueError):
    pass

class _claims_ClaimEnvironmentError(RuntimeError):
    pass

def _claims_finite_number(value: _claims_Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or (not _claims_math.isfinite(value)):
        raise _claims_ClaimError(f'{name} must be a finite JSON number')
    return float(value)

def _claims__pairs_no_duplicates(items):
    out = {}
    for key, value in items:
        if key in out:
            raise _claims_ClaimError(f'duplicate JSON key: {key}')
        out[key] = value
    return out

def _claims_read_claims(path: _claims_Path) -> dict:
    try:
        raw = path.read_text(encoding='utf-8')
        value = _claims_json.loads(raw, object_pairs_hook=_claims__pairs_no_duplicates, parse_constant=lambda token: (_ for _ in ()).throw(_claims_ClaimError(token)))
    except (OSError, UnicodeError, _claims_json.JSONDecodeError) as exc:
        raise _claims_ClaimError(f'scientific-claims.json is unreadable or malformed: {exc}') from exc
    if not isinstance(value, dict):
        raise _claims_ClaimError('scientific-claims.json root must be an object')
    return value

def _claims__sign(delta: float) -> str:
    return 'positive' if delta > 0 else 'negative' if delta < 0 else 'zero'

def _claims_validate_claims(claims: dict, *, model_sha256: str, choice: dict, pair_task_ids: dict[str, tuple[str, str]], deltas: list[dict], numerical_controls_changed: dict[str, list[str]], physical: dict[str, dict], job_map: dict[str, dict]) -> dict:
    """Validate candidate claims against values independently reconstructed by the scorer."""
    if claims.get('schema') != _claims_SCHEMA:
        raise _claims_ClaimError('unsupported scientific claims schema')
    if set(claims) != {'schema', 'scope', 'site_choice', 'method_design', 'paired_results', 'decision'}:
        raise _claims_ClaimError('scientific claims contain missing or extra top-level fields')
    scope = claims.get('scope')
    expected_scope = {'model_sha256': model_sha256, 'domain': 'fixed_32_metal_cell_selected_A_B_pair', 'claims_random_alloy_representativeness': False, 'claims_thermodynamic_occupancy': False, 'claims_magnetic_ground_state': False, 'claims_relaxed_absorption_enthalpy': False, 'claims_fracture_or_P3_P7_completion': False}
    if not isinstance(scope, dict) or set(scope) != set(expected_scope):
        raise _claims_ClaimError('scope claims must exactly identify this fixed model/pair and exclude unsupported extrapolations')
    if type(scope.get('model_sha256')) is not str or scope.get('model_sha256') != model_sha256 or type(scope.get('domain')) is not str or (scope.get('domain') != expected_scope['domain']) or any((type(scope.get(key)) is not bool or scope[key] is not False for key in expected_scope if key.startswith('claims_'))):
        raise _claims_ClaimError('scope claims must have exact string/bool types and exclude unsupported extrapolations')
    selected = {s: choice[f'site_{s}'] for s in ('A', 'B')}
    site_claim = claims.get('site_choice')
    if not isinstance(site_claim, dict) or set(site_claim) != {'purpose', 'site_ids', 'neighbor_counts', 'descriptor_delta'}:
        raise _claims_ClaimError('site_choice fields do not match the public structured rationale contract')
    if type(site_claim.get('purpose')) is not str or site_claim.get('purpose') != 'first_shell_composition_contrast':
        raise _claims_ClaimError('site selection purpose must identify the declared first-shell composition contrast')
    site_ids_claim = site_claim.get('site_ids')
    if not isinstance(site_ids_claim, dict) or set(site_ids_claim) != {'A', 'B'} or any((type(site_ids_claim[s]) is not str or site_ids_claim[s] != selected[s]['site_id'] for s in ('A', 'B'))):
        raise _claims_ClaimError('site-choice claim IDs differ from the frozen choice')
    counts = {s: {element: int(selected[s]['neighbor_counts'][element]) for element in _claims_ELEMENTS} for s in ('A', 'B')}
    claimed_counts = site_claim.get('neighbor_counts')
    if not isinstance(claimed_counts, dict) or set(claimed_counts) != {'A', 'B'} or any((not isinstance(claimed_counts[s], dict) or set(claimed_counts[s]) != set(_claims_ELEMENTS) or any((type(claimed_counts[s][e]) is not int or claimed_counts[s][e] != counts[s][e] for e in _claims_ELEMENTS)) for s in ('A', 'B'))):
        raise _claims_ClaimError('site-choice claim descriptors differ from the independently reconstructed model')
    expected_diff = {element: counts['A'][element] - counts['B'][element] for element in _claims_ELEMENTS}
    claimed_diff = site_claim.get('descriptor_delta')
    if not isinstance(claimed_diff, dict) or set(claimed_diff) != set(_claims_ELEMENTS) or any((type(claimed_diff[e]) is not int or claimed_diff[e] != expected_diff[e] for e in _claims_ELEMENTS)) or (not any(expected_diff.values())):
        raise _claims_ClaimError('site-choice descriptor contrast is missing or incorrect')
    method = claims.get('method_design')
    required_method = {'condition_task_ids', 'baseline_start', 'alternate_start', 'numerical_controls_changed', 'numerical_sensitivity_purpose', 'alternate_start_purpose', 'm1_interpretation', 'stopping_rule'}
    if not isinstance(method, dict) or set(method) != required_method:
        raise _claims_ClaimError('method_design fields do not match the public structured rationale contract')
    expected_pairs = {condition: {'A': pair_task_ids[condition][0], 'B': pair_task_ids[condition][1]} for condition in _claims_CONDITIONS}
    claimed_pairs = method.get('condition_task_ids')
    if not isinstance(claimed_pairs, dict) or set(claimed_pairs) != set(_claims_CONDITIONS) or any((not isinstance(claimed_pairs[c], dict) or set(claimed_pairs[c]) != {'A', 'B'} or any((type(claimed_pairs[c][s]) is not str or claimed_pairs[c][s] != expected_pairs[c][s] for s in ('A', 'B'))) for c in _claims_CONDITIONS)):
        raise _claims_ClaimError('method-design pair mapping differs from the six sealed native runs')
    base_start = job_map[pair_task_ids['baseline'][0]]['magnetic_start']
    alt_start = job_map[pair_task_ids['magnetic_sensitivity'][0]]['magnetic_start']
    if method.get('baseline_start') != base_start or method.get('alternate_start') != alt_start:
        raise _claims_ClaimError('method-design magnetic starts differ from native inputs')
    claimed_controls = method.get('numerical_controls_changed')
    if not isinstance(claimed_controls, dict) or set(claimed_controls) != {'A', 'B'} or any((not isinstance(claimed_controls[s], list) or any((type(x) is not str for x in claimed_controls[s])) or claimed_controls[s] != numerical_controls_changed[s] for s in ('A', 'B'))):
        raise _claims_ClaimError('claimed numerical controls differ from the independently compared inputs')
    if type(method.get('numerical_sensitivity_purpose')) is not str or method.get('numerical_sensitivity_purpose') != 'test_numerical_parameter_sensitivity':
        raise _claims_ClaimError('numerical-sensitivity purpose is missing or unsupported')
    if type(method.get('alternate_start_purpose')) is not str or method.get('alternate_start_purpose') != 'test_alternative_magnetic_initialization':
        raise _claims_ClaimError('alternate-start purpose is missing or unsupported')
    joint_fields = []
    for site in ('A', 'B'):
        base_id = pair_task_ids['baseline'][0 if site == 'A' else 1]
        alt_id = pair_task_ids['magnetic_sensitivity'][0 if site == 'A' else 1]
        base, alt = (physical[base_id], physical[alt_id])
        keys = sorted((set(base['incar']) | set(alt['incar'])) - {'MAGMOM', 'SYSTEM'})
        joint_fields.extend((k for k in keys if base['incar'].get(k) != alt['incar'].get(k)))
        if base['kpoints'] != alt['kpoints']:
            joint_fields.append('KPOINTS')
        if base.get('potcar_sha256') != alt.get('potcar_sha256'):
            joint_fields.append('POTCAR')
    expected_m1 = 'initial_magnetization_and_solver_joint_response' if joint_fields else 'initial_magnetization_response'
    if type(method.get('m1_interpretation')) is not str or method.get('m1_interpretation') != expected_m1:
        raise _claims_ClaimError('M1 interpretation fails to distinguish magnetic and solver/input changes')
    if type(method.get('stopping_rule')) is not str or method.get('stopping_rule') != 'complete_three_matched_pairs_or_authorized_deadline':
        raise _claims_ClaimError('stopping rule must preserve the declared three-pair/budget deadline')
    rows = claims.get('paired_results')
    if not isinstance(rows, list) or len(rows) != 3:
        raise _claims_ClaimError('paired_results must contain exactly the three matched conditions')
    expected_rows = {row['condition']: row for row in deltas}
    signs = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != {'condition', 'task_ids', 'delta_eV', 'direction'}:
            raise _claims_ClaimError('paired result row has an invalid field set')
        condition = row['condition']
        if type(condition) is not str or condition not in expected_rows or condition in signs:
            raise _claims_ClaimError('paired result conditions are duplicated or unknown')
        expected = expected_rows[condition]['delta_E_A_minus_B_eV']
        actual = _claims_finite_number(row['delta_eV'], f'{condition}.delta_eV')
        if abs(actual - expected) > 5.1e-09:
            raise _claims_ClaimError(f'{condition} claimed ΔE differs from native energies')
        if not isinstance(row['task_ids'], list) or len(row['task_ids']) != 2 or any((type(x) is not str for x in row['task_ids'])) or (row['task_ids'] != list(pair_task_ids[condition])):
            raise _claims_ClaimError(f'{condition} task references differ from the A/B pair')
        if type(row['direction']) is not str or row['direction'] != _claims__sign(expected):
            raise _claims_ClaimError(f'{condition} direction differs from the independently calculated sign')
        signs.append(condition)
    if set(signs) != set(_claims_CONDITIONS):
        raise _claims_ClaimError('paired_results do not cover the required conditions')
    by_condition = {row['condition']: _claims_finite_number(row['delta_E_A_minus_B_eV'], row['condition']) for row in deltas}
    same_nonzero_sign = all((v > 0 for v in by_condition.values())) or all((v < 0 for v in by_condition.values()))
    decimal_values = {k: _claims_Decimal(str(v)) for k, v in by_condition.items()}
    tight_response_decimal = abs(decimal_values['numerical_sensitivity'] - decimal_values['baseline'])
    alternate_response_decimal = decimal_values['magnetic_sensitivity'] - decimal_values['baseline']
    margin_decimal = min((abs(v) for v in decimal_values.values()))
    scale_decimal = _claims_Decimal('0.0082')
    tight_response = float(tight_response_decimal)
    alternate_response = float(alternate_response_decimal)
    margin = float(margin_decimal)
    rule_pass = same_nonzero_sign and margin_decimal > tight_response_decimal + scale_decimal
    direction = 'B_lower' if by_condition['baseline'] > 0 else 'A_lower' if by_condition['baseline'] < 0 else 'none'
    decision = claims.get('decision')
    if not isinstance(decision, dict) or set(decision) != {'claim', 'rule_id', 'rule_pass', 'same_sign', 'minimum_abs_delta_eV', 'numerical_response_eV', 'alternate_response_eV', 'exploratory_scale_eV', 'condition_directions', 'undecided_reason'}:
        raise _claims_ClaimError('decision fields do not match the public rule-report contract')
    expected_directions = {c: _claims__sign(by_condition[c]) for c in _claims_CONDITIONS}
    if decision.get('rule_id') != _claims_RULE_ID or type(decision.get('rule_pass')) is not bool or decision['rule_pass'] != rule_pass or (type(decision.get('same_sign')) is not bool) or (decision['same_sign'] != same_nonzero_sign):
        raise _claims_ClaimError('reported exploratory rule result differs from independent recomputation')
    for key, expected in (('minimum_abs_delta_eV', margin), ('numerical_response_eV', tight_response), ('alternate_response_eV', alternate_response), ('exploratory_scale_eV', _claims_EXPLORATORY_SCALE_EV)):
        if abs(_claims_finite_number(decision.get(key), key) - expected) > 1e-12:
            raise _claims_ClaimError(f'reported {key} differs from independent recomputation')
    if decision.get('condition_directions') != expected_directions:
        raise _claims_ClaimError('reported condition directions differ from independent native results')
    claim = decision.get('claim')
    if type(claim) is not str or claim not in {'UNDECIDED', 'A_lower', 'B_lower'}:
        raise _claims_ClaimError('decision claim must be UNDECIDED, A_lower, or B_lower')
    reason = decision.get('undecided_reason')
    if reason is not None and type(reason) is not str:
        raise _claims_ClaimError('undecided_reason must be a string or null')
    if not rule_pass:
        if claim != 'UNDECIDED' or reason != 'exploratory_rule_not_met':
            raise _claims_ClaimError('the exploratory preference rule did not pass; report UNDECIDED')
    elif claim == 'UNDECIDED':
        if reason not in {'magnetic_ground_state_unproven', 'conservative_scope_limit'}:
            raise _claims_ClaimError('a conservative UNDECIDED claim after rule passage needs a declared limitation')
    elif claim != direction or reason is not None:
        raise _claims_ClaimError('directional claim disagrees with the rule or ΔE_A−B sign')
    return {'claim': claim, 'rule_id': _claims_RULE_ID, 'rule_pass': rule_pass, 'same_sign': same_nonzero_sign, 'minimum_abs_delta_eV': margin, 'numerical_response_eV': tight_response, 'alternate_response_eV': alternate_response, 'exploratory_scale_eV': _claims_EXPLORATORY_SCALE_EV, 'condition_directions': expected_directions, 'm1_interpretation': expected_m1}
# executor_receipt scientific verification
"""Read-only Ed25519 verification of existing historical Oracle evidence.

This legacy reader is used only by the runner-controlled Oracle branch.
Fresh Agent execution uses the standard Slurm context below, without a
separate signing service or private signing key.
"""
import base64 as _receipt_base64
import hashlib as _receipt_hashlib
import json as _receipt_json
import re as _receipt_re
import math as _receipt_math
import stat as _receipt_stat
import zipfile as _receipt_zipfile
from datetime import datetime as _receipt_datetime, timezone as _receipt_timezone
from pathlib import Path as _receipt_Path, PurePosixPath as _receipt_PurePosixPath
from typing import Any as _receipt_Any
from cryptography.exceptions import InvalidSignature as _receipt_InvalidSignature
from cryptography.hazmat.primitives import serialization as _receipt_serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey as _receipt_Ed25519PublicKey
_receipt_SCHEMA = 'case01-executor-receipt/v1'
_receipt_KEY_ID = 'case01-executor-issuer-20261024'

class _receipt_ReceiptFailure(ValueError):
    """Candidate-provided receipt is missing, malformed, or inconsistent."""

class _receipt_ReceiptEnvironmentError(RuntimeError):
    """Trusted verifier key/dependency is unavailable or broken."""

def _receipt__json_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise _receipt_ReceiptFailure(f'duplicate JSON key: {key}')
        result[key] = value
    return result

def _receipt_canonical_payload(payload: dict) -> bytes:
    try:
        return _receipt_json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
    except (TypeError, ValueError, UnicodeError) as exc:
        raise _receipt_ReceiptFailure(f'receipt payload is not canonicalizable: {exc}') from exc

def _receipt_sha256_file(path: _receipt_Path) -> str:
    h = _receipt_hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()

def _receipt__utc(value: _receipt_Any, label: str) -> _receipt_datetime:
    if not isinstance(value, str):
        raise _receipt_ReceiptFailure(f'{label} must be an ISO-8601 timestamp')
    try:
        dt = _receipt_datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as exc:
        raise _receipt_ReceiptFailure(f'{label} is not a valid timestamp') from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise _receipt_ReceiptFailure(f'{label} must include a timezone')
    return dt.astimezone(_receipt_timezone.utc)

def _receipt__safe_file_ref(final_root: _receipt_Path, ref: _receipt_Any, label: str) -> _receipt_Path:
    if not isinstance(ref, dict) or set(ref) != {'path', 'bytes', 'sha256'}:
        raise _receipt_ReceiptFailure(f'{label} must contain path/bytes/sha256')
    rel = ref.get('path')
    if not isinstance(rel, str):
        raise _receipt_ReceiptFailure(f'{label}.path must be a relative path')
    pure = _receipt_PurePosixPath(rel)
    if pure.is_absolute() or '..' in pure.parts or '\\' in rel or (not pure.parts):
        raise _receipt_ReceiptFailure(f'{label}.path is unsafe')
    path = final_root.joinpath(*pure.parts)
    cursor = final_root
    for part in pure.parts:
        cursor = cursor / part
        try:
            st = cursor.lstat()
        except OSError as exc:
            raise _receipt_ReceiptFailure(f'{label} is missing: {rel}') from exc
        if _receipt_stat.S_ISLNK(st.st_mode):
            raise _receipt_ReceiptFailure(f'{label} contains a symlink: {rel}')
    try:
        if not path.is_file() or path.stat().st_size != ref.get('bytes'):
            raise _receipt_ReceiptFailure(f'{label} byte size differs: {rel}')
        digest = _receipt_sha256_file(path)
    except OSError as exc:
        raise _receipt_ReceiptFailure(f'{label} cannot be read: {rel}') from exc
    if not isinstance(ref.get('sha256'), str) or not _receipt_re.fullmatch('[0-9a-f]{64}', ref['sha256']):
        raise _receipt_ReceiptFailure(f'{label}.sha256 is malformed')
    if digest != ref['sha256']:
        raise _receipt_ReceiptFailure(f'{label} hash differs: {rel}')
    return path

def _receipt__check_file_bindings(final_root: _receipt_Path, values: _receipt_Any) -> dict[str, dict]:
    if not isinstance(values, list) or not values:
        raise _receipt_ReceiptFailure('file_bindings must be a non-empty list')
    seen = set()
    result = {}
    for i, ref in enumerate(values):
        path = _receipt__safe_file_ref(final_root, ref, f'file_bindings[{i}]')
        rel = ref['path']
        if rel in seen:
            raise _receipt_ReceiptFailure(f'file_bindings repeats {rel}')
        seen.add(rel)
        result[rel] = ref
    return result

def _receipt__validate_common_payload(payload: _receipt_Any, final_root: _receipt_Path, receipt_key_id: str) -> dict[str, dict]:
    common = {'schema', 'case_id', 'source_scope', 'issuer', 'issued_at_utc', 'choice', 'plan', 'file_bindings'}
    source_scope = payload.get('source_scope') if isinstance(payload, dict) else None
    required = common | ({'allocations'} if source_scope == 'fresh_candidate' else {'archival_attestation'})
    if not isinstance(payload, dict) or set(payload) != required:
        raise _receipt_ReceiptFailure('signed payload fields do not match the receipt schema')
    if payload.get('schema') != _receipt_SCHEMA or payload.get('case_id') != 'case-01':
        raise _receipt_ReceiptFailure('receipt schema or case_id is unsupported')
    if source_scope not in {'fresh_candidate', 'attested_archival_replay'}:
        raise _receipt_ReceiptFailure('receipt source_scope is unsupported')
    if not isinstance(payload.get('issuer'), str) or not payload['issuer'].strip():
        raise _receipt_ReceiptFailure('issuer identity is missing')
    _receipt__utc(payload.get('issued_at_utc'), 'issued_at_utc')
    choice = payload.get('choice')
    if not isinstance(choice, dict) or set(choice) != {'path', 'sha256', 'registered_at_utc', 'registration_source'} or choice.get('path') != 'pre-result-site-choice.json':
        raise _receipt_ReceiptFailure('choice receipt binding is malformed')
    _receipt__safe_file_ref(final_root, {'path': choice['path'], 'bytes': _receipt__size(final_root, choice['path']), 'sha256': choice['sha256']}, 'choice')
    _receipt__utc(choice.get('registered_at_utc'), 'choice.registered_at_utc')
    expected_source = 'trusted_live_issuer_event' if source_scope == 'fresh_candidate' else 'archival_source_review'
    if choice.get('registration_source') != expected_source:
        raise _receipt_ReceiptFailure('choice registration_source is unsupported')
    plan = payload.get('plan')
    if not isinstance(plan, dict) or set(plan) != {'path', 'sha256'} or plan.get('path') != 'settings.json':
        raise _receipt_ReceiptFailure('plan binding is malformed')
    _receipt__safe_file_ref(final_root, {'path': plan['path'], 'bytes': _receipt__size(final_root, plan['path']), 'sha256': plan['sha256']}, 'plan')
    if not _receipt_re.fullmatch('[0-9a-f]{64}', str(plan.get('sha256', ''))):
        raise _receipt_ReceiptFailure('plan hash is malformed')
    bindings = _receipt__check_file_bindings(final_root, payload.get('file_bindings'))
    for required_name in ('pre-result-site-choice.json', 'settings.json', 'native_outputs.zip'):
        if required_name not in bindings:
            raise _receipt_ReceiptFailure(f'file_bindings omits {required_name}')
    if bindings['pre-result-site-choice.json']['sha256'] != choice['sha256']:
        raise _receipt_ReceiptFailure('choice and file_bindings hashes differ')
    if bindings['settings.json']['sha256'] != plan['sha256']:
        raise _receipt_ReceiptFailure('plan and file_bindings hashes differ')
    return bindings

def _receipt__size(root: _receipt_Path, rel: str) -> int:
    if not isinstance(rel, str) or '/' in rel or rel in {'', '.', '..'}:
        raise _receipt_ReceiptFailure('receipt file path must name a direct final artifact')
    path = root / rel
    try:
        if path.is_symlink() or not path.is_file():
            raise _receipt_ReceiptFailure(f'required receipt artifact is missing or unsafe: {rel}')
        return path.stat().st_size
    except OSError as exc:
        raise _receipt_ReceiptFailure(f'required receipt artifact is unreadable: {rel}') from exc

def _receipt__native_job_records(native_zip: _receipt_Path) -> dict[str, dict]:
    records: dict[str, dict] = {}
    try:
        with _receipt_zipfile.ZipFile(native_zip) as archive:
            for name in archive.namelist():
                parts = _receipt_PurePosixPath(name).parts
                if len(parts) != 3 or parts[0] != 'runs' or parts[2] != 'job.json':
                    continue
                task_id = parts[1]
                value = _receipt_json.loads(archive.read(name).decode('utf-8'))
                if not isinstance(value, dict) or task_id in records or value.get('task_id') != task_id:
                    raise _receipt_ReceiptFailure('native job.json inventory is malformed or duplicated')
                records[task_id] = value
    except (OSError, _receipt_zipfile.BadZipFile, UnicodeError, _receipt_json.JSONDecodeError) as exc:
        raise _receipt_ReceiptFailure('native_outputs.zip cannot supply sealed job.json records') from exc
    return records

def _receipt__validate_fresh_allocations(values: _receipt_Any, final_root: _receipt_Path, choice_time: _receipt_datetime, issued_at: _receipt_datetime, settings: dict) -> dict[str, dict]:
    fields = {'job_id', 'allocation_id', 'array_job_id', 'task_ids', 'submitted_at_utc', 'started_at_utc', 'ended_at_utc', 'state', 'exit_code', 'nodes', 'mpi_ranks', 'memory_gib', 'requested_walltime_seconds', 'elapsed_wall_seconds', 'script', 'scheduler_record', 'stdout', 'stderr'}
    if not isinstance(values, list) or not 1 <= len(values) <= 6:
        raise _receipt_ReceiptFailure('fresh receipt needs 1-6 allocation records')
    deadlines = settings.get('deadlines')
    if not isinstance(deadlines, dict) or set(deadlines) != {'T0_utc', 'attempt_deadline_utc'}:
        raise _receipt_ReceiptFailure('fresh settings must sign the T0 and Harbor attempt deadline')
    t0 = _receipt__utc(deadlines.get('T0_utc'), 'settings.deadlines.T0_utc')
    attempt_deadline = _receipt__utc(deadlines.get('attempt_deadline_utc'), 'settings.deadlines.attempt_deadline_utc')
    if attempt_deadline <= t0 or issued_at > attempt_deadline:
        raise _receipt_ReceiptFailure('trusted receipt is outside the Harbor attempt deadline')
    tasks = {}
    allocations = set()
    for i, row in enumerate(values):
        label = f'allocations[{i}]'
        if not isinstance(row, dict) or set(row) != fields:
            raise _receipt_ReceiptFailure(f'{label} fields do not match the allocation schema')
        if any((not isinstance(row[k], str) or not row[k] for k in ('job_id', 'allocation_id', 'state', 'exit_code'))):
            raise _receipt_ReceiptFailure(f'{label} identifiers/status must be non-empty strings')
        if row['array_job_id'] is not None and (not isinstance(row['array_job_id'], str) or not row['array_job_id']):
            raise _receipt_ReceiptFailure(f'{label}.array_job_id must be a non-empty string or null')
        allocations.add(row['allocation_id'])
        submitted, started, ended = (_receipt__utc(row[k], f'{label}.{k}') for k in ('submitted_at_utc', 'started_at_utc', 'ended_at_utc'))
        if not t0 <= choice_time <= submitted <= started < ended <= attempt_deadline:
            raise _receipt_ReceiptFailure(f'{label} chronology conflicts with preregistered choice or run interval')
        if issued_at < ended:
            raise _receipt_ReceiptFailure('trusted receipt issuance predates a terminal scheduler record')
        elapsed = (ended - started).total_seconds()
        if type(row['elapsed_wall_seconds']) is not int or abs(elapsed - row['elapsed_wall_seconds']) > 2:
            raise _receipt_ReceiptFailure(f'{label} actual elapsed seconds differ from terminal timestamps')
        if row['state'] != 'COMPLETED' or row['exit_code'] not in {'0', '0:0'} or type(row['nodes']) is not int or (row['nodes'] < 1) or (type(row['mpi_ranks']) is not int) or (row['mpi_ranks'] < 1) or (isinstance(row['memory_gib'], bool) or not isinstance(row['memory_gib'], (int, float)) or not _receipt_math.isfinite(row['memory_gib']) or row['memory_gib'] <= 0) or (type(row['requested_walltime_seconds']) is not int) or (row['requested_walltime_seconds'] < 1) or (row['elapsed_wall_seconds'] > row['requested_walltime_seconds']):
            raise _receipt_ReceiptFailure(f'{label} violates the declared execution/resource contract')
        if not isinstance(row['task_ids'], list) or not row['task_ids']:
            raise _receipt_ReceiptFailure(f'{label}.task_ids must be a non-empty list')
        if not isinstance(row['task_ids'], list) or len(row['task_ids']) != 1:
            raise _receipt_ReceiptFailure('each scheduler execution record must bind exactly one task interval')
        for task_id in row['task_ids']:
            if not isinstance(task_id, str) or not task_id or task_id in tasks:
                raise _receipt_ReceiptFailure('fresh allocation task IDs are malformed or duplicated')
            tasks[task_id] = row
        file_paths = {}
        for key in ('script', 'scheduler_record', 'stdout', 'stderr'):
            file_paths[key] = _receipt__safe_file_ref(final_root, row[key], f'{label}.{key}')
        try:
            scheduler = _receipt_json.loads(file_paths['scheduler_record'].read_text(encoding='utf-8'))
        except (OSError, UnicodeError, _receipt_json.JSONDecodeError) as exc:
            raise _receipt_ReceiptFailure(f'{label}.scheduler_record is not valid JSON') from exc
        scheduler_fields = {'job_id', 'allocation_id', 'array_job_id', 'task_id', 'submitted_at_utc', 'started_at_utc', 'ended_at_utc', 'state', 'exit_code', 'nodes', 'mpi_ranks', 'memory_gib', 'requested_walltime_seconds', 'elapsed_wall_seconds'}
        expected_scheduler = {k: row['task_ids'][0] if k == 'task_id' else row[k] for k in scheduler_fields}
        if not isinstance(scheduler, dict) or set(scheduler) != scheduler_fields or scheduler != expected_scheduler:
            raise _receipt_ReceiptFailure(f'{label}.scheduler_record differs from signed scheduler fields')
        task_id = row['task_ids'][0]
        native_jobs = _receipt__native_job_records(final_root / 'native_outputs.zip')
        native_job = native_jobs.get(task_id)
        settings_job = settings.get('jobs_by_task_id', {}).get(task_id)
        if native_job is None or not isinstance(settings_job, dict) or any((settings_job.get(key) != value for key, value in native_job.items())):
            raise _receipt_ReceiptFailure(f'{label} does not match sealed native job.json and settings')
        resource = native_job.get('resource_profile')
        if not isinstance(resource, dict) or resource.get('nodes') != row['nodes'] or resource.get('ntasks') != row['mpi_ranks'] or (resource.get('mem_GiB') != row['memory_gib']) or (isinstance(resource.get('time_cap_minutes'), bool) or not isinstance(resource.get('time_cap_minutes'), (int, float)) or not _receipt_math.isfinite(resource['time_cap_minutes']) or resource['time_cap_minutes'] <= 0) or (abs(resource['time_cap_minutes'] * 60 - row['requested_walltime_seconds']) > 1e-6):
            raise _receipt_ReceiptFailure(f'{label} scheduler resources differ from native job.json')
    if len(tasks) != 6:
        raise _receipt_ReceiptFailure('fresh allocation records must cover exactly six task runs')
    if not 1 <= len(allocations) <= 6:
        raise _receipt_ReceiptFailure('fresh plan exceeds the six-allocation budget')
    return tasks

def _receipt__validate_archival_attestation(value: _receipt_Any, choice_time: _receipt_datetime) -> None:
    fields = {'archive_id', 'historical_allocation_count', 'source_manifest_sha256', 'source_tree_sha256', 'allocation_ledger_sha256', 'preflight_readback_sha256', 'task_bindings', 'choice_timestamp_status', 'missing_materials'}
    if not isinstance(value, dict) or set(value) != fields:
        raise _receipt_ReceiptFailure('archival_attestation fields are malformed')
    if value.get('archive_id') != 'case01-gold-history-20261024' or type(value.get('historical_allocation_count')) is not int or value['historical_allocation_count'] != 14:
        raise _receipt_ReceiptFailure('archival receipt must preserve the reviewed 14-allocation history')
    for key in ('source_manifest_sha256', 'source_tree_sha256', 'allocation_ledger_sha256', 'preflight_readback_sha256'):
        if not isinstance(value.get(key), str) or not _receipt_re.fullmatch('[0-9a-f]{64}', value[key]):
            raise _receipt_ReceiptFailure(f'archival attestation {key} is malformed')
    bindings = value.get('task_bindings')
    if not isinstance(bindings, dict) or len(bindings) != 6 or any((not isinstance(k, str) or not isinstance(v, str) for k, v in bindings.items())):
        raise _receipt_ReceiptFailure('archival attestation must bind the six native tasks to original ledger rows')
    if value.get('choice_timestamp_status') != 'archival_preflight_order_cross_bound_timestamp_unattested':
        raise _receipt_ReceiptFailure('archival receipt must distinguish preflight ordering from an unattested historical timestamp')
    missing = value.get('missing_materials')
    if not isinstance(missing, list) or 'original signed pre-result choice receipt was not found' not in missing:
        raise _receipt_ReceiptFailure('archival receipt must disclose the absent original signed choice receipt')
    if choice_time > _receipt_datetime.now(_receipt_timezone.utc):
        raise _receipt_ReceiptFailure('historical choice timestamp is in the future')

def _receipt_verify_receipt(receipt_path: _receipt_Path, final_root: _receipt_Path, public_key_path: _receipt_Path | bytes) -> dict:
    """Verify issuer signature and cross-check all candidate-supplied file bytes."""
    try:
        raw = receipt_path.read_text(encoding='utf-8')
        receipt = _receipt_json.loads(raw, object_pairs_hook=_receipt__json_pairs, parse_constant=lambda token: (_ for _ in ()).throw(_receipt_ReceiptFailure(token)))
    except (OSError, UnicodeError, _receipt_json.JSONDecodeError) as exc:
        raise _receipt_ReceiptFailure(f'execution-receipt.json is unreadable or malformed: {exc}') from exc
    expected = {'schema', 'key_id', 'signature_algorithm', 'payload', 'signature_base64'}
    if not isinstance(receipt, dict) or set(receipt) != expected:
        raise _receipt_ReceiptFailure('execution receipt field set is invalid')
    if receipt.get('schema') != _receipt_SCHEMA or receipt.get('key_id') != _receipt_KEY_ID or receipt.get('signature_algorithm') != 'Ed25519':
        raise _receipt_ReceiptFailure('execution receipt uses an untrusted schema/key/algorithm')
    payload = receipt.get('payload')
    bindings = _receipt__validate_common_payload(payload, final_root, receipt['key_id'])
    choice_time = _receipt__utc(payload['choice']['registered_at_utc'], 'choice.registered_at_utc')
    if payload['source_scope'] == 'fresh_candidate':
        settings_path = final_root / 'settings.json'
        try:
            settings = _receipt_json.loads(settings_path.read_text(encoding='utf-8'))
        except (OSError, UnicodeError, _receipt_json.JSONDecodeError) as exc:
            raise _receipt_ReceiptFailure('settings.json is malformed') from exc
        jobs = settings.get('jobs') if isinstance(settings, dict) else None
        if not isinstance(jobs, list) or len(jobs) != 6 or any((not isinstance(j, dict) for j in jobs)):
            raise _receipt_ReceiptFailure('settings.json must contain six job objects')
        settings['jobs_by_task_id'] = {job.get('task_id'): job for job in jobs}
        task_map = _receipt__validate_fresh_allocations(payload.get('allocations'), final_root, choice_time, _receipt__utc(payload['issued_at_utc'], 'issued_at_utc'), settings)
        for allocation in payload['allocations']:
            for key in ('script', 'scheduler_record', 'stdout', 'stderr'):
                ref = allocation[key]
                if bindings.get(ref['path']) != ref:
                    raise _receipt_ReceiptFailure(f"file_bindings omits or changes execution evidence {ref['path']}")
    else:
        archival = payload.get('archival_attestation')
        _receipt__validate_archival_attestation(archival, choice_time)
        native_tasks = set(_receipt__native_job_records(final_root / 'native_outputs.zip'))
        if set(archival['task_bindings']) != native_tasks:
            raise _receipt_ReceiptFailure('archival task ledger bindings do not cover the native task set')
        task_map = {}
    try:
        signature = _receipt_base64.b64decode(receipt['signature_base64'], validate=True)
    except (TypeError, ValueError) as exc:
        raise _receipt_ReceiptFailure('signature_base64 is malformed') from exc
    try:
        key_raw = public_key_path if isinstance(public_key_path, bytes) else public_key_path.read_bytes()
        public_key = _receipt_serialization.load_pem_public_key(key_raw)
    except (OSError, ValueError, TypeError) as exc:
        raise _receipt_ReceiptEnvironmentError(f'trusted executor public key is unreadable: {exc}') from exc
    if not isinstance(public_key, _receipt_Ed25519PublicKey):
        raise _receipt_ReceiptEnvironmentError('trusted executor public key is not Ed25519')
    try:
        public_key.verify(signature, _receipt_canonical_payload(payload))
    except _receipt_InvalidSignature as exc:
        raise _receipt_ReceiptFailure('execution receipt signature is invalid') from exc
    return {'source_scope': payload['source_scope'], 'issued_at_utc': payload['issued_at_utc'], 'issuer': payload['issuer'], 'file_bindings': bindings, 'task_map': task_map, 'choice_time_utc': choice_time.isoformat()}

parameters = _native_parameters
read_native = _native_read_native
read_poscar = _native_read_poscar
ClaimEnvironmentError = _claims_ClaimEnvironmentError
read_claims = _claims_read_claims
validate_claims = _claims_validate_claims
ReceiptEnvironmentError = _receipt_ReceiptEnvironmentError
verify_receipt = _receipt_verify_receipt


import argparse
import csv
import hashlib
import json
import math
import os
import pathlib
import re
import stat
import tempfile
import zipfile
import xml.etree.ElementTree as ET
from collections import Counter


APP_ROOT = pathlib.Path(os.environ.get("APP", "/app"))
if not (APP_ROOT / "assets").is_dir():
    APP_ROOT = pathlib.Path(__file__).resolve().parents[1] / "environment"
MODEL_PATH = APP_ROOT / "assets/task07-model.json"
INVENTORY_PATH = APP_ROOT / "assets/task07-site-inventory.csv"
RUN_FILES = {
    "CHG", "CHGCAR", "CONTCAR", "DOSCAR", "EIGENVAL", "IBZKPT", "INCAR", "KPOINTS",
    "OSZICAR", "OUTCAR", "PCDAT", "POSCAR", "PROCAR.gz", "READY.json", "REPORT",
    "WAVECAR", "XDATCAR", "deadline-guard.json", "execution-exit-code.txt", "input-sha256.txt",
    "job.json", "job-time-identity.json", "engine-exit.json", "modules.txt", "slurm-job.txt",
    "vasp.stderr", "vasp.stdout", "vasprun.xml.gz",
}
MAX_ZIP_MEMBERS = 400
MAX_ZIP_BYTES = 600 * 1024 * 1024
MAX_ZIP_INDEX_BYTES = 8 * 1024 * 1024


class ScienceFailure(ValueError):
    pass


class EvidenceEnvironmentError(RuntimeError):
    pass


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha_file(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_json(path: pathlib.Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ScienceFailure(f"expected JSON object in {path.name}")
    return value


def finite_number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ScienceFailure(f"{label} must be finite numeric data")
    return float(value)


def validate_public_geometry() -> tuple[dict, dict[str, dict]]:
    model = read_json(MODEL_PATH)
    atoms = model.get("metal_atoms")
    sites = model.get("octahedral_sites")
    if not isinstance(atoms, list) or not isinstance(sites, list):
        raise ScienceFailure("public model lacks atom/site arrays")
    counts = Counter(atom.get("element") for atom in atoms)
    expected = {"Co": 8, "Cr": 8, "Fe": 8, "Ni": 8}
    if len(atoms) != 32 or dict(counts) != expected or len(sites) != 32:
        raise ScienceFailure("public model is not the expected 32-atom equiatomic model with 32 octahedral sites")
    side = 2 * finite_number(model.get("lattice_a_A"), "lattice_a_A")
    for site in sites:
        frac = site.get("fractional")
        if not isinstance(frac, list) or len(frac) != 3:
            raise ScienceFailure("site fractional coordinate is malformed")
        distances = []
        for atom in atoms:
            dfrac = [float(x) - float(y) for x, y in zip(frac, atom["fractional"], strict=True)]
            dfrac = [x - round(x) for x in dfrac]
            distances.append((math.sqrt(sum((side * x) ** 2 for x in dfrac)), atom["element"]))
        nearest = sorted(distances)[:6]
        if len(nearest) != 6 or any(abs(d - side / 4) > 1e-6 for d, _ in nearest):
            raise ScienceFailure(f"{site.get('site_id')}: nearest shell is not six sites at a/2")
        descriptor = {element: sum(other == element for _, other in nearest) for element in expected}
        if descriptor != site.get("neighbor_counts"):
            raise ScienceFailure(f"{site.get('site_id')}: shell descriptor mismatch")
    inventory = {row["site_id"]: row for row in csv.DictReader(INVENTORY_PATH.open(encoding="utf-8"))}
    if set(inventory) != {site["site_id"] for site in sites}:
        raise ScienceFailure("public site inventory does not cover the model")
    return model, inventory


def _safe_extract_native(archive_path: pathlib.Path, destination: pathlib.Path, task_ids: set[str]) -> dict[str, pathlib.Path]:
    if archive_path.is_symlink() or not archive_path.is_file():
        raise ScienceFailure("native_outputs.zip is missing or redirected")
    try:
        zf = zipfile.ZipFile(archive_path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise ScienceFailure(f"native_outputs.zip is damaged: {exc}") from exc
    with zf:
        infos = zf.infolist()
        if not infos or len(infos) > MAX_ZIP_MEMBERS:
            raise ScienceFailure("native ZIP member count is outside the accepted bound")
        zip_names: set[str] = set()
        index_infos = []
        total = 0
        for info in infos:
            if info.filename in zip_names:
                raise ScienceFailure(f"native ZIP contains a duplicate member name: {info.filename!r}")
            zip_names.add(info.filename)
            if info.file_size < 0 or info.file_size > MAX_ZIP_BYTES:
                raise ScienceFailure(f"native ZIP member exceeds size bound: {info.filename}")
            total += info.file_size
            if total > MAX_ZIP_BYTES:
                raise ScienceFailure("native ZIP uncompressed size exceeds 600 MiB")
            if info.filename == "native_outputs_index.json":
                index_infos.append(info)
        if len(index_infos) != 1:
            raise ScienceFailure("native ZIP must contain exactly one internal member checksum index")
        index_info = index_infos[0]
        if index_info.file_size > MAX_ZIP_INDEX_BYTES:
            raise ScienceFailure("native ZIP checksum index exceeds its 8 MiB bound")
        try:
            with zf.open(index_info) as stream:
                index_bytes = stream.read(MAX_ZIP_INDEX_BYTES + 1)
            if len(index_bytes) != index_info.file_size or len(index_bytes) > MAX_ZIP_INDEX_BYTES:
                raise ScienceFailure("native ZIP checksum index length differs from its bounded header")
            internal_index = json.loads(index_bytes.decode("utf-8"))
        except (OSError, RuntimeError, UnicodeDecodeError, json.JSONDecodeError, zipfile.BadZipFile) as exc:
            raise ScienceFailure(f"native ZIP checksum index is damaged: {exc}") from exc
        if not isinstance(internal_index, dict):
            raise ScienceFailure("native ZIP checksum index root must be an object")
        index_rows = internal_index.get("members")
        if internal_index.get("schema") != "case05-native-outputs-zip-index/v1" or not isinstance(index_rows, list):
            raise ScienceFailure("native ZIP checksum index schema is invalid")
        if any(not isinstance(row, dict) or not isinstance(row.get("path"), str)
               or isinstance(row.get("size_bytes"), bool) or not isinstance(row.get("size_bytes"), int)
               or row.get("size_bytes") < 0
               or not isinstance(row.get("sha256"), str)
               or re.fullmatch(r"[0-9a-f]{64}", row["sha256"]) is None for row in index_rows):
            raise ScienceFailure("native ZIP checksum index contains a malformed member row")
        expected_index = {r["path"]: r for r in index_rows}
        if len(expected_index) != len(index_rows) or internal_index.get("member_count") != len(index_rows):
            raise ScienceFailure("native ZIP checksum index repeats entries or has wrong member count")
        allowed_history = {
            f"provenance/audit/batches/{batch}/runs/{task}/{name}"
            for batch in ("3890888", "3892058") for task in ("A-base-M1", "B-base-M1") for name in RUN_FILES
        }
        names: set[str] = set()
        for info in infos:
            name = info.filename
            if name == "native_outputs_index.json":
                continue
            pure = pathlib.PurePosixPath(name)
            mode = (info.external_attr >> 16) & 0xFFFF
            if (pure.is_absolute() or ".." in pure.parts or "\\" in name or name in names
                    or not (len(pure.parts) == 3 and pure.parts[0] == "runs" and pure.parts[1] in task_ids and pure.parts[2] in RUN_FILES)
                    and name not in allowed_history
                    or stat.S_ISLNK(mode)):
                raise ScienceFailure(f"unsafe, duplicate, or unapproved native ZIP member: {name!r}")
            names.add(name)
            row = expected_index.get(name)
            if (row is None or row.get("size_bytes") != info.file_size
                    or re.fullmatch(r"[0-9a-f]{64}", str(row.get("sha256", ""))) is None):
                raise ScienceFailure(f"native ZIP checksum index omits or misstates {name}")
            digest = hashlib.sha256()
            with zf.open(info) as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
            if digest.hexdigest() != row["sha256"]:
                raise ScienceFailure(f"native ZIP member hash differs from internal index: {name}")
        if names != set(expected_index):
            raise ScienceFailure("native ZIP checksum index member set differs from ZIP contents")
        paths: dict[str, pathlib.Path] = {}
        for task_id in task_ids:
            required = {f"runs/{task_id}/{name}" for name in (
                "CONTCAR", "INCAR", "KPOINTS", "OSZICAR", "OUTCAR", "POSCAR", "READY.json",
                "execution-exit-code.txt", "input-sha256.txt", "job.json", "vasprun.xml.gz",
            )}
            if not required.issubset(names):
                missing = sorted(required - names)
                raise ScienceFailure(f"native run {task_id} is missing required evidence: {missing}")
            paths[task_id] = destination / "runs" / task_id
        for task_id in task_ids:
            for name in (f"runs/{task_id}/{filename}" for filename in RUN_FILES):
                try:
                    info = zf.getinfo(name)
                except KeyError:
                    continue
                target = destination / name
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as source, target.open("xb") as sink:
                    for block in iter(lambda: source.read(1024 * 1024), b""):
                        sink.write(block)
    return paths


def read_input_hashes(path: pathlib.Path) -> dict[str, str]:
    found = {}
    for line in path.read_text(errors="replace").splitlines():
        parts = line.split(None, 1)
        if len(parts) != 2 or re.fullmatch(r"[0-9a-f]{64}", parts[0]) is None:
            raise ScienceFailure("input-sha256.txt contains a malformed record")
        name = pathlib.PurePosixPath(parts[1]).name
        if name in found:
            raise ScienceFailure(f"input-sha256.txt repeats {name}")
        found[name] = parts[0]
    return found


def _parse_magmoms(incar: dict, natoms: int) -> list[float]:
    raw = incar.get("MAGMOM")
    if not isinstance(raw, str) or not raw.strip():
        raise ScienceFailure("INCAR lacks an explicit MAGMOM vector")
    values: list[float] = []
    for token in re.split(r"[\s,]+", raw.strip()):
        if not token:
            continue
        repeat = re.fullmatch(r"(\d+)\s*\*\s*(.+)", token)
        count, scalar = (int(repeat.group(1)), repeat.group(2)) if repeat else (1, token)
        try:
            value = float(scalar.replace("D", "E").replace("d", "e"))
        except ValueError as exc:
            raise ScienceFailure("INCAR MAGMOM contains a malformed value") from exc
        if not math.isfinite(value) or count < 1 or len(values) + count > natoms:
            raise ScienceFailure("INCAR MAGMOM is nonfinite or has an invalid multiplicity")
        values.extend([value] * count)
    if len(values) != natoms:
        raise ScienceFailure(f"INCAR MAGMOM has {len(values)} entries, expected {natoms}")
    return values


def _final_local_moments(outcar: pathlib.Path, expected: int) -> list[list[float]]:
    text = outcar.read_text(errors="replace")
    sections = list(re.finditer(r"magnetization\s*\(x\)(.*?)(?=magnetization\s*\(x\)|\Z)", text, re.S | re.I))
    if not sections:
        raise ScienceFailure("OUTCAR has no local magnetization table")
    rows = []
    for line in sections[-1].group(1).splitlines():
        m = re.match(r"^\s*(\d+)\s+([-+0-9.EeDd]+)\s+([-+0-9.EeDd]+)\s+([-+0-9.EeDd]+)\s+([-+0-9.EeDd]+)\s*$", line)
        if m:
            rows.append([float(m.group(i).replace("D", "E").replace("d", "e")) for i in range(2, 6)])
    if len(rows) != expected or any(not math.isfinite(x) for row in rows for x in row):
        raise ScienceFailure(f"OUTCAR local moment table has {len(rows)} finite rows, expected {expected}")
    return rows


def _fractional_positions(poscar_path: pathlib.Path) -> tuple[list[list[float]], list[str], list[int], list[list[float]]]:
    cell, species, counts, positions = read_poscar(poscar_path)
    if any(abs(cell[i][j]) > 1e-7 for i in range(3) for j in range(3) if i != j):
        raise ScienceFailure("this case requires its sealed cubic diagonal cell")
    frac = [[p[j] / cell[j][j] for j in range(3)] for p in positions]
    return cell, species, counts, frac


def _check_static_geometry(run: pathlib.Path, selected: dict, choice: dict, public_model: dict) -> dict:
    cell_a, species_a, counts_a, frac_a = _fractional_positions(run / "POSCAR")
    cell_b, species_b, counts_b, frac_b = _fractional_positions(run / "CONTCAR")
    if species_a != species_b or counts_a != counts_b or len(frac_a) != 33 or len(frac_b) != 33:
        raise ScienceFailure("CONTCAR identities/counts differ from the 33-atom selected input")
    if any(abs(cell_a[i][j] - cell_b[i][j]) > 1e-8 for i in range(3) for j in range(3)):
        raise ScienceFailure("fixed geometry cell changed")
    expected_cell = public_model.get("supercell_lattice_A")
    if (not isinstance(expected_cell, list) or len(expected_cell) != 3
            or any(len(row) != 3 for row in expected_cell)
            or any(abs(cell_a[i][j] - float(expected_cell[i][j])) > 1e-7 for i in range(3) for j in range(3))):
        raise ScienceFailure("run cell differs from the public model supercell")
    displacement = max((math.sqrt(sum((((a[j] - b[j]) - round(a[j] - b[j])) * cell_a[j][j]) ** 2 for j in range(3))) for a, b in zip(frac_a, frac_b, strict=True)), default=0.0)
    if displacement > 2e-4:
        raise ScienceFailure(f"fixed geometry coordinates changed by {displacement} Angstrom")
    incar = parameters(run / "INCAR")
    if incar.get("NSW") != "0" or incar.get("IBRION") not in {"-1", "-1.0"}:
        raise ScienceFailure("native input is not a fixed-geometry static calculation")
    expected_h = choice["site_" + selected["site"]]["fractional"]
    if any(abs(frac_a[-1][i] - expected_h[i]) > 1e-8 for i in range(3)):
        raise ScienceFailure("POSCAR hydrogen position differs from frozen pre-result choice")
    metal_frac = frac_a[:32]
    # POSCAR groups atoms by element while the public model is site-ID ordered.
    # Bind the complete species-coordinate multiset with periodic tolerance.
    poscar_elements = [element for element, count in zip(species_a, counts_a, strict=True) for _ in range(count)]
    model_atoms = public_model.get("metal_atoms")
    if (not isinstance(model_atoms, list) or len(model_atoms) != 32 or len(poscar_elements) != 33
            or Counter(poscar_elements[:32]) != Counter({"Co": 8, "Cr": 8, "Fe": 8, "Ni": 8})
            or poscar_elements[32] != "H"):
        raise ScienceFailure("public metal geometry or POSCAR species list is malformed")
    unmatched = list(model_atoms)
    for element, coordinate in zip(poscar_elements[:32], metal_frac, strict=True):
        match_index = next((i for i, atom in enumerate(unmatched)
                            if atom.get("element") == element
                            and all(abs((coordinate[k] - float(atom["fractional"][k]))
                                        - round(coordinate[k] - float(atom["fractional"][k]))) <= 1e-8
                                    for k in range(3))), None)
        if match_index is None:
            raise ScienceFailure("run metal coordinates/species differ from the public model")
        unmatched.pop(match_index)
    if unmatched:
        raise ScienceFailure("run omits atoms from the public model")
    return {"cell": cell_a, "species": species_a, "counts": counts_a, "metal_fractional": metal_frac, "H_fractional": frac_a[-1], "max_displacement_A": displacement, "incar": incar}


def _validate_case01_input_policy(run: pathlib.Path, job: dict, settings: dict, geom: dict) -> tuple[dict, list[int]]:
    """Recheck the published static PBE/PAW and task-parameter envelope from native inputs."""
    incar = geom["incar"]
    def number(key: str) -> float:
        try:
            return finite_number(float(incar[key].replace("D", "E").replace("d", "e")), f"INCAR {key}")
        except (KeyError, ValueError, AttributeError) as exc:
            raise ScienceFailure(f"INCAR {key} is missing or malformed") from exc
    def integer(key: str) -> int:
        value = number(key)
        if not value.is_integer():
            raise ScienceFailure(f"INCAR {key} must be integral")
        return int(value)

    if integer("ISPIN") != 2 or incar.get("GGA", "").upper() != "PE":
        raise ScienceFailure("native inputs must be spin-polarized PBE calculations")
    enabled = {"T", "TRUE", ".TRUE.", "1", "YES"}
    forbidden_true = ("LHFCALC", "LDAU", "LSORBIT", "LNONCOLLINEAR", "LORBMOM")
    if any(incar.get(key, "").strip().upper() in enabled for key in forbidden_true):
        raise ScienceFailure("hybrid, DFT+U, spin-orbit, noncollinear, and orbital-moment models are outside this case")
    if incar.get("METAGGA", "").strip().upper() not in {"", "NONE"}:
        raise ScienceFailure("meta-GGA is outside the published PBE model")
    ranges = {"ENCUT": (350, 800), "NBANDS": (256, 512), "EDIFF": (1e-8, 1e-3),
              "SIGMA": (0.01, 0.3), "NELM": (80, 400), "AMIX": (0.01, 0.8),
              "AMIX_MAG": (0.01, 1.0), "BMIX": (1e-5, 0.1), "BMIX_MAG": (1e-5, 0.1)}
    values = {key: number(key) for key in ranges}
    integer("NBANDS")
    integer("NELM")
    for key, (lower, upper) in ranges.items():
        if not lower <= values[key] <= upper:
            raise ScienceFailure(f"INCAR {key} is outside the published range [{lower}, {upper}]")
    values["ISMEAR"] = number("ISMEAR")
    if not values["ISMEAR"].is_integer() or int(values["ISMEAR"]) not in {-5, 0, 1}:
        raise ScienceFailure("INCAR ISMEAR must be -5, 0, or 1")
    if incar.get("PREC", "").lower() not in {"normal", "accurate"}:
        raise ScienceFailure("INCAR PREC must be Normal or Accurate")
    if incar.get("ALGO", "").lower() not in {"normal", "all", "fast"}:
        raise ScienceFailure("INCAR ALGO must be Normal, All, or Fast")
    if "MAXMIX" in incar and not 4 <= integer("MAXMIX") <= 20:
        raise ScienceFailure("INCAR MAXMIX is outside the published range [4, 20]")

    try:
        lines = (run / "KPOINTS").read_text(encoding="utf-8").splitlines()
        if len(lines) < 4 or int(lines[1].strip()) != 0 or lines[2].strip().lower() not in {"gamma", "monkhorst-pack"}:
            raise ValueError("unsupported KPOINTS mode")
        mesh = [int(x) for x in lines[3].split()]
    except (OSError, UnicodeError, ValueError) as exc:
        raise ScienceFailure("KPOINTS must declare an explicit Gamma or Monkhorst-Pack mesh") from exc
    if len(mesh) != 3 or any(not 2 <= x <= 12 for x in mesh):
        raise ScienceFailure("KPOINTS mesh axes must each be within [2, 12]")
    nbands = int(values["NBANDS"])
    if nbands * mesh[0] * mesh[1] * mesh[2] > 100000:
        raise ScienceFailure("NBANDS × kmesh exceeds the published workload screen")
    if job.get("kmesh") != mesh or job.get("NBANDS") != nbands:
        raise ScienceFailure("sealed settings task kmesh/NBANDS differ from actual native inputs")
    expected_potcar = settings.get("potential_sha256")
    ready = read_json(run / "READY.json")
    if (not isinstance(expected_potcar, str) or re.fullmatch(r"[0-9a-f]{64}", expected_potcar) is None
            or ready.get("sha256", {}).get("POTCAR") != expected_potcar):
        raise ScienceFailure("native POTCAR hash differs from the plan's PBE/PAW potential binding")
    outcar = (run / "OUTCAR").read_text(encoding="utf-8", errors="replace")
    paw_elements = {match.group(1) for match in re.finditer(r"^\s*POTCAR:\s+PAW_PBE\s+([A-Z][a-z]?)", outcar, re.MULTILINE)}
    if paw_elements != {"Co", "Cr", "Fe", "Ni", "H"}:
        raise ScienceFailure("OUTCAR does not identify the expected Co/Cr/Fe/Ni/H PAW_PBE datasets")
    return values, mesh


def _assert_model_pair(public_model: dict, model_zip: pathlib.Path, choice: dict, run_meta: dict[str, dict]) -> None:
    try:
        with zipfile.ZipFile(model_zip) as z:
            required = {"models/model.json", "models/site-inventory.csv", "models/site-A-with-H.POSCAR", "models/site-B-with-H.POSCAR"}
            if set(z.namelist()) != required:
                raise ScienceFailure("models.zip member set differs from the declared four-file output")
            model_bytes = z.read("models/model.json")
            if sha_bytes(model_bytes) != choice.get("model_sha256"):
                raise ScienceFailure("models.zip model bytes do not match the frozen choice model hash")
            model = json.loads(model_bytes)
            for key in ("schema", "lattice_a_A", "supercell_lattice_A", "metal_atoms", "octahedral_sites"):
                if model.get(key) != public_model.get(key):
                    raise ScienceFailure(f"Gold model physics differs from public model at {key}")
            if z.read("models/site-inventory.csv") != (model_zip.parent / "site_inventory.csv").read_bytes():
                raise ScienceFailure("models.zip site inventory differs from final/site_inventory.csv")
            for site in ("A", "B"):
                task_id = run_meta[site]
                poscar = (run_meta[task_id]["path"] / "POSCAR").read_bytes()
                if z.read(f"models/site-{site}-with-H.POSCAR") != poscar:
                    raise ScienceFailure(f"models.zip {site} structure is not the sealed selected input")
    except (OSError, zipfile.BadZipFile, KeyError, json.JSONDecodeError) as exc:
        raise ScienceFailure(f"models.zip is missing, damaged, or malformed: {exc}") from exc


_standard_MARKER='# CCB_TASK7_INPUT_COMMIT_V1='
_standard_INPUTS=('POSCAR','INCAR','KPOINTS','POTCAR','job.json','pre-result-site-choice.json')
def _standard_canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)

def _standard_preamble(commit):
    encoded = _receipt_base64.b64encode(_standard_canonical(commit).encode()).decode()
    return _standard_MARKER + encoded + "\n/usr/bin/python3 -I - <<'CCB_TASK7_INPUT_CHECK'\nimport base64,hashlib,json\nfrom pathlib import Path\nc=json.loads(base64.b64decode(" + repr(encoded) + "))\nfor name,digest in c['inputs'].items():\n p=Path(name)\n if not (p.is_file() and not p.is_symlink() and hashlib.sha256(p.read_bytes()).hexdigest()==digest): raise SystemExit('input differs from submission commitment: '+name)\nCCB_TASK7_INPUT_CHECK\n"

def _standard_parse_commit(script, facts):
    text = script.decode('utf-8')
    header = re.match('\\A#!/bin/bash\\n(?:#SBATCH[^\\n]*\\n)*\\nset -euo pipefail\\ncd "\\$SLURM_SUBMIT_DIR"\\n', text)
    if not header:
        raise ValueError('actual script does not start with the standard Slurm body')
    body = text[header.end():]
    if not body.startswith(_standard_MARKER):
        raise ValueError('input commitment is not the first executed body block')
    encoded = body.splitlines()[0][len(_standard_MARKER):]
    commit = json.loads(_receipt_base64.b64decode(encoded, validate=True))
    fields = {'schema', 'attempt_id', 'image', 'task_sha256', 'T0_utc', 'task_id', 'choice_sha256', 'inputs'}
    if not isinstance(commit, dict) or set(commit) != fields or commit['schema'] != 'case01-ikkem-input-commit/v1':
        raise ValueError('input commitment schema differs')
    if not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', str(commit['task_id'])):
        raise ValueError('invalid task identity')
    if not isinstance(commit['inputs'], dict) or set(commit['inputs']) != set(_standard_INPUTS) or any((not re.fullmatch('[0-9a-f]{64}', str(v)) for v in commit['inputs'].values())):
        raise ValueError('input commitment must bind all six required files')
    if commit['choice_sha256'] != commit['inputs']['pre-result-site-choice.json']:
        raise ValueError('choice commitment differs')
    if any((commit[k] != facts[k] for k in ('attempt_id', 'image', 'task_sha256', 'T0_utc'))):
        raise ValueError('input commitment belongs to another attempt')
    if not body.startswith(_standard_preamble(commit)):
        raise ValueError('input commitment check is absent or modified')
    return commit

def _standard_context(final):
    trusted=pathlib.Path('/trusted/task7')
    try:
        context_path,closure_path,seal_path=(trusted/name for name in ('context.json','closure.json','seal.json'))
        for path in (trusted,context_path,closure_path,seal_path):
            info=path.lstat()
            if path.is_symlink() or (path==trusted and not pathlib.Path(path).is_dir()) or (path!=trusted and not pathlib.Path(path).is_file()):
                raise ValueError('trusted artifact path is not a regular non-link')
            if path!=trusted and info.st_nlink!=1:
                raise ValueError('trusted artifact file has an unexpected hard link')
        if {entry.name for entry in trusted.iterdir()}!={'context.json','closure.json','seal.json'}:
            raise ValueError('trusted artifact directory has an unexpected file set')
        context_raw=context_path.read_bytes();closure_raw=closure_path.read_bytes();seal=json.loads(seal_path.read_bytes())
        context=json.loads(context_raw);closure=json.loads(closure_raw)
        if seal.get('schema')!='case01-task7-seal/v1' or seal.get('success') is not True:
            raise ValueError('trusted seal is missing or unsuccessful')
        if seal.get('context_sha256')!=sha_bytes(context_raw) or seal.get('cleanup_sha256')!=sha_bytes(closure_raw):
            raise ValueError('trusted seal hashes do not match context and cleanup')
        if context.get('schema')!='case01-ikkem-runner-context/v2' or closure.get('schema')!='case01-task7-cleanup/v2':
            raise ValueError('unsupported trusted context or cleanup schema')
        if context.get('cleanup_success') is not True or closure.get('success') is not True:
            raise ValueError('trusted cleanup did not confirm success')
        if context.get('cleanup_sha256')!=sha_bytes(closure_raw):
            raise ValueError('context cleanup binding differs from the trusted cleanup artifact')
        facts=context.get('facts')
        if not isinstance(facts,dict) or facts.get('schema')!='case01-ikkem-attempt/v3':
            raise ValueError('trusted attempt facts are malformed')
        if facts.get('image_identity_kind')!='task_source_fingerprint':
            raise ValueError('trusted image identity kind is unsupported')
        source_assets=('task07_trusted.py','task07_submit.py','task07-model.json','task07-site-inventory.csv','task07-scientific-claims.schema.json')
        asset_hashes={name:sha_file(APP_ROOT/'assets'/name) for name in source_assets}
        task_sha=sha_bytes(json.dumps(asset_hashes,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode())
        adapter_sha=sha_file(APP_ROOT/'assets/task07_trusted.py')
        if facts.get('task_sha256')!=task_sha or facts.get('adapter_sha256')!=adapter_sha:
            raise ValueError('trusted Task 7 source binding differs from verifier assets')
        if not re.fullmatch(r'[0-9a-f]{64}',str(facts.get('skill_sha256',''))):
            raise ValueError('trusted image skill source hash is malformed')
        expected_image='task7-source-sha256:'+sha_bytes(json.dumps({'base_image':'compchembench-connectivity:hpc','task_sha256':task_sha,
            'adapter_sha256':adapter_sha,'skill_sha256':facts['skill_sha256']},sort_keys=True,separators=(',',':'),ensure_ascii=False).encode())
        if facts.get('image')!=expected_image:
            raise ValueError('trusted image source fingerprint differs')
        if not re.fullmatch(r'[0-9a-f]{32}',str(facts.get('attempt_id',''))):
            raise ValueError('trusted attempt identity is malformed')
        roots=facts.get('remote_roots')
        if not isinstance(roots,dict) or not roots or set(roots)!=set(facts.get('trusted_hosts',[])):
            raise ValueError('trusted attempt host scope is malformed')
        deadline=_receipt__utc(facts['attempt_deadline_utc'],'attempt deadline')
        t0=_receipt__utc(facts['T0_utc'],'T0')
        sealed=_receipt__utc(context['sealed_at_utc'],'collection')
        cleanup_sealed=_receipt__utc(closure['sealed_at_utc'],'cleanup')
        if not t0<cleanup_sealed<=sealed<=deadline or seal.get('sealed_at_utc')!=context.get('sealed_at_utc'):
            raise ValueError('trusted collection time is outside the Harbor attempt deadline')
        jobs=closure.get('jobs')
        terminal={'COMPLETED','FAILED','CANCELLED','TIMEOUT','OUT_OF_MEMORY','NODE_FAIL','PREEMPTED','BOOT_FAIL','DEADLINE','SPECIAL_EXIT','REVOKED'}
        if not isinstance(jobs,list) or any(not isinstance(job,dict) or job.get('state') not in terminal for job in jobs):
            raise ValueError('trusted cleanup does not prove terminal accounting for every owned job')
        closure_ids={str(job.get('host',''))+':'+str(job.get('job_id','')) for job in jobs}
        if len(closure_ids)!=len(jobs) or closure_ids!=set(context.get('owned_job_ids',[])):
            raise ValueError('trusted cleanup allocation set differs from the sealed attempt scope')
        expected={}
        for rel,digest in context.get('artifact_sha256',{}).items():
            if not isinstance(rel,str) or not rel.startswith('final/') or not re.fullmatch(r'[0-9a-f]{64}',str(digest)):
                raise ValueError('trusted frozen artifact map is malformed')
            expected[rel]=digest
        actual={}
        if final.is_symlink() or not final.is_dir():
            if expected: raise ValueError('frozen final directory is missing')
        else:
            for path in final.rglob('*'):
                info=path.lstat()
                if stat.S_ISLNK(info.st_mode) or not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
                    raise ValueError('collected final contains a link or special file')
                if stat.S_ISREG(info.st_mode):
                    if info.st_nlink!=1: raise ValueError('collected final contains a hard-linked file')
                    actual['final/'+path.relative_to(final).as_posix()]=sha_file(path)
        if actual!=expected:
            raise ValueError('Harbor-collected final bytes differ from the trusted frozen artifact map')
    except (OSError,ValueError,KeyError,TypeError,AttributeError) as exc:
        raise EvidenceEnvironmentError('invalid native Harbor trusted context: '+str(exc)) from exc
    if context.get('candidate_artifact_error'):
        raise ScienceFailure(str(context['candidate_artifact_error']))
    return context

def _standard_memory_gib(alloc_tres, reqmem, nodes, allocated_cpus):
    def memory_bytes(value):
        match=re.fullmatch(r'(\d+(?:\.\d+)?)([KMGTP])(?:i?B)?',value or '')
        return float(match[1])*1024**('KMGTP'.index(match[2])+1) if match else None
    allocated=dict(x.split('=',1) for x in (alloc_tres or '').split(',') if '=' in x)
    total_bytes=memory_bytes(allocated.get('mem'))
    if total_bytes is None:
        req=re.fullmatch(r'(\d+(?:\.\d+)?)([KMGTP])([nc])',reqmem or '')
        total_bytes=(float(req[1])*1024**('KMGTP'.index(req[2])+1)*(nodes if req[3]=='n' else allocated_cpus) if req else None)
    return total_bytes/1024**3 if total_bytes is not None else None

def _standard_resources_match(resource, nodes, ranks, memory_gib, wall_seconds):
    if not isinstance(resource,dict):return False
    mem=resource.get('mem_GiB') if isinstance(resource,dict) else None
    minutes=resource.get('time_cap_minutes') if isinstance(resource,dict) else None
    return (
        type(resource.get('nodes')) is int and resource['nodes']==nodes and nodes>0
        and type(resource.get('ntasks')) is int and resource['ntasks']==ranks and ranks>0
        and not isinstance(mem,bool) and isinstance(mem,(int,float)) and _native_math.isfinite(mem)
        and mem>0 and _native_math.isclose(mem,memory_gib,rel_tol=1e-9,abs_tol=1e-9)
        and not isinstance(minutes,bool) and isinstance(minutes,(int,float))
        and _native_math.isfinite(minutes) and minutes>0
        and _native_math.isclose(minutes*60,wall_seconds,rel_tol=0,abs_tol=1e-6)
    )

def _standard_receipt(final, *, required_jobs=6):
    context=_standard_context(final);facts=context['facts']
    manifest=read_json(final/'execution-receipt.json')
    if manifest.get('schema')!='case01-ikkem-slurm/v1':raise ScienceFailure('Agent submissions must use the standard Slurm receipt; historical replay is Oracle-only')
    rows=manifest.get('jobs')
    if not isinstance(rows,list) or len(rows)!=required_jobs:raise ScienceFailure('standard Slurm receipt must identify exactly six task executions')
    settings=read_json(final/'settings.json');choice_sha=sha_file(final/'pre-result-site-choice.json')
    deadlines=settings.get('deadlines',{})
    if deadlines!={k:facts[k] for k in ('T0_utc','attempt_deadline_utc')}:
        raise ScienceFailure('settings must preserve this Harbor attempt deadline')
    records=context['records']
    if not isinstance(records,list) or len(records)!=required_jobs:raise ScienceFailure('standard Slurm job inventory does not cover exactly six executions')
    try:scopes=_receipt_json.loads(_receipt_base64.b64decode(context['scope_accounting_raw_base64'],validate=True).decode())
    except (ValueError,UnicodeError) as exc:raise ScienceFailure('independent Slurm scope inventory is malformed') from exc
    if not isinstance(scopes,dict):raise ScienceFailure('independent Slurm scope inventory must be a host map')
    actual_owned=[]
    for host,encoded in scopes.items():
        root=facts.get('remote_roots',{}).get(host)
        if not root:raise ScienceFailure('scope accounting includes an untrusted Slurm host')
        raw=_receipt_base64.b64decode(encoded,validate=True).decode().splitlines()
        actual_owned.extend(host+':'+v.split('|')[0] for v in raw if len(v.split('|'))==2 and v.split('|')[1].startswith(root+'/'))
    expected_owned={r.get('host','')+':'+str(r.get('job_id','')) for r in records if isinstance(r,dict) and r.get('host') in facts.get('remote_roots',{}) and re.fullmatch(r'[0-9]+',str(r.get('job_id','')))}
    if len(expected_owned)!=required_jobs:raise ScienceFailure('standard Slurm job inventory has duplicate or untrusted host/job identities')
    if set(context.get('owned_job_ids',[]))!=set(actual_owned)|expected_owned or set(actual_owned)-expected_owned:raise ScienceFailure('independent Slurm scope enumeration found missing or extra allocations')
    bindings=_receipt__check_file_bindings(final,manifest.get('artifacts'))
    if not {'settings.json','pre-result-site-choice.json','native_outputs.zip'}<=set(bindings):raise ScienceFailure('standard receipt omits primary execution bindings')
    native_jobs=_receipt__native_job_records(final/'native_outputs.zip');settings_jobs={j['task_id']:j for j in settings.get('jobs',[])}
    seen=set();spans=[];task_map={}
    for row in rows:
        if not isinstance(row,dict) or set(row)!={'task_id','name','job_id','script','stdout','stderr'}:raise ScienceFailure('standard receipt job fields are malformed')
        task=row['task_id'];jid=str(row['job_id']);matches=[r for r in records if str(r.get('job_id',''))==jid and r.get('name')==row['name'] and isinstance(r.get('commit'),dict) and r['commit'].get('task_id')==task]
        record=matches[0] if len(matches)==1 else None
        if task in seen or record is None or record.get('invalid'):raise ScienceFailure('unbound, repeated or invalid standard Slurm execution')
        seen.add(task);task_map[task]=record
        commit=record['commit'];details=record['details'];native=native_jobs.get(task);job=settings_jobs.get(task)
        if not native or not job or any(job.get(k)!=v for k,v in native.items()):raise ScienceFailure('Slurm task mapping differs from native job.json/settings')
        if commit.get('task_id')!=task or commit.get('choice_sha256')!=choice_sha:raise ScienceFailure('Slurm submission did not precommit the selected sites for this task')
        for k in ('attempt_id','image','task_sha256','T0_utc'):
            if commit.get(k)!=facts[k]:raise ScienceFailure('Slurm input commitment belongs to another attempt')
        script=_receipt_base64.b64decode(record['script_base64'],validate=True)
        try:parsed_commit=_standard_parse_commit(script,facts)
        except (ValueError,KeyError,TypeError) as exc:raise ScienceFailure('invalid actual Slurm input commitment: '+str(exc)) from exc
        if parsed_commit!=commit:raise ScienceFailure('actual Slurm script commitment differs from runner record')
        if commit['inputs'].get('pre-result-site-choice.json')!=choice_sha or any(record['remote_native_sha256'].get(name)!=digest for name,digest in commit['inputs'].items()):
            raise ScienceFailure('Slurm committed inputs differ from the actual remote bytes')
        # Structured sacct receipts are optional (SSH-only agent path). When present
        # they must still validate; when absent, fall back to detailed accounting.
        receipt=record.get('receipt') if isinstance(record.get('receipt'), dict) else {}
        if receipt.get('receipt_schema')=='ikkem-slurm-sacct-receipt/v1':
            raw=_receipt_base64.b64decode(receipt['sacct_rows_base64'],validate=True);lines=raw.decode().splitlines()
            if sha_bytes(raw)!=receipt['sacct_rows_sha256'] or len(lines)!=1:raise ScienceFailure('standard accounting receipt raw bytes are invalid')
            cols=lines[0].split('|');fields=('Partition','ReqTRES','AllocTRES','NodeList','Elapsed','MaxRSS','State','ExitCode')
            if len(cols)!=9 or cols[0]!=jid or any((cols[i+1].strip() or None)!=receipt.get(k) for i,k in enumerate(fields)) or cols[7:]!=['COMPLETED','0:0']:
                raise ScienceFailure('standard scheduler receipt is inconsistent or unsuccessful')
        detail_raw=_receipt_base64.b64decode(record['accounting_raw_base64'],validate=True).decode().strip().splitlines()
        if len(detail_raw)!=1 or len(detail_raw[0].split('|'))!=14 or detail_raw[0].split('|')[0]!=jid:raise ScienceFailure('detailed scheduler receipt is missing')
        detail_keys=('job_id','job_name','state','exit_code','submitted','started','ended','nodes','ranks','cpus','mem','walltime','elapsed','workdir')
        if dict(zip(detail_keys,detail_raw[0].split('|')))!=details:raise ScienceFailure('detailed scheduler fields differ from their raw record')
        host=record.get('host');remote_root=facts.get('remote_roots',{}).get(host)
        if not remote_root or not details['workdir'].startswith(remote_root+'/'):raise ScienceFailure('execution workdir is outside this attempt')
        actual_tres=dict(x.split('=',1) for x in (receipt.get('AllocTRES') or '').split(',') if '=' in x)
        requested_tres=dict(x.split('=',1) for x in (receipt.get('ReqTRES') or '').split(',') if '=' in x)
        
        controls=dict(re.findall(r'([A-Za-z][A-Za-z0-9_]*)=([^ ]*)',_receipt_base64.b64decode(record['control_raw_base64']).decode()))
        if controls.get('JobId')!=jid or controls.get('JobName')!=row['name'] or controls.get('WorkDir')!=details['workdir'] or controls.get('ArrayTaskId') not in (None,'N/A','4294967294'):raise ScienceFailure('Slurm identity/workdir/array record differs')
        ranks=int(controls['NumTasks']);nodes=int(details['nodes'])
        if int(details['cpus'])<ranks:raise ScienceFailure('scheduler CPU accounting is inconsistent with the actual MPI allocation')
        mem_gib=_standard_memory_gib(receipt.get('AllocTRES'),details['mem'],nodes,int(details['cpus']))
        def seconds(value):
            day,sep,tail=value.partition('-');days=int(day) if sep else 0;parts=[int(x) for x in (tail if sep else day).split(':')];return days*86400+sum(x*60**i for i,x in enumerate(reversed(parts)))
        wall=seconds(details['walltime']);elapsed=seconds(details['elapsed']);resource=native.get('resource_profile',{})
        if mem_gib is None or wall<1 or elapsed>wall or not _standard_resources_match(resource,nodes,ranks,mem_gib,wall):raise ScienceFailure('actual scheduler allocation violates the declared task resources')
        t0=_receipt__utc(facts['T0_utc'],'T0');deadline=_receipt__utc(facts['attempt_deadline_utc'],'attempt deadline')
        submitted,started,ended=(_receipt__utc(details[k]+'Z' if not details[k].endswith('Z') else details[k],k) for k in ('submitted','started','ended'))
        sealed=_receipt__utc(context['sealed_at_utc'],'collection')
        if not t0<=submitted<=started<ended<=sealed<=deadline or abs((ended-started).total_seconds()-elapsed)>2:raise ScienceFailure('standard execution chronology exceeds the Harbor attempt deadline')
        for label in ('script','stdout','stderr'):
            rel=row[label]
            if rel not in bindings:raise ScienceFailure('standard receipt omits execution evidence '+label)
        if (final/row['script']).read_bytes()!=script:raise ScienceFailure('submitted batch script differs from the actual Slurm script')
        log_hashes=record.get('remote_log_sha256')
        if not isinstance(log_hashes,dict) or any(re.fullmatch(r'[0-9a-f]{64}',str(log_hashes.get(label,''))) is None for label in ('stdout','stderr')):
            raise EvidenceEnvironmentError('runner did not independently bind the actual Slurm stdout/stderr')
        for label in ('stdout','stderr'):
            if sha_file(final/row[label])!=log_hashes[label]:
                raise ScienceFailure('submitted '+label+' differs from the actual Slurm log')
        banner=re.search(rb'running\s+(\d+)\s+mpi-ranks,\s+on\s+(\d+)\s+nodes',(final/row['stdout']).read_bytes(),re.I)
        if not banner or tuple(map(int,banner.groups()))!=(ranks,nodes):raise ScienceFailure('native VASP banner does not confirm the Slurm MPI allocation')
        with zipfile.ZipFile(final/'native_outputs.zip') as archive:
            required={'POSCAR','INCAR','KPOINTS','job.json','READY.json','OUTCAR','OSZICAR','CONTCAR','vasprun.xml.gz','execution-exit-code.txt','input-sha256.txt'}
            if not required<=set(record['remote_native_sha256']):raise ScienceFailure('standard collect is missing required actual native files')
            for name in required:
                if sha_bytes(archive.read('runs/'+task+'/'+name))!=record['remote_native_sha256'][name]:raise ScienceFailure('submitted native output differs from the actual remote file: '+name)
    if seen!=set(native_jobs) or seen!=set(settings_jobs):raise ScienceFailure('standard execution mapping does not cover the scientific task set')
    return {'source_scope':'ikkem_slurm_fresh','file_bindings':bindings,'task_map':task_map,'choice_time_utc':min(r['details']['submitted'] for r in records)}

def _execution_receipt(final):
    if os.environ.get('CCB_ANSWER_MODE')=='oracle':
        try:key=json.loads(pathlib.Path(__file__).with_name('refs.json').read_text())['issuer_public_key_pem'].encode()
        except Exception as exc:raise EvidenceEnvironmentError('historical reference verification key is missing') from exc
        if sha_bytes(key)!='6737e666566c80c29e44a138497ee7b17f1cc0802ec40cd88bcc5ef68bca1806':raise EvidenceEnvironmentError('historical verification key differs')
        receipt=verify_receipt(final/'execution-receipt.json',final,key)
        if receipt['source_scope']!='attested_archival_replay':raise ScienceFailure('Oracle replay must identify its historical scope')
        return receipt
    return _standard_receipt(final)


def verify(app: pathlib.Path) -> dict:
    app = app.resolve()
    final = app / 'final'
    if os.environ.get('CCB_ANSWER_MODE') != 'oracle':
        _standard_context(final)
    if not (final/'execution-receipt.json').is_file():
        raise ScienceFailure('execution-receipt.json is required for Task7')
    receipt = _execution_receipt(final)
    required_files = {'models.zip', 'site_inventory.csv', 'convergence.csv', 'settings.json', 'native_outputs.zip', 'pre-result-site-choice.json', 'evidence-index.json', 'execution-evidence'}
    required_files |= {'scientific-claims.json', 'execution-receipt.json'}
    if not MODEL_PATH.is_file() or not INVENTORY_PATH.is_file():
        raise EvidenceEnvironmentError('public model or site inventory mount is missing')
    if sha_file(MODEL_PATH) != 'fe67b1f381f1a6ee40c06778f2eaa89327a4ea43b4ac0311bdc462ecd80ed6d4' or sha_file(INVENTORY_PATH) != 'b0c29d123d6678688100741e0a67ac5b371669bae5efe22b79c8a22bb67f0d06':
        raise EvidenceEnvironmentError('public model or site inventory differs from its fixed package binding')
    actual_files = {p.name for p in final.iterdir() if (p.is_file() or p.is_dir()) and (not p.is_symlink())} if final.is_dir() else set()
    if actual_files != required_files:
        raise ScienceFailure(f'final artifact set mismatch: missing={sorted(required_files - actual_files)}, extra={sorted(actual_files - required_files)}')
    if not (final / 'execution-evidence').is_dir() or any((path.is_symlink() or not (path.is_file() or path.is_dir()) for path in (final / 'execution-evidence').rglob('*'))):
        raise ScienceFailure('execution-evidence must be a regular directory tree without links or special files')
    (model, inventory) = validate_public_geometry()
    settings = read_json(final / 'settings.json')
    choice = read_json(final / 'pre-result-site-choice.json')
    index = read_json(final / 'evidence-index.json')
    if choice.get('schema') != 'pre-result-site-choice/v2':
        raise ScienceFailure('pre-result choice schema is not supported')
    trusted_model_sha = settings.get('model_sha256')
    if choice.get('model_sha256') != trusted_model_sha:
        raise ScienceFailure('pre-result choice does not bind the model hash recorded in settings')
    if not isinstance(choice.get('recorded_at_utc'), str):
        raise ScienceFailure('pre-result choice must include a timestamp')
    site_rows = {}
    for site in ('A', 'B'):
        row = choice.get(f'site_{site}')
        if not isinstance(row, dict) or row.get('site_id') not in inventory:
            raise ScienceFailure(f'site {site} is absent from public model/inventory')
        model_site = next((s for s in model['octahedral_sites'] if s['site_id'] == row['site_id']), None)
        if not model_site or model_site.get('fractional') != row.get('fractional') or model_site.get('neighbor_counts') != row.get('neighbor_counts'):
            raise ScienceFailure(f'site {site} coordinates/descriptor differ from public model')
        site_rows[site] = row
    if site_rows['A']['neighbor_counts'] == site_rows['B']['neighbor_counts']:
        raise ScienceFailure('A/B first-shell environments are identical')
    jobs = settings.get('jobs')
    if not isinstance(jobs, list) or len(jobs) != 6 or any((not isinstance(j, dict) for j in jobs)):
        raise ScienceFailure('settings must contain exactly six job objects')
    job_map = {j.get('task_id'): j for j in jobs}
    if len(job_map) != 6 or any((not isinstance(k, str) or re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', k) is None for k in job_map)):
        raise ScienceFailure('settings task IDs are missing, repeated, or unsafe')
    by_condition: dict[str, list[dict]] = {}
    for job in jobs:
        task_id = job['task_id']
        site = job.get('site')
        condition = job.get('condition')
        if site not in {'A', 'B'} or job.get('magnetic_start') not in {'M0', 'M1'}:
            raise ScienceFailure(f'{task_id}: site or magnetic-start assignment is invalid')
        if condition not in {'baseline', 'numerical_sensitivity', 'magnetic_sensitivity'}:
            raise ScienceFailure(f'{task_id}: unknown matched condition {condition!r}')
        by_condition.setdefault(condition, []).append(job)
        if job.get('composition') != 'CoCrFeNi32H' or job.get('n_atoms') != 33:
            raise ScienceFailure(f'{task_id}: wrong composition or atom count')
        if job.get('model_sha256') != choice['model_sha256'] or job.get('site_choice_sha256') != sha_file(final / 'pre-result-site-choice.json'):
            raise ScienceFailure(f'{task_id}: job does not bind the frozen model and site choice')
        if job.get('scientific_result_status') not in {None, 'NOT_RUN', 'VALID', 'PAIR_GATE_PASSED', 'PASSED'}:
            raise ScienceFailure(f'{task_id}: settings contain an invalid scientific status')
        resource = job.get('resource_profile', {})
        if not isinstance(resource, dict) or type(resource.get('nodes')) is not int or resource['nodes'] < 1 or (type(resource.get('ntasks')) is not int) or resource['ntasks'] < 1 or (isinstance(resource.get('mem_GiB'), bool) or not isinstance(resource.get('mem_GiB'), (int, float)) or not _native_math.isfinite(resource['mem_GiB']) or resource['mem_GiB'] <= 0) or (isinstance(resource.get('time_cap_minutes'), bool) or not isinstance(resource.get('time_cap_minutes'), (int, float)) or not _native_math.isfinite(resource['time_cap_minutes']) or resource['time_cap_minutes'] <= 0):
            raise ScienceFailure(f'{task_id}: per-job resource metadata must report positive actual requests')
    if set(by_condition) != {'baseline', 'numerical_sensitivity', 'magnetic_sensitivity'}:
        raise ScienceFailure('settings must provide baseline, numerical-sensitivity, and magnetic-start pairs')
    for (condition, pair) in by_condition.items():
        if len(pair) != 2 or {j['site'] for j in pair} != {'A', 'B'}:
            raise ScienceFailure(f'{condition}: expected exactly one A/B pair')
    if {j['magnetic_start'] for j in by_condition['baseline']} != {j['magnetic_start'] for j in by_condition['numerical_sensitivity']} or len({j['magnetic_start'] for j in by_condition['baseline']}) != 1 or len({j['magnetic_start'] for j in by_condition['numerical_sensitivity']}) != 1:
        raise ScienceFailure('baseline and numerical-sensitivity pairs must share one magnetic-start rule')
    baseline_start = by_condition['baseline'][0]['magnetic_start']
    magnetic_pair = by_condition['magnetic_sensitivity']
    if len({j['magnetic_start'] for j in magnetic_pair}) != 1 or magnetic_pair[0]['magnetic_start'] == baseline_start:
        raise ScienceFailure('magnetic-sensitivity pair must use one alternate magnetic-start rule')
    for job in jobs:
        if job['magnetic_start'] != job_map[job['task_id']]['magnetic_start']:
            raise ScienceFailure('inconsistent magnetic-start record')
    native_zip = final / 'native_outputs.zip'
    with tempfile.TemporaryDirectory(prefix='case01-native-') as td:
        run_paths = _safe_extract_native(native_zip, pathlib.Path(td), set(job_map))
        pass
        result_rows: dict[str, dict] = {}
        physical: dict[str, dict] = {}
        for (task_id, job) in job_map.items():
            run = run_paths[task_id]
            ready = read_json(run / 'READY.json')
            sealed_job = read_json(run / 'job.json')
            if ready.get('task_id') != task_id or not ready.get('input_ready'):
                raise ScienceFailure(f'{task_id}: READY identity/input_ready invalid')
            for field in ('site', 'condition', 'magnetic_start', 'settings_fingerprint', 'method_revision_id', 'model_sha256', 'site_choice_sha256'):
                if sealed_job.get(field) != job.get(field):
                    raise ScienceFailure(f'{task_id}: sealed job field {field} differs from settings')
                if field in ready and ready.get(field) != job.get(field):
                    raise ScienceFailure(f'{task_id}: READY field {field} differs from settings')
            ready_sha = ready.get('sha256')
            hashes = read_input_hashes(run / 'input-sha256.txt')
            if not isinstance(ready_sha, dict) or set(ready_sha) != {'POSCAR', 'INCAR', 'KPOINTS', 'POTCAR', 'job.json'}:
                raise ScienceFailure(f'{task_id}: READY hash set is malformed')
            if hashes.get('POTCAR') != ready_sha.get('POTCAR') or hashes.get('job.json') != ready_sha.get('job.json'):
                raise ScienceFailure(f'{task_id}: protected input hashes do not match READY')
            binary_names = [k for k in hashes if k not in ready_sha]
            expected_binary = settings.get('binary_expected_sha256')
            if len(binary_names) != 1 or 'vasp' not in binary_names[0].lower() or (expected_binary and hashes[binary_names[0]] != expected_binary):
                raise ScienceFailure(f'{task_id}: VASP executable hash differs from recorded binary')
            if set(hashes) != set(ready_sha) | set(binary_names) or any((hashes.get(k) != v for (k, v) in ready_sha.items())):
                raise ScienceFailure(f'{task_id}: input hash inventory differs from READY')
            for name in ('POSCAR', 'INCAR', 'KPOINTS', 'job.json'):
                actual = sha_file(run / name)
                if ready_sha.get(name) != actual or job.get('input_sha256', {}).get(name) != actual:
                    raise ScienceFailure(f'{task_id}: {name} bytes differ from READY/final settings')
            native = read_native(run)
            if not native['electronic_iteration_termination_valid'] or not native['electronic_energy_changes_valid'] or (not native['empty_band_check_valid']):
                raise ScienceFailure(f'{task_id}: strict native SCF/empty-band gate failed')
            xml_e0 = native.get('xml_energies', {}).get('e_0_energy')
            if not isinstance(xml_e0, (int, float)) or not math.isfinite(xml_e0) or abs(xml_e0 - native['energy_sigma0_eV']) > 1e-07:
                raise ScienceFailure(f'{task_id}: XML e_0_energy differs from OUTCAR sigma-to-zero energy')
            if (run / 'execution-exit-code.txt').read_text().strip() != '0':
                raise ScienceFailure(f'{task_id}: nonzero engine exit')
            moments = _final_local_moments(run / 'OUTCAR', 33)
            geom = _check_static_geometry(run, job, choice, model)
            (input_parameters, kmesh) = _validate_case01_input_policy(run, job, settings, geom)
            if not math.isfinite(native['energy_sigma0_eV']):
                raise ScienceFailure(f'{task_id}: nonfinite sigma-to-zero energy')
            result_rows[task_id] = {'task_id': task_id, 'site': job['site'], 'condition': job['condition'], 'magnetic_start': job['magnetic_start'], 'energy_sigma0_eV': native['energy_sigma0_eV'], 'scf_iterations': native['scf_iterations'], 'dE_eV': native['final_delta_free_energy_eV'], 'd_eps_eV': native['final_delta_band_energy_eV'], 'highest_band_occupation': native['top_band_occupation'], 'max_force_eV_A_diagnostic': native['max_force_eV_A'], 'local_moments_muB': moments, 'settings_fingerprint': job['settings_fingerprint'], 'method_revision_id': job['method_revision_id'], 'ready_sha256': sha_file(run / 'READY.json')}
            physical[task_id] = {'incar': {k: v for (k, v) in geom['incar'].items() if k != 'SYSTEM'}, 'kpoints': (run / 'KPOINTS').read_bytes(), 'potcar_sha256': ready_sha['POTCAR'], 'parameters': input_parameters, 'kmesh': kmesh, 'poscar': geom, 'job': sealed_job, 'magmoms': _parse_magmoms(geom['incar'], 33)}
            sealed_magmoms = job.get('magnetic_moments_muB')
            if not isinstance(sealed_magmoms, list) or len(sealed_magmoms) != 33 or any((abs(finite_number(x, f'{task_id} magnetic moment') - y) > 1e-08 for (x, y) in zip(sealed_magmoms, physical[task_id]['magmoms'], strict=True))):
                raise ScienceFailure(f'{task_id}: INCAR MAGMOM differs from the sealed initial magnetic vector')
        if len({physical[task_id]['potcar_sha256'] for task_id in job_map}) != 1:
            raise ScienceFailure('all six matched runs must use the same published PBE/PAW potential bytes')
        deltas = []
        condition_order = ['baseline', 'numerical_sensitivity', 'magnetic_sensitivity']
        pair_task_ids = {}
        for condition in condition_order:
            pair = by_condition[condition]
            a_job = next((j for j in pair if j['site'] == 'A'))
            b_job = next((j for j in pair if j['site'] == 'B'))
            (a_id, b_id) = (a_job['task_id'], b_job['task_id'])
            pair_task_ids[condition] = (a_id, b_id)
            (a, b) = (result_rows[a_id], result_rows[b_id])
            (pa, pb) = (physical[a_id], physical[b_id])
            if a['settings_fingerprint'] != b['settings_fingerprint'] or pa['incar'] != pb['incar'] or pa['kpoints'] != pb['kpoints'] or (pa['potcar_sha256'] != pb['potcar_sha256']) or (pa['job'].get('resource_profile') != pb['job'].get('resource_profile')) or (pa['job'].get('magnetic_moments_muB') != pb['job'].get('magnetic_moments_muB')) or (pa['magmoms'] != pb['magmoms']) or (pa['job'].get('magnetic_start') != pb['job'].get('magnetic_start')):
                raise ScienceFailure(f'{condition}: A/B physical inputs or magnetic-start rules are not matched')
            if pa['poscar']['cell'] != pb['poscar']['cell'] or pa['poscar']['metal_fractional'] != pb['poscar']['metal_fractional']:
                raise ScienceFailure(f'{condition}: A/B metal geometry differs beyond the selected H coordinate')
            actual = a['energy_sigma0_eV'] - b['energy_sigma0_eV']
            deltas.append({'condition': condition, 'delta_E_A_minus_B_eV': actual})
        numerical_controls_changed: dict[str, list[str]] = {'A': [], 'B': []}
        convergence_incar_fields = ('ENCUT', 'EDIFF', 'NBANDS', 'PREC', 'ISMEAR', 'SIGMA')
        for site in ('A', 'B'):
            base_job = next((j for j in by_condition['baseline'] if j['site'] == site))
            tight_job = next((j for j in by_condition['numerical_sensitivity'] if j['site'] == site))
            base_physics = physical[base_job['task_id']]
            tight_physics = physical[tight_job['task_id']]
            if base_physics['magmoms'] != tight_physics['magmoms']:
                raise ScienceFailure('baseline and numerical-sensitivity runs must preserve their magnetic start')
            changed_controls = [field for field in convergence_incar_fields if base_physics['incar'].get(field) != tight_physics['incar'].get(field)]
            if base_physics['kpoints'] != tight_physics['kpoints']:
                changed_controls.append('KPOINTS')
            if not changed_controls:
                raise ScienceFailure('numerical-sensitivity pair does not change a relevant accuracy control')
            numerical_controls_changed[site] = changed_controls
            alt_job = next((j for j in by_condition['magnetic_sensitivity'] if j['site'] == site))
            if physical[alt_job['task_id']]['magmoms'] == base_physics['magmoms']:
                raise ScienceFailure('alternate magnetic-start pair does not change the initial MAGMOM vector')
        site_run_map = {site: next((j['task_id'] for j in by_condition['baseline'] if j['site'] == site)) for site in ('A', 'B')}
        _assert_model_pair(model, final / 'models.zip', choice, {**{k: {'path': run_paths[k]} for k in run_paths}, 'A': site_run_map['A'], 'B': site_run_map['B']})
        with (final / 'site_inventory.csv').open(newline='', encoding='utf-8') as stream:
            final_inventory = list(csv.DictReader(stream))
        if len(final_inventory) != 32 or {row.get('site_id') for row in final_inventory} != set(inventory):
            raise ScienceFailure('final site inventory must contain all 32 public octahedral sites')
        inventory_by_id = {row['site_id']: row for row in final_inventory}
        model_by_id = {row['site_id']: row for row in model['octahedral_sites']}
        for (site_id, expected) in inventory.items():
            observed = inventory_by_id[site_id]
            model_site = model_by_id[site_id]
            expected_site = {'site_id': site_id, 'fx': model_site['fractional'][0], 'fy': model_site['fractional'][1], 'fz': model_site['fractional'][2], 'site_type': model_site['site_type'], **model_site['neighbor_counts'], 'multiplicity': model_site['multiplicity'], 'nearest_neighbor_distance_A': model_site['nearest_neighbor_distance_A']}
            if set(observed) != set(expected) or set(expected) != set(expected_site) or any((observed[key] != expected[key] for key in ('site_id', 'site_type', 'Co', 'Cr', 'Fe', 'Ni', 'multiplicity'))) or any((abs(finite_number(float(observed[key]), f'site_inventory.{site_id}.{key}') - finite_number(float(expected_site[key]), f'model.{site_id}.{key}')) > 1e-09 for key in ('fx', 'fy', 'fz', 'nearest_neighbor_distance_A'))):
                raise ScienceFailure(f'site_inventory.csv differs from the independently checked public model at {site_id}')
        with (final / 'models.zip').open('rb') as stream:
            pass
        with zipfile.ZipFile(final / 'models.zip') as z:
            if z.read('models/site-inventory.csv') != (final / 'site_inventory.csv').read_bytes():
                raise ScienceFailure('models.zip inventory differs from final/site_inventory.csv')
        with (final / 'convergence.csv').open(newline='', encoding='utf-8') as stream:
            convergence = list(csv.DictReader(stream))
        if len(convergence) != 3:
            raise ScienceFailure('convergence.csv must contain exactly three matched-pair rows')
        expected_alias = {'baseline': {'baseline'}, 'numerical_sensitivity': {'numerical_sensitivity', 'joint-tight'}, 'magnetic_sensitivity': {'magnetic_sensitivity', 'baseline'}}
        for (index_num, condition) in enumerate(condition_order):
            row = next((r for r in convergence if int(r.get('phase', 0)) == index_num + 1), None)
            if not row:
                raise ScienceFailure(f'convergence.csv is missing phase {index_num + 1}')
            (a_id, b_id) = pair_task_ids[condition]
            actual_delta = deltas[index_num]['delta_E_A_minus_B_eV']
            algo_a = physical[a_id]['incar'].get('ALGO', '').lower()
            expected_algo = 'all' if algo_a == 'all' else 'normal' if algo_a == 'normal' else algo_a
            if row.get('condition') not in expected_alias[condition] or row.get('gate') != 'PASSED' or row.get('magnetic_start') != job_map[a_id]['magnetic_start'] or (row.get('algorithm', '').lower() != expected_algo):
                raise ScienceFailure(f'convergence.csv phase {index_num + 1} metadata/gate does not match sealed inputs')
            try:
                reported_delta = finite_number(float(row.get('delta_E_A_minus_B_eV', '')), f'convergence.csv phase {index_num + 1} delta')
            except ValueError as exc:
                raise ScienceFailure(f'convergence.csv phase {index_num + 1} delta is malformed') from exc
            if abs(reported_delta - actual_delta) > 5.1e-09:
                raise ScienceFailure(f'convergence.csv phase {index_num + 1} delta differs from native energies')
            array_ids = {str(job_map[x].get('array_job_id')) for x in (a_id, b_id)}
            if row.get('array_job_id') and row['array_job_id'] not in array_ids:
                raise ScienceFailure(f'convergence.csv phase {index_num + 1} array ID differs from sealed jobs')
        scientific_claims = read_claims(final / 'scientific-claims.json')
        validate_claims(scientific_claims, model_sha256=choice['model_sha256'], choice=choice, pair_task_ids=pair_task_ids, deltas=deltas, numerical_controls_changed=numerical_controls_changed, physical=physical, job_map=job_map)
    rows = index.get('artifacts')
    if not isinstance(rows, list):
        raise ScienceFailure('evidence-index must be a list of non-index artifacts')
    expected_rows = {'final/' + n for n in required_files if n not in {'evidence-index.json', 'execution-evidence'}}
    expected_rows |= {'final/' + ref['path'] for ref in receipt['file_bindings'].values() if ref['path'].startswith('execution-evidence/')}
    actual_evidence_rows = {path.relative_to(final).as_posix() for path in (final / 'execution-evidence').rglob('*') if path.is_file()}
    expected_evidence_rows = {path.removeprefix('final/') for path in expected_rows if path.startswith('final/execution-evidence/')}
    if actual_evidence_rows != expected_evidence_rows:
        raise ScienceFailure('execution-evidence contains files not bound in the receipt/index or omits required files')
    observed_rows = set()
    for row in rows:
        p = row.get('path') if isinstance(row, dict) else None
        if p in observed_rows or p not in expected_rows:
            raise ScienceFailure('evidence-index has duplicate or undeclared artifact rows')
        observed_rows.add(p)
        file_path = app / p
        if not file_path.is_file() or file_path.stat().st_size != row.get('bytes') or sha_file(file_path) != row.get('sha256'):
            raise ScienceFailure(f'evidence-index hash mismatch: {p}')
    if observed_rows != expected_rows:
        raise ScienceFailure('evidence-index omits a declared scientific artifact')
    for (rel, binding) in receipt['file_bindings'].items():
        if not (final / rel).is_file() or sha_file(final / rel) != binding['sha256']:
            raise ScienceFailure(f'signed execution receipt artifact binding differs: {rel}')
    return {
        "schema": "case01-verification/v1", "case_id": "case-01",
        "status": "PASS", "scientific_status": "COMPLETE",
        "decision": read_claims(final / "scientific-claims.json")["decision"]["claim"],
        "valid_individuals": "6/6", "valid_pairs": "3/3",
        "paired_deltas_eV": deltas,
        "numerical_controls_changed": numerical_controls_changed,
        "execution_source_scope": receipt["source_scope"], "reward": 1.0,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--app", type=pathlib.Path, default=pathlib.Path(os.environ.get("APP", "/app")))
    parser.add_argument("--report", type=pathlib.Path, default=pathlib.Path(os.environ.get("LOGS", "/logs/verifier")) / "verification.json")
    args = parser.parse_args()
    try:
        report = verify(args.app)
    except EvidenceEnvironmentError as exc:
        report = {"schema": "case01-verification/v1", "case_id": "case-01", "status": "ENV_INVALID",
                  "scientific_status": "UNVERIFIED", "errors": [str(exc)]}
        code = 2
    except ReceiptEnvironmentError as exc:
        report = {"schema": "case01-verification/v1", "case_id": "case-01", "status": "ENV_INVALID",
                  "scientific_status": "UNVERIFIED", "errors": [str(exc)]}
        code = 2
    except ClaimEnvironmentError as exc:
        report = {"schema": "case01-verification/v1", "case_id": "case-01", "status": "ENV_INVALID",
                  "scientific_status": "UNVERIFIED", "errors": [str(exc)]}
        code = 2
    except (ScienceFailure, OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile, ET.ParseError) as exc:
        report = {"schema": "case01-verification/v1", "case_id": "case-01", "status": "FAIL", "reward": 0.0,
                  "scientific_status": "INVALID_OUTPUT", "errors": [str(exc)]}
        code = 1
    else:
        code = 1 if report["status"] == "FAIL" else 0
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
