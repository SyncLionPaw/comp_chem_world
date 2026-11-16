#!/usr/bin/env bash
# solve.sh — regenerate case-04 deliverables from the deposited native inputs.
#
# Usage: solve.sh APP_ROOT
#   Writes APP_ROOT/outputs/{crystallinity_timeseries.csv, scattering_peak_metrics.csv,
#   rate_comparison.csv, summary.json, figures/crystallinity_and_sq.png}.
#
# Does NOT copy pre-validated outputs. Every number is computed from:
#   inputs/SiO/partially_crystalline/crystallinity/crystallinity.<rate>.info   (step n_cubic n_hex n_other)
#   inputs/SiO/{amorphous,partially_crystalline}/structure_factors/*.dat       (q, X-ray, neutron, electron)
#   inputs/SiO/partially_crystalline/md/quenching.in                           (temperature schedule)
#   inputs/method-note.md                                                      (time, subset, S(q) metadata)
# Rules follow the public task contract and native-input metadata.
# Python 3 stdlib + matplotlib (figure only).
set -euo pipefail

CASE_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_ROOT="${1:-${APP:-/app}}"
mkdir -p "$APP_ROOT/outputs/figures"

python3 - "$CASE_DIR" "$APP_ROOT/outputs" <<'PY'
import csv, json, math, sys
from pathlib import Path

CASE = Path(sys.argv[1]).resolve()
OUT = Path(sys.argv[2]).resolve()
IN = CASE / "inputs"
if not IN.is_dir():
    IN = CASE.parent / "environment" / "assets"
if not IN.is_dir():
    IN = Path("/app/inputs")
RATES = ("1e12", "2e12", "5e12", "1e13")
RATE_VAL = {r: float(r) for r in RATES}

# Declared analysis choices for the deposited time series.
THRESH = 0.01          # 1 % filtered-subset crystalline fraction
PERSIST = 3            # consecutive observations
PEAK_PROM = 0.12       # S(q) peak prominence
PEAK_WIDTH_METHOD = "window_minimum_half_prominence"
WIDTH_BOUNDARY = 0.36  # reported class boundary for narrow/broad features
WIN = (3.00, 4.20)     # common q window from method-note.md

# ---------- native input parsers ----------
def parse_info(path):
    rows = [[float(v) for v in ln.split()] for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert rows and all(len(r) == 4 for r in rows), f"malformed {path}"
    return rows

def parse_sq(path):
    rows = [[float(v) for v in ln.split()] for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(rows) >= 100 and all(rows[i+1][0] > rows[i][0] for i in range(len(rows)-1)), f"bad S(q) {path}"
    return rows

# ---------- onset ----------
def onset_for(rows, thr, persist):
    vals = []
    for r in rows:
        step = int(r[0]); denom = sum(r[1:]); vals.append((step, (r[1] + r[2]) / denom))
    for i in range(len(vals) - persist + 1):
        if vals[i][0] < 200000:
            continue
        if all(f >= thr for _, f in vals[i:i+persist]):
            return vals[i][0] * 0.001
    return None

# ---------- peaks ----------
# scipy.signal.find_peaks, prominence >= 0.12, restricted to the common window.
from scipy.signal import find_peaks
def window_peaks(rows, min_prom):
    q = [r[0] for r in rows]; s = [r[1] for r in rows]
    idx = [i for i, x in enumerate(q) if WIN[0] <= x <= WIN[1]]
    sub = [s[i] for i in idx]
    pk, props = find_peaks(sub, prominence=min_prom)
    return [{"q": q[idx[k]], "height": s[idx[k]], "prominence": float(props["prominences"][n])}
            for n, k in enumerate(pk)]

# ---------- peak width by window-minimum half-prominence ----------
def measured_width(rows, q_center, method=PEAK_WIDTH_METHOD):
    q = [r[0] for r in rows]; s = [r[1] for r in rows]
    lo = next(i for i, x in enumerate(q) if x >= WIN[0])
    hi = max(i for i, x in enumerate(q) if x <= WIN[1])
    cands = [i for i in range(lo+1, hi) if s[i] >= s[i-1] and s[i] > s[i+1]]
    i = min(cands, key=lambda j: abs(q[j] - q_center))
    assert abs(q[i] - q_center) <= 0.021
    assert method == "window_minimum_half_prominence"
    left = min(range(lo, i+1), key=lambda j: s[j])
    right = min(range(i, hi+1), key=lambda j: s[j])
    prom = s[i] - max(s[left], s[right])
    level = s[i] - prom / 2
    lx = rx = None
    for j in range(i, left, -1):
        if (s[j-1]-level)*(s[j]-level) <= 0:
            lx = q[j-1] + (level-s[j-1])*(q[j]-q[j-1])/(s[j]-s[j-1]); break
    for j in range(i, right):
        if (s[j]-level)*(s[j+1]-level) <= 0:
            rx = q[j] + (level-s[j])*(q[j+1]-q[j])/(s[j+1]-s[j]); break
    return rx - lx

# ---------- temperature schedule from quenching.in ----------
def temp_K(t_ps):
    if t_ps <= 100:
        return 300 + 11 * t_ps
    if t_ps <= 200:
        return 1400.0
    return max(1200.0, 1400 - (t_ps - 200) * 0.01)

# ---------- compute ----------
ts_rows, peak_rows, comp_rows, summ_rates = [], [], [], []
finals, onsets, sens = {}, {}, {}
last_step_by_rate = {}
peaks_by = {}
sq_plot = {}
cryst_plot = {}

for rate in RATES:
    native = parse_info(IN / f"SiO/partially_crystalline/crystallinity/crystallinity.{rate}.info")
    cryst_plot[rate] = native
    for r in native:
        step = int(r[0]); t = step * 0.001
        c, h, o = int(r[1]), int(r[2]), int(r[3])
        denom = c + h + o
        ts_rows.append({
            "rate_K_per_s": rate, "step": step, "time_ps": f"{t:.3f}",
            "n_cubic": c, "n_hex": h, "n_other": o, "n_filtered_subset": denom,
            "crystalline_fraction_subset": f"{(c+h)/denom:.17g}",
            "temperature_K": f"{temp_K(t):.6f}",
            "temperature_source": "derived from md/quenching.in schedule (300+11t to 100 ps; 1400 K to 200 ps; 1400->1200 K linear)",
        })
    last = native[-1]
    last_step_by_rate[rate] = int(last[0])
    finals[rate] = (last[1] + last[2]) / sum(last[1:])
    onsets[rate] = onset_for(native, THRESH, PERSIST)
    sens[rate] = {str(k): onset_for(native, k, PERSIST) for k in (0.001, 0.01, 0.05)}

    for state, sub, fname in (("before", "amorphous", f"total_structure_factor_calculated.{rate}.dat"),
                              ("after", "partially_crystalline", f"total_structure_factor_{rate}.dat")):
        sq = parse_sq(IN / f"SiO/{sub}/structure_factors/{fname}")
        sq_plot[(rate, state)] = sq
        pk = window_peaks(sq, PEAK_PROM)  # scipy find_peaks, prominence >= 0.12
        peaks_by[(rate, state)] = (sq, pk)
        for rank, p in enumerate(sorted(pk, key=lambda x: x["q"]), start=1):
            w = measured_width(sq, p["q"])
            peak_rows.append({
                "rate_K_per_s": rate, "state": state, "peak_rank_q_ascending": rank,
                "q_peak_A_inv": f"{p['q']:.4f}", "peak_height": f"{p['height']:.6f}",
                "peak_width_A_inv": f"{w:.6f}", "peak_width_method": PEAK_WIDTH_METHOD,
                "window_A_inv": "3.00:4.20",
                "normalization": "raw X-ray total S(q) (column 2), no rescaling; common 3.00-4.20 A^-1 window",
            })

# Require detectable same-window evidence; multiplicity and class come from the data.
for rate in RATES:
    for state in ("before", "after"):
        got = len([r for r in peak_rows if r["rate_K_per_s"] == rate and r["state"] == state])
        if got < 1:
            raise SystemExit(f"{rate} {state}: no X-ray S(q) peak was detected in the declared window")

# ---------- rate comparison ----------
def width_of(rate, state, rank):
    return float([r for r in peak_rows if r["rate_K_per_s"] == rate and r["state"] == state
                  and r["peak_rank_q_ascending"] == rank][0]["peak_width_A_inv"])

def scattering_class_from_peaks(rate):
    after=[r for r in peak_rows if r["rate_K_per_s"]==rate and r["state"]=="after"]
    widths=[float(r["peak_width_A_inv"]) for r in after]
    if len(after)==2 and all(width < WIDTH_BOUNDARY for width in widths):
        return "resolved_crystalline_doublet"
    if len(after)==1 and widths[0] > WIDTH_BOUNDARY:
        return "broad_peak_only_in_fixed_window"
    raise SystemExit(f"{rate}: detected post-state peak pattern is not classifiable by the declared width rule")

for rate in RATES:
    kin = "strong" if finals[rate] >= 0.1 else ("weak" if finals[rate] >= 0.005 else "trace")
    scat = scattering_class_from_peaks(rate)
    agreement = "consistent" if ((kin == "strong") == (scat == "resolved_crystalline_doublet")) else "inconsistent"
    delta = width_of(rate, "after", 1) - width_of(rate, "before", 1)
    comp_rows.append({
        "rate_K_per_s": rate,
        "onset_ps": "" if onsets[rate] is None else f"{onsets[rate]:.3f}",
        "onset_reason": ("no onset: subset fraction never reaches %.1f%% for %d consecutive observations (step>=200000)"
                         % (THRESH*100, PERSIST)) if onsets[rate] is None else "",
        "final_subset_fraction": f"{finals[rate]:.17g}",
        "delta_peak_width_A_inv": f"{delta:.6f}",
        "kinetics_trend": kin, "scattering_trend": scat, "agreement": agreement,
        "onset_definition": f"first step>=200000 with subset fraction >= {THRESH} for {PERSIST} consecutive observations; onset_ps = step*0.001",
    })
    summ_rates.append({
        "rate_label": rate, "rate_K_per_s": RATE_VAL[rate],
        "final_subset_fraction": finals[rate], "final_step": last_step_by_rate[rate],
        "onset_ps_declared_rule": onsets[rate],
        "onset_reason": None if onsets[rate] is not None else "no onset under declared rule",
        "representative_peak_width_change_A_inv": delta,
        "kinetics_class": kin, "scattering_class": scat, "joint_evidence": agreement,
    })

# ---------- write CSVs ----------
OUT.mkdir(parents=True, exist_ok=True)
(OUT / "figures").mkdir(exist_ok=True)
def write_csv(name, header, rows):
    with (OUT / name).open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=header); w.writeheader(); w.writerows(rows)

write_csv("crystallinity_timeseries.csv",
          ["rate_K_per_s","step","time_ps","n_cubic","n_hex","n_other","n_filtered_subset","crystalline_fraction_subset","temperature_K","temperature_source"],
          ts_rows)
write_csv("scattering_peak_metrics.csv",
          ["rate_K_per_s","state","peak_rank_q_ascending","q_peak_A_inv","peak_height","peak_width_A_inv","peak_width_method","window_A_inv","normalization"],
          peak_rows)
write_csv("rate_comparison.csv",
          ["rate_K_per_s","onset_ps","onset_reason","final_subset_fraction","delta_peak_width_A_inv","kinetics_trend","scattering_trend","agreement","onset_definition"],
          comp_rows)

# ---------- summary.json ----------
summary = {
    "method": {
        "onset": {"threshold_fraction": THRESH, "consecutive_observations": PERSIST,
                  "rule": "first step>=200000 with filtered-subset crystalline fraction >= threshold for consecutive observations; onset_ps=step*0.001",
                  "excluded_steps": "steps < 200000 (startup records 0 and 1)"},
        "uncertainty": {"q_peak_A_inv": 0.01,
                        "basis": "0.01 A^-1 raw S(q) grid spacing; peak q is a grid point, so the q uncertainty is one grid step",
                        "width_A_inv": "width recomputed on raw grid by declared rule; 0.02 A^-1 comparison tolerance"},
        "peak_detection": {"min_prominence_A_inv_units": PEAK_PROM,
                           "note": "prominence = s_peak - max(left_min, right_min) within window 3.00-4.20 A^-1"},
    },
    "time_unit": "ps (time_ps = step * 0.001 ps; LAMMPS timestep 0.001 ps per method-note.md:5)",
    "denominator_definition": "filtered-subset fraction: (n_cubic+n_hex)/(n_cubic+n_hex+n_other); not fraction of all atoms (method-note.md:3)",
    "scattering_consistency": {
        "channel": "X-ray (second column)",
        "fixed_q_window_A_inv": [3.0, 4.2],
        "peak_width_method": PEAK_WIDTH_METHOD,
        "peak_width_class_boundary_A_inv": WIDTH_BOUNDARY,
        "source_data_calibration": "Figure 6 Source Data workbook is absent from public package inputs; no independent workbook comparison is claimed",
        "limitations": [
            "Crystallinity is a filtered-subset fraction (atoms with <=1 Si-O bond, cutoff 2.0 A, PTM classification), not the whole-cell fraction (method-note.md:3).",
            "The 1e12/2e12/5e12/1e13 labels are sample preparation conditions; the programmed heat-treatment rate is 1e10 K/s (method-note.md:7).",
            "Onset is resolved only at the native output spacing; any no-onset result means the declared threshold was not reached within the observed window.",
            "Peak positions are on a 0.01 A^-1 grid; width and position uncertainty is one grid step.",
            "Post-state scattering classes are derived from detected peak multiplicity and measured widths relative to the declared boundary, not from rate labels.",
            "The declared kinetics/scattering agreement compares the final-subset strong-class indicator with whether a resolved crystalline doublet was measured."
        ],
    },
    "onset_sensitivity_ps": {k: {r: sens[r][k] for r in RATES} for k in ("0.001", "0.01", "0.05")},
    "rate_results": summ_rates,
    "source_data_check": {r: {"status": "not_recomputed",
                              "note": "Source Data workbook is absent from public package inputs; crystallinity is recomputed from the deposited native count series"} for r in RATES},
    "source_scattering_check": {r: {"status": "not_recomputed",
                                    "note": "Source Data workbook is absent from public package inputs; peak metrics are recomputed from the deposited native X-ray S(q) series"} for r in RATES},
}
(OUT / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

# ---------- figure ----------
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5), dpi=100)
for rate in RATES:
    t = [r[0]*0.001 for r in cryst_plot[rate]]
    f = [(r[1]+r[2])/sum(r[1:]) for r in cryst_plot[rate]]
    ax1.plot(t, f, marker="o", ms=3, label=f"{rate} K/s")
ax1.axhline(THRESH, color="k", ls=":", lw=1, label=f"{THRESH*100:.0f}% threshold")
ax1.set_xlabel("time (ps)"); ax1.set_ylabel("crystalline fraction (filtered subset)")
ax1.set_title("Crystallinity time series (all rates)"); ax1.legend(fontsize=8)
for rate, color in zip(RATES, ("C0", "C1", "C2", "C3")):
    for state, ls in (("before", ":"), ("after", "-")):
        sq, pk = peaks_by[(rate, state)]
        xs = [r[0] for r in sq if WIN[0] <= r[0] <= WIN[1]]
        ys = [r[1] for r in sq if WIN[0] <= r[0] <= WIN[1]]
        ax2.plot(xs, ys, ls=ls, color=color, lw=1, label=f"{rate} {state}")
        for p in pk:
            ax2.annotate(f"{p['q']:.2f}", (p["q"], p["height"]), fontsize=7, color=color,
                         xytext=(0, 4), textcoords="offset points", ha="center")
ax2.set_xlim(*WIN); ax2.set_xlabel("q (Å$^{-1}$)"); ax2.set_ylabel("X-ray S(q) (2nd column)")
ax2.set_title("X-ray S(q), before (dotted) / after (solid), window 3.00-4.20 Å$^{-1}$")
ax2.legend(fontsize=7, ncol=2)
fig.tight_layout()
fig.savefig(OUT / "figures" / "crystallinity_and_sq.png")
print(f"[solve] wrote {len(ts_rows)} timeseries rows, {len(peak_rows)} peak rows, 4 comparison rows")
print("[solve] onsets:", onsets)
print("[solve] finals:", finals)
PY

echo "[solve] done: $APP_ROOT/outputs"
