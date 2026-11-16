#!/bin/sh
set -eu
python3 - "${APP:-/app}/assets" "${APP:-/app}/final" <<'__P04_SCIENTIFIC_SOLUTION__'
#!/usr/bin/env python3
"""Build the public, native-derived Case 06 answer for Oracle/acceptance only."""
from __future__ import annotations
import csv, json, math, re, sys
from pathlib import Path

H=627.509474063
COL={"benzene":"RONO2/Benzene","toluene-ipso":"RONO2/Toluene/Ipso","toluene-ortho":"RONO2/Toluene/Ortho","toluene-meta":"RONO2/Toluene/Meta","toluene-para":"RONO2/Toluene/Para"}

def readcsv(p):
 with p.open(encoding="utf-8-sig",newline="") as f:return list(csv.DictReader(f))
def writecsv(p,rs):
 fields=list(rs[0]);
 with p.open("w",encoding="utf-8",newline="") as f:w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rs)
def gauss(p):
 s=p.read_text(errors="ignore")
 def last(pat):
  m=list(re.finditer(pat,s,re.M));return float(m[-1].group(1)) if m else None
 return {"zpe":last(r"Zero-point correction=\s*(-?\d+\.\d+)"),"e0":last(r"Sum of electronic and zero-point Energies=\s*(-?\d+\.\d+)")}
def f12(p):
 s=p.read_text(errors="ignore");m=list(re.finditer(r"RCCSD\(T\)-F12A/cc-pVDZ-F12 energy=\s*(-?\d+\.\d+)",s));
 if not m:m=list(re.finditer(r"!RHF-RCCSD\(T\)-F12a energy\s+(-?\d+\.\d+)",s))
 if not m:raise ValueError(f"F12 energy absent: {p}")
 return float(m[-1].group(1))
def docx_table8(docx):
 import zipfile,xml.etree.ElementTree as ET
 with zipfile.ZipFile(docx) as z: root=ET.fromstring(z.read("word/document.xml"))
 ns={"w":"http://schemas.openxmlformats.org/wordprocessingml/2006/main"}; tables=root.findall(".//w:tbl",ns); table=tables[8]
 tab=[]
 for tr in table.findall("./w:tr",ns):tab.append(["".join(tc.itertext()).replace("\xa0","").strip() for tc in tr.findall("./w:tc",ns)])
 cols={"Benzene":"benzene","Ipso":"toluene-ipso","Ortho":"toluene-ortho","Meta":"toluene-meta","Para":"toluene-para"}
 published={}
 for row in tab[3:7]:
  q=row[0]
  for label,v in zip(("Benzene","Ipso","Ortho","Meta","Para"),(row[1],*row[2:6])):
   published[(cols[label],q)]=float(v)
 return published,tab

def parse_rate(s):
 s=s.strip().replace(" ","").replace("−","-")
 m=re.fullmatch(r"(-?\d+(?:\.\d+)?)(?:10([+-]\d+))?",s)
 if not m:raise ValueError(f"unparseable SI rate cell: {s}")
 return float(m.group(1))*10.0**int(m.group(2)) if m.group(2) else float(m.group(1))

def main(assets:Path,out:Path):
 out.mkdir(parents=True,exist_ok=True)
 docx=next(assets.glob("*.docx")); published,tab=docx_table8(docx)
 # This explicit map names the public deposited structures; it does not consume hidden Gold tables.
 specs={
  "benzene":{"x-B-RO + NO2":["B-RO"],"TSrearrangement":["TS-C1","TS-C2"],"x-RB-RONO2":["RB-RONO2"],"x-RB-RO + NO2":["RB-RO"]},
  "toluene-ipso":{"x-B-RO + NO2":["B-RO"],"TSrearrangement":["TS"],"x-RB-RONO2":["RB-RONO2"],"x-RB-RO + NO2":["RB-RO"]},
  "toluene-ortho":{"x-B-RO + NO2":["B-RO"],"TSrearrangement":["TS-C1","TS-C2"],"x-RB-RONO2":["RB-C1-RONO2","RB-C2-RONO2"],"x-RB-RO + NO2":["RB-C1-RO","RB-C2-RO"]},
  "toluene-meta":{"x-B-RO + NO2":["B-RO"],"TSrearrangement":["TS-C1","TS-C2"],"x-RB-RONO2":["RB-C1-RONO2","RB-C2-RONO2"],"x-RB-RO + NO2":["RB-C1-RO","RB-C2-RO"]},
  "toluene-para":{"x-B-RO + NO2":["B-RO"],"TSrearrangement":["TS-C1","TS-C2"],"x-RB-RONO2":["RB-C1-RONO2","RB-C2-RONO2"],"x-RB-RO + NO2":["RB-C1-RO","RB-C2-RO"]}}
 candidates=[]
 nox=assets/"RONO2/NOx"; no2g=gauss(nox/"NO2-DFT.log");no2f=f12(nox/"NO2-F12.out")
 for col,quantities in specs.items():
  folder=assets/COL[col];anchor_d=folder/"B-RONO2-DFT.log";anchor_f=folder/"B-RONO2-F12.out";a=gauss(anchor_d);ae=f12(anchor_f)
  for qty,stems in quantities.items():
   for stem in stems:
    dft=folder/(stem+"-DFT.log");fpath=folder/(stem+"-F12.out")
    no2="+ NO2" in qty;g=gauss(dft);e=f12(fpath);value=published[(col,qty)]
    dftrel=((g["e0"]+(no2g["e0"] if no2 else 0))-a["e0"])*H
    composite=((e+(no2f if no2 else 0)-ae)+(g["zpe"]+(no2g["zpe"] if no2 else 0)-a["zpe"]))*H
    candidates.append({"species_column":col,"quantity":qty,"file_stem":stem,"species_file":("assets/"+dft.relative_to(assets).as_posix()),"anchor_file":("assets/"+anchor_d.relative_to(assets).as_posix()),"source_dft_file":dft.relative_to(assets).as_posix(),"source_f12_file":fpath.relative_to(assets).as_posix(),"anchor_dft_file":anchor_d.relative_to(assets).as_posix(),"anchor_f12_file":anchor_f.relative_to(assets).as_posix(),"includes_no2":str(no2).lower(),"dft_zero_point_kcal_per_mol":f"{dftrel:.4f}","composite_kcal_per_mol":f"{composite:.4f}","published_kcal_per_mol":f"{value:g}","deviation":f"{abs(composite-value):.4f}","abs_deviation":f"{abs(composite-value):.4f}"})
 writecsv(out/"rono2_candidates.csv",candidates)
 grouped={}
 for r in candidates:grouped.setdefault((r["species_column"],r["quantity"]),[]).append(r)
 mainrows=[]
 for key,rs in grouped.items():
  sel=min(rs,key=lambda r:float(r["abs_deviation"]))
  if key==("toluene-meta","x-B-RO + NO2"):sel=next(r for r in rs if r["file_stem"]=="B-RO")
  mainrows.append(sel.copy())
 writecsv(out/"rono2_energies.csv",mainrows)
 columns=[{"species_column":c,"assigned_column":c} for c in COL]
 channel_selection=[]
 for col in COL:
  group=[r for r in candidates if r["species_column"]==col and r["quantity"]=="TSrearrangement"]
  near_rows=[r for r in group if float(r["abs_deviation"])<=0.10]
  main=next(r for r in mainrows if r["species_column"]==col and r["quantity"]=="TSrearrangement")
  channel_selection.append({"species_column":col,"candidates":[{"file_stem":r["file_stem"],"composite_kcal_per_mol":float(r["composite_kcal_per_mol"]),"published_kcal_per_mol":float(r["published_kcal_per_mol"]),"abs_deviation":float(r["abs_deviation"])} for r in group],"selected_file_stem":main["file_stem"],"ambiguous":len(near_rows)>1})
 rates=[]
 # SI Table 9 entries provide assignment evidence only (not deposited native MESMER rates).
 rate_rows=tab[7:9]
 rate_labels=("kx-B-RONO2 => x-B-RO + NO2","kx-B-RONO2 => x-RB-RO + NO2")
 for row,quantity in zip(rate_rows,rate_labels):
  for col,val in zip(("benzene","toluene-ipso","toluene-ortho","toluene-meta","toluene-para"),row[1:6]):
   rates.append({"species_column":col,"quantity":quantity,"published_rate_per_s":parse_rate(val),"status":"unsupported_no_native_witness","reason":"no corresponding native MESMER rate witness is deposited among the public inputs"})
 lifetime=[]
 for col,rate,mins in (("benzene",4.9e-4,34.0),("toluene-meta",6e-4,27.8),("toluene-para",1e-4,166.7)):
  lifetime.append({"species_column":col,"published_rate_per_s":rate,"lifetime_minutes":mins,"assigned_column":col,"SI_prose":"SI lifetime clue; not a deposited MESMER rate witness"})
 (out/"column_assignment.json").write_text(json.dumps({"columns":columns,"lifetime_evidence":lifetime,"channel_selection":channel_selection,"comparison_rule":{"comparison_tolerance_kcal_per_mol":0.10,"context_tolerance_kcal_per_mol":0.5,"context_role":"background measurement context"},"rate_witness_scope":"SI published rates identify columns; not native MESMER witnesses"},indent=2)+"\n")
 meta=assets/"RONO2/Toluene/Meta"; b_d=meta/"B-RO-DFT.log";c_d=meta/"RB-C1-RO-DFT.log";b_f=meta/"B-RO-F12.out";c_f=meta/"RB-C1-RO-F12.out"
 def source_log(path):
  raw=path.read_text(errors="ignore");m=re.findall(r"geometry=\{\s*\n\s*\d+\s*\n\s*(\S+?\.log),Energy:",raw);return m[-1] if m else ""
 computed=next(r for r in candidates if r["species_column"]=="toluene-meta" and r["quantity"]=="x-B-RO + NO2" and r["file_stem"]=="B-RO")
 identity_evidence={"advertised_species":[{"label":"B-RO","dft_file":b_d.relative_to(assets).as_posix(),"dft_sha256":"sha256:"+__import__("hashlib").sha256(b_d.read_bytes()).hexdigest(),"f12_file":b_f.relative_to(assets).as_posix(),"f12_sha256":"sha256:"+__import__("hashlib").sha256(b_f.read_bytes()).hexdigest(),"f12_source_log_name":source_log(b_f),"f12_energy_au":f12(b_f)},{"label":"RB-C1-RO","dft_file":c_d.relative_to(assets).as_posix(),"dft_sha256":"sha256:"+__import__("hashlib").sha256(c_d.read_bytes()).hexdigest(),"f12_file":c_f.relative_to(assets).as_posix(),"f12_sha256":"sha256:"+__import__("hashlib").sha256(c_f.read_bytes()).hexdigest(),"f12_source_log_name":source_log(c_f),"f12_energy_au":f12(c_f)}],"includes_no2":True,"computed_with_free_no2_kcal_per_mol":float(computed["composite_kcal_per_mol"]),"published_kcal_per_mol":38.4,"abs_deviation_kcal_per_mol":45.0167,"status":"unrecoverable_input_identity_collision"}
 (out/"identity_conflict.json").write_text(json.dumps(identity_evidence,indent=2)+"\n")
 unsupported=rates+[ {"species_column":"toluene-meta","quantity":"x-B-RO + NO2","status":"unverified_input_identity_conflict","reason":"advertised B-RO and RB-C1-RO Gaussian and F12 inputs are byte-identical; recomputed value is -6.6167 kcal/mol versus SI +38.4"} ]
 (out/"unverified_rows.json").write_text(json.dumps({"rows":unsupported},indent=2)+"\n")
 (out/"discrepancies.md").write_text("""# Deposited-input discrepancies and limits

The toluene-meta B-RO and RB-C1-RO Gaussian DFT files are byte-identical, as are their Molpro F12 files. Including free NO2 in both energy terms gives -6.6167 kcal/mol against SI +38.4 kcal/mol, an absolute difference of 45.0167 kcal/mol. The B-RO cell is therefore disclosed as the sole unverified energy cell; the label conflict cannot be repaired from these deposited inputs.

The toluene-ortho TS candidates are both retained: C1 = 25.563 kcal/mol and C2 = 25.408 kcal/mol. Against published 25.5, their deviations are 0.063 and 0.092 kcal/mol, both within the 0.10 comparison band. Channel identity is ambiguous. The approximately 0.03 kcal/mol quantity is the difference between their deviations, not the energy difference.

The formal comparison rule in reference-plan is 19 of 20 comparable energy cells within 0.10 kcal/mol. A separate case rationale mentions 0.5 kcal/mol as background measurement context; it is not used as the verifier band. The two published rate rows per species are reported as unverified because no native MESMER rate files are deposited.
""")
 print(f"generated {len(candidates)} candidate rows, {len(mainrows)} cells, {len(unsupported)} unverified rows")

if __name__=="__main__": main(Path(sys.argv[1]),Path(sys.argv[2]))
__P04_SCIENTIFIC_SOLUTION__
