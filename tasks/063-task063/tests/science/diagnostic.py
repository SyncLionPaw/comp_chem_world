#!/usr/bin/env python3
"""Partial deterministic diagnostics; scientific adjudication remains trusted review."""
import argparse, csv, hashlib, importlib.util, json, math, os, io, mimetypes
from pathlib import Path

TEXT_EXTENSIONS={'.json','.csv','.md','.txt','.yaml','.yml','.py','.sh','.r'}

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def _pairs(pairs):
    out={}
    for k,v in pairs:
        if k in out: raise ValueError('duplicate JSON key: '+str(k))
        out[k]=v
    return out
def _number(s):
    v=float(s)
    if not math.isfinite(v): raise ValueError('nonfinite JSON number')
    return v
def strict_json_loads(text):
    def constant(x): raise ValueError('nonfinite JSON constant: '+x)
    return json.loads(text,object_pairs_hook=_pairs,parse_constant=constant,parse_float=_number)
def load(p):
    return strict_json_loads(p.read_text())
def run(app, tests):
    import numpy as np
    protocol = load(tests/'assessment-protocol.json')
    contract = protocol['output_contract']
    for source, expected in protocol['inputs'].items():
        p=app/source
        if p.is_symlink() or not p.is_file() or sha(p)!=expected:
            raise RuntimeError('public input corrupted: '+source)
        if p.suffix=='.npz':
            with np.load(p, allow_pickle=False) as a:
                for key in a.files:
                    a[key]  # Real archive decode, not merely extension checking.
    checks=[]
    review_limits=contract.get('review_limits',{})
    max_text_bytes=int(review_limits.get('max_required_text_file_bytes',45000))
    max_total_text_bytes=int(review_limits.get('max_total_required_text_bytes',180000))
    max_csv_bytes=int(review_limits.get('max_csv_bytes',10000000))
    max_csv_columns=int(review_limits.get('max_csv_columns',128))
    max_csv_record_chars=int(review_limits.get('max_csv_record_chars',12000))
    max_artifact_files=int(review_limits.get('max_artifact_files',128))
    max_artifact_path_chars=int(review_limits.get('max_artifact_path_chars',512))
    max_review_view_chars=int(review_limits.get('max_review_view_chars',180000))
    def check(name, fn):
        try: fn(); checks.append({'criterion':name,'passed':True})
        except (ValueError, KeyError, TypeError, OSError, IndexError, AssertionError) as e:
            checks.append({'criterion':name,'passed':False,'error':str(e)})
    def delivery():
        total_text_bytes=0
        total_view_chars=0
        artifact_file_count=0
        def parse_file(path):
            nonlocal total_text_bytes,total_view_chars,artifact_file_count
            relative=path.relative_to(app).as_posix()
            artifact_file_count+=1
            if artifact_file_count>max_artifact_files: raise ValueError('artifact file count exceeds public max_artifact_files limit')
            if len(relative)>max_artifact_path_chars: raise ValueError('artifact path exceeds public max_artifact_path_chars limit: '+relative[:100])
            size=path.stat().st_size
            is_csv=path.suffix.lower()=='.csv'
            is_text=path.suffix.lower() in TEXT_EXTENSIONS
            if not is_text:
                metadata={'host_derived_artifact_metadata':True,'path':relative,'sha256':sha(path),
                    'bytes':size,'media_type':mimetypes.guess_type(relative)[0] or 'application/octet-stream',
                    'notice':'Optional extra artifact; content is not parsed or used as scientific evidence.'}
                total_view_chars+=len(json.dumps(metadata,ensure_ascii=False,sort_keys=True))
                if total_view_chars>max_review_view_chars: raise ValueError('candidate evidence exceeds public max_review_view_chars limit')
                return
            if is_csv and size>max_csv_bytes: raise ValueError('CSV exceeds public max_csv_bytes contract: '+str(path.relative_to(app)))
            if not is_csv:
                if size>max_text_bytes: raise ValueError('text artifact exceeds public max_required_text_file_bytes contract: '+str(path.relative_to(app)))
                total_text_bytes+=size
                if total_text_bytes>max_total_text_bytes: raise ValueError('text artifacts exceed public max_total_required_text_bytes contract')
            try: text=path.read_text(encoding='utf-8')
            except UnicodeDecodeError as exc: raise ValueError('output is not valid UTF-8: '+str(path.relative_to(app))) from exc
            if path.suffix=='.json':
                data=strict_json_loads(text)
                if not isinstance(data,(dict,list)) or not data: raise ValueError('empty/nonobject JSON: '+str(path.relative_to(app)))
            elif path.suffix=='.csv':
                reader=csv.DictReader(io.StringIO(text,newline="")); rows=list(reader)
                if not rows or not reader.fieldnames or len(set(reader.fieldnames))!=len(reader.fieldnames): raise ValueError('CSV has no records or duplicate header: '+str(path.relative_to(app)))
                if len(reader.fieldnames)>max_csv_columns: raise ValueError('CSV exceeds public max_csv_columns review limit: '+str(path.relative_to(app)))
                header_chars=sum(len(name) for name in reader.fieldnames)+max(0,len(reader.fieldnames)-1)
                if header_chars>max_csv_record_chars: raise ValueError('CSV header exceeds public max_csv_record_chars review limit: '+str(path.relative_to(app)))
                if any(None in row or any(value is None for value in row.values()) for row in rows): raise ValueError('CSV row width differs from header: '+str(path.relative_to(app)))
                if any(any('\n' in value or '\r' in value for value in row.values() if isinstance(value,str)) for row in rows): raise ValueError('CSV fields may not contain embedded newlines under the public evidence format: '+str(path.relative_to(app)))
                for row in rows:
                    record_chars=sum(len(value) for value in row.values() if isinstance(value,str))+max(0,len(reader.fieldnames)-1)
                    if record_chars>max_csv_record_chars: raise ValueError('CSV record exceeds public max_csv_record_chars review limit: '+str(path.relative_to(app)))
                    for value in row.values():
                        if value is None or not value.strip(): continue
                        try: number=float(value)
                        except ValueError: continue
                        if not math.isfinite(number): raise ValueError('CSV contains non-finite numeric value: '+str(path.relative_to(app)))
                fields=contract['schemas'].get(path.relative_to(app).as_posix(),'').split(';')[0].split(',')
                fields=[x.strip() for x in fields]
                if len(fields)>1 and all(x.replace('_','').isalnum() for x in fields):
                    if not set(fields)<=set(reader.fieldnames): raise ValueError('CSV columns missing: '+str(path.relative_to(app)))
            # Match host_scientific_review.review_view(), which chooses its
            # bounded large-CSV representation by decoded text characters.
            if is_csv and len(text)>45000:
                header=reader.fieldnames
                physical_lines=text.splitlines()
                numeric={key:{'n':0,'min':None,'max':None,'mean':None} for key in header}
                first=[];last=[]
                for index,row in enumerate(rows,2):
                    record=dict(row)
                    raw_line=physical_lines[index-1]
                    item={'line':index,'raw':raw_line,'values':record}
                    if len(first)<4:first.append(item)
                    last.append(item)
                    if len(last)>4:last.pop(0)
                    for key,value in record.items():
                        if not value.strip():continue
                        try:number=float(value)
                        except ValueError:continue
                        entry=numeric[key];entry['n']+=1;n=entry['n']
                        entry['mean']=number if n==1 else entry['mean']*((n-1)/n)+number/n
                        entry['min']=number if entry['min'] is None else min(entry['min'],number)
                        entry['max']=number if entry['max'] is None else max(entry['max'],number)
                summary={key:{'count':entry['n'],'min':entry['min'],'max':entry['max'],'mean':entry['mean']}
                         for key,entry in numeric.items() if entry['n']}
                view=json.dumps({'host_derived_full_csv_summary':True,'path':relative,
                    'sha256_of_complete_original_artifact':sha(path),'row_count':len(rows),'header':header,
                    'numeric_column_summary':summary,'first_rows':first,'last_rows':last,
                    'notice':'Full CSV bytes were parsed; this bounded view is not a replacement artifact. Use supplied deterministic checks for claim-level validation.'},
                    ensure_ascii=False,sort_keys=True,separators=(',',':'))
            else:
                lines=text.splitlines()
                view='\n'.join(f'L{i:06d}: {line}' for i,line in enumerate(lines,1))
            total_view_chars+=len(view)
            if total_view_chars>max_review_view_chars: raise ValueError('candidate evidence exceeds public max_review_view_chars limit')
        for raw in contract['required_paths']:
            p=app/raw
            if any(q.is_symlink() for q in [p,*p.parents] if q!=app.parent):
                raise ValueError('symlink output: '+raw)
            if raw.endswith('/'):
                if not p.is_dir() or not any(x.is_file() for x in p.rglob('*')): raise ValueError('empty directory: '+raw)
                for item in p.rglob('*'):
                    if item.is_symlink(): raise ValueError('symlink output: '+raw)
                    if item.is_file(): parse_file(item)
                continue
            elif not p.is_file() or not p.read_bytes().strip(): raise ValueError('missing/empty output: '+raw)
            if p.suffix.lower() not in TEXT_EXTENSIONS:
                raise ValueError('required output must use a contracted text format: '+raw)
            # Every declared deliverable is text-based in this benchmark. Catch
            # malformed encodings in the deterministic layer so a candidate
            # artifact cannot turn a scientific delivery defect into a host
            # reviewer infrastructure error.
            parse_file(p)
    check('delivery_and_parse',delivery)
    cid=protocol['case_id']
    if all(c['passed'] for c in checks) and cid in ('case-03-binding-free-energy-stop-rule','case-06-water-model-free-energy'):
        spec=importlib.util.spec_from_file_location('numeric',tests/'verify.py')
        mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
        check('existing_numeric_and_scope_reference',lambda:mod.check(app/'submission' if cid=='case-06-water-model-free-energy' else app))
    numeric_result=None
    if all(c['passed'] for c in checks):
        spec=importlib.util.spec_from_file_location('numeric_evidence',tests/'numeric_evidence.py')
        if spec is None or spec.loader is None: raise RuntimeError('trusted numeric evidence module cannot be loaded')
        mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
        refs=load(tests/'refs.json')
        numeric_result=mod.evaluate(cid,app,app,protocol,refs)
        nstatus=numeric_result.get('status')
        if nstatus=='INFRA': raise RuntimeError('independent trusted numeric computation failed: '+json.dumps(numeric_result,ensure_ascii=False))
        if nstatus not in ('FAIL','NEEDS_JUDGE','PASS'): raise RuntimeError('numeric evidence returned invalid status')
        checks.append({'criterion':'independent_numeric_evidence','passed':nstatus!='FAIL','result':numeric_result})
    # Open scientific decisions remain pending independent review after runtime integration.
    return {'status':'REVIEW_REQUIRED' if all(c['passed'] for c in checks) else 'FAIL','checks':checks,
            'numeric_evidence':numeric_result,
            'scope':'delivery diagnostics; existing fixed numeric checks where defined; scientific criteria require trusted review'}
if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('--submission',type=Path,required=True);args=a.parse_args()
    try:
        r=run(args.submission,Path(os.environ.get('TESTS',Path(__file__).parent))); print(json.dumps(r));raise SystemExit(1 if r['status']=='FAIL' else 0)
    except Exception as e:
        print(json.dumps({'status':'INFRASTRUCTURE_ERROR','error':str(e)}));raise SystemExit(2)
