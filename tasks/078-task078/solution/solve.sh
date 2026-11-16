#!/usr/bin/env bash
set -euo pipefail
OUTPUT="${1:-/app/final}"
mkdir -p "$OUTPUT"
exec python3 - "$OUTPUT" <<'PYCODE'
#!/usr/bin/env python3
"""Recompute Case 03 directly from the two public PDFs."""
import csv, hashlib, json, math, re, sys
from pathlib import Path
import pdfplumber

ASSETS=Path('/app/inputs'); OUT=Path(sys.argv[1] if len(sys.argv)>1 else '/app/final')
SI='ct2c00144_si_001.pdf'; MAIN='hehn2022_main.pdf'
def digest(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def page_text(pdf,n): return pdf.pages[n-1].extract_text() or ''
def table_lines(text,nxt=None):
    start=text.find(f'Table {nxt[0]}:') if nxt else -1
    return text[start:] if start>=0 else text
def numeric_rows(text, nvals):
    out={}
    for line in text.splitlines():
        m=re.match(r'^\s*M(\d+)\s+((?:-?\d+\.\d+\s+){%d}-?\d+\.\d+)\s*$'%(nvals-1),line)
        if m: out[int(m.group(1))]=[float(x) for x in m.group(2).split()]
    if len(out)!=35: raise RuntimeError(f'Expected 35 molecule rows, extracted {len(out)}')
    return out
def block(text,start,end):
    a=text.find(start); b=text.find(end,a+len(start)) if end else -1
    if a<0: raise RuntimeError(f'PDF table marker missing: {start}')
    return text[a:b if b>=0 else None]
def table_stats(text, start, end, labels):
    b=block(text,start,end); rows={}
    for line in b.splitlines():
        m=re.match(r'^\s*(DZVP|TZVP|TZV2P|cc-GRB-[DTQ]|dzp|tzp|tz2p|ADMM|PBE0|sTDA@PBE0|sTDA@ADMM)\s+((?:-?\d+\.\d+\s+){3}-?\d+\.\d+)\s*$',line)
        if m: rows[m.group(1)]=[float(v) for v in m.group(2).split()]
    return rows
def main():
    OUT.mkdir(parents=True,exist_ok=True)
    with pdfplumber.open(ASSETS/SI) as pdf:
        tab42=page_text(pdf,67); tab43=page_text(pdf,68)
        tab45=page_text(pdf,70); tab46=page_text(pdf,70)
        tab47=page_text(pdf,75); tab48=page_text(pdf,76); tab50=page_text(pdf,78); tab51=page_text(pdf,78)
    ead42=numeric_rows(tab42,9); ead43=numeric_rows(tab43,6)
    efl47=numeric_rows(tab47,9); efl48=numeric_rows(tab48,6)
    # Table column order is read from the table headers: three conventional PBE0
    # columns followed by six ADMM columns (MOLOPT), or three plus three (ccGRB).
    combos=[('DZVP','dzp',0,3),('TZVP','dzp',1,4),('TZV2P','dzp',2,5),
            ('TZVP','tzp',1,6),('TZV2P','tzp',2,7),('TZV2P','tz2p',2,8)]
    samples={}; stats=[]
    for quantity,rows in [('EAD',ead42),('EFL',efl47)]:
        for pbs,abs_,refi,admi in combos:
            errs=[{'mol':f'M{i}', 'label':'', 'err':rows[i][admi]-rows[i][refi]} for i in range(1,36)]
            key=f'{quantity}|{abs_}|{pbs}'; samples[key]=errs
            vals=[x['err'] for x in errs]; mean=sum(vals)/len(vals); mae=sum(abs(x) for x in vals)/len(vals)
            mx=max(vals,key=abs); sd=math.sqrt(sum((x-mean)**2 for x in vals)/len(vals))
            stats.append(['recomputed-from-raw',quantity,pbs,abs_,'ADMM',mean,mae,mx,sd,
                          'SI Table 45' if quantity=='EAD' else 'SI Table 50',
                          'ADMM − conventional PBE0 (same primary basis).'])
    # ccGRB tables contain PBE0 D/T/Q followed by corresponding ADMM D/T/Q.
    for quantity,rows in [('EAD',ead43),('EFL',efl48)]:
        for pbs,abs_,idx in [('cc-GRB-D','dzp',0),('cc-GRB-T','tzp',1),('cc-GRB-Q','tz2p',2)]:
            errs=[{'mol':f'M{i}','label':'','err':rows[i][idx+3]-rows[i][idx]} for i in range(1,36)]
            key=f'{quantity}|{abs_}|{pbs}';samples[key]=errs
            vals=[x['err'] for x in errs]; mean=sum(vals)/35; mae=sum(abs(x) for x in vals)/35
            mx=max(vals,key=abs);sd=math.sqrt(sum((x-mean)**2 for x in vals)/35)
            stats.append(['recomputed-from-raw',quantity,pbs,abs_,'ADMM',mean,mae,mx,sd,
                          'SI Table 45' if quantity=='EAD' else 'SI Table 50',
                          'ADMM − conventional PBE0 (same primary basis).'])
    # Extract the published verify-only tables from their native text blocks.
    with pdfplumber.open(ASSETS/SI) as pdf:
        p46=page_text(pdf,70); p51=page_text(pdf,78)
    def extract_kernel(page,table,quantity):
        b=block(page,f'Table {table}:',None)
        found=[]
        for line in b.splitlines():
            m=re.search(r'(?:(?:PBE0|ADMM|sTDA@PBE0|sTDA@ADMM)\s+)?(DZVP|TZVP|TZV2P|DZVP\+dzp|TZVP\+dzp|TZV2P\+dzp|TZVP\+tzp|TZV2P\+tzp|TZV2P\+tz2p)\s+(-?\d+\.\d+)\s+(\d+\.\d+)\s+(-?\d+\.\d+)\s+(\d+\.\d+)\s*$',line.strip())
            if m: found.append((m.group(1),list(map(float,m.groups()[1:]))))
        specs=([('PBE0','DZVP'),('PBE0','TZVP'),('PBE0','TZV2P'),('ADMM','TZVP+tzp'),('ADMM','TZV2P+tzp'),('sTDA@PBE0','TZVP'),('sTDA@ADMM','TZVP+tzp')] if table==46 else
               [('PBE0','DZVP'),('PBE0','TZVP'),('PBE0','TZV2P'),('ADMM','DZVP+dzp'),('ADMM','TZVP+dzp'),('ADMM','TZV2P+dzp'),('ADMM','TZVP+tzp'),('ADMM','TZV2P+tzp'),('ADMM','TZV2P+tz2p'),('sTDA@PBE0','TZVP'),('sTDA@ADMM','TZVP+tzp')])
        if len(found)!=len(specs):raise RuntimeError(f'Table {table} rows parsed {len(found)} expected {len(specs)}')
        ref='EOM-CCSD' if table==46 else 'PBE0/def2-QZVPP/Turbomole'
        return [['verified-against-SI',quantity,'',basis,method,*values,f'SI Table {table}',ref] for (_,values),(method,basis) in zip(found,specs)]
    stats += extract_kernel(p46,46,'EAD')+extract_kernel(p51,51,'EFL')
    with (OUT/'statistics.csv').open('w',newline='') as f:
        w=csv.writer(f);w.writerow(['row_type','quantity','pbs','abs','method','me','mae','max','std','source_table','reference']);w.writerows(stats)
    inputs={SI:digest(ASSETS/SI),MAIN:digest(ASSETS/MAIN)}
    (OUT/'provenance.json').write_text(json.dumps({'inputs':inputs,'samples':samples,'derivation':'err=ADMM-PBE0 at same primary basis; moments use population standard deviation (ddof=0), signed MAX with greatest absolute magnitude.'},indent=2)+'\n')
    triple=[x for x in stats if x[0]=='recomputed-from-raw' and x[3] in ('tzp','tz2p')]
    with pdfplumber.open(ASSETS/MAIN) as main_pdf:
        abstract = re.sub(r'\s+', '', page_text(main_pdf, 1)).lower()
    bounds = re.search(r'intherangeof(\d+\.\d+)[−–-](\d+\.\d+)evforverticalexcitation,adiabaticexcitation,andfluorescenceenergies', abstract)
    if not bounds:
        raise RuntimeError('ADMM energy MAE interval could not be extracted from the abstract')
    lower, upper = map(float, bounds.groups())
    supported=all(lower-1e-9 <= x[6] <= upper+1e-9 for x in triple)
    verdict='supported' if supported else 'not uniformly supported'
    (OUT/'report.md').write_text('# Case 03 results\n\nRecomputed per-molecule ADMM−PBE0 errors from SI Tables 42/43 and 47/48, then calculated ME, MAE, signed MAX (largest absolute magnitude), and population STD. The triple-zeta auxiliary-basis MAEs are '+verdict+' for the published '+format(lower,'.2f')+'–'+format(upper,'.2f')+' eV interval; see the rows in `statistics.csv`. The published kernel-level statistics are transcribed as verify-only from Tables 46 and 51; their reference systems remain separate (EOM-CCSD for Ead, PBE0/def2-QZVPP/Turbomole for Efl). The per-molecule vertical excitation energies were not published and are out of scope.\n\nInput SHA-256 values are recorded in `provenance.json`.\n')
if __name__=='__main__': main()

PYCODE
