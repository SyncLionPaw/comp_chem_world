#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# L1 Deliverables: Check required deliverables for completeness and parseability.
# L2 Execution: Check the use of supplied data or archived evidence where required.
# L3 Science: Finite-temperature SiO₂ phase stability and free-energy sensitivity.
"""Case02 masked Gibbs-grid verifier: exit 0 PASS, 1 candidate FAIL, 2 ENV_ERROR."""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import itertools
import io
import base64
import zlib
import json
import math
import os
import sys
from pathlib import Path

try:
    import numpy as np
    from scipy.optimize import brentq
except ImportError as exc:
    print(f"ENV_ERROR: required scientific dependency unavailable: {exc}", file=sys.stderr)
    raise SystemExit(2)

csv.field_size_limit(sys.maxsize)
REF_PAYLOADS = {}
_REF_CACHE = {}

def ref_bytes(label):
    if label in _REF_CACHE: return _REF_CACHE[label]
    item=REF_PAYLOADS[label]; data=base64.b64decode(item["data"])
    if item["encoding"]=="zlib+base64": data=zlib.decompress(data)
    if len(data)!=item["size"] or hashlib.sha256(data).hexdigest()!=item["sha256"]: raise EvaluatorEnvError(f"corrupt encoded reference: {label}")
    _REF_CACHE[label]=data
    return data

def ref_text(label): return ref_bytes(label).decode("utf-8-sig")

def verify_large_encoded_hash(label):
    item=REF_PAYLOADS[label]
    packed=base64.b64decode(item["data"])
    h=hashlib.sha256(); size=0
    if item["encoding"]=="zlib+base64":
        dec=zlib.decompressobj()
        for offset in range(0,len(packed),1<<20):
            chunk=dec.decompress(packed[offset:offset+(1<<20)])
            h.update(chunk); size+=len(chunk)
        chunk=dec.flush(); h.update(chunk); size+=len(chunk)
    else:
        for offset in range(0,len(packed),1<<20):
            chunk=packed[offset:offset+(1<<20)]; h.update(chunk); size+=len(chunk)
    if size!=item["size"] or h.hexdigest()!=item["sha256"]: raise EvaluatorEnvError(f"corrupt encoded reference: {label}")
    return True

PHASES = ("alpha_quartz", "beta_quartz", "coesite", "cristobalite", "melt", "tridymite", "tridymite_low")
GRID_HEADER = ["T_K", "P_bar", "valid_phases", "G_min_meV_per_atom", "stable_phase", "reason"]
BOUNDARY_HEADER = ["boundary_id", "phase_a", "phase_b", "T_K", "P_bar", "kind", "valid_overlap", "uncertainty_bar", "basis", "reason"]
SENS_HEADER = ["perturbation_meV_per_atom", "perturbed_phase", "sign", "boundary_id", "phase_a", "phase_b", "T_K", "nominal_P_bar", "perturbed_P_bar", "delta_P_bar", "valid_overlap", "ambiguous_domain", "reason"]


class CandidateFail(Exception): pass
class EvaluatorEnvError(Exception): pass


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def read_json(path, env=False):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        error = EvaluatorEnvError if env else CandidateFail
        raise error(f"invalid JSON {path}: {exc}") from exc


def load_reference(refdir: Path, root: Path):
    refs=json.loads(((refdir/"refs.json") if refdir.is_dir() else (refdir.parent/"refs.json")).read_text(encoding="utf-8"))
    global REF_PAYLOADS
    REF_PAYLOADS=refs["_private_payloads"]
    _REF_CACHE.clear()
    meta=json.loads(ref_bytes("private/reference_metadata.json").decode("utf-8"))
    for group, records in (("input",meta.get("input_hashes",{})),("author",meta.get("author_references",{}))):
        for name,digest in records.items():
            label="source/"+name; item=REF_PAYLOADS.get(label)
            if item is None or item["sha256"]!=digest: raise EvaluatorEnvError(f"missing/corrupt encoded {group} reference: {name}")
            if item["encoding"]=="public-asset":
                continue
            verify_large_encoded_hash(label)
    for name,digest in meta.get("reference_artifacts",{}).items():
        label="private/"+name; item=REF_PAYLOADS.get(label)
        if item is None or item["sha256"]!=digest: raise EvaluatorEnvError(f"missing/corrupt encoded artifact: {name}")
        verify_large_encoded_hash(label)
    grid=gzip.GzipFile(fileobj=io.BytesIO(ref_bytes("private/reference_phase_grid.csv.gz")),mode="rb")
    header=next(csv.reader(io.TextIOWrapper(grid,encoding="utf-8",newline="")))
    if header != ["T_K","P_bar","valid_phases","G_min_meV_per_atom","stable_phase"]: raise EvaluatorEnvError("wrong hidden reference grid header")
    return meta


def public_phase_diagram_root(base: Path) -> Path:
    for candidate in (base / "inputs/phase_diagram", base / "environment/assets/phase_diagram",
                      base / "assets/phase_diagram", base / "phase_diagram"):
        if candidate.is_dir():
            return candidate
    return base / "inputs/phase_diagram"


def load_fits(package: Path, metadata, input_root: Path | None = None):
    fits = {p: {} for p in PHASES}
    public_root = public_phase_diagram_root(input_root or package)
    for phase in PHASES:
        path = public_root / phase / "fit_gibbs_energy.csv"
        if not path.is_file(): raise EvaluatorEnvError(f"missing public input {path}")
        source_rel=f"raw_data/unpacked/results-277b5114949b/results/phase_diagram/{phase}/fit_gibbs_energy.csv"
        if sha256(path)!=metadata["input_hashes"].get(source_rel): raise EvaluatorEnvError(f"public input provenance/hash mismatch: {path}")
        try:
            with path.open(encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)
                required = ["", "temperature", "min_pressure", "max_pressure", "std", "maxdev", "polypara"]
                if reader.fieldnames != required: raise ValueError(f"wrong header {reader.fieldnames}; expected a blank zero-based source index plus {required[1:]}")
                for source_index,r in enumerate(reader):
                    if not r.get("temperature", "").strip(): continue
                    index=exact_int(r[""],f"{phase} source row index")
                    if index!=source_index: raise ValueError(f"nonconsecutive source row index {index}; expected {source_index}")
                    t = exact_int(r["temperature"],f"{phase} temperature")
                    coeff = np.fromstring(r["polypara"].strip().strip("[]"), sep=" ")
                    if len(coeff) != 4 or not np.isfinite(coeff).all(): raise ValueError(f"bad cubic {phase}/{t}")
                    fit = {"lo": float(r["min_pressure"]), "hi": float(r["max_pressure"]),
                           "std": float(r["std"]), "maxdev": float(r["maxdev"]), "coeff": coeff}
                    if not all(math.isfinite(fit[k]) for k in ("lo", "hi", "std", "maxdev")) or fit["hi"] <= fit["lo"] or fit["std"]<0 or fit["maxdev"]<0:
                        raise ValueError(f"bad pressure/error window {phase}/{t}")
                    fits[phase][t] = fit
        except Exception as exc: raise EvaluatorEnvError(f"corrupt public Gibbs input {path}: {exc}") from exc
    return fits


def verify_grid(path: Path, refdir: Path, fits, meta, refs):
    if not path.is_file(): raise CandidateFail("missing outputs/phase_grid.csv")
    try:
        with path.open(encoding="utf-8-sig", newline="") as cf, io.TextIOWrapper(gzip.GzipFile(fileobj=io.BytesIO(ref_bytes("private/reference_phase_grid.csv.gz")),mode="rb"),encoding="utf-8",newline="") as rf:
            cr, rr = csv.DictReader(cf), csv.DictReader(rf)
            if cr.fieldnames != GRID_HEADER: raise CandidateFail(f"phase_grid.csv wrong header: {cr.fieldnames}")
            count = 0
            for i, pair in enumerate(itertools.zip_longest(cr, rr), 1):
                got, ref = pair
                if got is None or ref is None:
                    raise CandidateFail("phase_grid row count differs from the frozen 601–3999 K, 100-bar lattice")
                count += 1
                if exact_int(got["T_K"],f"phase_grid row {i} T_K") != int(ref["T_K"]) or exact_int(got["P_bar"],f"phase_grid row {i} P_bar") != int(ref["P_bar"]):
                    raise CandidateFail(f"phase_grid row {i}: grid must cover 601–3999 K by 1 K and 0–50000 bar by 100 bar")
                active = set(ref["valid_phases"].split(";")) if ref["valid_phases"] else set()
                actual = set(got["valid_phases"].split(";")) if got["valid_phases"].strip() else set()
                if actual != active:
                    raise CandidateFail(f"phase_grid row {i}: valid-phase mask differs from min/max pressure windows")
                if ref["G_min_meV_per_atom"]:
                    g = float(got["G_min_meV_per_atom"]); gr = float(ref["G_min_meV_per_atom"])
                    if not math.isfinite(g) or abs(g-gr) > refs["phase_grid_energy_tolerance_meV_per_atom"]:
                        raise CandidateFail(f"phase_grid row {i}: lower-envelope Gibbs differs by {abs(g-gr):.5g} meV/atom")
                    if got["stable_phase"] != ref["stable_phase"]:
                        raise CandidateFail(f"phase_grid row {i}: stable phase differs from valid-phase lower envelope")
                elif got["G_min_meV_per_atom"].strip() or got["stable_phase"].strip() or not got["reason"].strip():
                    raise CandidateFail(f"phase_grid row {i}: empty phase set needs blank minimum/winner and mask reason")
            if next(cr, None) is not None or count == 0: raise CandidateFail("phase_grid row count differs from the frozen 601–3999 K, 100-bar lattice")
    except CandidateFail: raise
    except Exception as exc: raise CandidateFail(f"invalid phase_grid.csv: {exc}") from exc
    return count



def canonical_pair(a,b): return tuple(sorted((a,b)))

def exact_int(value,label):
    try: x=float(value)
    except (TypeError,ValueError) as exc: raise CandidateFail(f"{label} must be a finite integer") from exc
    if not math.isfinite(x) or abs(x-round(x))>1e-9: raise CandidateFail(f"{label} must be a finite integer")
    return int(round(x))


def finite_float(value,label):
    try: x=float(value)
    except (TypeError,ValueError) as exc: raise CandidateFail(f"{label} must be a finite number") from exc
    if not math.isfinite(x): raise CandidateFail(f"{label} must be a finite number")
    return x


def verify_boundaries(path: Path, refdir: Path, fits):
    if not path.is_file(): raise CandidateFail("missing outputs/boundaries.csv")
    expected=[]
    with io.StringIO(ref_text("private/reference_boundaries.csv"),newline="") as f:
        for row in csv.DictReader(f): expected.append(row)
    try:
        with path.open(encoding="utf-8-sig", newline="") as f:
            reader=csv.DictReader(f)
            if reader.fieldnames != BOUNDARY_HEADER: raise CandidateFail("boundaries.csv wrong exact header")
            rows=list(reader)
    except CandidateFail: raise
    except Exception as exc: raise CandidateFail(f"invalid boundaries.csv: {exc}") from exc
    if not rows: raise CandidateFail("boundaries.csv is empty")
    by_t_pair={}
    ids=set()
    for i,r in enumerate(rows,1):
        bid=r["boundary_id"].strip(); a,b=r["phase_a"],r["phase_b"]
        if not bid or bid in ids: raise CandidateFail(f"boundaries row {i}: boundary_id must be unique")
        ids.add(bid)
        if a not in PHASES or b not in PHASES or a==b: raise CandidateFail(f"boundaries row {i}: invalid phase pair")
        t=(int(round(finite_float(r["T_K"],f"boundary row {i} T_K"))) if r["kind"]=="alpha_beta_line" else exact_int(r["T_K"],f"boundary row {i} T_K")); p=finite_float(r["P_bar"],f"boundary row {i} P_bar"); unc=finite_float(r["uncertainty_bar"],f"boundary row {i} uncertainty_bar")
        minimum_uncertainty=0.0 if r["kind"]=="alpha_beta_line" else 50.0
        if unc < minimum_uncertainty: raise CandidateFail(f"boundaries row {i}: uncertainty must be >= {minimum_uncertainty:g} bar")
        if r["valid_overlap"].lower() not in {"true","false"}: raise CandidateFail(f"boundaries row {i}: valid_overlap must be boolean")
        by_t_pair.setdefault((t,canonical_pair(a,b)),[]).append((p,r))
    used_ids=set()
    for j,e in enumerate(expected):
        key=(int(e["T_K"]),canonical_pair(e["phase_a"],e["phase_b"]))
        is_cross="shared-valid Gibbs crossing" in e["basis"]
        expected_kind="crossing" if is_cross else "support_edge"
        candidates=[x for x in by_t_pair.get(key,[]) if x[1]["kind"]==expected_kind]
        if not candidates: raise CandidateFail(f"missing lower-envelope boundary T={key[0]} {key[1]}")
        available=[x for x in candidates if x[1]["boundary_id"] not in used_ids]
        if not available: raise CandidateFail(f"duplicate/missing boundary T={key[0]} {key[1]}")
        p,r=min(available,key=lambda x:abs(x[0]-float(e["P_bar_midpoint"])))
        used_ids.add(r["boundary_id"])
        unc=float(r["uncertainty_bar"])
        if abs(p-float(e["P_bar_midpoint"])) > 150.0:
            raise CandidateFail(f"boundary {r['boundary_id']} differs from independent lower-envelope bracket by >150 bar")
        if is_cross and (r["kind"]!="crossing" or r["valid_overlap"].lower()!="true"):
            raise CandidateFail(f"boundary {r['boundary_id']}: shared-support Gibbs root mislabeled as a mask edge")
        if not is_cross and r["kind"]!="support_edge":
            raise CandidateFail(f"boundary {r['boundary_id']}: valid-window edge must be labeled support_edge")
        if not r["basis"].strip(): raise CandidateFail(f"boundary {r['boundary_id']}: basis must explain how the boundary was identified")
        if is_cross:
            tkey=key[0]; fa=fits[key[1][0]].get(tkey); fb=fits[key[1][1]].get(tkey)
            if fa is None or fb is None: raise EvaluatorEnvError(f"missing fit metadata for boundary at {tkey} K")
            da=np.polyval(np.polyder(fa["coeff"]),p); db=np.polyval(np.polyder(fb["coeff"]),p)
            slope=abs(float(da-db))
            if slope<=1e-15: raise CandidateFail(f"boundary {r['boundary_id']}: zero Gibbs-pressure slope cannot support a finite uncertainty")
            sa=max(fa["std"],fa["maxdev"]); sb=max(fb["std"],fb["maxdev"])
            uncertainty=max(50.0,50.0+math.hypot(sa,sb)/slope)
            # Accept one-decimal reported uncertainties (e.g. 136.5 for 136.53877 bar).
            rounding_tolerance=max(0.05,1e-6*uncertainty)
            if unc<uncertainty-rounding_tolerance or unc>uncertainty*1.5+1:
                raise CandidateFail(f"boundary {r['boundary_id']}: uncertainty must propagate std/maxdev through |dΔG/dP| plus half-grid resolution ({uncertainty:.2f} bar)")
    # Extra boundaries are permitted only for the separate source-data alpha/beta line.
    for key, vals in by_t_pair.items():
        for _,r in vals:
            if r["boundary_id"] not in used_ids and not (key[1]==canonical_pair("alpha_quartz","beta_quartz") and r["kind"]=="alpha_beta_line"):
                raise CandidateFail(f"unsupported extra boundary row {r['boundary_id']}")
    return rows


def _pair_root(fa, fb, pressure_center, bias_ev=0.0):
    """Return the supported cubic-equality root nearest pressure_center, or None."""
    lo=max(fa["lo"],fb["lo"]); hi=min(fa["hi"],fb["hi"])
    if hi<=lo: return None
    coeff=fa["coeff"]-fb["coeff"]
    coeff[-1]+=bias_ev
    roots=np.roots(coeff)
    real=[float(x.real) for x in roots if abs(x.imag)<1e-6 and lo-1e-7<=x.real<=hi+1e-7]
    return min(real,key=lambda x:abs(x-pressure_center)) if real else None


def _representative_crossings(refdir: Path, candidate_rows):
    by_pair={}
    with io.StringIO(ref_text("private/reference_boundaries.csv"),newline="") as f:
        for r in csv.DictReader(f):
            if "shared-valid Gibbs crossing" not in r["basis"]: continue
            by_pair.setdefault(canonical_pair(r["phase_a"],r["phase_b"]),[]).append(r)
    result=[]
    for pair, rows in by_pair.items():
        rows.sort(key=lambda x:(int(x["T_K"]),float(x["P_bar_midpoint"])))
        ref=rows[len(rows)//2]
        options=[r for r in candidate_rows if canonical_pair(r["phase_a"],r["phase_b"])==pair and int(float(r["T_K"]))==int(ref["T_K"]) and r["kind"]=="crossing"]
        if not options: raise CandidateFail(f"missing representative sensitivity boundary for {pair}")
        result.append(min(options,key=lambda r:abs(float(r["P_bar"])-float(ref["P_bar_midpoint"]))))
    return result


def verify_sensitivity(path: Path, refdir: Path, rows, fits):
    if not path.is_file(): raise CandidateFail("missing outputs/sensitivity.csv")
    try:
        with path.open(encoding="utf-8-sig",newline="") as f:
            rd=csv.DictReader(f)
            if rd.fieldnames!=SENS_HEADER: raise CandidateFail("sensitivity.csv wrong exact header")
            got=list(rd)
    except CandidateFail: raise
    except Exception as exc: raise CandidateFail(f"invalid sensitivity.csv: {exc}") from exc
    selected=_representative_crossings(refdir,rows)
    expected={}
    for b in selected:
        pair=canonical_pair(b["phase_a"],b["phase_b"])
        for mag in (0.1,2.0,5.0):
            for phase in pair:
                for sign in (-1,1): expected[(b["boundary_id"],mag,phase,sign)]=(b,pair)
    keyed={}
    for i,r in enumerate(got,1):
        try:
            mag=float(r["perturbation_meV_per_atom"])
            sign={"+":1,"-":-1}.get(r["sign"], exact_int(r["sign"],f"sensitivity row {i} sign") if r["sign"] not in {"+","-"} else 0)
            key=(r["boundary_id"],mag,r["perturbed_phase"],sign)
        except Exception as exc: raise CandidateFail(f"sensitivity row {i}: invalid identity fields: {exc}") from exc
        if key in keyed: raise CandidateFail(f"sensitivity row {i}: duplicate perturbation identity")
        keyed[key]=r
    if set(keyed)!=set(expected): raise CandidateFail(f"sensitivity.csv must cover both boundary phases × both signs × 0.1/2/5 meV for each of {len(selected)} representative crossings")
    for key,(b,pair) in expected.items():
        r=keyed[key]; _,mag,phase,sign=key
        t=exact_int(b["T_K"],"sensitivity boundary T"); pgrid=float(b["P_bar"])
        a,bp=pair
        if (r["phase_a"],r["phase_b"]) not in {(a,bp),(bp,a)} or exact_int(r["T_K"],f"sensitivity {key} T")!=t:
            raise CandidateFail(f"sensitivity {key}: does not point to its declared nominal boundary")
        fit_a=fits[a].get(t); fit_b=fits[bp].get(t)
        if fit_a is None or fit_b is None: raise EvaluatorEnvError(f"sensitivity reference missing boundary polynomials at {t} K")
        pnom=float(r["nominal_P_bar"])
        if not math.isfinite(pnom) or abs(pnom-pgrid)>150.0: raise CandidateFail(f"sensitivity {key}: nominal root must remain within its grid boundary bracket")
        base_root=_pair_root(fit_a,fit_b,pgrid,0.0)
        if base_root is None or abs(base_root-pnom)>5.0: raise CandidateFail(f"sensitivity {key}: nominal_P_bar does not solve the unperturbed Gibbs equality")
        bias=sign*mag/1000.0*(1 if phase==a else -1)
        root=_pair_root(fit_a,fit_b,base_root,bias)
        if root is None:
            for field in ("perturbed_P_bar","delta_P_bar"):
                if r[field].strip(): finite_float(r[field],f"sensitivity {key} {field}")
            if r["valid_overlap"].lower()!="false" or r["ambiguous_domain"].lower()!="true" or not r["reason"].strip():
                raise CandidateFail(f"sensitivity {key}: a root outside the shared pressure window must be marked ambiguous with no valid overlap")
            continue
        pgot=float(r["perturbed_P_bar"]); dgot=float(r["delta_P_bar"])
        if not math.isfinite(pgot) or not math.isfinite(dgot) or abs(pgot-root)>5.0 or abs(dgot-(root-pnom))>5.0:
            raise CandidateFail(f"sensitivity {key}: shifted cubic root or delta-P is incorrect")
        if r["valid_overlap"].lower()!="true": raise CandidateFail(f"sensitivity {key}: root is inside both phases' fitted pressure windows")
        # If another valid phase beats this shifted pair, the two-phase boundary
        # is metastable under the perturbation and must be labeled ambiguous.
        actual_bias=sign*mag/1000.0
        ga=np.polyval(fit_a["coeff"],root)+(actual_bias if phase==a else 0)
        gb=np.polyval(fit_b["coeff"],root)+(actual_bias if phase==bp else 0)
        tie=(ga+gb)/2
        beaten=False
        for other in PHASES:
            if other in pair: continue
            f=fits[other].get(t)
            if f and f["lo"]<=root<=f["hi"] and np.polyval(f["coeff"],root)<tie-0.00005:
                beaten=True; break
        amb=r["ambiguous_domain"].lower()=="true"
        if r["ambiguous_domain"].lower() not in {"true","false"} or amb!=beaten:
            raise CandidateFail(f"sensitivity {key}: ambiguous_domain must reflect a lower competing phase")
        if amb and not r["reason"].strip(): raise CandidateFail(f"sensitivity {key}: ambiguous perturbation needs a reason")
    return len(got),len(selected)



def verify_alpha_beta(package: Path, metadata, boundary_rows, summary, input_root: Path | None = None):
    path=public_phase_diagram_root(input_root or package)/"alpha_quartz_beta_quartz.txt"
    try: raw=np.loadtxt(path)
    except Exception as exc: raise EvaluatorEnvError(f"invalid alpha-beta public input: {exc}") from exc
    if raw.shape != (15,3) or not np.isfinite(raw).all(): raise EvaluatorEnvError("alpha-beta raw input must be 15×3 finite pressure/temperature estimates")
    if sha256(path)!=metadata["alpha_beta"].get("source_sha256"): raise EvaluatorEnvError("alpha-beta public input provenance/hash mismatch")
    p,t1,t2=raw.T; mean=(t1+t2)/2
    coeff=np.polyfit(p/10000.0,mean,1)
    meta=metadata["alpha_beta"]
    if len(meta["all_input_points"])!=15 or np.max(np.abs(np.asarray(meta["author_fit_coefficients_desc_K_per_GPa_all_rows"])-coeff))>1e-7:
        raise EvaluatorEnvError("alpha-beta reference does not represent the 15-row all-data fit")
    ab=[r for r in boundary_rows if canonical_pair(r["phase_a"],r["phase_b"])==canonical_pair("alpha_quartz","beta_quartz") and r["kind"]=="alpha_beta_line"]
    if len(ab)<10: raise CandidateFail("need alpha-beta fit samples inside 2759–32400 bar plot window")
    treatment=summary.get("alpha_beta_treatment")
    if not isinstance(treatment,dict):
        raise CandidateFail("summary.alpha_beta_treatment must describe the unlabeled trajectory estimates")
    window=(p>=2759)&(p<=32400)
    nwindow=int(window.sum())
    fit_rows=exact_int(treatment.get("fit_rows",treatment.get("fit_row_count")),"alpha-beta fit_rows")
    if "fit_rows" in treatment and "fit_row_count" in treatment and exact_int(treatment["fit_rows"],"alpha-beta fit_rows")!=exact_int(treatment["fit_row_count"],"alpha-beta fit_row_count"):
        raise CandidateFail("alpha-beta fit row-count fields disagree")
    if fit_rows not in {15,nwindow}: raise CandidateFail("alpha-beta line must declare all 15 rows or the rows inside its plot window")
    fit_basis=treatment.get("fit_basis",treatment.get("fit_subset"))
    if "fit_basis" in treatment and "fit_subset" in treatment and treatment["fit_basis"]!=treatment["fit_subset"]:
        raise CandidateFail("alpha-beta fit_basis and fit_subset disagree")
    if fit_basis not in {"all_15_rows","plot_window_only"} or (fit_basis=="all_15_rows")!=(fit_rows==15):
        raise CandidateFail("alpha-beta fit_basis disagrees with declared fit rows")
    selected=np.ones(len(p),dtype=bool) if fit_rows==15 else window
    expected_coeff=np.polyfit(p[selected]/10000.0,mean[selected],1)
    for r in ab:
        pressure=finite_float(r["P_bar"],"alpha-beta boundary pressure"); temp=finite_float(r["T_K"],"alpha-beta boundary temperature")
        if not (2759<=pressure<=32400): raise CandidateFail("alpha-beta fit extrapolated outside 2759–32400 bar")
        expect=float(np.polyval(expected_coeff,pressure/10000.0))
        if abs(temp-expect)>0.5: raise CandidateFail("alpha-beta plotted fit differs from its declared linear fit by >0.5 K")
    slope=treatment.get("fit_slope_K_per_GPa")
    if slope is None and treatment.get("slope_K_per_bar") is not None:
        slope=finite_float(treatment["slope_K_per_bar"],"alpha-beta slope_K_per_bar")*10000.0
    elif slope is not None and treatment.get("slope_K_per_bar") is not None:
        if abs(finite_float(slope,"alpha-beta fit_slope_K_per_GPa")-10000.0*finite_float(treatment["slope_K_per_bar"],"alpha-beta slope_K_per_bar"))>1e-7:
            raise CandidateFail("alpha-beta slope fields disagree")
    intercept=treatment.get("fit_intercept_K",treatment.get("intercept_K"))
    if "fit_intercept_K" in treatment and "intercept_K" in treatment and abs(finite_float(treatment["fit_intercept_K"],"alpha-beta fit_intercept_K")-finite_float(treatment["intercept_K"],"alpha-beta intercept_K"))>1e-7:
        raise CandidateFail("alpha-beta intercept fields disagree")
    gap=treatment.get("estimate_gap_statistics_K",{})
    mean_gap=treatment.get("mean_abs_estimate_gap_K",gap.get("abs_mean_K") if isinstance(gap,dict) else None)
    max_gap=treatment.get("max_abs_estimate_gap_K",gap.get("abs_max_K") if isinstance(gap,dict) else None)
    if isinstance(gap,dict):
        for key,nested in (("mean_abs_estimate_gap_K","abs_mean_K"),("max_abs_estimate_gap_K","abs_max_K")):
            if key in treatment and nested in gap and abs(finite_float(treatment[key],f"alpha-beta {key}")-finite_float(gap[nested],f"alpha-beta {nested}"))>1e-7:
                raise CandidateFail(f"alpha-beta {key} fields disagree")
    for k,value,expected_value in (("fit_slope_K_per_GPa",slope,expected_coeff[0]),
            ("fit_intercept_K",intercept,expected_coeff[1]),
            ("mean_abs_estimate_gap_K",mean_gap,float(np.mean(np.abs(t1-t2)))),
            ("max_abs_estimate_gap_K",max_gap,float(np.max(np.abs(t1-t2))))):
        if abs(finite_float(value,f"alpha-beta summary {k}")-expected_value)>1e-7: raise CandidateFail(f"alpha-beta summary {k} mismatch")
    return len(ab)



def load_scoring_refs(tests: Path):
    try:
        refs=json.loads((tests/"refs.json").read_text(encoding="utf-8"))
        required=("phase_grid_energy_tolerance_meV_per_atom","lower_envelope_reference")
        if not isinstance(refs,dict) or not set(required).issubset(refs) or not isinstance(refs.get("_private_payloads"),dict):raise ValueError("missing scoring references or encoded closure")
        tol=refs["phase_grid_energy_tolerance_meV_per_atom"]
        if isinstance(tol,bool) or not isinstance(tol,(int,float)) or not math.isfinite(float(tol)) or tol<0:raise ValueError("phase-grid tolerance must be finite and nonnegative")
        if not isinstance(refs["lower_envelope_reference"],str) or not refs["lower_envelope_reference"].strip():raise ValueError("lower-envelope reference path missing")
        return refs
    except Exception as exc: raise EvaluatorEnvError(f"tests/refs.json missing or malformed ({exc})") from exc

def run(output:Path, package:Path, refdir:Path, root:Path, input_root:Path|None=None):
    refs=load_scoring_refs(package/"tests")
    meta=load_reference(refdir,root); fits=load_fits(package,meta,input_root)
    out=output/"outputs" if (output/"outputs").is_dir() else output
    summary=read_json(out/"summary.json")
    required={"units","method","boundaries","sensitivity","alpha_beta_treatment","limitations"}
    if not isinstance(summary,dict) or not required.issubset(summary): raise CandidateFail("summary.json missing scientific fields")
    units=summary["units"]
    if not isinstance(units,dict) or units.get("pressure")!="bar" or units.get("temperature")!="K":
        raise CandidateFail("summary.units must state pressure=bar and temperature=K")
    gibbs=units.get("gibbs",units.get("gibbs_energy"))
    if not isinstance(gibbs,str) or not gibbs.strip().lower().startswith("mev/atom"):
        raise CandidateFail("summary.units must state Gibbs energy in meV/atom")
    if not isinstance(summary["method"],(dict,str)) or not summary["method"]:
        raise CandidateFail("summary.method must be a short description")
    if not isinstance(summary["boundaries"],(dict,str)) or not summary["boundaries"]:
        raise CandidateFail("summary.boundaries must describe the boundary results")
    if not isinstance(summary["sensitivity"],(dict,str)) or not summary["sensitivity"]:
        raise CandidateFail("summary.sensitivity must describe the perturbation results")
    ngrid=verify_grid(out/"phase_grid.csv",refdir,fits,meta,refs)
    boundaries=verify_boundaries(out/"boundaries.csv",refdir,fits)
    nab=verify_alpha_beta(package,meta,boundaries,summary,input_root)
    nsens, nsens_boundaries=verify_sensitivity(out/"sensitivity.csv",refdir,boundaries,fits)
    if not isinstance(summary["limitations"],(list,str)) or not summary["limitations"]: raise CandidateFail("summary.limitations must state finite-window/mask limits")
    # Compact counts are useful, but the verified CSV/grid are authoritative.
    if isinstance(summary["boundaries"],dict):
        if "count" in summary["boundaries"] and summary["boundaries"]["count"]!=len(boundaries):
            raise CandidateFail("summary.boundaries.count disagrees with boundaries.csv")
        if "grid_transition_count" in summary["boundaries"] and summary["boundaries"]["grid_transition_count"]!=meta["reference_boundary_count"]:
            raise CandidateFail("summary.boundaries.grid_transition_count disagrees with the checked grid")
    if isinstance(summary["sensitivity"],dict):
        pair_count=summary["sensitivity"].get("representative_crossing_pair_count")
        row_count=summary["sensitivity"].get("row_count",summary["sensitivity"].get("rows"))
        if pair_count is not None and pair_count!=nsens_boundaries:
            raise CandidateFail("summary.sensitivity representative-pair count disagrees with sensitivity.csv")
        if row_count is not None and row_count!=nsens:
            raise CandidateFail("summary.sensitivity row count disagrees with sensitivity.csv")
    if nab<10: raise CandidateFail("need at least 10 alpha-beta fit samples inside the requested plot window")
    fig=out/"figures/phase_map.png"
    try:
        from PIL import Image
        with Image.open(fig) as im: im.verify()
        with Image.open(fig) as im:
            pixels=np.asarray(im.convert("RGB"),dtype=np.uint8)
            if float(pixels.std())<5.0: raise CandidateFail("phase_map.png is effectively blank or uniform")
    except FileNotFoundError: raise CandidateFail("missing outputs/figures/phase_map.png")
    except ImportError as exc: raise EvaluatorEnvError(f"Pillow required to verify phase_map.png: {exc}")
    except Exception as exc:
        if isinstance(exc,CandidateFail): raise
        raise CandidateFail(f"invalid phase_map.png: {exc}") from exc
    return f"L1/L2/L3 PASS: validated {ngrid} masked Gibbs grid points, {len(boundaries)} support-aware boundaries, {nsens} recalculated free-energy perturbations, and the alpha-beta fit"


def main():
    ap=argparse.ArgumentParser(); ap.add_argument("output_dir",nargs="?",default="."); ap.add_argument("--reference-dir",type=Path); ap.add_argument("--suite-root",type=Path); ap.add_argument("--input-root",type=Path); a=ap.parse_args()
    package=Path(__file__).resolve().parents[1]; root=a.suite_root or Path(__file__).resolve().parents[3]
    ref=a.reference_dir or Path(os.environ.get("P2B_REFERENCE_ROOT",root/"author/local-reference/references"))/"case-02"
    try:
        app=Path(a.output_dir).resolve()
        input_root=(a.input_root or (app if (app/"inputs").is_dir() else package)).resolve()
        if not input_root.is_dir(): raise EvaluatorEnvError("input root is missing or is not a directory")
        print(run(app,package,ref.resolve(),root.resolve(),input_root)); return 0
    except CandidateFail as exc: print(f"FAIL: {exc}"); return 1
    except EvaluatorEnvError as exc: print(f"ENV_ERROR: {exc}"); return 2
    except Exception as exc: print(f"ENV_ERROR: unexpected evaluator/reference error: {type(exc).__name__}: {exc}"); return 2

if __name__=="__main__": raise SystemExit(main())
