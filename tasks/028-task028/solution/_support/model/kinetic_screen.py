#!/usr/bin/env python3
"""Exact/independently checked early-time competition for a preformed toluene i-BPR.

This is a narrow first-pass model, not a complete atmospheric oxidation network.
It only implements the two reported unimolecular ring-opening channels and the
SI's lumped i-BPR + NO loss. It deliberately leaves downstream O2/HO2 kinetics
unmodeled until species- and condition-appropriate source parameters are supplied.
"""
from __future__ import annotations
import csv, hashlib, json, math, platform, sys, os
import re
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZipFile
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(os.environ.get("CASE08_OUTPUT_DIR", str(ROOT / "model"))).resolve()
RATE_FILE = ROOT / "data" / "rate_evidence.csv"
SOURCE_MANIFEST = ROOT / "sources" / "source-manifest.json"
K_B = 1.380649e-23
REQUIRED = {
    "i-BPR -> P-C1": ("s^-1", "preformed toluene-derived ipso-BPR"),
    "i-BPR -> P-C2": ("s^-1", "preformed toluene-derived ipso-BPR"),
    "i-BPR + NO -> nitrate/NO-derived sinks": ("cm^3 molecule^-1 s^-1",
        "preformed toluene-derived i-BPR; SI assumes NO is sole fate"),
}
SECONDS = tuple(sorted(set([i / 10 for i in range(101)] + [0.83, 1.50, 3.68])))
NO_PPBV = (0.0, 1.0, 10.0, 200.0)
MESMER_MEMBER_SHA256 = "e919fd67260d98c5bbbf2edff3a114ce54ba336e3bdd59556856abea5f4f6516"
MESMER_MEMBER_FILE = "Toluene-ipso-HR-300-mesmer_out.xml"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_pinned_rates() -> tuple[dict[str, float], float, float]:
    """Read parameters from source-linked CSV and recheck acquired source hashes."""
    manifest=json.loads(SOURCE_MANIFEST.read_text())
    if manifest.get("schema") != "case08-reference-sources/v1":
        raise ValueError("unsupported source acquisition manifest")
    files={}
    for item in manifest.get("files", []):
        p=ROOT/"sources"/item["file"]
        if p.is_symlink() or not p.is_file():
            raise ValueError(f"missing or unsafe acquired source: {item['file']}")
        if sha(p) != item["sha256"] or p.stat().st_size != item["bytes"]:
            raise ValueError(f"acquired source pin mismatch: {item['file']}")
        files[item["file"]]=item["sha256"]
    article_tree=ET.parse(ROOT/"sources"/"article.xml")
    article_text=" ".join("".join(node.itertext()) for node in article_tree.iter() if node.tag.endswith("p"))
    normalized_article=re.sub(r"\s+"," ",article_text)
    rate_match=re.search(r"At P\s*=\s*1 atm and T\s*=\s*300 K, the unimolecular rate coefficients of the two pathways are\s*([0-9.]+)\s*s−1 and\s*([0-9.]+)\s*s−1, respectively",normalized_article)
    if not rate_match:
        raise ValueError("primary article no longer supports the pinned i-BPR rates/conditions")
    article_rates=(float(rate_match.group(1)),float(rate_match.group(2)))
    archive_item=manifest.get("archive_member")
    if not isinstance(archive_item,dict) or archive_item.get("source_file")!="QC-Files3.zip":
        raise ValueError("public MESMER archive extraction provenance is missing")
    archived_xml=(ROOT/"sources"/MESMER_MEMBER_FILE).read_bytes()
    archived_sha=hashlib.sha256(archived_xml).hexdigest()
    if archived_sha!=MESMER_MEMBER_SHA256 or archive_item.get("sha256")!=MESMER_MEMBER_SHA256:
        raise ValueError("MESMER output member differs from the reviewed public archive member")
    archived_root=ET.fromstring(archived_xml)
    rate_list=next((node for node in archived_root.iter() if node.tag.endswith("rateList")),None)
    if rate_list is None or rate_list.attrib.get("T")!="300" or rate_list.attrib.get("units")!="s-1" or rate_list.attrib.get("bathGas")!="N2":
        raise ValueError("MESMER rateList conditions/units differ from reviewed conditions")
    concentration=float(rate_list.attrib["conc"])
    ideal_300k_1atm=101325/(K_B*300)/1e6
    if abs(concentration/ideal_300k_1atm-1)>2e-5:
        raise ValueError("MESMER concentration does not correspond to 300 K, 1 atm ideal-gas density")
    archived_rates={node.attrib.get("toRef"):float(node.text) for node in rate_list if node.tag.endswith("firstOrderRate")}
    if set(archived_rates)!={"ringopen-prod1","ringopen-prod2"}:
        raise ValueError("unexpected MESMER product/channel references")
    exact_channel_rates=(archived_rates["ringopen-prod1"],archived_rates["ringopen-prod2"])
    si_path=ROOT/"sources"/"41467_2023_40675_MOESM1_ESM.docx"
    ns={"w":"http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    with ZipFile(si_path) as archive:
        si_doc=ET.fromstring(archive.read("word/document.xml"))
    source_no_rate=None
    for paragraph in si_doc.findall(".//w:p",ns):
        runs=paragraph.findall("./w:r",ns)
        for index,run in enumerate(runs):
            text="".join(x.text or "" for x in run.findall("./w:t",ns))
            if "9.15" not in text:
                continue
            sequence=[]
            for next_run in runs[index+1:index+5]:
                value="".join(x.text or "" for x in next_run.findall("./w:t",ns))
                symbol=next_run.find("./w:sym",ns)
                if symbol is not None and symbol.attrib.get("{%s}char" % ns["w"]) == "F0B4":
                    value="×"
                align=next_run.find("./w:rPr/w:vertAlign",ns)
                vertical=align.attrib.get("{%s}val" % ns["w"]) if align is not None else None
                sequence.append((value.strip(),vertical))
            if sequence[:4] == [("×",None),("10",None),("-1","superscript"),("2","superscript")]:
                mantissa_match=re.search(r"([0-9]+(?:\.[0-9]+)?)\s*$",text)
                if mantissa_match:
                    source_no_rate=float(mantissa_match.group(1))*10**-12
    if source_no_rate is None:
        raise ValueError("SI source does not verify the 9.15 × 10^-12 coefficient typography")
    rows={}; conditions=set()
    with RATE_FILE.open(newline="") as stream:
        for row in csv.DictReader(stream):
            key=row["reaction"]
            if key in rows or key not in REQUIRED:
                raise ValueError("unexpected or duplicated kinetic parameter row")
            unit,population=REQUIRED[key]
            if row["rate_units"] != unit or row["reactant_population"] != population:
                raise ValueError(f"unit or population mismatch for {key}")
            conditions.add((float(row["temperature_K"]),float(row["pressure_atm"])))
            if row["source_file"] not in files and row["source_file"] != archive_item.get("source_file"):
                raise ValueError(f"rate row cites a source absent from the acquisition manifest: {key}")
            if not row["source_locator"] or not row["source_locator"].strip():
                raise ValueError(f"missing source locator for {key}")
            rate=float(row["rate_value"])
            if not math.isfinite(rate) or rate <= 0:
                raise ValueError(f"invalid rate for {key}")
            rows[key]=rate
    if set(rows) != set(REQUIRED):
        raise ValueError("kinetic rate evidence CSV does not contain the exact required rows")
    if len(conditions) != 1:
        raise ValueError("kinetic rates do not share the same temperature and pressure")
    temperature,pressure_atm=next(iter(conditions))
    if temperature != 300 or pressure_atm != 1:
        raise ValueError("conditions do not match the reported i-BPR rate conditions")
    if (rows["i-BPR -> P-C1"],rows["i-BPR -> P-C2"]) != exact_channel_rates:
        raise ValueError("CSV channel rates differ from pinned MESMER output")
    if tuple(round(x,2) for x in exact_channel_rates) != article_rates:
        raise ValueError("MESMER channel rates do not round to the article's reported values/order")
    if rows["i-BPR + NO -> nitrate/NO-derived sinks"] != source_no_rate:
        raise ValueError("CSV NO coefficient differs from the SI superscript-verified source")
    return rows, temperature, pressure_atm*101325.0


RATES, T, P_PA = read_pinned_rates()
P_ATM = 1.0
K_C1 = RATES["i-BPR -> P-C1"]
K_C2 = RATES["i-BPR -> P-C2"]
K_NO = RATES["i-BPR + NO -> nitrate/NO-derived sinks"]


def simulate(t: float, no_ppbv: float, k1: float = K_C1,
             k2: float = K_C2, kno: float = K_NO) -> dict[str, float]:
    """Analytic solution for I -> C1/C2 and I+NO -> lumped sink, I(0)=1."""
    gas_cm3 = P_PA / (K_B * T) / 1e6
    no_cm3 = no_ppbv * 1e-9 * gas_cm3
    k_loss = kno * no_cm3
    total = k1 + k2 + k_loss
    remaining = math.exp(-total * t)
    reacted = -math.expm1(-total * t)
    c1 = (k1 / total) * reacted
    c2 = (k2 / total) * reacted
    no_sink = (k_loss / total) * reacted
    return {"time_s":t,"no_ppbv":no_ppbv,"no_molecule_cm3":no_cm3,
        "k_NO_pseudo_s-1":k_loss,"iBPR":remaining,"P-C1":c1,"P-C2":c2,
        "NO_lumped_sink":no_sink,"mass_closure":remaining+c1+c2+no_sink,
        "open_fraction_of_initial":c1+c2,
        "C1_fraction_of_opened":k1/(k1+k2),
        "C2_fraction_of_opened":k2/(k1+k2)}


def rk4(t: float, no_ppbv: float, dt: float) -> list[float]:
    """Independent explicit RK4 integration for convergence verification."""
    gas_cm3 = P_PA / (K_B * T) / 1e6
    rates = (K_C1, K_C2, K_NO * no_ppbv * 1e-9 * gas_cm3)
    state = [1.0, 0.0, 0.0, 0.0]
    def deriv(y):
        i = y[0]
        return [-sum(rates)*i, rates[0]*i, rates[1]*i, rates[2]*i]
    n = math.ceil(t/dt)
    h = t/n
    for _ in range(n):
        a=deriv(state)
        b=deriv([y+h*x/2 for y,x in zip(state,a)])
        c=deriv([y+h*x/2 for y,x in zip(state,b)])
        d=deriv([y+h*x for y,x in zip(state,c)])
        state=[y+h*(x+2*z+2*q+w)/6 for y,x,z,q,w in zip(state,a,b,c,d)]
    return state


def main() -> None:
    OUT.mkdir(exist_ok=True)
    source_manifest = json.loads(SOURCE_MANIFEST.read_text())
    archive_item = source_manifest["archive_member"]
    started=datetime.now(timezone.utc).isoformat()
    rows=[simulate(t,no) for t in SECONDS for no in NO_PPBV]
    with (OUT/"early_competition.csv").open("w",newline="") as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    sensitivity=[]
    for f1 in (0.1,1.0,10.0):
      for f2 in (0.1,1.0,10.0):
       for fno in (0.1,1.0,10.0):
        d=simulate(1.5,1.0,K_C1*f1,K_C2*f2,K_NO*fno)
        sensitivity.append({"time_s":1.5,"no_ppbv":1.0,"k1_factor":f1,
           "k2_factor":f2,"kno_factor":fno,"P-C1":d["P-C1"],"P-C2":d["P-C2"],
           "NO_lumped_sink":d["NO_lumped_sink"],"mass_closure":d["mass_closure"],
           "uncertainty_label":"order-of-magnitude stress test; not a confidence interval"})
    with (OUT/"stress_sensitivity.csv").open("w",newline="") as f:
        w=csv.DictWriter(f,fieldnames=list(sensitivity[0]));w.writeheader();w.writerows(sensitivity)
    checks=[]
    for no in NO_PPBV:
      exact=simulate(3.68,no)
      for dt in (0.1,0.01,0.001):
        numeric=rk4(3.68,no,dt)
        err=max(abs(x-y) for x,y in zip(numeric,[exact['iBPR'],exact['P-C1'],exact['P-C2'],exact['NO_lumped_sink']]))
        checks.append({"no_ppbv":no,"dt_s":dt,"max_abs_RK4_vs_exact":err,
                       "nonnegative":min(numeric)>=-1e-12,"mass_closure":sum(numeric)})
    accepted=[x for x in checks if x["dt_s"] <= 0.01]
    coarse=[x for x in checks if x["dt_s"] > 0.01]
    accepted_error=max(x["max_abs_RK4_vs_exact"] for x in accepted)
    accepted_closure=max(abs(x["mass_closure"]-1) for x in accepted)
    accepted_nonnegative=all(x["nonnegative"] for x in accepted)
    validation={"schema":"case08-kinetic-screen-validation/v1","initial_population":"1.0 preformed toluene i-BPR molecule-equivalent",
      "active_reactions":[f"i-BPR -> P-C1, k={K_C1:.6g} s^-1 (public MESMER output)",f"i-BPR -> P-C2, k={K_C2:.6g} s^-1 (public MESMER output)","i-BPR + NO -> lumped sink, k=9.15e-12 cm3 molecule^-1 s^-1 (unit dimension inferred; SI coefficient source-checked)"],
      "conditions":{"temperature_K":T,"pressure_atm":P_ATM,"ideal_gas_NO_conversion":True},
      "checks":{"accepted_step_sizes_s":[0.01,0.001],"accepted_grid_nonnegative":accepted_nonnegative,
        "accepted_grid_max_mass_closure_error":accepted_closure,"accepted_grid_max_RK4_exact_error":accepted_error,
        "accepted_grid_pass":accepted_nonnegative and accepted_closure < 1e-10 and accepted_error < 1e-9,
        "coarse_step_failures_retained":coarse,"all_step_results":checks},
      "scope_limit":"No post-open O2 autoxidation, HO2 termination, product yields, precursor formation, or aerosol mass yield is computed. No species-specific post-open rate was found in the acquired article/SI. O2 and HO2 scans are therefore a blocked next step, not omitted zeros.",
      "started_at_utc":started,"python":sys.version,"platform":platform.platform(),
      "input_sha256":{"rate_evidence.csv":sha(RATE_FILE),"QC-Files3.zip":archive_item["source_sha256"],"MESMER_output_member":MESMER_MEMBER_SHA256,
        "source-manifest.json":sha(SOURCE_MANIFEST),
        "mesmer_output_member":sha(ROOT/"sources"/MESMER_MEMBER_FILE),
        "kinetic_screen.py":sha(Path(__file__))},
      "output_sha256":{"early_competition.csv":sha(OUT/"early_competition.csv"),"stress_sensitivity.csv":sha(OUT/"stress_sensitivity.csv")}}
    (OUT/"validation.json").write_text(json.dumps(validation,indent=2)+"\n")
    receipt={"schema":"case08-local-preparation-run/v1","command":"python3 model/kinetic_screen.py","started_at_utc":started,"finished_at_utc":datetime.now(timezone.utc).isoformat(),"status":"completed_local_analysis_only","python":sys.version.split()[0],"script_sha256":sha(Path(__file__)),"input_sha256":{"rate_evidence.csv":sha(RATE_FILE)},"output_sha256":{"early_competition.csv":sha(OUT/"early_competition.csv"),"stress_sensitivity.csv":sha(OUT/"stress_sensitivity.csv"),"validation.json":sha(OUT/"validation.json")},"hpc_job_id":None,"allocated_cpu_hours":0,"receipt_note":"This local calculation has no HPC scheduler receipt and is preparation evidence only, not a Case08 completion claim."}
    (OUT/"run-receipt.json").write_text(json.dumps(receipt,indent=2)+"\n")
    print(json.dumps({"rows":len(rows),"sensitivity_rows":len(sensitivity),"checks":validation['checks'],"outputs":validation['output_sha256']},indent=2))

if __name__ == "__main__": main()
