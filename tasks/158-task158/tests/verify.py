#!/usr/bin/env python3
# L1 Deliverables: Check required deliverables for completeness and parseability.
# L2 Execution: Check the use of supplied data or archived evidence where required.
# L3 Science: SiO thermal crystallization kinetics and scattering response.
"""Portable L1/L2/L3 verifier for the SiO heat-treatment case.

Exit 0: science PASS; exit 1: candidate science/contract FAIL; exit 2: verifier,
reference, required-input, or Python environment error. Uses Pillow to validate PNG files.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import sys
from pathlib import Path

RATES = ("1e12", "2e12", "5e12", "1e13")
RATE = {r: float(r) for r in RATES}
HEADERS = {
    "crystallinity_timeseries.csv": ["rate_K_per_s","step","time_ps","n_cubic","n_hex","n_other","n_filtered_subset","crystalline_fraction_subset","temperature_K","temperature_source"],
    "scattering_peak_metrics.csv": ["rate_K_per_s","state","peak_rank_q_ascending","q_peak_A_inv","peak_height","peak_width_A_inv","peak_width_method","window_A_inv","normalization"],
    "rate_comparison.csv": ["rate_K_per_s","onset_ps","onset_reason","final_subset_fraction","delta_peak_width_A_inv","kinetics_trend","scattering_trend","agreement","onset_definition"],
}

class ScienceFailure(Exception): pass
class EnvironmentFailure(Exception): pass

def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""): h.update(block)
    return h.hexdigest()

def read_csv(path: Path, expected_header):
    try:
        with path.open(encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames != expected_header: raise ScienceFailure(f"{path.name}: wrong header")
            rows = list(reader)
    except ScienceFailure: raise
    except Exception as e: raise ScienceFailure(f"{path.name}: unreadable CSV ({e})") from e
    if not rows: raise ScienceFailure(f"{path.name}: no data rows")
    return rows

def number(row, key, context, nullable=False):
    raw = row.get(key)
    if nullable and (raw is None or (isinstance(raw, str) and raw.strip() == "")): return None
    try: value = float(raw)
    except (TypeError, ValueError): raise ScienceFailure(f"{context}: {key} must be numeric")
    if not math.isfinite(value): raise ScienceFailure(f"{context}: {key} must be finite")
    return value

def close(a, b, tol, label):
    if not math.isfinite(a) or not math.isfinite(b): raise ScienceFailure(f"{label}: values must be finite")
    if abs(a-b) > tol: raise ScienceFailure(f"{label}: {a:g} differs from reference {b:g} by > {tol:g}")

def integer(row, key, context):
    value=number(row,key,context)
    rounded=round(value)
    if value != rounded: raise ScienceFailure(f"{context}: {key} must be an integer")
    return int(rounded)

def parse_info(path: Path):
    try:
        lines = [line.split() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        rows = [[float(v) for v in row] for row in lines]
    except Exception as e: raise EnvironmentFailure(f"required crystallinity input unreadable: {path} ({e})") from e
    if not rows or any(len(row) != 4 or not all(math.isfinite(x) for x in row) for row in rows):
        raise EnvironmentFailure(f"required crystallinity input malformed: {path}")
    if any(row[1] < 0 or row[2] < 0 or row[3] < 0 for row in rows):
        raise EnvironmentFailure(f"negative native category count in {path}")
    return rows

def parse_sq(path: Path):
    try:
        rows = [[float(v) for v in line.split()] for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except Exception as e: raise EnvironmentFailure(f"required S(q) input unreadable: {path} ({e})") from e
    if len(rows) < 100 or any(len(r) < 2 or not all(math.isfinite(x) for x in r[:2]) for r in rows):
        raise EnvironmentFailure(f"required S(q) input malformed: {path}")
    if any(rows[i+1][0] <= rows[i][0] for i in range(len(rows)-1)):
        raise EnvironmentFailure(f"q grid is not strictly increasing: {path}")
    return rows

def native_window_peaks(rows, refs):
    # Local maxima in the locked curve; prominence is retained as a physical check.
    q, s = [r[0] for r in rows], [r[1] for r in rows]
    idx = [i for i, x in enumerate(q) if refs["q_window_A_inv"][0] <= x <= refs["q_window_A_inv"][1]]
    peaks = []
    for k in range(1, len(idx)-1):
        i = idx[k]
        if s[i] >= s[i-1] and s[i] > s[i+1]:
            # Baseline is the higher of the nearest local minima on either side.
            left = min(range(idx[0], i), key=lambda j: s[j])
            right = min(range(i+1, idx[-1]+1), key=lambda j: s[j])
            prominence = s[i] - max(s[left], s[right])
            if prominence < refs["raw_peak_min_prominence"]: continue
            half = s[i] - prominence/2
            l = i
            while l > left and s[l] > half: l -= 1
            rr = i
            while rr < right and s[rr] > half: rr += 1
            peaks.append({"q":q[i],"height":s[i],"width":(q[rr]-q[l]),"prominence":prominence})
    return peaks

def measured_width(rows, q_center, method, refs):
    q=[r[0] for r in rows]; s=[r[1] for r in rows]
    lo=next(i for i,x in enumerate(q) if x>=refs["q_window_A_inv"][0]); hi=max(i for i,x in enumerate(q) if x<=refs["q_window_A_inv"][1])
    candidates=[i for i in range(lo+1,hi) if s[i]>=s[i-1] and s[i]>s[i+1]]
    i=min(candidates,key=lambda j:abs(q[j]-q_center))
    if abs(q[i]-q_center)>refs["q_center_grid_tolerance_A_inv"]: raise ScienceFailure("peak center does not map to the 0.01 A^-1 raw q grid")
    if method=="window_minimum_half_prominence":
        left=min(range(lo,i+1),key=lambda j:s[j]); right=min(range(i,hi+1),key=lambda j:s[j])
    elif method=="scipy_prominence_half_height":
        left_bound=i
        while left_bound>lo and s[left_bound-1] <= s[i]: left_bound-=1
        right_bound=i
        while right_bound<hi and s[right_bound+1] <= s[i]: right_bound+=1
        left=min(range(left_bound,i+1),key=lambda j:s[j]); right=min(range(i,right_bound+1),key=lambda j:s[j])
    else:
        raise ScienceFailure("peak_width_method must be scipy_prominence_half_height or window_minimum_half_prominence")
    prominence=s[i]-max(s[left],s[right])
    if prominence<=0: raise ScienceFailure("reported feature has no positive prominence")
    level=s[i]-prominence/2
    left_x=right_x=None
    for j in range(i,left,-1):
        if (s[j-1]-level)*(s[j]-level)<=0:
            left_x=q[j-1]+(level-s[j-1])*(q[j]-q[j-1])/(s[j]-s[j-1]); break
    for j in range(i,right):
        if (s[j]-level)*(s[j+1]-level)<=0:
            right_x=q[j]+(level-s[j])*(q[j+1]-q[j])/(s[j+1]-s[j]); break
    if left_x is None or right_x is None: raise ScienceFailure("could not recompute peak width from raw S(q)")
    return right_x-left_x

def load_reference(ref_dir):
    try:
        bundle=json.loads((Path(__file__).resolve().parent/"refs.json").read_text(encoding="utf-8"))["private_reference"]
        meta=bundle["metadata"]; rates=bundle["rates"]
    except Exception as e: raise EnvironmentFailure(f"private reference missing or damaged in refs.json ({e})") from e
    if meta.get("reference_type") != "computed from deposited native inputs plus Source Data cross-check" or len(rates.get("rate_results", [])) != 4:
        raise EnvironmentFailure("private reference provenance/schema invalid")
    checks=meta.get("source_data_checks",{})
    if set(checks)!=set(RATES): raise EnvironmentFailure("private Figure 6a calibration coverage incomplete")
    for rate,check in checks.items():
        if check.get("source_rows")!=101 or check.get("max_count_abs_difference")!=0 or check.get("max_fraction_abs_difference",1)>1e-12:
            raise EnvironmentFailure(f"private Figure 6a cross-check invalid for {rate}")
    scattering=meta.get("source_scattering_checks",{})
    if set(scattering)!=set(RATES): raise EnvironmentFailure("private Figure 6g+h+i+j calibration coverage incomplete")
    for rate,check in scattering.items():
        if check.get("source_rows")!=2450 or check.get("q_max_abs_difference_A_inv",1)>1e-12 or check.get("xray_s_max_abs_difference",1)>1e-12:
            raise EnvironmentFailure(f"private Source Data X-ray scattering cross-check invalid for {rate}")
    peaks=meta.get("peak_reference_measurement",{}).get("method_crosscheck_all_peaks",[])
    if len(peaks)!=10: raise EnvironmentFailure("private peak-method scan must cover all ten reference peaks")
    for entry in peaks:
        try:
            if not math.isfinite(float(entry["scipy_prominence_half_height_A_inv"])) or not math.isfinite(float(entry["window_minimum_half_prominence_A_inv"])):
                raise ValueError("nonfinite peak width")
        except Exception as e: raise EnvironmentFailure(f"private peak-method scan is damaged ({e})") from e
    narrow=[float(e["window_minimum_half_prominence_A_inv"]) for e in peaks if e["state"]=="after" and e["rate_label"] in ("1e12","2e12")]
    broad=[float(e["window_minimum_half_prominence_A_inv"]) for e in peaks if e["state"]=="after" and e["rate_label"] in ("5e12","1e13")]
    derived_boundary=(max(narrow)+min(broad))/2
    if abs(float(meta["peak_reference_measurement"].get("peak_width_class_boundary_A_inv",-1))-derived_boundary)>1e-3:
        raise EnvironmentFailure("private width-class boundary does not match measured baseline-method scan")
    authors=meta.get("author_method_artifacts_sha256",{})
    required_author_artifacts=("raw_data/unpacked/results-277b5114949b/results/SiO/partially_crystalline/crystallinity/get_cristallinity.py",
        "raw_data/unpacked/results-277b5114949b/results/SiO/partially_crystalline/md/run.sh",
        "raw_data/unpacked/results-277b5114949b/results/SiO/compute_structure_factor.py",
        "raw_data/unpacked/results-277b5114949b/results/SiO/structure_factor.py")
    if any(not isinstance(authors.get(p),str) or len(authors[p])!=64 for p in required_author_artifacts):
        raise EnvironmentFailure("private native-method provenance hashes missing")
    return meta, rates

def public_input_root(case_root):
    app_inputs=case_root/"inputs"
    if (app_inputs/"method-note.md").is_file(): return app_inputs
    assets=case_root/"environment/assets"
    if (assets/"method-note.md").is_file(): return assets
    raise EnvironmentFailure("public inputs are missing from /inputs or environment/assets")

def check_inputs(case_root, meta):
    input_root=public_input_root(case_root)
    expected = meta.get("input_sha256")
    if not isinstance(expected, dict) or not expected: raise EnvironmentFailure("reference input hash manifest missing")
    for rel, digest in expected.items():
        path = input_root / rel.removeprefix("inputs/")
        if not path.is_file(): raise EnvironmentFailure(f"required input missing: {rel}")
        if sha(path) != digest: raise EnvironmentFailure(f"required input hash mismatch: {rel}")
    return input_root

def onset_for(rows, threshold, persistence, refs):
    vals=[]
    for row in rows:
        step=int(row[0]); denom=sum(row[1:]); frac=(row[1]+row[2])/denom
        vals.append((step,frac))
    for i in range(len(vals)-persistence+1):
        if vals[i][0] < refs["onset_start_step_exclusive"]: continue
        if all(frac >= threshold for _,frac in vals[i:i+persistence]): return vals[i][0]*refs["time_step_ps"]
    return None

def check_png(path):
    try:
        from PIL import Image
        with Image.open(path) as image:
            if image.format != "PNG":
                raise ValueError("not a PNG")
            image.verify()
        with Image.open(path) as image:
            image.load()
    except ImportError as exc:
        raise EnvironmentFailure(f"Pillow required for PNG verification: {exc}") from exc
    except Exception as exc:
        raise ScienceFailure(f"missing/invalid scientific figure: {exc}") from exc


def load_scoring_refs(tests: Path):
    try:
        data=json.loads((tests/"refs.json").read_text(encoding="utf-8"))
        required=("time_step_ps","onset_threshold_fraction_range","onset_persistence_observations_range","onset_start_step_exclusive","q_window_A_inv","q_grid_spacing_A_inv","q_center_grid_tolerance_A_inv","raw_peak_match_q_tolerance_A_inv","raw_peak_match_height_tolerance","raw_peak_min_prominence","peak_width_recompute_tolerance_A_inv","representative_width_delta_tolerance_A_inv","narrow_peak_delta_max_A_inv","broad_peak_delta_range_A_inv","kinetics_class_fraction_thresholds","after_doublet_rates")
        if not isinstance(data,dict) or set(data)!=(set(required)|{"width_class_boundary_source","private_reference"}): raise ValueError("missing or unexpected scoring reference key")
        numeric=[k for k in required if k!="onset_threshold_fraction_range" and k!="onset_persistence_observations_range" and k!="q_window_A_inv" and k!="broad_peak_delta_range_A_inv" and k!="kinetics_class_fraction_thresholds" and k!="after_doublet_rates"]
        if any(isinstance(data[k],bool) or not isinstance(data[k],(int,float)) or not math.isfinite(float(data[k])) or (float(data[k])<0 and k!="narrow_peak_delta_max_A_inv") for k in numeric): raise ValueError("scoring references must be finite numbers with nonnegative tolerances")
        for key in ("onset_threshold_fraction_range","onset_persistence_observations_range","q_window_A_inv","broad_peak_delta_range_A_inv"):
            bounds=data[key]
            if not isinstance(bounds,list) or len(bounds)!=2 or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(float(v)) for v in bounds) or bounds[0]>bounds[1]: raise ValueError(f"malformed scoring range: {key}")
        if data["onset_threshold_fraction_range"][0]<0.001 or data["onset_threshold_fraction_range"][1]>0.05 or data["onset_persistence_observations_range"][0]<1 or data["onset_persistence_observations_range"][1]>5 or data["q_window_A_inv"][0]>=data["q_window_A_inv"][1]: raise ValueError("invalid onset or q-window range")
        rates=data["after_doublet_rates"]
        if not isinstance(rates,list) or rates != ["1e12","2e12"]: raise ValueError("invalid calibrated doublet rate set")
        kin=data["kinetics_class_fraction_thresholds"]
        if not isinstance(kin,list) or len(kin)!=2 or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(float(v)) or v<0 for v in kin) or kin[0]<=kin[1]: raise ValueError("invalid kinetics classification thresholds")
        if data["width_class_boundary_source"]!="private_reference_measurement": raise ValueError("width boundary must bind to measured private reference")
        return data
    except Exception as e: raise EnvironmentFailure(f"tests/refs.json missing or malformed ({e})") from e

def verify(case_root: Path, ref_dir: Path, refs):
    meta, ref = load_reference(ref_dir)
    width_boundary=float(meta["peak_reference_measurement"]["peak_width_class_boundary_A_inv"])
    input_root=check_inputs(case_root, meta)
    out=case_root/"outputs"
    summary_path=out/"summary.json"
    if not summary_path.is_file(): raise ScienceFailure("missing outputs/summary.json")
    try: summary=json.loads(summary_path.read_text(encoding="utf-8"))
    except Exception as e: raise ScienceFailure(f"invalid summary JSON ({e})") from e
    if not isinstance(summary,dict): raise ScienceFailure("summary.json must be an object")
    for k in ("method","rate_results","time_unit","denominator_definition","scattering_consistency","onset_sensitivity_ps","source_data_check","source_scattering_check"):
        if k not in summary: raise ScienceFailure(f"summary missing required field {k}")
    if not isinstance(summary["rate_results"],list) or len(summary["rate_results"]) != 4:
        raise ScienceFailure("summary.rate_results must contain all four rates")
    method=summary["method"]
    if not isinstance(method,dict) or not isinstance(method.get("onset"),dict) or not isinstance(method.get("uncertainty"),dict):
        raise ScienceFailure("summary must state onset rule and uncertainty basis")
    threshold=number(method["onset"],"threshold_fraction","summary.method.onset")
    persistence=number(method["onset"],"consecutive_observations","summary.method.onset")
    if not refs["onset_threshold_fraction_range"][0] <= threshold <= refs["onset_threshold_fraction_range"][1] or int(persistence)!=persistence or not refs["onset_persistence_observations_range"][0] <= persistence <= refs["onset_persistence_observations_range"][1]:
        raise ScienceFailure("onset rule outside calibrated range (fraction 0.1–5%, persistence 1–5 frames)")
    persistence=int(persistence)
    if "ps" not in summary["time_unit"] or "subset" not in summary["denominator_definition"].lower():
        raise ScienceFailure("time unit and filtered-subset denominator must be explicit")
    if number(method["uncertainty"],"q_peak_A_inv","summary.method.uncertainty") < 0.01:
        raise ScienceFailure("q uncertainty must account for the 0.01 A^-1 input grid")
    if not isinstance(summary["scattering_consistency"],dict): raise ScienceFailure("scattering_consistency must be an object")
    sc=summary["scattering_consistency"]
    if sc.get("channel") != "X-ray (second column)" or sc.get("fixed_q_window_A_inv") != refs["q_window_A_inv"]:
        raise ScienceFailure("scattering must use X-ray column 2 and common q window [3.0,4.2] A^-1")
    if not isinstance(sc.get("limitations"),list) or len(sc["limitations"])<2:
        raise ScienceFailure("summary must record observation and subset limitations")
    width_method=sc.get("peak_width_method")
    if width_method not in ("scipy_prominence_half_height","window_minimum_half_prominence"):
        raise ScienceFailure("summary must declare a supported, reproducible peak-width definition")
    if not isinstance(sc.get("source_data_calibration"),str) or "Figure 6" not in sc["source_data_calibration"]:
        raise ScienceFailure("summary must identify its Source Data scattering cross-check")
    if set(summary["source_data_check"])!=set(RATES) or set(summary["source_scattering_check"])!=set(RATES):
        raise ScienceFailure("summary must report both source-data cross-checks for all four rates")

    ts=read_csv(out/"crystallinity_timeseries.csv",HEADERS["crystallinity_timeseries.csv"])
    by_rate={r:[] for r in RATES}
    for row in ts:
        rv=number(row,"rate_K_per_s","crystallinity_timeseries")
        label=min(RATES,key=lambda x:abs(RATE[x]-rv))
        if abs(RATE[label]-rv)>1: raise ScienceFailure("unknown rate in crystallinity_timeseries")
        by_rate[label].append(row)
    for rate in RATES:
        native=parse_info(input_root/f"SiO/partially_crystalline/crystallinity/crystallinity.{rate}.info")
        rows=by_rate[rate]
        if len(rows)!=len(native): raise ScienceFailure(f"{rate}: crystallinity time series must preserve all native rows, including startup")
        for i,(outrow,raw) in enumerate(zip(rows,native)):
            ctx=f"{rate} frame {i}"
            step=integer(outrow,"step",ctx); t=number(outrow,"time_ps",ctx)
            if step!=raw[0]: raise ScienceFailure(f"{ctx}: native timestep mismatch")
            close(t,raw[0]*refs["time_step_ps"],1e-9,ctx+" time_ps; expected step*0.001")
            c,h,o=[integer(outrow,k,ctx) for k in ("n_cubic","n_hex","n_other")]
            if [c,h,o] != [int(x) for x in raw[1:]]: raise ScienceFailure(f"{ctx}: PTM category counts differ from native input")
            denom=integer(outrow,"n_filtered_subset",ctx)
            if denom!=int(sum(raw[1:])): raise ScienceFailure(f"{ctx}: wrong denominator; use cubic+hex+other filtered-subset counts")
            frac=number(outrow,"crystalline_fraction_subset",ctx)
            # Six-decimal reported fractions are within ~5e-7 of the exact ratio.
            close(frac,(raw[1]+raw[2])/sum(raw[1:]),5e-7,ctx+" subset fraction")
            temp=number(outrow,"temperature_K",ctx)
            tps=raw[0]*.001
            expected_temp=300+11*tps if tps<=100 else (1400 if tps<=200 else max(1200,1400-(tps-200)*.01))
            close(temp,expected_temp,0.05,ctx+" temperature schedule")
            if "derived" not in outrow["temperature_source"].lower() and "quenching.in" not in outrow["temperature_source"]:
                raise ScienceFailure(f"{ctx}: temperature provenance missing")

    peaks=read_csv(out/"scattering_peak_metrics.csv",HEADERS["scattering_peak_metrics.csv"])
    peak_groups={(r,s):[] for r in RATES for s in ("before","after")}
    for row in peaks:
        rv=number(row,"rate_K_per_s","scattering_peak_metrics")
        rate=min(RATES,key=lambda x:abs(RATE[x]-rv))
        if abs(RATE[rate]-rv)>1: raise ScienceFailure("unknown rate in scattering_peak_metrics")
        state=row["state"]
        if state not in ("before","after"): raise ScienceFailure("scattering state must be before or after")
        if row["window_A_inv"] != f"{refs['q_window_A_inv'][0]:.2f}:{refs['q_window_A_inv'][1]:.2f}" or "X-ray" not in row["normalization"]:
            raise ScienceFailure("peak metrics must declare common 3.00:4.20 window and X-ray channel")
        if row.get("peak_width_method") != width_method:
            raise ScienceFailure("all before/after widths must use the same declared width method")
        if integer(row,"peak_rank_q_ascending","scattering_peak_metrics") < 1:
            raise ScienceFailure("peak ranks start at 1")
        peak_groups[(rate,state)].append(row)
    ref_by={x["rate_label"]:x for x in ref["rate_results"]}
    computed_peak={}
    for rate in RATES:
        for state in ("before","after"):
            subdir="amorphous" if state=="before" else "partially_crystalline"
            fname=(f"total_structure_factor_calculated.{rate}.dat" if state=="before" else f"total_structure_factor_{rate}.dat")
            native=parse_sq(input_root/f"SiO/{subdir}/structure_factors/{fname}")
            native_peaks=native_window_peaks(native,refs)
            # Reference sets the observed physical windows. Candidate peak detection may use
            # a different defensible baseline, but every reported peak must exist in raw X-ray S(q).
            actual=sorted(peak_groups[(rate,state)],key=lambda x:number(x,"q_peak_A_inv",rate+" "+state))
            expected=ref_by[rate]["before_peaks_q_3_0_4_2_A_inv"] if state=="before" else ref_by[rate]["after_peaks_q_3_0_4_2_A_inv"]
            want_count=2 if state=="after" and rate in ("1e12","2e12") else 1
            if len(actual)!=want_count: raise ScienceFailure(f"{rate} {state}: expected {want_count} resolved peak(s) in the common window")
            if [integer(x,"peak_rank_q_ascending",rate+" "+state) for x in actual] != list(range(1,want_count+1)):
                raise ScienceFailure(f"{rate} {state}: peak ranks must be unique and ordered by increasing q")
            raw_peaks=native_window_peaks(native,refs)
            if len(raw_peaks)<want_count: raise ScienceFailure(f"{rate} {state}: reported resolved peaks are not supported by raw X-ray S(q)")
            for i,row in enumerate(actual):
                ctx=f"{rate} {state} peak {i+1}"
                q=number(row,"q_peak_A_inv",ctx); height=number(row,"peak_height",ctx); width=number(row,"peak_width_A_inv",ctx)
                if not any(abs(q-p["q"]) <= refs["raw_peak_match_q_tolerance_A_inv"] and abs(height-p["height"]) <= refs["raw_peak_match_height_tolerance"] for p in raw_peaks):
                    raise ScienceFailure(f"{ctx}: peak location/height does not correspond to a local maximum in raw S(q)")
                if q<refs["q_window_A_inv"][0] or q>refs["q_window_A_inv"][1] or width<=0: raise ScienceFailure(ctx+": invalid peak position/width")
                recomputed=measured_width(native,q,width_method,refs)
                close(width,recomputed,refs["peak_width_recompute_tolerance_A_inv"],ctx+" width recomputed using declared baseline rule")
                if state=="after" and rate in ("1e12","2e12") and recomputed>=width_boundary:
                    raise ScienceFailure(ctx+f": resolved doublet members must be below measured {width_boundary:.3f} A^-1 separation boundary")
                if state=="after" and rate in ("5e12","1e13") and recomputed<=width_boundary:
                    raise ScienceFailure(ctx+f": broad feature must be above measured {width_boundary:.3f} A^-1 separation boundary")
            # For the doublet, q windows are intentionally broad enough for equivalent
            # baseline/peak-centre methods on a 0.01 A^-1 grid.
            qvals=[number(x,"q_peak_A_inv",rate+" "+state) for x in actual]
            if state=="after" and rate in ("1e12","2e12"):
                if not (3.20<=qvals[0]<=3.36 and 3.68<=qvals[1]<=3.94):
                    raise ScienceFailure(f"{rate}: reported doublet is outside its calibrated q windows")
            if state=="after" and rate in ("5e12","1e13"):
                if not 3.30<=qvals[0]<=3.95: raise ScienceFailure(f"{rate}: broad-window feature position is implausible")
            computed_peak[(rate,state)]=raw_peaks

    comp=read_csv(out/"rate_comparison.csv",HEADERS["rate_comparison.csv"])
    if len(comp)!=4: raise ScienceFailure("rate_comparison must contain all four rates")
    comp_by={}
    for row in comp:
        rv=number(row,"rate_K_per_s","rate_comparison")
        rate=min(RATES,key=lambda x:abs(RATE[x]-rv))
        if abs(RATE[rate]-rv)>1 or rate in comp_by: raise ScienceFailure("rate_comparison has unknown or duplicate rate")
        comp_by[rate]=row
    result_by={x.get("rate_label"):x for x in summary["rate_results"] if isinstance(x,dict)}
    if set(result_by)!=set(RATES): raise ScienceFailure("summary.rate_results must name exactly the four rates")
    onsets={}
    finals={}
    for rate in RATES:
        row=comp_by[rate]
        native=parse_info(input_root/f"SiO/partially_crystalline/crystallinity/crystallinity.{rate}.info")
        last=native[-1]; final=(last[1]+last[2])/sum(last[1:])
        finals[rate]=final
        close(number(row,"final_subset_fraction",rate+" rate_comparison"),final,5e-10,rate+" final fraction")
        calc=onset_for(native,threshold,persistence,refs)
        candidate=number(row,"onset_ps",rate+" rate_comparison",nullable=True)
        onsets[rate]=candidate
        if calc is None:
            if candidate is not None or not row.get("onset_reason","").strip(): raise ScienceFailure(f"{rate}: no-onset must be null with an observation-window reason")
        elif candidate is None:
            raise ScienceFailure(f"{rate}: expected onset under the declared rule")
        else:
            close(candidate,calc,1e-6,rate+" onset under declared threshold/persistence")
        result=result_by[rate]
        close(number(result,"final_subset_fraction",rate+" summary"),final,5e-10,rate+" summary final fraction")
        if number(result,"onset_ps_declared_rule",rate+" summary",nullable=True) != candidate:
            raise ScienceFailure(f"{rate}: summary onset must match the predeclared onset rule")
        if not isinstance(result.get("joint_evidence"),str) or not result["joint_evidence"].strip():
            raise ScienceFailure(f"{rate}: summary must state the two-stream joint-evidence conclusion")
        if row.get("onset_definition","").strip()=="": raise ScienceFailure(f"{rate}: onset rule must be recorded")
    expected_order=sorted(RATES,key=lambda r:finals[r],reverse=True)
    if expected_order != ["1e12","2e12","5e12","1e13"]: raise ScienceFailure("crystalline subset fraction rate ordering is wrong")
    observed=sorted((r for r in RATES if onsets[r] is not None),key=lambda r:onsets[r])
    expected_observed_order=[r for r in ("1e12","2e12","5e12","1e13") if onsets[r] is not None]
    if observed != expected_observed_order or observed[:2] != ["1e12","2e12"]:
        raise ScienceFailure("observed onsets must retain the calibrated slower-rate-first order under the declared threshold")
    # A doublet is the key discriminator, not the broad maximum near q~5.
    dual_rates=[r for r in RATES if len(peak_groups[(r,"after")])>=2]
    if dual_rates != ["1e12","2e12"]: raise ScienceFailure("post-state narrow doublet should be resolved only for 1e12 and 2e12 in the calibrated window")
    for rate in RATES:
        row=comp_by[rate]
        expected_kin="strong" if finals[rate]>=refs["kinetics_class_fraction_thresholds"][0] else ("weak" if finals[rate]>=refs["kinetics_class_fraction_thresholds"][1] else "trace")
        expected_scatter="resolved_crystalline_doublet" if rate in ("1e12","2e12") else "broad_peak_only_in_fixed_window"
        if row.get("kinetics_trend") != expected_kin: raise ScienceFailure(f"{rate}: kinetics label conflicts with its measured final subset fraction")
        if row.get("scattering_trend") != expected_scatter: raise ScienceFailure(f"{rate}: scattering label conflicts with measured same-window peaks")
        if row.get("agreement") != "consistent": raise ScienceFailure(f"{rate}: the two evidence streams should be reported as consistent")
        if result_by[rate].get("kinetics_class") != expected_kin or result_by[rate].get("scattering_class") != expected_scatter or result_by[rate].get("joint_evidence") != "consistent":
            raise ScienceFailure(f"{rate}: summary classification conflicts with measured evidence")
        before_rows=sorted(peak_groups[(rate,"before")],key=lambda x:number(x,"q_peak_A_inv",rate+" before"))
        after_rows=sorted(peak_groups[(rate,"after")],key=lambda x:number(x,"q_peak_A_inv",rate+" after"))
        expected_delta=number(after_rows[0],"peak_width_A_inv",rate+" after primary")-number(before_rows[0],"peak_width_A_inv",rate+" before primary")
        delta=number(row,"delta_peak_width_A_inv",rate+" rate_comparison")
        close(delta,expected_delta,refs["representative_width_delta_tolerance_A_inv"],rate+" delta width; lowest-q after peak minus before peak")
        if rate in refs["after_doublet_rates"] and delta >= refs["narrow_peak_delta_max_A_inv"]:
            raise ScienceFailure(f"{rate}: the representative post-treatment peak should be materially narrower")
        if rate not in refs["after_doublet_rates"] and not refs["broad_peak_delta_range_A_inv"][0] <= delta <= refs["broad_peak_delta_range_A_inv"][1]:
            raise ScienceFailure(f"{rate}: broad-peak width change is outside the calibrated weak-response range")

    sens=summary["onset_sensitivity_ps"]
    for label,th in (("0.001",0.001),("0.01",0.01),("0.05",0.05)):
        if label not in sens or not isinstance(sens[label],dict): raise ScienceFailure("summary must include 0.1%, 1%, and 5% onset sensitivity")
        for rate in RATES:
            calc=onset_for(parse_info(input_root/f"SiO/partially_crystalline/crystallinity/crystallinity.{rate}.info"),th,persistence,refs)
            val=sens[label].get(rate)
            if calc is None:
                if val is not None: raise ScienceFailure(f"{rate}: {label} onset sensitivity should be null")
            else: close(float(val),calc,1e-6,f"{rate} {label} onset sensitivity")
    check_png(out/"figures/crystallinity_and_sq.png")
    return {"status":"PASS","reward":1,"levels":{"L1":"PASS","L2":"PASS","L3":"PASS"},
            "coverage":{"rate_count":4,"timeseries_rows":len(ts),"scattering_peak_rows":len(peaks),
                        "source_data_figure6a_rows":404,"onset_threshold_sensitivity":[0.001,0.01,0.05],
                        "resolved_doublet_rates":["1e12","2e12"]}}

def main():
    try:
        case_root=Path(sys.argv[1] if len(sys.argv)>1 else ".").resolve()
        if not (case_root/"outputs").exists() and (case_root/"outputs").is_dir() is False:
            raise ScienceFailure("candidate root must contain outputs/")
        tests=Path(__file__).resolve().parent
        # Test assets are delivered by the scoring runner; source author references are a local fallback.
        result=verify(case_root,tests,load_scoring_refs(tests))
        print(json.dumps(result,sort_keys=True)); return 0
    except ScienceFailure as e:
        print(json.dumps({"status":"FAIL","reward":0,"error_type":"science_failure","message":str(e)},sort_keys=True)); return 1
    except EnvironmentFailure as e:
        print(json.dumps({"status":"ERROR","reward":None,"error_type":"environment_or_reference_error","message":str(e)},sort_keys=True)); return 2
    except Exception as e:
        print(json.dumps({"status":"ERROR","reward":None,"error_type":"verifier_error","message":str(e)},sort_keys=True)); return 2

if __name__=="__main__": raise SystemExit(main())
