#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability.
# L2 Execution: Check the use of supplied data or archived evidence where required.
# L3 Science: Accuracy of Four Response Kernels Relative to EOM-CCSD.
"""Validate identified molecular errors, their statistics and energy references.

Parsing accepts equivalent chemical notation; scientific tolerances and complete
sample multiplicities are invariant. Candidate errors are FAIL, damaged trusted
references or unexpected verifier failures are ENV_INVALID with no reward.
"""
from __future__ import annotations
import csv
import json
import math
import os
import re
from collections import defaultdict
from pathlib import Path

CASE_ID = 'case-02-kernel-accuracy-vs-eom-ccsd'
GEOMETRY = ('PBE0|TZVP', 'ADMM-PBE0|TZVP+tzp', 'sTDA@PBE0|TZVP', 'sTDA@ADMM-PBE0|TZVP+tzp')
ENERGY = ('PBE0|DZVP', 'PBE0|TZVP', 'PBE0|TZV2P', *GEOMETRY[1:])
QUANTITIES = ('bond', 'angle', 'dihedral')
ENERGY_SOURCES = {'Evert': 27, 'Ead': 46, 'Efl': 51}
STATS = ('me', 'mae', 'max', 'std')
COLUMNS = ('row_type', 'kernel', 'basis', 'quantity', *STATS, 'source_table')
GEOM_TOL = 0.02
ENERGY_TOL = 0.005
ITEM_TOL = 0.006

class CandidateError(ValueError):
    pass

class InfraError(ValueError):
    pass

def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'duplicate JSON key {key!r}')
        result[key] = value
    return result

def read_json(path, error_type):
    try:
        return json.loads(path.read_text(encoding='utf-8-sig'), object_pairs_hook=unique_object,
                          parse_constant=lambda token: (_ for _ in ()).throw(ValueError(f'non-finite JSON value {token}')))
    except (OSError, UnicodeError, ValueError) as exc:
        raise error_type(f'{path.name}: {exc}') from exc

def number(value, where, error_type=CandidateError):
    try:
        if isinstance(value, bool):
            raise ValueError('boolean is not a scientific number')
        x = float(str(value).strip().replace('−', '-'))
        if not math.isfinite(x):
            raise ValueError('number must be finite')
        return x
    except (ValueError, TypeError) as exc:
        raise error_type(f'{where}: invalid finite number {value!r}') from exc

def method_key(kernel, basis):
    """Resolve declared equivalent method spellings without changing the method."""
    if not isinstance(kernel, str) or not isinstance(basis, str):
        raise CandidateError('kernel and basis must be strings')
    kernel_aliases = {'pbe0': 'PBE0', 'admm-pbe0': 'ADMM-PBE0',
                      'stda@pbe0': 'sTDA@PBE0', 'stda@admm-pbe0': 'sTDA@ADMM-PBE0',
                      'stda@admm': 'sTDA@ADMM-PBE0'}
    basis_aliases = {b.lower(): b for b in ('DZVP', 'TZVP', 'TZV2P', 'TZVP+tzp')}
    k = re.sub(r'\s+', '', kernel).replace('−', '-').lower()
    b = re.sub(r'\s+', '', basis).lower()
    if k not in kernel_aliases or b not in basis_aliases:
        raise CandidateError(f'unknown method/basis {kernel!r}/{basis!r}')
    return kernel_aliases[k] + '|' + basis_aliases[b]

def quantity_name(value):
    aliases = {'bond': 'bond', 'bond_length': 'bond', 'angle': 'angle',
               'bond_angle': 'angle', 'dihedral': 'dihedral', 'dihedral_angle': 'dihedral',
               'evert': 'Evert', 'ead': 'Ead', 'efl': 'Efl'}
    q = value.strip().lower()
    if q not in aliases:
        raise CandidateError(f'unknown quantity {value!r}')
    return aliases[q]

def norm_label(value):
    """Tokenize atom labels, retaining atom order, indices and multiplicity.

    C-H, C–H and C H denote the same label; arbitrary punctuation or words are
    not discarded, and atom sequences are never sorted or deduplicated.
    """
    if not isinstance(value, str):
        raise CandidateError('atom label must be a string')
    s = value.casefold().replace('∠', ' ').replace('η', ' ')
    s = re.sub(r'[‐‑‒–—−-]', ' ', s)
    s = re.sub(r'\bh\s+ald\b', 'hald', s)
    return ' '.join(s.split())

def molecule_id(value):
    if isinstance(value, bool):
        raise CandidateError(f'invalid molecule identifier {value!r}')
    if isinstance(value, int):
        result = value
    elif isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer():
            raise CandidateError(f'invalid molecule identifier {value!r}')
        result = int(value)
    else:
        text = str(value).strip()
        match = re.fullmatch(r'(?i)m?(\d+)', text)
        if not match:
            raise CandidateError(f'invalid molecule identifier {value!r}')
        try:
            result = int(match.group(1))
        except (ValueError, OverflowError) as exc:
            raise CandidateError(f'invalid molecule identifier {value!r}') from exc
    if result < 1:
        raise CandidateError(f'invalid molecule identifier {value!r}')
    return result

def sample_groups(raw, error_type=CandidateError):
    if not isinstance(raw, dict):
        raise error_type('samples must be an object keyed by method|basis|quantity')
    groups = {}
    try:
        for key, items in raw.items():
            parts = key.split('|')
            if len(parts) != 3:
                raise CandidateError(f'invalid sample group {key!r}')
            canonical = method_key(parts[0], parts[1]) + '|' + quantity_name(parts[2])
            if canonical in groups:
                raise CandidateError(f'duplicate equivalent sample group {key!r}')
            if not isinstance(items, list) or not items:
                raise CandidateError(f'{key}: nonempty molecular sample array required')
            parsed = []
            for i, item in enumerate(items):
                if not isinstance(item, dict) or not {'mol', 'label', 'err'} <= item.keys():
                    raise CandidateError(f'{key} item {i}: mol, label and err required')
                parsed.append((molecule_id(item['mol']), norm_label(item['label']),
                               number(item['err'], f'{key} item {i}')))
            groups[canonical] = parsed
    except CandidateError as exc:
        raise error_type(str(exc)) from exc
    return groups

def moments(values):
    mean = math.fsum(values) / len(values)
    return (mean, math.fsum(abs(v) for v in values) / len(values),
            max(values, key=abs), math.sqrt(math.fsum((v-mean)**2 for v in values) / len(values)))

def close(got, expected, tolerance, allow_sign=False):
    return (abs(got-expected) <= tolerance+1e-9
            or (allow_sign and abs(got+expected) <= tolerance+1e-9))

def read_refs(tests):
    refs = read_json(tests/'refs.json', InfraError)
    if not isinstance(refs, dict) or refs.get('schema') != 'bench12-refs/v1':
        raise InfraError('invalid reference schema')
    gold = sample_groups(refs.get('per_item'), InfraError)
    expected = {f'{k}|{q}' for k in GEOMETRY for q in QUANTITIES}
    if set(gold) != expected:
        raise InfraError('reference molecular group inventory differs from the scientific scope')
    try:
        for q in QUANTITIES:
            for k in GEOMETRY:
                row = refs['kernel_geometry_stats'][q][k]
                if not isinstance(row, list) or len(row) != 4:
                    raise InfraError(f'invalid geometry references: {k}|{q}')
                for x in row:
                    number(x, 'geometry reference', InfraError)
                # Verify reference consistency before reading any candidate data.
                calc = moments([x[2] for x in gold[f'{k}|{q}']])
                if not all(close(a,b,GEOM_TOL) for a,b in zip(calc,row)):
                    raise InfraError(f'published/per-item reference inconsistency: {k}|{q}')
        for q in ENERGY_SOURCES:
            for k in ENERGY:
                row = refs['kernel_energy_verify_only'][q]['values'][k]
                if not isinstance(row, list) or len(row) != 3:
                    raise InfraError(f'invalid energy references: {k}|{q}')
                for x in row:
                    number(x,'energy reference',InfraError)
        if number(refs['per_item_tol'],'reference item tolerance',InfraError) != ITEM_TOL:
            raise InfraError('unexpected molecular error tolerance')
    except (KeyError, TypeError) as exc:
        raise InfraError(f'incomplete trusted references: {exc}') from exc
    return refs, gold

def read_statistics(path):
    try:
        with path.open(encoding='utf-8-sig',newline='') as f:
            reader = csv.DictReader(f,strict=True)
            headers = [h.strip() for h in reader.fieldnames or []]
            if len(headers)!=len(set(headers)) or not set(COLUMNS)<=set(headers):
                raise CandidateError('statistics.csv requires unique columns: '+','.join(COLUMNS))
            rows = {}
            for line, raw in enumerate(reader,2):
                if None in raw or any(v is None for v in raw.values()):
                    raise CandidateError(f'statistics.csv row {line}: wrong number of fields')
                row = {k.strip():v.strip() for k,v in raw.items()}
                key = method_key(row['kernel'],row['basis']);q=quantity_name(row['quantity'])
                identity=f'{key}|{q}'
                if identity in rows:
                    raise CandidateError(f'duplicate scientific row {identity}')
                geometry = q in QUANTITIES and key in GEOMETRY
                energy = q in ENERGY_SOURCES and key in ENERGY
                if not (geometry or energy):
                    raise CandidateError(f'row outside task scope: {identity}')
                expected_type='recomputed-from-raw' if geometry else 'verified-against-si'
                if row['row_type'].lower()!=expected_type:
                    raise CandidateError(f'{identity}: row_type must be {expected_type}')
                if row.get('evidence_status') and row['evidence_status'].lower()!=expected_type:
                    raise CandidateError(f'{identity}: conflicting evidence_status')
                vals={s:number(row[s],f'{identity}.{s}') for s in STATS if row[s]}
                needed=STATS if geometry else ('me','mae','std')
                if not set(needed)<=vals.keys():
                    raise CandidateError(f'{identity}: missing required statistics')
                if vals['mae']<0 or vals['std']<0:
                    raise CandidateError(f'{identity}: MAE and STD cannot be negative')
                rows[identity]={'stats':vals,'source':row['source_table']}
            return rows
    except (OSError,UnicodeError,csv.Error) as exc:
        raise CandidateError(f'statistics.csv: {exc}') from exc

def source_matches(text, expected):
    # Accept explicit table citations and a bare identifier, but not incidental
    # numbers in prose such as "3 molecules".
    if not isinstance(text, str):
        return False
    numbers = set()
    def add_number(raw):
        numbers.add(raw.lstrip('0') or '0')

    boundary = r'(?!\d|\.\d)'
    bare = re.fullmatch(r'\s*(\d+)(?:\.(?!\d))?\s*', text)
    if bare:
        add_number(bare.group(1))
    for match in re.finditer(rf'(?<!\w)S\s*(\d+){boundary}', text, re.I):
        add_number(match.group(1))
    for match in re.finditer(rf'(?<!\w)SI\s*(\d+){boundary}', text, re.I):
        add_number(match.group(1))
    citation = re.compile(
        rf'(?<!\w)(?:tables?|t|表)\s*(?:s\s*)?\d+{boundary}'
        rf'(?:(?:\s*(?:,|and|&)\s*)(?:s\s*)?\d+{boundary})*', re.I)
    for match in citation.finditer(text):
        for number_match in re.finditer(r'\d+', match.group()):
            add_number(number_match.group())
    return str(expected) in numbers

def check_items(items, gold, key):
    got=defaultdict(list);want=defaultdict(list)
    for mol,label,err in items:got[(mol,label)].append(err)
    for mol,label,err in gold:want[(mol,label)].append(err)
    problems=[]
    for identity in sorted(got.keys()|want.keys()):
        a,b=sorted(got[identity]),sorted(want[identity])
        if len(a)!=len(b):
            problems.append(f'{key}: M{identity[0]} {identity[1]!r} sample count {len(a)}; expected {len(b)}')
        elif any(not close(x,y,ITEM_TOL) for x,y in zip(a,b)):
            problems.append(f'{key}: M{identity[0]} {identity[1]!r} molecular errors differ from source beyond {ITEM_TOL}')
    return problems

def report_numbers(text):
    return [float(x.replace('−','-')) for x in re.findall(r'(?<![\w.])[+−-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+−-]?\d+)?(?!\w)',text)]

def distinct_numbers_present(values, targets, tol):
    # Bipartite matching avoids order-dependent greedy matches for nearby values.
    assigned={}
    def place(i,seen):
        for j,value in enumerate(values):
            if j not in seen and close(value,targets[i],tol):
                seen.add(j)
                if j not in assigned or place(assigned[j],seen):
                    assigned[j]=i
                    return True
        return False
    return all(place(i,set()) for i in range(len(targets)))

def evaluate(app,tests):
    refs,gold=read_refs(tests)
    final=app/'final'
    for name in ('statistics.csv','provenance.json','report.md'):
        p=final/name
        if p.is_symlink() or not p.is_file():
            raise CandidateError(f'final/{name}: regular submission file required')
    provenance=read_json(final/'provenance.json',CandidateError)
    if not isinstance(provenance,dict):
        raise CandidateError('provenance.json must be an object')
    samples=sample_groups(provenance.get('samples'))
    expected_geometry=set(gold)
    expected_energy={f'{k}|{q}' for k in ENERGY for q in ENERGY_SOURCES}
    if set(samples)!=expected_geometry:
        raise CandidateError(f'molecular group inventory differs: missing {sorted(expected_geometry-set(samples))}; extra {sorted(set(samples)-expected_geometry)}')
    rows=read_statistics(final/'statistics.csv')
    expected=expected_geometry|expected_energy
    if set(rows)!=expected:
        raise CandidateError(f'statistics row inventory differs: missing {sorted(expected-set(rows))}; extra {sorted(set(rows)-expected)}')
    problems=[];checks=['submission parsed: 12 geometry groups and 18 energy rows']
    for key in sorted(expected_geometry):
        method,q=key.rsplit('|',1);row=rows[key]
        item_problems = check_items(samples[key],gold[key],key)
        problems.extend(item_problems)
        # Derived statistics from a molecular group already known to be wrong
        # are meaningless. In particular, huge finite candidate values must
        # remain an ordinary candidate FAIL, not overflow into ENV_INVALID.
        if item_problems:
            continue
        calculated=moments([x[2] for x in samples[key]])
        expected_stats=refs['kernel_geometry_stats'][q][method]
        for s,actual,published in zip(STATS,calculated,expected_stats):
            claimed=row['stats'][s]
            if not close(claimed,actual,GEOM_TOL):
                problems.append(f'{key}.{s}: claimed {claimed}, molecular recomputation {actual:.8f}')
            if not close(claimed,published,GEOM_TOL):
                problems.append(f'{key}.{s}: claimed {claimed}, published {published}')
        source=14 if method.startswith('sTDA') else 3
        if not source_matches(row['source'],source):
            problems.append(f'{key}: source citation does not identify the matching raw geometry table')
    if not problems:checks.append('all identified molecular errors and four geometry statistics verified')
    for key in sorted(expected_energy):
        method,q=key.rsplit('|',1);row=rows[key]
        for s,published in zip(('me','mae','std'),refs['kernel_energy_verify_only'][q]['values'][method]):
            if not close(row['stats'][s],published,ENERGY_TOL):
                problems.append(f'{key}.{s}: claimed {row["stats"][s]}, published {published}')
        if not source_matches(row['source'],ENERGY_SOURCES[q]):
            problems.append(f'{key}: energy reference citation does not identify the matching aggregate table')
    try:text=(final/'report.md').read_text(encoding='utf-8-sig')
    except (OSError,UnicodeError) as exc:raise CandidateError(f'report.md: {exc}') from exc
    numeric=report_numbers(text)
    if not re.search(r'(?i)\bm\s*14\b|formyl\s+chloride|甲酰氯',text) or not distinct_numbers_present(numeric,[0.2,0.25],0.001):
        problems.append('report: discuss the M14 default and remedy parameters separately')
    means=[rows[f'{k}|dihedral']['stats']['me'] for k in GEOMETRY]
    if not distinct_numbers_present(numeric,means,0.05):
        problems.append('report: quantify each of the four submitted dihedral mean errors with separate numeric observations')
    if not re.search(r'(?i)s\s*tda',text) or not re.search(r'(?i)dihedral|torsion|二面角',text):
        problems.append('report: discuss the response-kernel dihedral comparison')
    if not problems:checks.append('energy statistics, source references and quantitative report verified')
    return {'case_id':CASE_ID,'status':'FAIL' if problems else 'PASS','checks_passed':checks,'problems':problems}

def main():
    app=Path(os.environ.get('APP','/app'));tests=Path(os.environ.get('TESTS','/tests'));logs=Path(os.environ.get('LOGS','/logs/verifier'))
    logs.mkdir(parents=True,exist_ok=True)
    (logs/'reward.txt').unlink(missing_ok=True)
    try:
        report=evaluate(app,tests)
    except CandidateError as exc:
        report={'case_id':CASE_ID,'status':'FAIL','checks_passed':[],'problems':[str(exc)]}
    except Exception as exc:
        report={'case_id':CASE_ID,'status':'ENV_INVALID','checks_passed':[],'problems':[f'{type(exc).__name__}: {exc}']}
    status=report['status']
    if status in ('PASS','FAIL'):report['reward']=1.0 if status=='PASS' else 0.0
    (logs/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    for problem in report['problems']:print(status+': '+problem)
    print('verdict: '+status)
    return {'PASS':0,'FAIL':1,'ENV_INVALID':2}[status]

if __name__=='__main__':
    raise SystemExit(main())
