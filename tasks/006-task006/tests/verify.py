# 人工审核：自动检查结果供参考，科学结论需人工复核。
"""Open research evidence rubric. No automatic scientific acceptance is issued.

Candidate code is never executed; methods and source identities are unrestricted.
"""
from __future__ import annotations
import csv
import json
import math
import os
from pathlib import Path, PurePosixPath

VERSION = 'case06-open-research-evidence/v1'


class EvidenceError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise EvidenceError(message)


def text(value):
    return isinstance(value, str) and bool(value.strip())


def json_object(path):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, f'duplicate JSON key: {key}')
            result[key] = value
        return result
    def finite_float(raw):
        value = float(raw)
        require(math.isfinite(value), 'nonfinite JSON number')
        return value
    try:
        value = json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=pairs, parse_float=finite_float,
                           parse_constant=lambda s: (_ for _ in ()).throw(EvidenceError(f'nonfinite JSON: {s}')))
    except (OSError, UnicodeError, ValueError) as exc:
        raise EvidenceError(f'{path.name}: {exc}') from exc
    require(isinstance(value, dict), f'{path.name} must be an object')
    return value


def safe_file(final, rel):
    require(text(rel) and '\\' not in rel and '\x00' not in rel, 'invalid evidence path')
    path = PurePosixPath(rel)
    require(not path.is_absolute() and all(p not in ('', '.', '..') for p in rel.split('/')), f'unsafe path: {rel}')
    current = final
    for part in path.parts:
        current /= part
        require(not current.is_symlink(), f'symlink rejected: {rel}')
    require(current.is_file(), f'missing regular evidence file: {rel}')
    return current


def paths(final, value, nonempty=True):
    require(isinstance(value, list) and (bool(value) or not nonempty), 'evidence paths must be an array')
    return [safe_file(final, p) for p in value]


def records(value, label):
    require(isinstance(value, list), f'{label} must be an array')
    out = {}
    for row in value:
        require(isinstance(row, dict) and text(row.get('id')), f'{label}: missing ID')
        require(row['id'] not in out, f'{label}: duplicate ID')
        out[row['id']] = row
    return out


def refs(value, mapping, label, nonempty=True):
    require(isinstance(value, list) and (bool(value) or not nonempty), f'{label}: expected ID array')
    require(all(isinstance(v, str) and v in mapping for v in value), f'{label}: unresolved ID')


def numeric(value):
    if isinstance(value, list):
        return bool(value) and all(numeric(v) for v in value)
    return type(value) in (int, float) and math.isfinite(value)


def number(value):
    try:
        result = float(value)
    except (ValueError, TypeError, OverflowError) as exc:
        raise EvidenceError('invalid numeric CSV value') from exc
    require(math.isfinite(result), 'nonfinite CSV number')
    return result


def recompute(final, check, quantities):
    require(isinstance(check, dict) and text(check.get('id')), 'check requires ID')
    qid = check.get('quantity_id')
    require(isinstance(qid, str) and qid in quantities, 'check quantity not found')
    quantity = quantities[qid]
    require(numeric(quantity['value']) and not isinstance(quantity['value'], list), 'check requires scalar quantity')
    path = safe_file(final, check.get('path'))
    require(check['path'] in quantity['evidence_paths'], 'check table must be cited by its quantity')
    with path.open(encoding='utf-8', newline='') as stream:
        reader = csv.DictReader(stream)
        names = reader.fieldnames
        require(names and len(names) == len(set(names)), 'CSV requires unique headers')
        rows = list(reader)
    require(rows and all(None not in r and all(v is not None for v in r.values()) for r in rows), 'empty or ragged CSV')
    op, col = check.get('operation'), check.get('column')
    require(isinstance(col, str) and col in names, 'check column not found')
    values = [number(r[col]) for r in rows]
    if op == 'count':
        actual = len(rows)
    elif op in ('sum', 'mean', 'min', 'max'):
        actual = {'sum': math.fsum, 'mean': lambda v: math.fsum(v)/len(v), 'min': min, 'max': max}[op](values)
    elif op in ('mae', 'rmse'):
        ref = check.get('reference_column')
        require(isinstance(ref, str) and ref in names, 'reference column not found')
        errors = [v-number(r[ref]) for v, r in zip(values, rows)]
        actual = math.fsum(abs(e) for e in errors)/len(errors) if op == 'mae' else math.sqrt(math.fsum(e*e for e in errors)/len(errors))
    else:
        raise EvidenceError('unsupported optional summary operation; omit this optional check for other calculations')
    factor = check.get('unit_factor', 1)
    require(type(factor) in (int, float) and math.isfinite(factor) and factor > 0, 'invalid unit factor')
    actual *= factor
    expected = quantity['value']
    require(abs(actual - expected) <= 1e-8 + 1e-6 * abs(expected), f'{check["id"]}: numerical mismatch')
    return {'id': check['id'], 'quantity_id': qid, 'recomputed': actual, 'declared': expected}


def evaluate(final):
    components, details = {}, []
    def score(name, fn):
        try:
            fn()
            components[name] = 1
        except (EvidenceError, OSError, UnicodeError, OverflowError, RecursionError) as exc:
            components[name] = 0
            details.append({'component': name, 'reason': str(exc)})
    require(not final.is_symlink() and final.is_dir(), 'missing regular submission directory')
    require(not any(p.is_symlink() for p in final.rglob('*')), 'submission contains symlinks')
    provenance = json_object(safe_file(final, 'provenance.json'))
    result = json_object(safe_file(final, 'results.json'))
    sources = records(provenance.get('sources'), 'sources')
    executions = records(provenance.get('executions'), 'executions')
    decisions = records(provenance.get('decisions'), 'decisions')
    claims = records(provenance.get('claims'), 'claims')
    quantities = records(result.get('quantities'), 'quantities')
    def report():
        require(bool(safe_file(final, 'claim.md').read_text(encoding='utf-8').strip()), 'empty claim report')
        for key in ('scope', 'validation'):
            require((text(result.get(key)) or isinstance(result.get(key), dict) and bool(result[key])), f'missing {key}')
        c = result.get('conclusion')
        require(isinstance(c, dict) and c.get('status') in ('supported', 'refuted', 'inconclusive'), 'invalid conclusion')
        require(text(c.get('rationale')) and bool(c.get('limitations')), 'conclusion needs rationale and limitations')
        refs(c.get('claim_ids'), claims, 'conclusion')
    def provenance_links():
        require(bool(sources) and bool(decisions), 'sources and decisions are required')
        for s in sources.values():
            require(text(s.get('origin')) and s.get('acquisition') in ('acquired','constructed'), 'source origin/acquisition missing')
            require(isinstance(s.get('path'), str) and s['path'].startswith('native_evidence/'), 'source must reside in native_evidence')
            safe_file(final, s['path'])
        for d in decisions.values():
            require(text(d.get('decision')) and text(d.get('reason')), 'decision needs reason')
            refs(d.get('evidence_ids'), {**sources, **executions, **claims}, 'decision')
    def execution():
        require(bool(executions), 'no execution documentation')
        for e in executions.values():
            require(text(e.get('stage')) and text(e.get('status')), 'execution stage/status missing')
            paths(final, e.get('input_paths')); paths(final, e.get('output_paths'))
            paths(final, e.get('receipt_paths'), nonempty=False)
        # Presence is documentation, never authentication of execution or receipts.
    def support():
        require(bool(claims) and bool(quantities), 'claims and quantities required')
        for q in quantities.values():
            require(text(q.get('name')) and text(q.get('unit')) and numeric(q.get('value')), 'invalid quantity')
            require(all(k in q for k in ('conditions','population','uncertainty')), 'quantity context missing')
            paths(final, q.get('evidence_paths'))
        for c in claims.values():
            require(text(c.get('statement')), 'empty claim')
            refs(c.get('result_ids'), quantities, 'claim results')
            refs(c.get('source_ids'), sources, 'claim sources')
            refs(c.get('execution_ids'), executions, 'claim executions')
            paths(final, c.get('evidence_paths'))
    checked = []
    def reproducibility():
        # With no optional arithmetic checks, evidence is marked documented only.
        checks = result.get('checks', [])
        require(isinstance(checks, list), 'checks must be an array')
        ids = set()
        for check in checks:
            require(isinstance(check, dict) and text(check.get('id')) and check['id'] not in ids, 'invalid/duplicate check ID')
            ids.add(check['id']); checked.append(recompute(final, check, quantities))
        require(bool(checks), 'no automatically recomputable scalar summaries; method-specific reproducibility awaits human review')
    for name, fn in [('research_report',report),('provenance_links',provenance_links),('execution_documentation',execution),('quantitative_evidence_links',support),('optional_numerical_consistency',reproducibility)]:
        score(name, fn)
    return components, details, checked


def main():
    final = Path(os.environ.get('APP','/app'))/'final'
    logs = Path(os.environ.get('LOGS','/logs/verifier'))
    logs.mkdir(parents=True, exist_ok=True)
    reward = logs/'reward.txt'; reward.unlink(missing_ok=True)
    result = {'schema':VERSION, 'status':'REVIEW_REQUIRED', 'scientific_status':'REVIEW_REQUIRED',
              'scientific_success':None, 'score_kind':'evidence_only', 'human_review_required':True,
              'execution_attested':False, 'source_truth_verified':False, 'reward':0.0,
              'limitations':['No source or model whitelist.', 'Documentation is not execution authentication.',
                  'No arbitrary candidate code is executed.', 'Numerical consistency is not scientific correctness.',
                  'Human review must assess scientific validity, independence, uncertainty and relevance.']}
    rc = 0
    try:
        components, issues, checks = evaluate(final)
        result.update(components=components, issues=issues, numerical_checks=checks, reward=sum(components.values())/5)
    except (EvidenceError, OSError, UnicodeError, RecursionError) as exc:
        result.update(components={}, issues=[{'reason':str(exc)}])
    except Exception as exc:
        result.update(status='INFRA_ERROR', reward=None, errors=[f'{type(exc).__name__}: {exc}'])
        rc = 2
    encoded = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)+'\n'
    (logs/'verification.json').write_text(encoded, encoding='utf-8')
    if rc == 0:
        reward.write_text(f'{result["reward"]:.8g}\n', encoding='utf-8')
    print(encoded, end='')
    return rc


if __name__ == '__main__':
    raise SystemExit(main())
