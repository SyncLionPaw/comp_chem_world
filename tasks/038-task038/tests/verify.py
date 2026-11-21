# L1 Deliverables: Check required deliverables for completeness and parseability.
# L2 Execution: Check execution evidence through bounded replay or independent recomputation where implemented.
# L3 Science: Assess potential alignment, barrier comparisons, and conditional pathway ordering.
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
            reward_file.write_text('0\n')
            print(json.dumps(result, ensure_ascii=False))
            return 0
        elif status == 'ENVIRONMENT_ERROR' and proc.returncode == 2 and ('reward' not in result):
            result = {**result, 'scientific_status': status, 'status': 'ENV_INVALID'}
        else:
            raise ValueError('unknown/inconsistent verifier status or exit code')
    except Exception as exc:
        result = {'status': 'ENV_INVALID', 'error': type(exc).__name__ + ': ' + str(exc)}
    report_file.write_text(json.dumps(result, ensure_ascii=False) + '\n')
    reward_file.write_text('0\n')
    print(json.dumps(result, ensure_ascii=False))
    return 0
if __name__ == '__main__' and sys.argv[1:] == ['--grade']:
    raise SystemExit(_grade_entry())
'Structured local scientific verification in portable and CompChemBench layouts.'
import csv, json, os, sys
from pathlib import Path
'Evaluator science functions, independently using acquired source/reference data.'
import ast as _bench38_0_ast, hashlib as _bench38_0_hashlib, json as _bench38_0_json, math as _bench38_0_math, re as _bench38_0_re
from pathlib import Path as _bench38_0_Path
_bench38_0_SYSTEMS = ['water_CO2', 'water_CO2anion', '2K_CO2', '2K_CO2anion']
_bench38_0_C_CM_FS = 2.99792458e-05
_bench38_0_BANDS = {'bending': [400, 950], 'symmetric': [900, 1500], 'asymmetric_neutral': [2000, 2700], 'asymmetric_anion': [1300, 1950]}

class _bench38_0_EquivalenceReviewRequired(ValueError):
    pass

def _bench38_0_digest(path):
    h = _bench38_0_hashlib.sha256()
    with _bench38_0_Path(path).open('rb') as f:
        for b in iter(lambda: f.read(1048576), b''):
            h.update(b)
    return h.hexdigest()

def _bench38_0_loads_json(text):

    def duplicate(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate JSON key ' + key)
            result[key] = value
        return result

    def invalid(value):
        raise ValueError('nonfinite JSON value ' + value)
    return _bench38_0_json.loads(text, object_pairs_hook=duplicate, parse_constant=invalid)

def _bench38_0_read_json(path):
    return _bench38_0_loads_json(_bench38_0_Path(path).read_text())

def _bench38_0_number(value):
    if type(value) not in (int, float) or not _bench38_0_math.isfinite(value):
        raise ValueError('expected finite real number')
    return float(value)

def _bench38_0_integer(value):
    if type(value) is int:
        return value
    if isinstance(value, str) and _bench38_0_re.fullmatch('[+-]?(?:0|[1-9][0-9]*)', value.strip()):
        return int(value)
    raise ValueError('expected integer or unambiguous integer string')

def _bench38_0_near(value, target, tolerance=1e-06):
    if abs(_bench38_0_number(value) - target) > tolerance:
        raise ValueError('numeric mismatch: ' + str(target))

def _bench38_0_pointer(doc, _bench38_0_pointer):
    if _bench38_0_pointer.startswith('#'):
        _bench38_0_pointer = _bench38_0_pointer[1:]
    if _bench38_0_pointer and (not _bench38_0_pointer.startswith('/')):
        raise ValueError('invalid JSON Pointer')
    result = doc
    segments = [] if _bench38_0_pointer == '' else _bench38_0_pointer[1:].split('/')
    for segment in segments:
        if _bench38_0_re.search('~(?![01])', segment):
            raise ValueError('invalid JSON Pointer escape')
        segment = segment.replace('~1', '/').replace('~0', '~')
        result = result[int(segment)] if isinstance(result, list) else result[segment]
    return result

def _bench38_0_normalize_scope(scope):
    if isinstance(scope, list) and len(scope) == 1:
        scope = scope[0]
    if not isinstance(scope, str):
        raise ValueError('scope must be one string value')
    return scope

def _bench38_0_canonical_selections(metadata, source=None):
    """Accept the two documented layouts, checking scientific fields if both occur."""
    flat = metadata.get('selection')
    systems = metadata.get('systems')
    nested = {}
    if isinstance(systems, dict):
        for name, item in systems.items():
            if not isinstance(item, dict) or not isinstance(item.get('selection'), dict):
                continue
            chosen = item['selection']
            nested[name] = dict(chosen)
            for key in ('start_frame', 'end_frame_exclusive'):
                if key in item:
                    if key in nested[name] and _bench38_0_integer(nested[name][key]) != _bench38_0_integer(item[key]):
                        raise ValueError('conflicting nested ' + key + ' for ' + name)
                    nested[name][key] = _bench38_0_integer(item[key])
            if 'start_frame' in nested[name]:
                nested[name]['start_frame'] = _bench38_0_integer(nested[name]['start_frame'])
            if 'end_frame_exclusive' in nested[name]:
                nested[name]['end_frame_exclusive'] = _bench38_0_integer(nested[name]['end_frame_exclusive'])
            if isinstance(nested[name].get('hydrogen_masses_u'), list):
                h = nested[name]['hydrogen_masses_u']
                if any((type(x) not in (int, float) or not _bench38_0_math.isfinite(x) for x in h)):
                    raise ValueError('invalid hydrogen mass list for ' + name)
                nested[name]['hydrogen_masses_u'] = sorted(set((float(x) for x in h)))
            if isinstance(nested[name].get('atom_indices'), list):
                ids = nested[name]['atom_indices']
                if any((type(x) is bool for x in ids)):
                    raise ValueError('boolean atom index for ' + name)
                nested[name]['atom_indices'] = [_bench38_0_integer(x) for x in ids]
            if source:
                declared = next((item[k] for k in ('frame_count_total', 'n_frames') if k in item), None)
                if declared is not None and _bench38_0_integer(declared) != _bench38_0_integer(source[name]['n_frames']):
                    raise ValueError('total-frame count mismatch for ' + name)
            if 'frame_count_total' in item and 'n_frames' in item and (_bench38_0_integer(item['frame_count_total']) != _bench38_0_integer(item['n_frames'])):
                raise ValueError('conflicting total-frame count for ' + name)
            if 'selected_frame_count' in item and 'start_frame' in nested[name] and ('end_frame_exclusive' in nested[name]):
                if _bench38_0_integer(item['selected_frame_count']) != _bench38_0_integer(nested[name]['end_frame_exclusive']) - _bench38_0_integer(nested[name]['start_frame']):
                    raise ValueError('conflicting selected-frame count for ' + name)
    if not isinstance(flat, dict):
        flat = {}
    if not isinstance(systems, dict):
        systems = {}
    normalized_flat = {}
    for name, item in flat.items():
        if not isinstance(item, dict):
            raise ValueError('selection entry must be object for ' + name)
        normalized_flat[name] = dict(item)
        for key in ('start_frame', 'end_frame_exclusive'):
            if key in item:
                normalized_flat[name][key] = _bench38_0_integer(item[key])
        if isinstance(item.get('atom_indices'), list):
            if any((type(x) is bool for x in item['atom_indices'])):
                raise ValueError('boolean atom index for ' + name)
            normalized_flat[name]['atom_indices'] = [_bench38_0_integer(x) for x in item['atom_indices']]
        if isinstance(item.get('hydrogen_masses_u'), list):
            h = item['hydrogen_masses_u']
            if any((type(x) not in (int, float) or not _bench38_0_math.isfinite(x) for x in h)):
                raise ValueError('invalid hydrogen mass list for ' + name)
            normalized_flat[name]['hydrogen_masses_u'] = sorted(set((float(x) for x in h)))
    flat = normalized_flat
    if flat and nested:
        for name in _bench38_0_SYSTEMS:
            if name not in flat or name not in nested:
                raise ValueError('flat/nested selection must cover all four systems')
            for key in ('atom_indices', 'start_frame', 'end_frame_exclusive', 'mass_u', 'hydrogen_masses_u'):
                if key not in flat[name] or key not in nested[name] or flat[name][key] != nested[name][key]:
                    raise ValueError('conflicting flat/nested ' + key + ' for ' + name)
    chosen = flat or nested
    if set(chosen) != set(_bench38_0_SYSTEMS):
        raise ValueError('selection must cover all four systems')
    return chosen

def _bench38_0_normalize_claims(actual):
    if isinstance(actual, dict):
        claims = actual
    elif isinstance(actual, list):
        claims = {}
        for item in actual:
            if not isinstance(item, dict) or not isinstance(item.get('claim'), str):
                raise ValueError('claim list items require a claim name')
            name = item['claim']
            item = {k: v for k, v in item.items() if k != 'claim'}
            if name in claims:
                raise ValueError('duplicate claim ' + name)
            claims[name] = item
    else:
        raise ValueError('claims must be a mapping or named list')
    normalized = {}
    for name, item in claims.items():
        if not isinstance(item, dict):
            raise ValueError('claim body must be an object')
        item = dict(item)
        if 'scope' in item:
            item['scope'] = _bench38_0_normalize_scope(item['scope'])
        if 'evidence' in item and isinstance(item['evidence'], list):
            refs = []
            for ref in item['evidence']:
                prefix, parts = _bench38_0_canonical_reference(ref)
                escaped = [x.replace('~', '~0').replace('/', '~1') for x in parts]
                refs.append(prefix + ':/' + '/'.join(escaped))
            item['evidence'] = sorted(set(refs))
        normalized[name] = item
    return normalized

def _bench38_0_parse_reference(ref):
    if not isinstance(ref, str):
        raise ValueError('invalid evidence pointer')
    if ':' in ref:
        return ref.split(':', 1)
    if '#' in ref:
        return ref.split('#', 1)
    raise ValueError('invalid evidence pointer')

def _bench38_0_canonical_reference(ref):
    prefix, key = _bench38_0_parse_reference(ref)
    key = key[1:] if key.startswith('#') else key
    if key and (not key.startswith('/')):
        raise ValueError('invalid JSON Pointer')
    encoded = [] if key == '' else key[1:].split('/')
    if any((_bench38_0_re.search('~(?![01])', x) for x in encoded)):
        raise ValueError('invalid JSON Pointer escape')
    parts = [x.replace('~1', '/').replace('~0', '~') for x in encoded]
    return (prefix, parts)

def _bench38_0_exact_evidence_path(actual_paths, document, pointer):
    prefix, parts = _bench38_0_canonical_reference(document + ':' + pointer)
    return any((actual_prefix == prefix and actual_parts == parts for actual_prefix, actual_parts in actual_paths))

def _bench38_0_evidence_covers(actual_paths, document, pointer):
    prefix, required_parts = _bench38_0_canonical_reference(document + ':' + pointer)
    return any(actual_prefix == prefix and actual_parts and
               (actual_parts[:len(required_parts)] == required_parts or
                required_parts[:len(actual_parts)] == actual_parts)
               for actual_prefix, actual_parts in actual_paths)

def _bench38_0_overclaim_status(name, claim):
    """Return an explicit-overclaim error, an ambiguity review, or None."""
    text = str(claim.get('scope', '')) + '\n' + str(claim.get('rationale', ''))
    review_reasons = []
    for match in _bench38_0_re.finditer(r'\bunconditional(?:ly)?\b', text, _bench38_0_re.I):
        prefix = text[:match.start()].lower()
        tail = prefix[-180:]
        clause = _bench38_0_re.split(r'[.;:\n]', tail)[-1]
        contrast = _bench38_0_re.search(r'\bnot\s+(?:merely|only|just)\b[\s\S]*\bbut\b', clause)
        direct_negation = bool(_bench38_0_re.search(r'\bnot\s+(?:an?\s+)?$', prefix))
        predicate_negation = bool(_bench38_0_re.search(r'\b(?:does|do|did|is|are|was|were|would|could|should|might|may|can)\s+not\s+(?:hold|apply|follow|be)\s*$', prefix))
        if contrast:
            raise ValueError('unconditional ordering claim is unsupported for ' + name)
        negation_context = _bench38_0_re.split(r'\b(?:and|or)\b', clause)[-1]
        negation_count = len(_bench38_0_re.findall(r'\bnot\b', negation_context))
        if (direct_negation or predicate_negation) and negation_count == 1:
            continue
        if negation_count:
            review_reasons.append('unverified negation around an unconditional ranking for ' + name)
            continue
        if _bench38_0_re.search(r'\b(?:is|are|was|were|holds?|applies?|follows?|remains?|becomes?)\s*$', prefix):
            raise ValueError('unconditional ordering claim is unsupported for ' + name)
        review_reasons.append('unverified wording around an unconditional ranking for ' + name)
    pattern = r'\b(?:experimentally\s+(?:proven|proved|established|demonstrated|confirmed|measured)|(?:proven|proved|established|demonstrated|confirmed)\s+experimentally)\b'
    for match in _bench38_0_re.finditer(pattern, text, _bench38_0_re.I):
        prefix = text[:match.start()].lower()
        tail = prefix[-180:]
        clause = _bench38_0_re.split(r'[.;:\n]', tail)[-1]
        contrast = _bench38_0_re.search(r'\bnot\s+(?:merely|only|just)\b[\s\S]*\bbut\b', clause)
        direct_negation = bool(_bench38_0_re.search(r'\bnot\s+(?:an?\s+)?$', prefix))
        if contrast:
            raise ValueError('experimental extrapolation is unsupported for ' + name)
        negation_context = _bench38_0_re.split(r'\b(?:and|or)\b', clause)[-1]
        negation_count = len(_bench38_0_re.findall(r'\bnot\b', negation_context))
        if direct_negation and negation_count == 1:
            continue
        if negation_count:
            review_reasons.append('unverified negation around experimental evidence for ' + name)
            continue
        if _bench38_0_re.search(r'\b(?:is|are|was|were|has been|have been|proves?|establishes?|demonstrates?|confirms?)\s*$', prefix):
            raise ValueError('experimental extrapolation is unsupported for ' + name)
        review_reasons.append('unverified wording around experimental evidence for ' + name)
    return '; '.join(review_reasons) if review_reasons else None

def _bench38_0_supported_ordering_review(name, claim, actual_paths):
    """Accept only bounded, explicitly model-conditional positive rankings."""
    result_path = {
        'K_slower_OS_than_water': '/OS_barrier_gap_lower_eV',
        'K_IS_faster_than_K_OS': '/K_pathway_gap_lower_eV',
    }[name]
    if not _bench38_0_exact_evidence_path(actual_paths, 'result', result_path):
        raise ValueError('missing exact result lower-bound evidence for ' + name)
    if not _bench38_0_evidence_covers(actual_paths, 'input', '/assumptions/0'):
        raise ValueError('missing common-prefactor assumption evidence for ' + name)

    legacy_perturbation = _bench38_0_evidence_covers(actual_paths, 'input', '/assumptions/1')
    declared_parent = _bench38_0_exact_evidence_path(actual_paths, 'input', '/conditional_barrier_perturbations_eV')
    if name == 'K_slower_OS_than_water':
        declared_children = (
            _bench38_0_evidence_covers(actual_paths, 'input', '/conditional_barrier_perturbations_eV/K')
            and _bench38_0_evidence_covers(actual_paths, 'input', '/conditional_barrier_perturbations_eV/water')
        )
    else:
        declared_children = _bench38_0_evidence_covers(actual_paths, 'input', '/conditional_barrier_perturbations_eV/K')
    if not (legacy_perturbation or declared_parent or declared_children):
        raise ValueError('missing required declared perturbation evidence for ' + name)

    scope = claim.get('scope')
    rationale = claim.get('rationale', '')
    if not isinstance(scope, str) or not scope.strip():
        return 'positive ranking lacks a nonempty conditional scope for ' + name
    scope_text = scope.lower()
    rationale_text = rationale.lower()

    def has_prefactor(text):
        return ('prefactor' in text and bool(_bench38_0_re.search(r'\b(?:equal|same|common)\b', text)))

    def has_declared_independent_perturbations(text):
        return (('perturb' in text or 'sensitivity' in text)
                and bool(_bench38_0_re.search(r'\b(?:declared|specified)\b', text))
                and bool(_bench38_0_re.search(r'\bindependent(?:ly)?\b', text)))

    scope_context = (any(word in scope_text for word in ('illustrative', 'model', 'scenario'))
                     and bool(_bench38_0_re.search(r'\b(?:under|within|with|assuming|conditional(?:ly)?(?:\s+on|-on)?)\b', scope_text)))
    rationale_context = (any(word in rationale_text for word in ('scenario', 'model'))
                         and bool(_bench38_0_re.search(r'\b(?:declared|specified)\b', rationale_text)))
    scope_disclaims_extrapolation = bool(_bench38_0_re.search(r'\bnot\s+(?:an?\s+)?(?:experimental|measured)\b', scope_text))
    if not (scope_context and rationale_context and scope_disclaims_extrapolation
            and has_prefactor(scope_text) and has_prefactor(rationale_text)
            and has_declared_independent_perturbations(scope_text)
            and has_declared_independent_perturbations(rationale_text)):
        return 'positive ranking has unverified conditional wording for ' + name
    return None

def _bench38_0_normalize_replay_json(filename, value):
    """Canonicalize only documented equivalent public interface shapes."""
    if filename in ('peaks.json', 'robustness.json') and 'claims' in value:
        value = dict(value)
        value['claims'] = _bench38_0_normalize_claims(value['claims'])
    if filename == 'metadata.json':
        value = dict(value)
        if isinstance(value.get('selection'), dict) or isinstance(value.get('systems'), dict):
            value['selection'] = _bench38_0_canonical_selections(value)
            value.pop('systems', None)
        value.setdefault('estimator_aggregation', 'full_selected_sequence')
        labels = value.get('provided_ensembles')
        if isinstance(labels, list):
            value['provided_ensembles'] = sorted(labels)
        elif isinstance(labels, dict):
            expected = {'water_CO2': 'OS_neutral', '2K_CO2': 'OS_neutral', 'water_CO2anion': 'OS_anion', '2K_CO2anion': 'OS_anion'}
            if labels == expected:
                value['provided_ensembles'] = sorted(set(labels.values()))
        diag = value.get('script_diagnostics')
        if isinstance(diag, dict):
            required = ('loop_components', 'required_interface_components', 'example_system', 'atom_scope', 'VACF_transform', 'frequency_offset_cm-1', 'full_convolution_alignment')
            diag = {k: diag[k] for k in required if k in diag}
            for key in ('loop_components', 'required_interface_components'):
                if isinstance(diag.get(key), str) and diag[key].strip().isdigit():
                    diag[key] = int(diag[key])
            value['script_diagnostics'] = diag
    return value

def _bench38_0_check_arguments(actual, expected, documents):
    actual = _bench38_0_normalize_claims(actual)
    if set(actual) != set(expected):
        raise ValueError('scientific claim set incomplete/unknown')
    pending_review = []
    for name, rubric in expected.items():
        claim = actual[name]
        if claim.get('verdict') not in ('supported', 'conditional', 'not_established'):
            raise ValueError('invalid verdict for ' + name)
        ordering_claim = (name in ('K_slower_OS_than_water', 'K_IS_faster_than_K_OS')
                          and rubric['verdict'] == 'conditional'
                          and claim['verdict'] in ('supported', 'conditional'))
        if claim['verdict'] != rubric['verdict'] and not ordering_claim:
            raise ValueError('unsupported inference: ' + name)
        references = claim['evidence']
        if not isinstance(references, list):
            raise ValueError('evidence must be a JSON Pointer list for ' + name)
        actual_paths = [_bench38_0_canonical_reference(x) for x in references]
        declared_parent = _bench38_0_exact_evidence_path(actual_paths, 'input', '/conditional_barrier_perturbations_eV')
        if name == 'K_slower_OS_than_water':
            declared_children = (
                _bench38_0_evidence_covers(actual_paths, 'input', '/conditional_barrier_perturbations_eV/K')
                and _bench38_0_evidence_covers(actual_paths, 'input', '/conditional_barrier_perturbations_eV/water')
            )
        else:
            declared_children = _bench38_0_evidence_covers(actual_paths, 'input', '/conditional_barrier_perturbations_eV/K')
        declared_source_ordering = ordering_claim and (declared_parent or declared_children)
        if ordering_claim:
            overclaim_review = _bench38_0_overclaim_status(name, claim)
            if overclaim_review:
                pending_review.append(overclaim_review)
        if ordering_claim and (claim['verdict'] == 'supported' or declared_source_ordering):
            semantic_review = _bench38_0_supported_ordering_review(name, claim, actual_paths)
            if semantic_review:
                pending_review.append(semantic_review)
        else:
            for required in rubric['evidence']:
                rp = _bench38_0_canonical_reference(required)
                if not any((ap[1] and ap[0] == rp[0] and (ap[1][:len(rp[1])] == rp[1] or rp[1][:len(ap[1])] == ap[1]) for ap in actual_paths)):
                    raise ValueError('missing premise ' + required + ' for ' + name)
        for ref in references:
            document, key = _bench38_0_parse_reference(ref)
            if document not in documents:
                raise ValueError('unknown evidence prefix ' + document)
            _bench38_0_pointer(documents[document], key)
        if not isinstance(claim.get('rationale'), str) or not claim['rationale'].strip():
            raise ValueError('missing reasoning for ' + name)
        if 'scope' in claim:
            scope = _bench38_0_normalize_scope(claim['scope'])
            if not scope.strip():
                raise ValueError('scope must be non-empty text for ' + name)
    return pending_review

def _bench38_0_check_report_and_code(output, claims):
    """Structured claims carry L3 semantics; prose is an explanatory L1 attachment."""
    program = (output / 'analysis.py').read_text()
    tree = _bench38_0_ast.parse(program)
    if not any((isinstance(x, _bench38_0_ast.Call) for x in _bench38_0_ast.walk(tree))):
        raise ValueError('analysis.py has no executable analysis calls')
    text = (output / 'report.md').read_text()
    start = '<!-- scientific-claims:start -->'
    end = '<!-- scientific-claims:end -->'
    has_markers = start in text or end in text
    explanatory = text
    if has_markers:
        if text.count(start) != 1 or text.count(end) != 1:
            raise ValueError('report markers must form one complete claims pair')
        first = text.index(start)
        last = text.index(end)
        if last < first:
            raise ValueError('report claims markers are out of order')
        block = text[first + len(start):last].strip()
        fenced = _bench38_0_re.fullmatch('```(?:json)?\\s*\\n(.*?)\\n```', block, _bench38_0_re.S)
        embedded = _bench38_0_loads_json(fenced.group(1) if fenced else block)
        if _bench38_0_normalize_claims(embedded) != _bench38_0_normalize_claims(claims):
            raise ValueError('report claim block conflicts with structured results')
        explanatory = text[:first] + text[last + len(end):]
    explanatory = _bench38_0_re.sub(r'```.*?```', '', explanatory, flags=_bench38_0_re.S)
    if not explanatory.strip():
        raise ValueError('missing explanatory report')

def _bench38_0_potential_reference(data):
    b = data['barriers_eV']
    d = data['conditional_barrier_perturbations_eV']
    f = data['fermi_levels_eV']
    kbt = 8.617333262145e-05 * data['temperature_K']
    return {'K_vs_water_OS_log10_rate': -(b['K_OS'] - b['water_OS']) / (kbt * _bench38_0_math.log(10)), 'K_IS_vs_OS_log10_rate': (b['K_OS'] - b['K_IS']) / (kbt * _bench38_0_math.log(10)), 'water_fermi_shift_eV': f['water_anion']['mean'] - f['water_neutral']['mean'], 'K_fermi_shift_eV': f['K_anion']['mean'] - f['K_neutral']['mean'], 'OS_barrier_gap_lower_eV': b['K_OS'] - d['K'] - b['water_OS'] - d['water'], 'K_pathway_gap_lower_eV': b['K_OS'] - d['K'] - b['K_IS'] - d['K']}

def _bench38_0_potential_rubric():

    def item(verdict, evidence, scope):
        return {'verdict': verdict, 'evidence': evidence, 'scope': scope}
    return {'K_slower_OS_than_water': item('conditional', ['result:/OS_barrier_gap_lower_eV', 'input:/assumptions/0', 'input:/assumptions/1'], 'specified_equal_prefactor_and_barrier_bounds'), 'K_IS_faster_than_K_OS': item('conditional', ['result:/K_pathway_gap_lower_eV', 'input:/assumptions/0', 'input:/assumptions/1'], 'specified_equal_prefactor_and_barrier_bounds'), 'fermi_spread_is_SEM': item('not_established', ['input:/fermi_levels_eV', 'input:/not_provided/0'], 'missing_effective_sample_count'), 'strict_constant_electrode_potential': item('not_established', ['result:/water_fermi_shift_eV', 'result:/K_fermi_shift_eV', 'input:/not_provided/1'], 'Fermi_is_not_electrode_inner_potential'), 'barrier_bounds_are_measured_uncertainty': item('not_established', ['input:/assumptions/1', 'input:/not_provided/2'], 'conditional_sensitivity_only'), 'experimental_TOF_determined': item('not_established', ['input:/assumptions/0', 'input:/barriers_eV'], 'relative_model_rates_not_measured_TOF'), 'short_range_causality_proven': item('not_established', ['input:/not_provided/1', 'input:/not_provided/2'], 'kinetic_ordering_not_causal_control')}

def _bench38_0_validate_estimator(spec, n):
    kind = spec['kind']
    window = spec['window']
    detrend = spec['detrend']
    if kind not in ['periodogram', 'welch', 'vacf_fft']:
        raise _bench38_0_EquivalenceReviewRequired('unregistered estimator; use evaluator equivalence review')
    if window not in ['hann', 'boxcar', 'blackmanharris'] or detrend not in ['constant', 'linear', False]:
        raise ValueError('invalid window/detrend')
    nfft = spec.get('nfft')
    if nfft is not None and (not n <= _bench38_0_integer(nfft) <= 4 * n):
        raise ValueError('nfft must be between selected length and four times length')
    if kind == 'welch':
        nperseg = _bench38_0_integer(spec['nperseg'])
        noverlap = _bench38_0_integer(spec['noverlap'])
        if not 1024 <= nperseg <= n or not 0 <= noverlap < nperseg:
            raise ValueError('invalid Welch segmentation')
    count = _bench38_0_integer(spec['block_count'])
    if not 3 <= count <= 6 or n // count < 1024:
        raise ValueError('block stability needs 3–6 contiguous blocks of at least1024 frames')

def _bench38_0_psd(values, spec):
    import numpy as np
    from scipy.signal import periodogram, welch
    n = len(values)
    nfft = spec.get('nfft')
    kwargs = {'fs': 1, 'window': spec['window'], 'detrend': spec['detrend'], 'axis': 0, 'scaling': 'density', 'nfft': nfft}
    if spec['kind'] == 'welch':
        segment = min(spec['nperseg'], n)
        overlap = min(spec['noverlap'], segment - 1)
        f, p = welch(values, nperseg=segment, noverlap=overlap, **kwargs)
    else:
        f, p = periodogram(values, **kwargs)
    return (f / _bench38_0_C_CM_FS, p)

def _bench38_0_projected_peak(values, spec, mode, band):
    import numpy as np
    wave, p = _bench38_0_psd(values, spec)
    curve = p[:, 2:].sum(axis=1) if mode == 'bending' else p[:, 0 if mode == 'symmetric' else 1]
    ids = np.flatnonzero((wave >= band[0]) & (wave <= band[1]))
    k = ids[np.argmax(curve[ids])]
    return float(wave[k])

def _bench38_0_spectrum_rubric():
    return {'absolute_IR_Raman_intensity': {'verdict': 'not_established', 'evidence': ['metadata:/absolute_IR_or_Raman_intensity'], 'scope': 'velocity_DOS_only'}, 'charge_state_structural_fingerprint': {'verdict': 'conditional', 'evidence': ['peaks:/water_CO2', 'peaks:/water_CO2anion', 'peaks:/2K_CO2', 'peaks:/2K_CO2anion'], 'scope': 'provided_OS_ensembles_only'}, 'unique_IS_or_OS_assignment': {'verdict': 'not_established', 'evidence': ['metadata:/provided_ensembles', 'metadata:/missing_IS_comparison'], 'scope': 'no_pathway_uniqueness_from_vibrations'}, 'block_range_is_confidence_interval': {'verdict': 'not_established', 'evidence': ['metadata:/estimator/block_count'], 'scope': 'finite_block_stability_not_independent_CI'}}

def _bench38_0_spectrum_expected(data, source, name, metadata):
    import numpy as np
    selected = metadata['selection'][name]
    n = source[name]['n_frames']
    start = _bench38_0_integer(selected['start_frame'])
    end = _bench38_0_integer(selected['end_frame_exclusive'])
    if not 0 <= start <= 3000 or end > n or end - start < 6500:
        raise ValueError('unsupported or too-short equilibrium selection')
    indices = selected['atom_indices']
    expected = source[name]['indices']
    if not isinstance(indices, list) or len(indices) != 3 or indices[0] != expected[0] or (sorted(indices[1:]) != sorted(expected[1:])):
        raise ValueError('incorrect CO2 atom identity')
    hydrogen = selected['hydrogen_masses_u']
    if selected['mass_u'] != source[name]['mass_u'] or not isinstance(hydrogen, list) or any((type(x) not in (int, float) or not _bench38_0_math.isfinite(x) for x in hydrogen)) or (sorted(set((float(x) for x in hydrogen))) != sorted(set((float(x) for x in source[name]['hydrogen_masses_u'])))):
        raise ValueError('mass provenance mismatch')
    spec = metadata['estimator']
    _bench38_0_validate_estimator(spec, end - start)
    aggregation = metadata.get('estimator_aggregation', 'full_selected_sequence')
    if aggregation == 'mean_contiguous_blocks':
        raise _bench38_0_EquivalenceReviewRequired('block-averaged Welch aggregation is unregistered; evaluator review required, no reward')
    if aggregation != 'full_selected_sequence':
        raise ValueError('unknown estimator aggregation')
    v = data[name + '_v'][start:end]
    q = data[name + '_m'][start:end]
    wave, p = _bench38_0_psd(v, spec)
    power = p.sum(axis=1)
    bands = {'bending': _bench38_0_BANDS['bending'], 'symmetric': _bench38_0_BANDS['symmetric'], 'asymmetric': _bench38_0_BANDS['asymmetric_anion' if 'anion' in name else 'asymmetric_neutral']}
    modes = {}
    for mode, band in bands.items():
        center = _bench38_0_projected_peak(q, spec, mode, band)
        blocks = [_bench38_0_projected_peak(block, spec, mode, band) for block in np.array_split(q, spec['block_count'])]
        modes[mode] = {'peak': center, 'blocks': blocks, 'span': [min(blocks), max(blocks)], 'band': band}
    return (wave, power, modes)

def _bench38_0_validate_spectrum(candidate_wave, candidate_power, wave, power):
    import numpy as np
    w = np.asarray(candidate_wave, dtype=float)
    p = np.asarray(candidate_power, dtype=float)
    if w.ndim != 1 or p.ndim != 1 or len(w) != len(p) or (len(w) > len(wave)):
        raise ValueError('frequency grid/PSD length mismatch with declared estimator')
    if not np.all(np.isfinite(w)) or not np.all(np.isfinite(p)) or np.any(p < 0) or np.any(np.diff(w) <= 0):
        raise ValueError('nonfinite/invalid PSD')
    n = int(np.searchsorted(wave, 3000, side='left'))
    if len(w) < max(100, n + 1) or w[-1] < 3000 - 1e-05 or (not np.allclose(w, wave[:len(w)], rtol=1e-08, atol=1e-05)):
        raise ValueError('incorrect frequency axis/offset or incomplete 0..3000 prefix')
    if p.max() <= 0:
        raise ValueError('zero PSD')
    prefix = power[:len(p)]
    if not np.allclose(p / p.max(), prefix / prefix.max(), atol=2e-05, rtol=0.0002):
        raise ValueError('PSD inconsistent with CO2 velocities/declared estimator')

def _bench38_0_validate_modes(actual, expected, wave, power):
    import numpy as np
    from scipy.signal import find_peaks
    if set(actual) != {'bending', 'symmetric', 'asymmetric'}:
        raise ValueError('missing/extra vibration mode')
    for mode, target in expected.items():
        item = actual[mode]
        _bench38_0_near(item['wavenumber_cm-1'], target['peak'], 0.001)
        if item['range_kind'] != 'block_minmax' or item['mode_source'] != {'bending': 'bond_transverse', 'symmetric': 'bond_rate_sum', 'asymmetric': 'bond_rate_difference'}[mode]:
            raise ValueError('incorrect mode basis/range semantics')
        if len(item['block_peaks_cm-1']) != len(target['blocks']):
            raise ValueError('missing block calculations')
        for x, y in zip(item['block_peaks_cm-1'], target['blocks']):
            _bench38_0_near(x, y, 0.001)
        for x, y in zip(item['stability_range_cm-1'], target['span']):
            _bench38_0_near(x, y, 0.001)
        if len(item['stability_range_cm-1']) != 2:
            raise ValueError('invalid range')
        resolved = item['status'] == 'resolved'
        unresolved = item['status'] == 'unresolved'
        if not (resolved or unresolved):
            raise ValueError('invalid mode status')
        local, _ = find_peaks(power)
        width = max(25, float(np.max(np.diff(wave))) * 2)
        matched = [i for i in local if abs(wave[i] - target['peak']) <= width]
        mask = (wave >= target['band'][0]) & (wave <= target['band'][1])
        weak = power[mask].max() / power.max() < 0.08
        drifting = target['span'][1] - target['span'][0] >= 40
        other = [v['peak'] for k, v in expected.items() if k != mode]
        overlap = any((abs(target['peak'] - x) <= 100 for x in other))
        if resolved and (not matched):
            raise ValueError('resolved mode unsupported by total CO2 PSD')
        if unresolved:
            reason = item['unresolved_reason']
            if not {'weak_in_total_PSD': weak, 'block_drift': drifting, 'mode_overlap': overlap}.get(reason, False):
                raise ValueError('unresolved claim unsupported by spectral/block evidence')
        if not isinstance(item.get('rationale'), str) or not item['rationale'].strip():
            raise ValueError('missing mode interpretation')
"Replay analysis in the evaluator's isolated runtime; development uses trusted author code."
import json as _bench38_1_json, os as _bench38_1_os, re as _bench38_1_re, shutil as _bench38_1_shutil, subprocess as _bench38_1_subprocess, sys as _bench38_1_sys, tempfile as _bench38_1_tempfile
from pathlib import Path as _bench38_1_Path

def _bench38_1_replay(root, output, required, normalize_json=None, attachments=()):
    with _bench38_1_tempfile.TemporaryDirectory(prefix='local-analysis-replay-') as directory:
        work = _bench38_1_Path(directory)
        generated = work / 'result'
        tests = _bench38_1_Path(_bench38_1_os.environ.get('TESTS', root / 'tests'))
        command = [_bench38_1_sys.executable, str((output / 'analysis.py').resolve()), str((root / 'environment/assets').resolve()), str(generated)]
        env = {'PATH': _bench38_1_os.defpath, 'LANG': 'C.UTF-8', 'PYTHONHASHSEED': '0', 'OPENBLAS_NUM_THREADS': '1', 'OMP_NUM_THREADS': '1'}
        for key in ['APP', 'TESTS']:
            if key in _bench38_1_os.environ:
                env[key] = _bench38_1_os.environ[key]
        try:
            execution = _bench38_1_subprocess.run(command, cwd=work, env=env, capture_output=True, text=True, timeout=180)
        except _bench38_1_subprocess.TimeoutExpired:
            return {'status': 'FAIL', 'error': 'analysis replay timeout'}
        if execution.returncode:
            missing = _bench38_1_re.search("ModuleNotFoundError: No module named '([A-Za-z0-9_.]+)'", execution.stderr)
            if missing:
                return {'status': 'ENVIRONMENT_ERROR', 'error': 'analysis replay dependency unavailable: ' + missing.group(1)}
            return {'status': 'FAIL', 'error': 'analysis replay exited ' + str(execution.returncode)}
        for filename in required:
            if not (generated / filename).is_file():
                return {'status': 'FAIL', 'error': 'analysis replay did not produce ' + filename}
        for filename in required:
            if filename.endswith('.json'):
                try:
                    regenerated = _bench38_1_json.loads((generated / filename).read_text())
                    submitted = _bench38_1_json.loads((output / filename).read_text())
                    if normalize_json is not None:
                        regenerated = normalize_json(filename, regenerated)
                        submitted = normalize_json(filename, submitted)
                    if regenerated != submitted:
                        return {'status': 'FAIL', 'error': 'analysis replay differs from submitted ' + filename}
                except (ValueError, OSError, KeyError, TypeError, IndexError) as exc:
                    return {'status': 'FAIL', 'error': 'analysis replay invalid ' + filename + ': ' + type(exc).__name__ + ': ' + str(exc)}
        for filename in attachments:
            _bench38_1_shutil.copyfile(output / filename, generated / filename)
        try:
            check = _bench38_1_subprocess.run([_bench38_1_sys.executable, str(tests / 'verify.py'), str(generated), '--replay-result'], cwd=work, env=env, capture_output=True, text=True, timeout=180)
        except _bench38_1_subprocess.TimeoutExpired:
            return {'status': 'ENVIRONMENT_ERROR', 'error': 'nested evaluator timeout'}
        except OSError as exc:
            return {'status': 'ENVIRONMENT_ERROR', 'error': 'nested evaluator launch: ' + str(exc)}
        try:
            result = _bench38_1_json.loads(check.stdout)
        except ValueError:
            return {'status': 'ENVIRONMENT_ERROR', 'error': 'nested evaluator output unparseable'}
        if result.get('status') == 'ENVIRONMENT_ERROR':
            return result
        if result.get('status') == 'REVIEW_REQUIRED' and check.returncode == 2 and ('reward' not in result):
            return result
        if check.returncode or result.get('status') != 'PASS':
            return {'status': 'FAIL', 'error': 'replayed scientific artifacts fail independent verification'}
    return {'status': 'PASS'}

def equivalence_review(root, out, refs):
    tests = Path(os.environ.get('TESTS', root / 'tests'))
    if '--review-file' not in sys.argv:
        print(json.dumps({'status': 'REVIEW_REQUIRED', 'reason': 'Scientific equivalence of the unregistered estimator needs evaluator review; no reward.'}))
        return 2
    try:
        path = Path(sys.argv[sys.argv.index('--review-file') + 1]).resolve()
        if path.is_relative_to(out.resolve()):
            raise ValueError('evaluator review cannot be supplied inside candidate outputs')
        review = _bench38_0_read_json(path)
        if review['schema'] != 'local-science-review/v1' or review['case_id'] != refs.get('case_id', root.name):
            raise ValueError('review identity/schema')
        if review['evaluation_refs_sha256'] != _bench38_0_digest(tests / 'refs.json'):
            raise ValueError('review reference stale')
        for filename in refs['required']:
            if review['candidate_hashes'][filename] != _bench38_0_digest(out / filename):
                raise ValueError('review candidate stale')
        criteria = ['deliverables_complete', 'spectral_estimator_validity', 'peak_assignment_and_identifiability', 'structured_scientific_arguments']
        if set(review['criteria']) != set(criteria) or any((x not in ['PASS', 'FAIL'] for x in review['criteria'].values())):
            raise ValueError('review coverage')
        if not review['reviewer'].strip() or not review['rationale'].strip():
            raise ValueError('missing evaluator reasoning')
        passed = all((x == 'PASS' for x in review['criteria'].values()))
        print(json.dumps({'status': 'PASS' if passed else 'FAIL', 'reward': int(passed), 'verification_coverage': 'COMPLETE', 'method': 'evaluator_equivalence_review', 'review_sha256': _bench38_0_digest(path)}))
        return 0 if passed else 1
    except Exception as exc:
        print(json.dumps({'status': 'ENVIRONMENT_ERROR', 'error': 'invalid evaluator review: ' + str(exc)}))
        return 2

def main():
    root = Path(os.environ.get('APP', Path(__file__).resolve().parents[1]))
    tests = Path(os.environ.get('TESTS', root / 'tests'))
    out = Path(sys.argv[1])
    errors = []
    pending_review = []
    try:
        refs = _bench38_0_read_json(tests / 'refs.json')
        for rel, h in refs['asset_hashes'].items():
            if _bench38_0_digest(root / 'environment' / rel) != h.removeprefix('sha256:'):
                raise RuntimeError('corrupt/missing evaluation input ' + rel)
        for rel, h in refs['evidence_files'].items():
            if _bench38_0_digest(tests / rel) != h:
                raise RuntimeError('corrupt/missing evaluator reference ' + rel)
        if refs['mode'] == 'spectrum':
            import numpy as np
            import ase
            from scipy import signal
            source = refs['reference']['sources']
            data = {name: np.asarray(item['values'], dtype=item['dtype']).reshape(item['shape']) for name, item in refs['spectrum_arrays'].items()}
            for name in _bench38_0_SYSTEMS:
                if data[name + '_v'].shape != (source[name]['n_frames'], 9) or data[name + '_m'].shape != (source[name]['n_frames'], 8):
                    raise RuntimeError('invalid reference arrays')
        else:
            public = _bench38_0_read_json(root / 'environment/assets/kinetics.json')
            reference = refs['reference']
            expected = _bench38_0_potential_reference(public)
            if reference['numeric'] != expected or reference['claims'] != _bench38_0_potential_rubric():
                raise RuntimeError('inconsistent potential reference')
    except Exception as exc:
        print(json.dumps({'status': 'ENVIRONMENT_ERROR', 'error': str(exc)}, ensure_ascii=False))
        return 2
    try:
        for filename in refs['required']:
            if not (out / filename).is_file() or (out / filename).stat().st_size == 0:
                raise ValueError('missing ' + filename)
        if refs['mode'] == 'potential':
            result = _bench38_0_read_json(out / 'robustness.json')
            for name, value in expected.items():
                _bench38_0_near(result[name], value)
            pending_review = _bench38_0_check_arguments(result['claims'], _bench38_0_potential_rubric(), {'input': public, 'result': result})
            if 'uncertainty_semantics' in result and result['uncertainty_semantics'] != 'conditional_bounds_not_Fermi_spread_CI':
                raise ValueError('uncertainty meaning')
            _bench38_0_check_report_and_code(out, result['claims'])
        else:
            metadata = _bench38_0_read_json(out / 'metadata.json')
            peaks = _bench38_0_read_json(out / 'peaks.json')
            _bench38_0_near(metadata['dt_fs'], 1)
            _bench38_0_near(metadata['speed_of_light_cm_per_fs'], _bench38_0_C_CM_FS, 1e-12)
            _bench38_0_near(metadata['Nyquist_cm-1'], 0.5 / _bench38_0_C_CM_FS, 0.001)
            if metadata['absolute_IR_or_Raman_intensity'] is not False or metadata['mass_rescaled'] is not False:
                raise ValueError('invalid absolute intensity/mass inference')
            ensembles = metadata['provided_ensembles']
            if isinstance(ensembles, list):
                valid_ensembles = set(ensembles) == {'OS_neutral', 'OS_anion'} and len(ensembles) == 2
            elif isinstance(ensembles, dict):
                valid_ensembles = ensembles == {'water_CO2': 'OS_neutral', '2K_CO2': 'OS_neutral', 'water_CO2anion': 'OS_anion', '2K_CO2anion': 'OS_anion'}
            else:
                valid_ensembles = False
            if not valid_ensembles or metadata['missing_IS_comparison'] is not True:
                raise ValueError('dataset applicability')
            if not isinstance(metadata['time_source'], str) or not metadata['time_source'].strip():
                raise ValueError('missing time provenance')
            diagnostic = metadata['script_diagnostics']
            if not isinstance(diagnostic, dict):
                raise ValueError('script_diagnostics must be an object')
            for key in ('loop_components', 'required_interface_components'):
                value = diagnostic.get(key)
                if isinstance(value, str):
                    diagnostic[key] = _bench38_0_integer(value)
            expected_diagnostics = {'loop_components': 177, 'required_interface_components': 531, 'example_system': 'water_CO2', 'atom_scope': 'whole_interface', 'VACF_transform': 'squared_again', 'frequency_offset_cm-1': -50, 'full_convolution_alignment': 'not_corrected'}
            for key, value in expected_diagnostics.items():
                if diagnostic.get(key) != value:
                    raise ValueError('script_diagnostics.' + key + ' incorrect')
            if not {'systems', 'claims'} <= set(peaks) or set(peaks['systems']) != set(_bench38_0_SYSTEMS):
                raise ValueError('peak system set')
            selections = _bench38_0_canonical_selections(metadata, source)
            rows = list(csv.DictReader((out / 'spectra.csv').open()))
            if {r['system'] for r in rows} != set(_bench38_0_SYSTEMS):
                raise ValueError('spectrum system set')
            for name in _bench38_0_SYSTEMS:
                local_metadata = dict(metadata)
                local_metadata['selection'] = selections
                wave, power, modes = _bench38_0_spectrum_expected(data, source, name, local_metadata)
                series = [r for r in rows if r['system'] == name]
                _bench38_0_validate_spectrum([_bench38_0_number(float(r['wavenumber_cm-1'])) for r in series], [_bench38_0_number(float(r['power_arb'])) for r in series], wave, power)
                _bench38_0_validate_modes(peaks['systems'][name], modes, wave, power)
            pending_review = _bench38_0_check_arguments(peaks['claims'], _bench38_0_spectrum_rubric(), {'metadata': metadata, 'peaks': peaks['systems']})
            _bench38_0_check_report_and_code(out, peaks['claims'])
    except _bench38_0_EquivalenceReviewRequired:
        return equivalence_review(root, out, refs)
    except Exception as exc:
        errors.append(type(exc).__name__ + ': ' + str(exc))
    if not errors and '--replay-result' not in sys.argv:
        science_files = ['robustness.json'] if refs['mode'] == 'potential' else ['spectra.csv', 'peaks.json', 'metadata.json']
        result = _bench38_1_replay(root, out, science_files, normalize_json=_bench38_0_normalize_replay_json, attachments=['analysis.py', 'report.md'])
        if result['status'] == 'ENVIRONMENT_ERROR':
            print(json.dumps(result, ensure_ascii=False))
            return 2
        if result['status'] == 'REVIEW_REQUIRED':
            pending_review.append(result.get('reason', 'replayed scientific claim wording requires review'))
        elif result['status'] != 'PASS':
            errors.append(result['error'])
    if not errors and pending_review:
        print(json.dumps({'status': 'REVIEW_REQUIRED', 'reason': '; '.join(pending_review)}, ensure_ascii=False))
        return 2
    print(json.dumps({'status': 'FAIL' if errors else 'PASS', 'reward': 0 if errors else 1, 'verification_coverage': 'COMPLETE', 'errors': errors}, ensure_ascii=False))
    return 1 if errors else 0
if __name__ == '__main__':
    sys.exit(main())
