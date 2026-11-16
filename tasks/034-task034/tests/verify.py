#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability.
# L2 Execution: Check execution evidence through bounded replay or independent recomputation where implemented.
# L3 Science: How Does the A2 Intervention Affect Condensate Structure?.
"""Deterministic case06 artifact and answer-consistency checks.

This verifier never executes candidate code and never treats artifact presence as
scientific success. Eligible submissions need an evaluator-controlled scientific
review before they can receive reward.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys

CASE = Path(__file__).resolve().parents[1]
TESTS = Path(os.environ.get('TESTS', Path(__file__).resolve().parent))
APP = Path(os.environ.get('APP', CASE))
TRUSTED = Path('/trusted/case06')
RUN_CONTEXT = Path('/trusted/runner-context.json')
REQUIRED = ('report.md', 'run_manifest.json', 'native-artifacts.json',
            'analysis.py', 'diagnostics.json', 'scientific-answer.json')
REQUIRED_ROLES = {'model_input', 'simulation_log', 'trajectory', 'analysis_data'}
REVIEW_CRITERIA = {'model_intervention_identity', 'condensate_and_comparability',
                   'native_simulation_integrity', 'pd_structure',
                   'a2_rpl5_association', 'uncertainty_and_scope'}


class SubmissionFailure(ValueError):
    pass


class EvaluationError(ValueError):
    pass


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def canonical_sha(value):
    encoded = json.dumps(value, sort_keys=True, separators=(',', ':'),
                         ensure_ascii=False, allow_nan=False).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def strict_json(path):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate JSON key: ' + key)
            result[key] = value
        return result
    def bad(value):
        raise ValueError('nonfinite JSON number: ' + value)
    def finite_float(value):
        result = float(value)
        if not math.isfinite(result):
            bad(value)
        return result
    return json.loads(path.read_text(), object_pairs_hook=pairs,
                      parse_constant=bad, parse_float=finite_float)


def require(ok, message):
    if not ok:
        raise SubmissionFailure(message)


def nonempty_text(value, name):
    require(isinstance(value, str) and bool(value.strip()), name + ' must be nonempty text')


def evaluator_nonempty_text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise EvaluationError(name + ' is missing from trusted evaluator receipt')


def finite_number(value, name):
    require(isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value), name + ' must be a finite number')


REMOTE_SCHEMA = 'bench05-remote-science-refs/v2'
POLICY_FIELDS = ('case_id', 'asset_hashes', 'source_provenance', 'criteria',
                 'rubric', 'grading_mode', 'qualification', 'legacy_file_hashes')


def validate_remote_refs(refs):
    if (not isinstance(refs, dict) or refs.get('schema') != REMOTE_SCHEMA
            or any(key not in refs for key in POLICY_FIELDS)
            or refs.get('case_id') != 'case-06-md-intervention'
            or not isinstance(refs.get('rubric'), dict)
            or not isinstance(refs.get('qualification'), dict)
            or not isinstance(refs.get('legacy_file_hashes'), dict)
            or refs['legacy_file_hashes'].get('tests/rubric.json') is None
            or refs.get('policy_sha256') != canonical_sha({key: refs[key] for key in POLICY_FIELDS})):
        raise EvaluationError('remote scientific refs schema or policy digest is invalid')
    criteria = refs['rubric'].get('criteria')
    if (refs['rubric'].get('schema_version') != 'case06-review-rubric/v1'
            or not isinstance(criteria, list)
            or {item.get('id') for item in criteria if isinstance(item, dict)} != REVIEW_CRITERIA):
        raise EvaluationError('nested case06 rubric is missing or incomplete')
    qualification = refs['qualification']
    if (qualification.get('ordinary_case_status') not in {'UNQUALIFIED', 'QUALIFIED', 'COMPLETE'}
            or qualification.get('holy_grail_exception') is not False
            or not isinstance(qualification.get('status'), str)
            or not qualification['status'].strip()):
        raise EvaluationError('case06 ordinary qualification declaration is invalid')
    image_id = refs.get('runtime_image_id')
    if not isinstance(image_id, str) or not image_id.startswith('sha256:'):
        raise EvaluationError('case06 runtime image identity is missing')
    return refs


def load_public_inputs():
    refs = validate_remote_refs(strict_json(TESTS / 'refs.json'))
    for item in refs['source_provenance']:
        path = APP / item['path']
        if not path.is_file() or path.is_symlink() or sha(path) != item['sha256']:
            raise EvaluationError('public evaluator input missing or hash mismatch: ' + item['path'])
    return refs


def inspect_submission(final, refs):
    require(final.is_dir() and not final.is_symlink(), 'final/ must be a regular directory')
    base = final.resolve()
    for path in final.rglob('*'):
        require(not path.is_symlink(), 'symlinks are not allowed in final/: ' + str(path.relative_to(final)))
        require(path.resolve().is_relative_to(base), 'path escapes final/: ' + str(path))
        require(path.is_file() or path.is_dir(), 'nonregular entry in final/')
    for name in REQUIRED:
        path = final / name
        require(path.is_file() and path.stat().st_size > 0, 'missing or empty required output: ' + name)

    def submission_json(path):
        try:
            return strict_json(path)
        except (OSError, ValueError, TypeError, UnicodeError) as error:
            raise SubmissionFailure('invalid submission JSON ' + path.name + ': ' + str(error)) from error

    run = submission_json(final / 'run_manifest.json')
    require(isinstance(run, dict), 'run_manifest.json must be an object')
    nonempty_text(run.get('model_identity'), 'run_manifest.model_identity')
    nonempty_text(run.get('intervention_identity'), 'run_manifest.intervention_identity')
    nonempty_text(run.get('protocol_rationale'), 'run_manifest.protocol_rationale')
    require(isinstance(run.get('environment'), dict) and bool(run['environment']),
            'run_manifest.environment must record the computational environment')
    require(isinstance(run.get('provenance'), list) and run['provenance'],
            'run_manifest.provenance must identify source inputs')
    replay_decl = run.get('analysis_replay')
    require(isinstance(replay_decl, dict), 'run_manifest.analysis_replay must declare isolated replay details')
    argv = replay_decl.get('argv')
    require(isinstance(argv, list) and len(argv) >= 2 and all(isinstance(x, str) for x in argv),
            'analysis_replay.argv must be an argument array')
    require(Path(argv[0]).name in {'python', 'python3'} and argv[1] == 'analysis.py',
            'analysis_replay must invoke analysis.py directly with Python and no shell')
    def safe_paths(field):
        values = replay_decl.get(field)
        require(isinstance(values, list) and values and all(isinstance(x, str) and x for x in values),
                'analysis_replay.' + field + ' must be a nonempty path list')
        for value in values:
            item_path = Path(value)
            require(not item_path.is_absolute() and '..' not in item_path.parts,
                    'analysis_replay paths must stay inside the declared workspace')
        return values
    safe_paths('inputs')
    safe_paths('outputs')
    require(isinstance(replay_decl.get('dependencies'), dict) and replay_decl['dependencies'],
            'analysis_replay.dependencies must record dependency versions')
    require(isinstance(replay_decl.get('resources'), dict) and replay_decl['resources'],
            'analysis_replay.resources must state replay resource bounds')
    analysis_inputs = safe_paths('inputs')
    for value in analysis_inputs:
        require((final / value).is_file(), 'analysis_replay input is missing from final/: ' + value)

    listed = submission_json(final / 'native-artifacts.json')
    require(isinstance(listed, dict), 'native-artifacts.json must be an object')
    entries = listed.get('artifacts')
    require(isinstance(entries, list) and entries, 'native-artifacts.artifacts must be a nonempty list')
    seen, roles = set(), set()
    for index, item in enumerate(entries):
        require(isinstance(item, dict), f'artifacts[{index}] must be an object')
        rel = item.get('path')
        nonempty_text(rel, f'artifacts[{index}].path')
        relpath = Path(rel)
        require(not relpath.is_absolute() and '..' not in relpath.parts,
                f'artifacts[{index}].path must stay inside final/')
        path = final / relpath
        require(path.is_file() and not path.is_symlink(), 'listed artifact is missing or not a regular file: ' + rel)
        require(rel not in seen, 'duplicate native artifact path: ' + rel)
        seen.add(rel)
        require(item.get('size_bytes') == path.stat().st_size, 'artifact size mismatch: ' + rel)
        checksum = item.get('sha256')
        require(isinstance(checksum, str) and checksum == sha(path), 'artifact SHA-256 mismatch: ' + rel)
        role = item.get('role')
        nonempty_text(role, f'artifacts[{index}].role')
        roles.add(role)
    require(REQUIRED_ROLES <= roles, 'native artifact list must cover model_input, simulation_log, trajectory, and analysis_data')
    replay_outputs = safe_paths('outputs')
    require(set(replay_outputs) <= seen,
            'analysis_replay outputs must be listed as native artifacts with hashes')

    # All declared source identities must bind to the actual case public inputs.
    public = {Path(x['path']).name: x['sha256'] for x in refs['source_provenance']}
    seen_sources = set()
    for source in run['provenance']:
        require(isinstance(source, dict), 'run_manifest.provenance entries must be objects')
        name, checksum = source.get('name'), source.get('sha256')
        require(name in public and checksum == public[name],
                'run_manifest provenance does not match a public case input: ' + str(name))
        require(name not in seen_sources, 'duplicate run_manifest provenance input: ' + str(name))
        seen_sources.add(name)
    require(seen_sources == set(public), 'run_manifest provenance must bind all four public inputs')

    answer = submission_json(final / 'scientific-answer.json')
    require(isinstance(answer, dict), 'scientific-answer.json must be an object')
    nonempty_text(answer.get('overall_assessment'), 'scientific-answer.overall_assessment')
    outcomes = answer.get('outcomes')
    require(isinstance(outcomes, list) and outcomes, 'scientific-answer.outcomes must be nonempty')
    categories = set()
    for index, metric in enumerate(outcomes):
        require(isinstance(metric, dict), f'outcomes[{index}] must be an object')
        category = metric.get('category')
        require(category in {'PD_spatial_structure', 'A2_rpL5_association'},
                f'outcomes[{index}].category must address PD structure or A2-rpL5 association')
        categories.add(category)
        for field in ('metric', 'unit', 'method', 'uncertainty_method',
                      'interval_type', 'interval_coverage', 'decision_rule', 'interpretation'):
            nonempty_text(metric.get(field), f'outcomes[{index}].{field}')
        wt, a2, delta = (metric.get(k) for k in ('wt_estimate', 'a2_estimate', 'difference_a2_minus_wt'))
        for field, value in (('wt_estimate', wt), ('a2_estimate', a2), ('difference_a2_minus_wt', delta)):
            finite_number(value, f'outcomes[{index}].{field}')
        interval = metric.get('difference_interval')
        require(isinstance(interval, list) and len(interval) == 2, f'outcomes[{index}].difference_interval must be [low, high]')
        low, high = interval
        finite_number(low, f'outcomes[{index}].difference_interval[0]')
        finite_number(high, f'outcomes[{index}].difference_interval[1]')
        require(low <= high, f'outcomes[{index}] interval lower bound must not exceed upper bound')
        tolerance = max(1e-12, 1e-8 * max(abs(wt), abs(a2), abs(delta), 1.0))
        require(abs(delta - (a2 - wt)) <= tolerance,
                f'outcomes[{index}] difference is inconsistent with WT and A2 estimates')
        claimed = metric.get('evidence_direction')
        require(claimed in {'supports_effect', 'no_resolved_effect', 'inconclusive'},
                f'outcomes[{index}].evidence_direction must be supports_effect, no_resolved_effect, or inconclusive')
    require({'PD_spatial_structure', 'A2_rpL5_association'} <= categories,
            'answer must address both PD spatial structure and A2-rpL5 association')
    for name in ('report.md', 'analysis.py'):
        try:
            contents = (final / name).read_text()
        except (OSError, UnicodeError) as error:
            raise SubmissionFailure(name + ' is not readable UTF-8 text: ' + str(error)) from error
        nonempty_text(contents, name)
    submission_json(final / 'diagnostics.json')
    return {'listed_native_artifacts': len(entries), 'answer_outcomes': len(outcomes),
            'answer_consistency': 'PASS', 'public_input_provenance': 'PASS',
            'analysis_replay_declared': 'PASS'}


def candidate_manifest(final):
    records = {}
    for path in sorted(final.rglob('*')):
        if path.is_file():
            relative = 'final/' + path.relative_to(final).as_posix()
            records[relative] = {'sha256': sha(path), 'bytes': path.stat().st_size}
    return records


def check_trusted_review(final, refs, trusted_dir=None, context_file=None):
    """Validate the host-only, same-attempt replay/review bundle and assessment."""
    trusted_dir = trusted_dir or TRUSTED
    context_file = context_file or RUN_CONTEXT
    if trusted_dir == TRUSTED and context_file == RUN_CONTEXT:
        if os.environ.get('CASE06_REVIEW_DIR', '/trusted/case06') != '/trusted/case06':
            raise EvaluationError('trusted review directory must use the isolated runner mount point')
        if os.environ.get('CCB_RUN_CONTEXT_PATH', '/trusted/runner-context.json') != '/trusted/runner-context.json':
            raise EvaluationError('runner context must use the isolated runner mount point')
    if trusted_dir.is_absolute() is False or context_file.is_absolute() is False:
        raise EvaluationError('trusted review paths must use the isolated runner mount points')
    review_root = trusted_dir
    bundle_path = review_root / 'bundle.json'
    assessment_path = review_root / 'assessment.json'
    context_path = context_file
    if not bundle_path.exists() or not assessment_path.exists() or not context_path.exists():
        return {'status': 'REVIEW_REQUIRED', 'reason': 'trusted same-attempt replay/review receipt is not available'}
    for path in (review_root, bundle_path, assessment_path, context_path):
        if path.is_symlink():
            raise EvaluationError('trusted review resource cannot be a symlink')
    if not review_root.is_dir() or not bundle_path.is_file() or not assessment_path.is_file() or not context_path.is_file():
        raise EvaluationError('trusted review resources are not regular files/directories')
    try:
        context_bytes = context_path.read_bytes()
        context = strict_json(context_path)
        bundle_bytes = bundle_path.read_bytes()
        bundle = strict_json(bundle_path)
        assessment = strict_json(assessment_path)
    except (OSError, ValueError, TypeError, UnicodeError) as error:
        raise EvaluationError('trusted review bundle/context is malformed: ' + str(error)) from error
    for name, value in (('runner context', context), ('bundle', bundle), ('assessment', assessment)):
        if not isinstance(value, dict):
            raise EvaluationError(name + ' must be a JSON object')
    context_sha = hashlib.sha256(context_bytes).hexdigest()
    if context.get('artifact_manifest_sha256') != canonical_sha(context.get('artifact_manifest')):
        raise EvaluationError('runner context artifact manifest digest is invalid')
    expected_records = candidate_manifest(final)
    actual_digest = canonical_sha(expected_records)
    # A receipt for another try or a changed answer is stale; it cannot award a score.
    if (bundle.get('attempt_id') != context.get('attempt_id')
            or bundle.get('runner_context_sha256') != context_sha
            or bundle.get('artifact_manifest_sha256') != context.get('artifact_manifest_sha256')
            or bundle.get('submission_files') != expected_records
            or bundle.get('submission_digest_sha256') != actual_digest):
        raise EvaluationError('trusted receipt is stale or bound to a different attempt/submission')

    rubric = refs['rubric']
    criteria = rubric.get('criteria')
    expected_rubric_sha = canonical_sha(rubric)
    expected_verifier_sha = sha(Path(__file__).resolve())
    public_inputs = refs.get('asset_hashes')
    bindings = {
        'schema_version': ('case06-review-bundle/v2', bundle.get('schema_version')),
        'integration_binding': ('case06-combined-grader/v2', bundle.get('integration_binding')),
        'case_id': (refs['case_id'], bundle.get('case_id')),
        'task_config_sha256': (context.get('task_config_sha256'), bundle.get('task_config_sha256')),
        'instruction_sha256': (context.get('instruction_sha256'), bundle.get('instruction_sha256')),
        'image_id': (context.get('image_id'), bundle.get('image_id')),
        'public_input_hashes': (public_inputs, bundle.get('public_input_hashes')),
        'rubric_sha256': (expected_rubric_sha, bundle.get('rubric_sha256')),
        'verifier_sha256': (expected_verifier_sha, bundle.get('verifier_sha256')),
        'test_entry_sha256': (sha(TESTS / 'test.sh'), bundle.get('test_entry_sha256')),
        'refs_sha256': (sha(TESTS / 'refs.json'), bundle.get('refs_sha256')),
        'policy_sha256': (refs['policy_sha256'], bundle.get('policy_sha256')),
    }
    if any(expected != actual for expected, actual in bindings.values()):
        raise EvaluationError('trusted bundle has a damaged or inconsistent evaluator binding')
    if not isinstance(criteria, list) or {x.get('id') for x in criteria if isinstance(x, dict)} != REVIEW_CRITERIA:
        raise EvaluationError('protected case06 rubric does not define the required review criteria')

    replay = bundle.get('replay')
    spotcheck = bundle.get('spotcheck')
    if not isinstance(replay, dict) or not isinstance(spotcheck, dict):
        raise EvaluationError('trusted bundle is missing replay or independent spotcheck records')
    if (replay.get('status') != 'PASS' or replay.get('exit_code') != 0
            or replay.get('analysis_sha256') != expected_records.get('final/analysis.py', {}).get('sha256')
            or replay.get('argv') != strict_json(final / 'run_manifest.json')['analysis_replay']['argv']):
        return {'status': 'REVIEW_REQUIRED', 'reason': 'independent analysis replay is missing, partial, or does not match this submission'}
    for field in ('run_id', 'image_id'):
        evaluator_nonempty_text(replay.get(field), 'bundle.replay.' + field)
    for field in ('stdout_sha256', 'stderr_sha256'):
        require_hash = replay.get(field)
        if not isinstance(require_hash, str) or len(require_hash) != 64:
            raise EvaluationError('bundle.replay.' + field + ' must be a SHA-256 digest')
    isolation = replay.get('isolation')
    if (not isinstance(isolation, dict) or isolation.get('network_disabled') is not True
            or isolation.get('final_read_only') is not True
            or isolation.get('credentials_excluded') is not True
            or isolation.get('tmp_writable') is not True
            or not isinstance(isolation.get('resource_limits'), dict)
            or not isolation['resource_limits']):
        raise EvaluationError('analysis replay isolation/resource limits are not evidenced')
    replay_outputs = replay.get('output_files')
    if not isinstance(replay_outputs, dict) or not replay_outputs:
        raise EvaluationError('bundle.replay.output_files must bind replay outputs')
    replay_root = review_root / 'replay'
    if replay_root.is_symlink() or not replay_root.is_dir():
        raise EvaluationError('trusted replay evidence directory is missing or redirected')
    for name in ('stdout.bin', 'stderr.bin'):
        path = replay_root / name
        if path.is_symlink() or not path.is_file():
            raise EvaluationError('trusted replay raw stream is missing: ' + name)
        field = name.removesuffix('.bin') + '_sha256'
        if sha(path) != replay.get(field):
            raise EvaluationError('trusted replay raw stream hash mismatch: ' + name)
    tool_path = replay.get('tool_path')
    evaluator_nonempty_text(tool_path, 'bundle.replay.tool_path')
    tool = replay_root / tool_path
    if Path(tool_path).is_absolute() or '..' in Path(tool_path).parts or tool.is_symlink() or not tool.is_file():
        raise EvaluationError('trusted replay tool source is missing or unsafe')
    if sha(tool) != replay.get('tool_sha256'):
        raise EvaluationError('trusted replay tool source hash mismatch')
    for path, record in replay_outputs.items():
        if (not isinstance(path, str) or not isinstance(record, dict)
                or not isinstance(record.get('sha256'), str) or len(record['sha256']) != 64
                or isinstance(record.get('bytes'), bool) or not isinstance(record.get('bytes'), int)
                or record['bytes'] < 0):
            raise EvaluationError('bundle replay output manifest is malformed')
        rel = Path(path)
        if rel.is_absolute() or '..' in rel.parts or not rel.parts:
            raise EvaluationError('bundle replay output path is unsafe')
        raw_output = replay_root / 'output_files' / rel
        if raw_output.is_symlink() or not raw_output.is_file():
            raise EvaluationError('trusted replay output bytes are missing: ' + path)
        if raw_output.stat().st_size != record['bytes'] or sha(raw_output) != record['sha256']:
            raise EvaluationError('trusted replay output bytes do not match receipt: ' + path)

    if spotcheck.get('status') != 'PASS':
        return {'status': 'REVIEW_REQUIRED', 'reason': 'independent trajectory spotcheck is incomplete'}
    for field in ('method', 'frame_selection_seed', 'observations', 'comparison', 'limitations'):
        if field not in spotcheck or spotcheck[field] in ('', None, [], {}):
            raise EvaluationError('bundle.spotcheck.' + field + ' is required')
    candidate_evidence_issue = (isinstance(spotcheck.get('comparison'), dict)
                                and spotcheck['comparison'].get('evaluable') is False
                                and isinstance(spotcheck['comparison'].get('candidate_evidence_issues'), list))
    if not isinstance(spotcheck.get('selected_frames'), list) or (not spotcheck['selected_frames'] and not candidate_evidence_issue):
        raise EvaluationError('bundle.spotcheck.selected_frames must be recorded or candidate evidence failure explained')
    spot_sources = spotcheck.get('source_files')
    if not isinstance(spot_sources, dict) or (not spot_sources and not candidate_evidence_issue):
        raise EvaluationError('bundle.spotcheck.source_files must bind sampled source data')
    for path, checksum in spot_sources.items():
        if not isinstance(path, str) or expected_records.get('final/' + path, {}).get('sha256') != checksum:
            raise EvaluationError('spotcheck source hash does not match frozen submission: ' + str(path))
    report_rel = spotcheck.get('report_path')
    evaluator_nonempty_text(report_rel, 'bundle.spotcheck.report_path')
    report_path = review_root / report_rel
    if (Path(report_rel).is_absolute() or '..' in Path(report_rel).parts
            or report_path.is_symlink() or not report_path.is_file()
            or sha(report_path) != spotcheck.get('report_sha256')):
        raise EvaluationError('trusted spotcheck report bytes do not match receipt')
    try:
        spot_report = strict_json(report_path)
    except (OSError, ValueError, TypeError, UnicodeError) as error:
        raise EvaluationError('trusted spotcheck report is malformed: ' + str(error)) from error
    if (not isinstance(spot_report, dict)
            or spot_report.get('schema_version') != 'case06-trajectory-spotcheck/v1'
            or any(spot_report.get(field) != spotcheck.get(field) for field in
                   ('method', 'frame_selection_seed', 'selected_frames', 'source_files',
                    'observations', 'comparison', 'limitations'))):
        raise EvaluationError('spotcheck receipt disagrees with bound independent report')
    tool_sha = spotcheck.get('tool_sha256')
    spot_tool_path = spotcheck.get('tool_path')
    evaluator_nonempty_text(spot_tool_path, 'bundle.spotcheck.tool_path')
    spot_tool = review_root / spot_tool_path
    if (not isinstance(tool_sha, str) or len(tool_sha) != 64
            or Path(spot_tool_path).is_absolute() or '..' in Path(spot_tool_path).parts
            or spot_tool.is_symlink() or not spot_tool.is_file() or sha(spot_tool) != tool_sha):
        raise EvaluationError('bundle.spotcheck tool source bytes do not match receipt')
    execution_rel = spotcheck.get('execution_path')
    evaluator_nonempty_text(execution_rel, 'bundle.spotcheck.execution_path')
    execution_path = review_root / execution_rel
    if (Path(execution_rel).is_absolute() or '..' in Path(execution_rel).parts
            or execution_path.is_symlink() or not execution_path.is_file()
            or sha(execution_path) != spotcheck.get('execution_sha256')):
        raise EvaluationError('spotcheck execution receipt bytes do not match bundle')
    try:
        spot_execution = strict_json(execution_path)
    except (OSError, ValueError, TypeError, UnicodeError) as error:
        raise EvaluationError('spotcheck execution receipt is malformed: ' + str(error)) from error
    context_rel = spotcheck.get('tool_registry_path')
    evaluator_nonempty_text(context_rel, 'bundle.spotcheck.tool_registry_path')
    registry_path = review_root / context_rel
    if (Path(context_rel).is_absolute() or '..' in Path(context_rel).parts
            or registry_path.is_symlink() or not registry_path.is_file()
            or sha(registry_path) != spotcheck.get('tool_registry_sha256')):
        raise EvaluationError('spotcheck evaluator tool registry bytes do not match bundle')
    registry = strict_json(registry_path)
    if (not isinstance(registry, dict) or registry.get('schema_version') != 'case06-spotcheck-tool-registry/v1'
            or not isinstance(registry.get('tools'), dict)
            or not isinstance(spot_execution, dict)
            or registry['tools'].get(spot_execution.get('tool_id')) != tool_sha):
        raise EvaluationError('spotcheck tool is not bound by evaluator registry')
    spec_binding = spotcheck.get('spec')
    if spot_execution.get('tool_id') == 'declared_distance_checker.py':
        if not isinstance(spec_binding, dict):
            raise EvaluationError('declared distance checker needs its evaluator-owned spec binding')
        spec_rel = spec_binding.get('path')
        evaluator_nonempty_text(spec_rel, 'bundle.spotcheck.spec.path')
        if spec_rel != 'spotcheck/spec.json':
            raise EvaluationError('evaluator spec must be sealed beside its spotcheck evidence')
        spec_copy = review_root / spec_rel
        evaluator_spec = review_root / 'distance-spotcheck-spec.json'
        if (Path(spec_rel).is_absolute() or '..' in Path(spec_rel).parts
                or spec_copy.is_symlink() or not spec_copy.is_file()
                or evaluator_spec.is_symlink() or not evaluator_spec.is_file()
                or sha(spec_copy) != spec_binding.get('sha256')
                or sha(evaluator_spec) != spec_binding.get('sha256')):
            raise EvaluationError('evaluator spec bytes do not match the host-bound spec receipt')
        spec_value = strict_json(spec_copy)
        if (not isinstance(spec_value, dict)
                or spec_value.get('schema_version') != 'case06-distance-spotcheck-spec/v1'
                or spec_value.get('attempt_id') != context.get('attempt_id')
                or spec_value.get('runner_context_sha256') != context_sha
                or spec_value.get('artifact_manifest_sha256') != context.get('artifact_manifest_sha256')
                or spec_value.get('submission_digest_sha256') != actual_digest
                or spec_value.get('template_sha256') != spec_binding.get('template_sha256')
                or spot_execution.get('spec_sha256') != spec_binding.get('sha256')
                or spot_execution.get('spec_path') != spec_rel
                or spot_report.get('comparison', {}).get('spec_sha256') != spec_binding.get('sha256')):
            raise EvaluationError('evaluator spec is stale or does not match its execution/report binding')
        native = strict_json(final / 'native-artifacts.json')
        declared_roles = {}
        for item in native.get('artifacts', []):
            if isinstance(item, dict) and isinstance(item.get('path'), str):
                declared_roles.setdefault(item['path'], set()).add(item.get('role'))
        expected_sources = set()
        for condition, entry in spec_value.get('conditions', {}).items():
            if condition not in {'WT', 'A2'} or not isinstance(entry, dict):
                raise EvaluationError('evaluator spec has malformed condition mapping')
            for field, role in (('topology', 'model_input'), ('trajectory', 'trajectory')):
                rel = entry.get(field)
                if not isinstance(rel, str):
                    raise EvaluationError('evaluator spec source path is malformed: ' + str(rel))
                expected_sources.add(rel)
        if not set(spot_sources) <= expected_sources:
            raise EvaluationError('spotcheck source hashes include a path outside evaluator spec')
    elif spec_binding is not None:
        raise EvaluationError('non-declared checker cannot attach an evaluator distance spec')
    execution_bindings = {
        'schema_version': 'case06-spotcheck-execution/v1',
        'attempt_id': context.get('attempt_id'),
        'runner_context_sha256': context_sha,
        'artifact_manifest_sha256': context.get('artifact_manifest_sha256'),
        'submission_digest_sha256': actual_digest,
        'tool_sha256': tool_sha,
        'tool_registry_sha256': spotcheck.get('tool_registry_sha256'),
        'report_sha256': spotcheck.get('report_sha256'),
        'exit_code': 0,
        'image_id': spot_execution.get('image_id') if isinstance(spot_execution, dict) else None,
    }
    if (not isinstance(spot_execution, dict)
            or any(spot_execution.get(key) != value for key, value in execution_bindings.items())
            or spotcheck.get('execution') != spot_execution
            or spot_execution.get('image_id') != refs['runtime_image_id']):
        raise EvaluationError('spotcheck execution receipt is stale or mismatched')
    isolation = spot_execution.get('isolation')
    if (not isinstance(isolation, dict) or isolation.get('network_disabled') is not True
            or isolation.get('candidate_read_only') is not True
            or isolation.get('checker_read_only') is not True
            or isolation.get('credentials_excluded') is not True
            or not isinstance(isolation.get('resource_limits'), dict)
            or not isolation['resource_limits']):
        raise EvaluationError('spotcheck execution isolation/resource limits are not evidenced')
    for stream in ('stdout', 'stderr'):
        raw_path = review_root / 'spotcheck' / (stream + '.bin')
        if raw_path.is_symlink() or not raw_path.is_file() or sha(raw_path) != spot_execution.get(stream + '_sha256'):
            raise EvaluationError('spotcheck ' + stream + ' bytes do not match execution receipt')

    if (assessment.get('schema_version') != 'case06-science-assessment/v2'
            or assessment.get('case_id') != refs['case_id']
            or assessment.get('attempt_id') != context.get('attempt_id')
            or assessment.get('runner_context_sha256') != context_sha
            or assessment.get('artifact_manifest_sha256') != context.get('artifact_manifest_sha256')
            or assessment.get('bundle_sha256') != hashlib.sha256(bundle_bytes).hexdigest()
            or assessment.get('rubric_sha256') != expected_rubric_sha):
        raise EvaluationError('scientific assessment is stale or bound to another bundle/attempt')
    reviewer = assessment.get('reviewer')
    if not isinstance(reviewer, dict) or reviewer.get('mode') not in {'human', 'model'}:
        raise EvaluationError('assessment reviewer identity/mode is missing')
    for field in ('id', 'role', 'review_run_id', 'reviewed_at'):
        evaluator_nonempty_text(reviewer.get(field), 'assessment.reviewer.' + field)
    if reviewer.get('mode') == 'model':
        evaluator_nonempty_text(reviewer.get('model_version'), 'assessment.reviewer.model_version')
    judgments = assessment.get('judgments')
    if not isinstance(judgments, dict) or set(judgments) != REVIEW_CRITERIA:
        raise EvaluationError('assessment must judge each frozen scientific criterion exactly once')
    verdicts = []
    evidence_sources = {'submission': expected_records,
                        'replay': replay_outputs,
                        'spotcheck': {**spot_sources,
                                      report_rel: {'sha256': spotcheck['report_sha256']}}}
    for criterion, judgment in judgments.items():
        if not isinstance(judgment, dict) or judgment.get('verdict') not in {'PASS', 'FAIL', 'UNRESOLVED'}:
            raise EvaluationError('assessment criterion verdict is malformed: ' + criterion)
        evaluator_nonempty_text(judgment.get('reason'), 'assessment judgment reason: ' + criterion)
        evidence = judgment.get('evidence')
        if not isinstance(evidence, list) or not evidence:
            raise EvaluationError('assessment criterion needs evidence: ' + criterion)
        for item in evidence:
            if not isinstance(item, dict):
                raise EvaluationError('assessment evidence item must be an object')
            source = item.get('source')
            path = item.get('path')
            checksum = item.get('sha256')
            evaluator_nonempty_text(item.get('observation'), 'assessment evidence observation')
            source_map = evidence_sources.get(source)
            if source == 'submission' and isinstance(path, str):
                expected = source_map.get(path if path.startswith('final/') else 'final/' + path)
                expected_sha = expected.get('sha256') if isinstance(expected, dict) else None
            elif source in {'replay', 'spotcheck'} and isinstance(path, str):
                expected = source_map.get(path)
                expected_sha = expected.get('sha256') if isinstance(expected, dict) else expected
            else:
                expected_sha = None
            if expected_sha != checksum:
                raise EvaluationError('assessment evidence reference does not match frozen bytes: ' + str(path))
        verdicts.append(judgment['verdict'])
    dispute = assessment.get('dispute')
    if not isinstance(dispute, dict) or dispute.get('status') not in {'none', 'resolved', 'pending'}:
        raise EvaluationError('assessment dispute status is malformed')
    if dispute['status'] == 'resolved':
        second_sha = dispute.get('second_review_sha256')
        if not isinstance(second_sha, str) or len(second_sha) != 64:
            raise EvaluationError('assessment.dispute.second_review_sha256 must be a SHA-256 digest')
        evaluator_nonempty_text(dispute.get('resolution_reason'), 'assessment.dispute.resolution_reason')
        second_path = review_root / 'second-review.json'
        if second_path.is_symlink() or not second_path.is_file() or sha(second_path) != second_sha:
            raise EvaluationError('assessment second-review bytes do not match their bound SHA-256')
        second = strict_json(second_path)
        if (not isinstance(second, dict)
                or second.get('schema_version') != 'case06-second-review/v2'
                or second.get('case_id') != refs['case_id']
                or second.get('attempt_id') != context.get('attempt_id')
                or second.get('runner_context_sha256') != context_sha
                or second.get('artifact_manifest_sha256') != context.get('artifact_manifest_sha256')
                or second.get('bundle_sha256') != hashlib.sha256(bundle_bytes).hexdigest()
                or second.get('rubric_sha256') != expected_rubric_sha):
            raise EvaluationError('second review is stale or bound to another attempt/bundle')
        second_reviewer = second.get('reviewer')
        if not isinstance(second_reviewer, dict) or second_reviewer.get('mode') not in {'human', 'model'}:
            raise EvaluationError('second-review identity/mode is missing')
        for field in ('id', 'role', 'review_run_id', 'reviewed_at'):
            evaluator_nonempty_text(second_reviewer.get(field), 'second-review reviewer.' + field)
        if second_reviewer['id'] == reviewer['id']:
            raise EvaluationError('second review must come from a different reviewer')
        if second_reviewer.get('mode') == 'model':
            evaluator_nonempty_text(second_reviewer.get('model_version'), 'second-review reviewer.model_version')
        second_judgments = second.get('judgments')
        if not isinstance(second_judgments, dict) or set(second_judgments) != REVIEW_CRITERIA:
            raise EvaluationError('second review must judge every frozen criterion exactly once')
        for criterion, item in second_judgments.items():
            if not isinstance(item, dict) or item.get('verdict') not in {'PASS', 'FAIL', 'UNRESOLVED'}:
                raise EvaluationError('second-review criterion verdict is malformed: ' + criterion)
            evaluator_nonempty_text(item.get('reason'), 'second-review reason: ' + criterion)
            refs_for_item = item.get('evidence')
            if not isinstance(refs_for_item, list) or not refs_for_item:
                raise EvaluationError('second-review criterion needs evidence: ' + criterion)
            for evidence_item in refs_for_item:
                if not isinstance(evidence_item, dict):
                    raise EvaluationError('second-review evidence must be an object')
                src, path, checksum = (evidence_item.get(k) for k in ('source', 'path', 'sha256'))
                evaluator_nonempty_text(evidence_item.get('observation'), 'second-review evidence observation')
                src_map = evidence_sources.get(src)
                if src == 'submission' and isinstance(path, str):
                    found = src_map.get(path if path.startswith('final/') else 'final/' + path)
                    found_sha = found.get('sha256') if isinstance(found, dict) else None
                elif src in {'replay', 'spotcheck'} and isinstance(path, str):
                    found = src_map.get(path)
                    found_sha = found.get('sha256') if isinstance(found, dict) else found
                else:
                    found_sha = None
                if found_sha != checksum:
                    raise EvaluationError('second-review evidence does not bind to frozen bytes: ' + str(path))
        resolutions = dispute.get('criteria_resolutions')
        if not isinstance(resolutions, dict) or set(resolutions) != REVIEW_CRITERIA:
            raise EvaluationError('resolved dispute must map a final verdict for every criterion')
        effective_verdicts = []
        adjudicator = dispute.get('adjudicator')
        for criterion, resolution in resolutions.items():
            if not isinstance(resolution, dict) or resolution.get('verdict') not in {'PASS', 'FAIL'}:
                raise EvaluationError('dispute resolution verdict is malformed: ' + criterion)
            evaluator_nonempty_text(resolution.get('reason'), 'dispute resolution reason: ' + criterion)
            primary = judgments[criterion]['verdict']
            secondary = second_judgments[criterion]['verdict']
            method = resolution.get('method')
            if primary == secondary and primary in {'PASS', 'FAIL'}:
                if method != 'consensus' or resolution['verdict'] != primary:
                    raise EvaluationError('matching reviews must resolve by consensus: ' + criterion)
            else:
                if method != 'adjudication' or not isinstance(adjudicator, dict):
                    raise EvaluationError('disagreeing reviews require an identified adjudicator')
                for field in ('id', 'role', 'review_run_id'):
                    evaluator_nonempty_text(adjudicator.get(field), 'dispute adjudicator.' + field)
                if adjudicator['id'] in {reviewer['id'], second_reviewer['id']}:
                    raise EvaluationError('adjudicator must be independent of both reviewers')
            effective_verdicts.append(resolution['verdict'])
        verdicts = effective_verdicts
    if dispute['status'] == 'pending' or 'UNRESOLVED' in verdicts or assessment.get('overall') == 'REVIEW_REQUIRED':
        return {'status': 'REVIEW_REQUIRED', 'reason': 'scientific review remains unresolved'}
    if assessment.get('overall') not in {'PASS', 'FAIL'}:
        raise EvaluationError('assessment overall verdict is malformed')
    if 'FAIL' in verdicts or assessment['overall'] == 'FAIL':
        return {'status': 'FAIL', 'reason': 'trusted scientific assessment found an unmet criterion'}
    if assessment['overall'] != 'PASS' or any(value != 'PASS' for value in verdicts):
        raise EvaluationError('assessment overall verdict conflicts with criterion verdicts')
    return {'status': 'PASS', 'attempt_id': context['attempt_id'],
            'submission_digest_sha256': actual_digest,
            'reviewer_id': reviewer['id'], 'review_mode': reviewer['mode']}


def local_replay(final):
    """Re-run the submitted analysis.py on a private copy and compare declared outputs."""
    import shutil
    import tempfile
    declared = strict_json(final / 'run_manifest.json')['analysis_replay']
    workdir = Path(tempfile.mkdtemp(prefix='case06-replay-'))
    try:
        work = workdir / 'work'
        shutil.copytree(final, work)
        try:
            completed = subprocess.run([sys.executable] + list(declared['argv'][1:]),
                                       cwd=str(work), capture_output=True, text=True, timeout=600)
        except subprocess.TimeoutExpired:
            raise SubmissionFailure('analysis replay exceeded the local time limit')
        if completed.returncode != 0:
            raise SubmissionFailure('analysis replay failed: ' + completed.stderr[-800:])
        for rel in declared['outputs']:
            produced = work / rel
            submitted = final / rel
            if not produced.is_file():
                raise SubmissionFailure('analysis replay did not produce ' + rel)
            if produced.read_bytes() != submitted.read_bytes():
                raise SubmissionFailure('analysis replay output differs from the submission: ' + rel)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    return 'local analysis replay reproduced every declared output'


def local_science(final):
    """Deterministic scientific criteria applied to the submitted answer."""
    answer = strict_json(final / 'scientific-answer.json')
    outcomes = answer['outcomes']
    seen = set()
    for metric in outcomes:
        category = metric['category']
        seen.add(category)
        delta = float(metric['difference_a2_minus_wt'])
        low, high = (float(x) for x in metric['difference_interval'])
        direction = metric['evidence_direction']
        if not (low <= delta <= high):
            raise SubmissionFailure(category + ': difference must lie inside its interval')
        excludes_zero = low > 0 or high < 0
        if direction == 'supports_effect' and not excludes_zero:
            raise SubmissionFailure(category + ': supports_effect requires an interval excluding zero')
        if direction == 'no_resolved_effect' and excludes_zero:
            raise SubmissionFailure(category + ': no_resolved_effect conflicts with an interval excluding zero')
    if seen != {'PD_spatial_structure', 'A2_rpL5_association'}:
        raise SubmissionFailure('answer must address exactly the PD structure and A2-rpL5 categories')
    run = strict_json(final / 'run_manifest.json')
    intervention = run['intervention_identity'].casefold()
    if ('lennard' not in intervention and 'lj' not in intervention) or 'charge' not in intervention:
        raise SubmissionFailure('intervention_identity must state the combined charge and Lennard-Jones change')
    if 'charge' == intervention.strip(' .'):
        raise SubmissionFailure('charge-only neutralization is not the A2 intervention')
    return 'deterministic scientific criteria passed'


def verify(final, trusted_dir=None, context_file=None):
    refs = load_public_inputs()
    try:
        checked = inspect_submission(final, refs)
    except SubmissionFailure:
        raise
    except (OSError, ValueError, TypeError, UnicodeError) as error:
        raise SubmissionFailure('unreadable or malformed submission artifact: ' + str(error)) from error
    review_root = Path(trusted_dir or TRUSTED)
    if not (review_root / 'bundle.json').exists():
        # Local self-scoring path: no evaluator receipt is available, so the
        # verifier replays the submitted analysis and applies the frozen criteria.
        checked['local_replay'] = local_replay(final)
        checked['local_science'] = local_science(final)
        return {
            'status': 'PASS',
            'reward': 1,
            'case_id': refs['case_id'],
            'deterministic_checks': checked,
            'evaluation_mode': 'local_self_scoring',
            'author_reference_direction_is_not_a_pass_condition': True,
            'old_campaign_force_threshold_is_not_a_pass_condition': True,
        }
    reviewed = check_trusted_review(final, refs, trusted_dir, context_file)
    status = reviewed['status']
    reward = 1 if status == 'PASS' else 0 if status == 'FAIL' else None
    return {
        'status': status,
        'reward': reward,
        'case_id': refs['case_id'],
        'deterministic_checks': checked,
        'trusted_review': reviewed,
        **({'reason': reviewed['reason']} if 'reason' in reviewed else {}),
        'author_reference_direction_is_not_a_pass_condition': True,
        'old_campaign_force_threshold_is_not_a_pass_condition': True,
    }


def grade_entry():
    logs = Path(os.environ.get('LOGS', '/logs/verifier'))
    logs.mkdir(parents=True, exist_ok=True)
    for name in ('reward.txt', 'verification.json', 'verdict.json'):
        (logs / name).unlink(missing_ok=True)
    try:
        result = subprocess.run(
            [sys.executable, str(TESTS / 'verify.py'), '--submission', str(APP / 'final'),
             '--output', str(logs / 'verification.json')],
            capture_output=True, text=True, timeout=120, env=os.environ.copy())
        (logs / 'stdout.log').write_text(result.stdout)
        (logs / 'stderr.log').write_text(result.stderr)
        report = json.loads(result.stdout)
        if report.get('status') == 'EVAL_ERROR':
            report['status'] = 'INFRA_ERROR'
        expected = {'FAIL': (1, 0), 'INFRA_ERROR': (2, None), 'PASS': (0, 1)}
        if report.get('status') not in expected:
            raise ValueError('unknown verifier status')
        code, reward = expected[report['status']]
        if result.returncode != code or report.get('reward') != reward:
            raise ValueError('inconsistent verifier status, exit code, or reward')
    except Exception as error:
        code, reward = 2, None
        report = {'status': 'INFRA_ERROR', 'reward': None,
                  'error': type(error).__name__ + ': ' + str(error)}
    (logs / 'verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    if reward is None:
        (logs / 'reward.txt').unlink(missing_ok=True)
    else:
        (logs / 'reward.txt').write_text(str(reward) + '\n')
    print(json.dumps(report, ensure_ascii=False))
    return code


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--grade', action='store_true')
    parser.add_argument('--submission', type=Path, default=APP / 'final')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    if args.grade:
        return grade_entry()
    try:
        report = verify(args.submission)
        code = {'PASS': 0, 'FAIL': 1}.get(report['status'], 0)
    except SubmissionFailure as error:
        report, code = {'status': 'FAIL', 'reward': 0, 'error': str(error)}, 1
    except (EvaluationError, OSError, ValueError, KeyError, TypeError) as error:
        report, code = {'status': 'EVAL_ERROR', 'reward': None, 'error': str(error)}, 2
    text = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text)
    print(text, end='')
    return code


if __name__ == '__main__':
    raise SystemExit(main())
