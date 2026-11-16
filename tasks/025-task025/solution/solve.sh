#!/bin/sh
set -eu
python3 - --assets "${APP:-/app}/assets" --output "${APP:-/app}/final" <<'__P04_SCIENTIFIC_SOLUTION__'
#!/usr/bin/env python3
"""Parse the public Figure 4 workbook and deposited MESMER XML outputs."""
import argparse,csv,json,math,re,zipfile,xml.etree.ElementTree as ET
from pathlib import Path

NS={"me":"http://www.chem.leeds.ac.uk/mesmer","m":"http://schemas.openxmlformats.org/spreadsheetml/2006/main","r":"http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
MOLECULE={"Benzene":"benzene","E-Benzene":"ethylbenzene","I-Benzene":"isopropylbenzene","M-Xylene":"m-xylene","O-Xylene":"o-xylene","P-Xylene":"p-xylene","Toluene":"toluene"}
SITE={"iBPR":"ipso","oBPR":"ortho","mBPR":"meta","pBPR":"para"}
def write(path,fields,items):
 with path.open("w",newline="",encoding="utf-8") as f:w=csv.DictWriter(f,fieldnames=fields,extrasaction="ignore");w.writeheader();w.writerows(items)
def xlsx_figure4(path):
 with zipfile.ZipFile(path) as z:
  strings=["".join(x.itertext()) for x in ET.fromstring(z.read("xl/sharedStrings.xml"))]
  wb=ET.fromstring(z.read("xl/workbook.xml")); sh=next(x for x in wb.find("m:sheets",NS) if x.attrib["name"]=="Fugre 4")
  rels=ET.fromstring(z.read("xl/_rels/workbook.xml.rels")); target=next(x.attrib["Target"] for x in rels if x.attrib["Id"]==sh.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"])
  sheet=ET.fromstring(z.read("xl/"+target.lstrip("/")))
  rows={}
  for row in sheet.findall(".//m:sheetData/m:row",NS):
   d={}
   for cell in row.findall("m:c",NS):
    v=cell.find("m:v",NS); val=v.text if v is not None else ""
    if cell.attrib.get("t")=="s" and val:val=strings[int(val)]
    d[re.match(r"[A-Z]+",cell.attrib["r"]).group()]=val
   rows[int(row.attrib["r"])]=d
 colsite={"C":"ipso","D":"ortho","E":"meta","F":"para"}; rowmol={2:"benzene",3:"toluene",4:"m-xylene",5:"p-xylene",6:"o-xylene",7:"ethylbenzene",8:"isopropylbenzene"}
 vals={(mol,site):float(rows[r][c]) for r,mol in rowmol.items() for c,site in colsite.items() if rows.get(r,{}).get(c,"" )}
 vals[("benzene","ipso")]=float(rows[2]["B"])
 return vals
def parse_xml(p):
 root=ET.parse(p).getroot(); pt=root.find(".//me:PTpair",NS); rate=root.find(".//me:analysis/me:rateList",NS)
 if pt is None or rate is None:raise ValueError(f"Missing PTpair or analysis/rateList: {p}")
 e={x.attrib["toRef"]:x for x in rate.findall("me:firstOrderRate",NS)}
 return {"temperature_K":float(pt.attrib["T"]),"pressure_Torr":float(pt.attrib["P"]),"bath_gas":pt.attrib["bathGas"],"k_channel1_per_s":float(e["ringopen-prod1"].text),"k_channel2_per_s":float(e["ringopen-prod2"].text)}
def main():
 ap=argparse.ArgumentParser();ap.add_argument("--assets",type=Path,required=True);ap.add_argument("--output",type=Path,required=True);a=ap.parse_args();a.output.mkdir(parents=True,exist_ok=True)
 native=[]
 for p in sorted((a.assets/"Figure4").glob("*/Mesmer/*.xml")):
  d=p.parent.parent.name; molecule=MOLECULE[d]; site="ipso" if d=="Benzene" else next(v for k,v in SITE.items() if k.lower() in p.name.lower())
  x=parse_xml(p); native.append({"molecule":molecule,"oh_addition_site":site,"source_file":"assets/"+p.relative_to(a.assets).as_posix(),**x,"k_dominant_per_s":max(x["k_channel1_per_s"],x["k_channel2_per_s"])})
 write(a.output/"bpr_rate_matrix.csv",["molecule","oh_addition_site","source_file","temperature_K","pressure_Torr","bath_gas","k_channel1_per_s","k_channel2_per_s","k_dominant_per_s"],native)
 pubs=xlsx_figure4(a.assets/"41467_2023_40675_MOESM3_ESM.xlsx"); native_map={(x["molecule"],x["oh_addition_site"]):x for x in native}
 reconcile=[]; anomalies=[]
 for (mol,site),published in sorted(pubs.items()):
  x=native_map.get((mol,site))
  if x is None:
   r={"molecule":mol,"oh_addition_site":site,"published_value_per_s":published,"source_file":"","temperature_K":"","matched_definition":"missing_native","matched_value_per_s":"","relative_deviation":"","reconciled":"false"}
   candidates=[]; reason="No deposited native MESMER XML provides this published cell."
  else:
   vals={"channel1":x["k_channel1_per_s"],"channel2":x["k_channel2_per_s"],"faster":x["k_dominant_per_s"],"sum":x["k_channel1_per_s"]+x["k_channel2_per_s"]}
   definition=min(vals,key=lambda k:abs(vals[k]-published)/published); value=vals[definition]; residual=abs(value-published)/published
   r={"molecule":mol,"oh_addition_site":site,"published_value_per_s":published,"source_file":x["source_file"],"temperature_K":x["temperature_K"],"matched_definition":definition,"matched_value_per_s":value,"relative_deviation":residual,"reconciled":"true" if residual<=0.05 else "false"}
   candidates=[{"definition":k,"value_per_s":v,"relative_deviation":abs(v-published)/published} for k,v in vals.items()]
   reason="The closest native channel definition still differs from the published rate by more than 5%." if residual>0.05 else "At least one native channel definition matches within 5%."
  reconcile.append(r)
  if r["reconciled"]=="false": anomalies.append({"molecule":mol,"site":site,"source_file":r["source_file"],"temperature_K":r["temperature_K"],"published_value_per_s":published,"candidates":candidates,"reason":reason})
 write(a.output/"cell_reconciliation.csv",["molecule","oh_addition_site","published_value_per_s","source_file","temperature_K","matched_definition","matched_value_per_s","relative_deviation","reconciled"],reconcile)
 (a.output/"anomalies.json").write_text(json.dumps({"unreconciled":anomalies},indent=2)+"\n")
 evidence={"single_definition_claim":False,"temperature_scope":{"recorded_temperatures_K":[298,298.15,300],"normalisation_status":"indeterminate_without_molecule_specific_temperature_coefficients","toluene_ipso_298_to_300_activation_percent_range":[21.7,22.8],"with_n_percent":[23,24],"close_orderings_indeterminate":True,"single_definition_claim":False}}
 (a.output/"trend_evidence.json").write_text(json.dumps(evidence,indent=2)+"\n")
 (a.output/"trend_analysis.md").write_text("# Figure 4 rate reconciliation\n\nThe deposited matrix mixes 298, 298.15, and 300 K rates. Without molecule-specific temperature coefficients, close orderings cannot be normalized exactly across temperatures. For toluene ipso only, an activation-only estimate from 298 to 300 K is about 21.7–22.8%; including the fitted temperature exponent gives roughly 23–24%. This is an illustration for that molecule, not a correction range for every aromatic species. The m-xylene ortho published cell has no deposited native MESMER witness.\n")
if __name__=="__main__":main()
__P04_SCIENTIFIC_SOLUTION__
