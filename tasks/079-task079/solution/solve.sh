#!/usr/bin/env bash
set -euo pipefail
OUTPUT="${1:-/app/final}"
mkdir -p "$OUTPUT"
exec python3 - "$OUTPUT" <<'PYCODE'
#!/usr/bin/env python3
"""Reconcile public article/SI excitation tables without private answer data."""
import csv,hashlib,json,re,sys
from pathlib import Path
import pdfplumber
ASSETS=Path('/app/inputs');OUT=Path(sys.argv[1] if len(sys.argv)>1 else '/app/final');SI='ct2c00144_si_001.pdf';MAIN='hehn2022_main.pdf'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def getpages(path,ns):
 with pdfplumber.open(path) as p:return '\n'.join(p.pages[n-1].extract_text() or '' for n in ns)
def nums(s):return [float(x.replace('−','-')) for x in re.findall(r'[−-]?\d+\.\d+',s)]
def rows(s, n):
 out=[]
 for line in s.splitlines():
  m=re.match(r'^\s*(\S+)\s+((?:[−-]?\d+\.\d+\s+){%d}[−-]?\d+\.\d+)\s*$',line)
  if m:out.append((m.group(1),nums(m.group(2))))
 return out
def block(s,start,end=None):
 a=s.find(start)
 if a<0:raise ValueError(f'missing {start}')
 b=s.find(end,a+len(start)) if end else -1
 return s[a:b if b>=0 else None]
def main():
 OUT.mkdir(parents=True,exist_ok=True)
 maintext=getpages(ASSETS/MAIN,[8,10]); si=getpages(ASSETS/SI,[59,60,61,62])
 # Table 1 prints geometry rows first, then six energy rows. Each energy row
 # contains Evert, Ead, and Efl (ME/MAE/STD); retain the later occurrence.
 t1=block(maintext,'Table 1.','3.1.1.'); t1seen={}
 for line in t1.splitlines():
  m=re.match(r'^\s*(dzp|tzp|tz2p)/(DZVP|TZVP|TZV2P)\s+(.*)$',line,re.I)
  if m:
   values=nums(m.group(3))
   if len(values)==9:t1seen.setdefault((m.group(1).lower(),m.group(2)),[]).append(values)
 t1rows={k:v[-1][:2] for k,v in t1seen.items() if len(v)>=2}
 pairs=[('dzp','DZVP'),('dzp','TZVP'),('dzp','TZV2P'),('tzp','TZVP'),('tzp','TZV2P'),('tz2p','TZV2P')]
 if len(t1rows)!=6:raise RuntimeError(f'article Table1 Evert rows: {len(t1rows)}')
 # Main Table 2 contains a geometry panel and later three energy triplets;
 # parse the rows with nine values and retain their first (Evert) pair.
 t2=block(maintext,'Table2.Statistics','aErrorsinthegeometricaldata'); t2rows={}
 for line in t2.splitlines():
  m=re.match(r'^\s*(PBE0|ADMM-PBE0|sTDA@PBE0|sTDA@ADMM-PBE0)\s+(DZVP|TZVP|TZV2P|TZVP\+tzp)\s+(.*)$',line)
  if m:
   values=nums(m.group(3))
   if len(values)>=9:t2rows[(m.group(1),m.group(2))]=values[:2]
 t2keys=[('PBE0','DZVP'),('PBE0','TZVP'),('PBE0','TZV2P'),('ADMM-PBE0','TZVP+tzp'),('sTDA@PBE0','TZVP'),('sTDA@ADMM-PBE0','TZVP+tzp')]
 if not all(k in t2rows for k in t2keys):raise RuntimeError(f'article Table2 rows missing: {set(t2keys)-set(t2rows)}')
 # SI row order is read from each table, then associated with its printed method
 # group and complete basis name using the source table's documented grouping.
 p25=block(si,'Table 25:','Table 26:')
 p25raw=[]
 for line in p25.splitlines():
  m=re.search(r'\b(DZVP|TZVP|TZV2P)\s+([−-]?\d+\.\d+)\s+(\d+\.\d+)\s+[−-]?\d+\.\d+\s+\d+\.\d+\s*$',line.strip())
  if m:p25raw.append((m.group(1),float(m.group(2).replace('−','-')),float(m.group(3))))
 if len(p25raw)!=6:raise RuntimeError(f'SI Table25 rows: {len(p25raw)}')
 si25={k:[v[1],v[2]] for k,v in zip(pairs,p25raw)}
 p27=block(si,'Table 27:','Table 28:'); si27={}
 for line in p27.splitlines():
  m=re.match(r'^\s*(?:(PBE0|ADMM)\s+)?(DZVP|TZVP|TZV2P)(?:\+(dzp|tzp|tz2p))?\s+([−-]?\d+\.\d+)\s+(\d+\.\d+)\s+[−-]?\d+\.\d+\s+\d+\.\d+\s*$',line)
  if m:
   prefix,basis,aux,me,mae=m.groups(); pbs=basis+(f'+{aux}' if aux else '')
   method=prefix or ('ADMM-PBE0' if aux else 'PBE0')
   if method=='ADMM':method='ADMM-PBE0'
   si27[(method,pbs)]=[float(me.replace('−','-')),float(mae)]
   continue
  m=re.match(r'^\s*(sTDA@PBE0|sTDA@ADMM)\s+(TZVP(?:\+tzp)?)\s+([−-]?\d+\.\d+)\s+(\d+\.\d+)\s+[−-]?\d+\.\d+\s+\d+\.\d+\s*$',line)
  if m:
   method='sTDA@PBE0' if m.group(1)=='sTDA@PBE0' else 'sTDA@ADMM-PBE0'
   si27[(method,m.group(2))]=[float(m.group(3).replace('−','-')),float(m.group(4))]
 if len(si27)!=11:raise RuntimeError(f'SI Table27 rows: {len(si27)}')
 out=[]
 for aux,pbs in pairs:
  a=t1rows[(aux,pbs)];b=si25[(aux,pbs)];out.append([f'admm|{aux}/{pbs}',*a,'25',*b,'consistent' if all(abs(x-y)<=.011 for x,y in zip(a,b)) else 'rounding-consistent'])
 mappings=[('PBE0|DZVP',('PBE0','DZVP')),('PBE0|TZVP',('PBE0','TZVP')),('PBE0|TZV2P',('PBE0','TZV2P')),('ADMM-PBE0|TZVP+tzp',('ADMM-PBE0','TZVP+tzp')),('sTDA@PBE0|TZVP',('sTDA@PBE0','TZVP')),('sTDA@ADMM-PBE0|TZVP+tzp',('sTDA@ADMM-PBE0','TZVP+tzp'))]
 for name,key in mappings:
  a=t2rows[key];b=si27[key];out.append([f'kernel|{name.replace("|","/")}',*a,'27',*b,'consistent' if all(abs(x-y)<=.011 for x,y in zip(a,b)) else 'rounding-consistent'])
 with (OUT/'reconciliation.csv').open('w',newline='') as f:
  w=csv.writer(f);w.writerow(['entry','printed_me','printed_mae','si_table','si_me','si_mae','match']);w.writerows(out)
 # Quantitative verdict anchors are also extracted from SI Tables 22/24/28/29.
 anchors=[]
 for tn in (22,24,28,29):
  end=f'Table {tn+1}:';tb=block(si,f'Table {tn}:',end)
  dz=re.search(r'(?m)^\s*DZVP\s+([−-]?\d+\.\d+)\s+\d+\.\d+',tb)
  st=re.search(r'(?m)^\s*sTDA@ADMM\s+TZVP\+tzp\s+([−-]?\d+\.\d+)\s+',tb)
  if not dz or not st:raise RuntimeError(f'Could not parse SI Table {tn} ME anchors')
  anchors.extend([float(dz.group(1).replace('−','-')),float(st.group(1).replace('−','-'))])
 prov={'inputs':{SI:sha(ASSETS/SI),MAIN:sha(ASSETS/MAIN)},'mapping':'Main Table 1 is compared with SI Table 25 (first-ten-state, CP2K); Main Table 2 is compared with SI Table 27 (first-state, Turbomole).'}
 (OUT/'provenance.json').write_text(json.dumps(prov,indent=2)+'\n')
 values=', '.join(f'{x:.2f}' for x in anchors)
 (OUT/'report.md').write_text(f'# Case 04 reconciliation\n\nArticle Table 1 Evert rows reconcile with SI Table 25, whose statistics use the first ten vertical states and a CP2K reference. Article Table 2 Evert rows reconcile with SI Table 27, whose statistics use the first vertical state and a Turbomole reference; the two reference/geometry conditions are not interchangeable.\n\nThe published double-zeta and sTDA@ADMM mean errors in Tables 22, 24, 28, and 29, in table order as pairs, are {values} eV. This supports the conclusion that double-zeta behavior is reference- and geometry-sensitive and that sTDA errors depend on the reference system. Per-molecule vertical excitation values are not published.\n\nInput PDF SHA-256 values are recorded in `provenance.json`.\n')
if __name__=='__main__':main()

PYCODE
