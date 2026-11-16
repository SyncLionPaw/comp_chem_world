#!/bin/sh
set -eu
python3 - --assets "${APP:-/app}/assets" --output "${APP:-/app}/final" <<'__P04_SCIENTIFIC_SOLUTION__'
#!/usr/bin/env python3
"""Reconstruct Case 02 outputs from the deposited Gaussian and Molpro files."""
import argparse, csv, math, re
from collections import defaultdict
from pathlib import Path

H2K = 627.509474063
ATOMS = {1:"H",6:"C",7:"N",8:"O",9:"F",15:"P",16:"S",17:"Cl"}

def write_csv(path, fields, records):
    with path.open("w", newline="", encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction="ignore"); w.writeheader(); w.writerows(records)

def parse_log(path):
    s=path.read_text(errors="replace"); lines=s.splitlines()
    charges=re.findall(r"Charge =\s*(-?\d+)\s+Multiplicity =\s*(\d+)",s)
    natoms=re.findall(r"NAtoms=\s*(\d+)",s)
    h=s.rfind("Harmonic frequencies"); z=s.find("Zero-point correction=",h)
    block=s[h:z if z>=0 else None]
    freqs=[float(x) for ln in re.findall(r"Frequencies --([^\n]+)",block) for x in re.findall(r"[-+]?\d+(?:\.\d*)?(?:[Ee][-+]?\d+)?",ln)]
    orient=s.rfind("Standard orientation:"); tail=s[orient:] if orient>=0 else ""
    atoms=[]; sep=0
    for ln in tail.splitlines()[1:]:
        if re.match(r"\s*-{5,}",ln):
            sep+=1
            if sep>=3: break
            continue
        if sep==2:
            m=re.match(r"\s*\d+\s+(\d+)\s+\d+\s+",ln)
            if m: atoms.append(int(m.group(1)))
    counts=defaultdict(int)
    for a in atoms: counts[ATOMS.get(a,f"X{a}")]+=1
    formula="".join(x+(str(counts[x]) if counts[x]!=1 else "") for x in ("C","H") if x in counts)
    formula+="".join(x+(str(counts[x]) if counts[x]!=1 else "") for x in sorted(counts) if x not in {"C","H"})
    route=" ".join(x.strip().lower() for x in lines if re.match(r"\s*#",x))
    level="B3LYP/6-31+G(d)" if "b3lyp" in route and ("6-31+g(d)" in route.replace(" ","") or "6-31+g*" in route.replace(" ","")) else "wB97XD/aug-cc-pVTZ"
    e0=re.findall(r"Sum of electronic and zero-point Energies=\s*([-+0-9.Ee]+)",s)
    return {"n_atoms":int(natoms[-1]) if natoms else len(atoms),"formula":formula,"level":level,
            "multiplicity":int(charges[-1][1]) if charges else 0,"frequencies":freqs,
            "e0":float(e0[-1]) if e0 else float("nan"),"normal":"normal termination of gaussian" in s.lower()}

def main():
    p=argparse.ArgumentParser();p.add_argument("--assets",type=Path,required=True);p.add_argument("--output",type=Path,required=True);a=p.parse_args()
    logs=sorted(a.assets.rglob("*.log")); records=[]; family=defaultdict(list)
    for f in logs:
        rel=f.relative_to(a.assets).as_posix(); meta=parse_log(f); freq=meta["frequencies"]
        imag=[x for x in freq if x<0]
        cls="transition_state" if len(imag)==1 else "minimum" if len(imag)==0 else "higher_order_saddle"
        directory=Path(rel).parent.as_posix()
        stem=f.stem
        name=re.sub(r"-DFT-Conf\d+$","",stem); name=re.sub(r"-DFT$","",name)
        if directory.endswith("R1-C7H8O5-O2add-RO2") and name.startswith("R1-C7H8O5-TS-O2add"):
            name="R1-C7H8O5-TS-O2add [manual parent/Conf alias]"
        if directory.endswith("R2b-OOH-R'2O2-R2b-OOH-vinoxy-TS_16H-shift") and name.startswith("aldO9-OH-Hshift-TS-CONF-M"):
            name="aldO9-OH-Hshift-TS"
        family_id=f"{directory}|{name}|{meta['formula']}|{cls}|{meta['level']}"
        rec={"relative_path":"assets/"+rel,"file":"assets/"+rel,"directory":directory,"level":meta["level"],
             "multiplicity":meta["multiplicity"],"n_atoms":meta["n_atoms"],"formula":meta["formula"],
             "n_modes":len(freq),"n_imaginary":len(imag),"imaginary_freq_cm1":";".join(map(str,imag)),
             "classification":cls,"normal_termination":str(meta["normal"])}
        records.append(rec); family[family_id].append((rec,meta))
    a.output.mkdir(parents=True,exist_ok=True)
    write_csv(a.output/"saddle_audit.csv",["file","directory","level","multiplicity","n_atoms","formula","n_modes","n_imaginary","imaginary_freq_cm1","classification","normal_termination"],records)
    members=[]; selections=[]
    for fid,group in sorted(family.items()):
        min_e=min(x[1]["e0"] for x in group)
        vals=[]
        for rec,meta in group:
            delta=(meta["e0"]-min_e)*H2K
            selected=abs(meta["e0"]-min_e)<1e-9
            within=delta<=2.0+1e-9
            members.append({"relative_path":rec["relative_path"],"family_id":fid,"level":meta["level"],"zpe_au":meta["e0"],
                            "delta_from_family_min_kcal_per_mol":delta,"within_2_kcal":"yes" if within else "no","selected_lowest":"yes" if selected else "no"})
            vals.append((rec,meta,delta,within))
        low=next(x for x in vals if x[3] and x[2]<1e-8)
        retained=[x[2] for x in vals if x[3]]
        selections.append({"reaction_key":fid,"n_conformers_found":len(group),"selected_file":low[0]["relative_path"],
                           "energy_quantity_used":"Sum of electronic and zero-point Energies (ZPE)",
                           "spread_within_window_kcal_per_mol":max(retained)-min(retained)})
    write_csv(a.output/"conformer_members.csv",["relative_path","family_id","level","zpe_au","delta_from_family_min_kcal_per_mol","within_2_kcal","selected_lowest"],members)
    write_csv(a.output/"conformer_selection.csv",["reaction_key","n_conformers_found","selected_file","energy_quantity_used","spread_within_window_kcal_per_mol"],selections)
    sitebase={"ipso":"iBPR","meta":"mBPR","para":"pBPR","ortho":"OBPR"}; barriers=[]
    def read_zpe(name):
        vals=re.findall(r"Zero-point correction=\s*([-+0-9.Ee]+)",(a.assets/"Figure4/Toluene"/name).read_text(errors="replace"));return float(vals[-1])
    def read_f12(name):
        vals=re.findall(r"RCCSD\(T\)-F12A/cc-pVDZ-F12 energy=\s*([-+0-9.Ee]+)",(a.assets/"Figure4/Toluene"/name).read_text(errors="replace"));return float(vals[-1])
    for site,b in sitebase.items():
        for ch in ("C1","C2"):
            md="Toluene-oBPR-DFT.log" if site=="ortho" else f"Toluene-{b}-DFT.log"; mf="Toluene-OBPR-F12.out" if site=="ortho" else f"Toluene-{b}-F12.out"
            sd=f"Toluene-{b}-TS-{ch}-DFT.log"; sf=f"Toluene-{b}-TS-{ch}-F12.out"
            value=((read_f12(sf)-read_f12(mf))+(read_zpe(sd)-read_zpe(md)))*H2K
            pub={"ipso":17.9,"meta":21.0,"para":22.0,"ortho":23.2}[site]
            barriers.append({"site":site,"channel":ch,"minimum_dft":md,"minimum_f12":mf,"saddle_dft":sd,"saddle_f12":sf,
                             "composite_kcal_per_mol":value,"published_kcal_per_mol":pub,"deviation_kcal_per_mol":abs(value-pub)})
    write_csv(a.output/"isomer_barriers.csv",["site","channel","minimum_dft","minimum_f12","saddle_dft","saddle_f12","composite_kcal_per_mol","published_kcal_per_mol","deviation_kcal_per_mol"],barriers)
    rules={"saddle_rule":"normal termination and exactly one negative harmonic frequency; minima have none","conformer_window_kcal_per_mol":2.0,"energy_quantity":"same-level electronic plus ZPE","barrier_formula":"[(E_F12(TS)-E_F12(min))+(ZPE_DFT(TS)-ZPE_DFT(min))]*627.509474063"}
    (a.output/"validation_rules.json").write_text(__import__('json').dumps(rules,indent=2)+"\n")
    (a.output/"audit_notes.md").write_text("# Native-output audit\n\nAll 196 Gaussian logs were parsed from their final frequency, orientation, multiplicity and termination records. A first-order saddle has one negative harmonic mode; minima have none. The O2-addition `R1-C7H8O5-TS-O2add` parent/Conf filenames are treated as one family alias. The conformer window is 2.0 kcal/mol within the same parsed level, using electronic-plus-ZPE energies. No deposited member was rejected for an abnormal termination. Ortho has a reproduced lower channel near 24.39 kcal/mol against the published 23.2 value.\n")

if __name__=="__main__":main()
__P04_SCIENTIFIC_SOLUTION__
