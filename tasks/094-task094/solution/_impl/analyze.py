#!/usr/bin/env python3
"""Analyze selected SPC/E configurations using direct reciprocal-vector sums."""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import math
import sys
import time
from pathlib import Path
import numpy as np

EPS0 = 8.8541878128e-12
KB = 1.380649e-23
E_CHARGE = 1.602176634e-19
TEMP_K = 300.0
BOOTSTRAP_SEED = 20261008
BOOTSTRAP_REPLICATES = 2000
BLOCK_LENGTH_PS = 1000.0
MAX_N = 62
LOW_WINDOW = (0.15, 1.20)
PEAK_WINDOW = (2.0, 4.5)


def canonical_vectors(max_n: int = MAX_N) -> np.ndarray:
    rows = []
    for n in range(1, max_n + 1):
        rows.extend(((n, 0, 0), (0, n, 0), (0, 0, n)))
    return np.asarray(rows, dtype=np.int16)


def read_vectors(path: Path | None) -> np.ndarray:
    if path is None:
        return canonical_vectors()
    rows = []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != ["nx", "ny", "nz"]:
            raise ValueError("mode vector CSV header must be nx,ny,nz")
        for row in reader:
            rows.append([int(row[k]) for k in ("nx", "ny", "nz")])
    v = np.asarray(rows, dtype=np.int64)
    if v.ndim != 2 or v.shape[1] != 3 or len(v) == 0 or np.any(np.all(v == 0, axis=1)):
        raise ValueError("mode vector file must contain nonzero integer triples")
    if np.max(np.abs(v)) > MAX_N:
        raise ValueError("integer vector components must be within -62..62")
    return v.astype(np.int16)


def mode_shells(vectors: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    n2 = np.sum(vectors.astype(np.int64) ** 2, axis=1)
    n_shell = np.rint(np.sqrt(n2)).astype(int)
    if np.any(n_shell < 1) or np.any(n_shell > MAX_N) or np.any(n_shell * n_shell != n2):
        raise ValueError("every mode must lie on an integer-|n| shell from 1 through 62")
    shells = np.arange(1, int(n_shell.max()) + 1, dtype=int)
    if not np.array_equal(np.unique(n_shell), shells):
        raise ValueError("mode vector file must cover contiguous integer-|n| shells")
    counts = np.bincount(n_shell, minlength=len(shells) + 1)[1:]
    if np.any(counts == 0):
        raise ValueError("every integer-|n| shell needs at least one reciprocal vector")
    canonical = []
    for vec in vectors.astype(np.int64):
        nz = np.flatnonzero(vec)
        canonical.append(tuple((-vec if vec[nz[0]] < 0 else vec).tolist()))
    if len(set(canonical)) != len(canonical):
        raise ValueError("duplicate reciprocal vectors up to sign are not allowed")
    return n_shell, counts


def load_sample(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    with np.load(path, allow_pickle=False) as z:
        required = {"positions_A", "box_dimensions_A_deg", "charges_e", "times_ps", "frame_indices"}
        if set(z.files) != required:
            raise ValueError(f"sample keys must be exactly {sorted(required)}")
        positions = np.asarray(z["positions_A"], dtype=np.float64)
        box6 = np.asarray(z["box_dimensions_A_deg"], dtype=np.float64)
        charges = np.asarray(z["charges_e"], dtype=np.float64)
        times = np.asarray(z["times_ps"], dtype=np.float64)
        indices = np.asarray(z["frame_indices"], dtype=np.int64)
    if positions.ndim != 3 or positions.shape[1:] != (27099, 3) or positions.shape[0] < 8:
        raise ValueError("positions_A must have shape (frames>=10,27099,3)")
    nf = len(positions)
    if box6.shape != (nf, 6) or charges.shape != (27099,) or times.shape != (nf,) or indices.shape != (nf,):
        raise ValueError("sample arrays have inconsistent dimensions")
    if not all(np.isfinite(a).all() for a in (positions, box6, charges, times)):
        raise ValueError("sample contains nonfinite values")
    if np.any(charges.reshape(-1, 3)[:, 0] >= 0) or not np.allclose(charges.reshape(-1, 3), [-0.8476, 0.4238, 0.4238], atol=2e-4, rtol=0):
        raise ValueError("partial charges are not SPC/E OW,HW1,HW2 triples")
    if abs(float(charges.sum())) > 1e-4:
        raise ValueError("SPC/E charge vector is not neutral")
    if not np.allclose(box6, box6[0], atol=2e-3, rtol=0):
        raise ValueError("sample box varies across frames")
    if np.max(np.abs(box6[0, :3] - np.mean(box6[0, :3]))) > 2e-3 or not np.allclose(box6[0, 3:], 90.0, atol=2e-3, rtol=0):
        raise ValueError("response analysis requires a fixed cubic box")
    if np.any(box6[0, :3] <= 0) or len(np.unique(times)) != nf or len(np.unique(indices)) != nf:
        raise ValueError("times and frame indices must be unique and box lengths positive")
    order = np.argsort(times, kind="stable")
    return positions[order], box6[order], charges, times[order], indices[order]


def direct_structure_factors(positions: np.ndarray, charges: np.ndarray,
                             box_a: float, vectors: np.ndarray) -> np.ndarray:
    """Return per-frame, per-vector |sum_j q_j exp(-i k.r_j)|^2.

    Axis-aligned integer shells use a complex phase recurrence, which is exact
    up to floating-point roundoff and avoids allocating a dense frames-atoms-k array.
    Other integer vectors use a direct exponential sum.
    """
    nf = len(positions)
    powers = np.empty((nf, len(vectors)), dtype=np.float64)
    kfac = 2.0 * np.pi / box_a
    axis_vectors = np.zeros((3, MAX_N, 3), dtype=np.int16)
    axis_members: dict[int, list[tuple[int, int]]] = {0: [], 1: [], 2: []}
    is_axis = np.zeros(len(vectors), dtype=bool)
    for j, vec in enumerate(vectors):
        nz = np.flatnonzero(vec)
        if len(nz) == 1:
            axis, n = int(nz[0]), abs(int(vec[nz[0]]))
            axis_members[axis].append((j, n))
            is_axis[j] = True
    axis_columns = [j for j, b in enumerate(is_axis) if b]
    other_columns = [j for j, b in enumerate(is_axis) if not b]
    for fi, xyz32 in enumerate(positions):
        xyz = np.remainder(xyz32.astype(np.float64), box_a)
        for axis in range(3):
            members = sorted(axis_members[axis], key=lambda item: item[1])
            if not members:
                continue
            base = np.exp((-2j * np.pi / box_a) * xyz[:, axis])
            phase = base.copy()
            wanted: dict[int, list[int]] = {}
            for j, n in members:
                wanted.setdefault(n, []).append(j)
            for n in range(1, max(wanted) + 1):
                if n in wanted:
                    rho = np.dot(charges, phase)
                    value = float(rho.real * rho.real + rho.imag * rho.imag)
                    for j in wanted[n]:
                        powers[fi, j] = value
                phase *= base
        for j in other_columns:
            kvec = kfac * vectors[j].astype(np.float64)
            angle = np.remainder(xyz @ kvec, 2.0 * np.pi)
            rho = np.dot(charges, np.exp(-1j * angle))
            powers[fi, j] = float(rho.real * rho.real + rho.imag * rho.imag)
    return powers


def dipoles_and_m2(positions: np.ndarray, charges: np.ndarray, box_a: float) -> np.ndarray:
    xyz = positions.reshape(len(positions), 9033, 3, 3)
    dr = xyz[:, :, 1:, :] - xyz[:, :, :1, :]
    dr -= box_a * np.rint(dr / box_a)
    q = charges.reshape(9033, 3)[:, 1:]
    return np.einsum("fwhc,wh->fc", dr, q, optimize=True)


def parabolic_extremum(k: np.ndarray, y: np.ndarray, i: int, kind: str) -> tuple[float, float]:
    x3 = k[i-1:i+2]
    y3 = y[i-1:i+2]
    a, b, c = np.polyfit(x3, y3, 2)
    if kind == "min" and a <= 0 or kind == "max" and a >= 0:
        return float(k[i]), float(y[i])
    xv = -b / (2.0 * a)
    if not (x3[0] <= xv <= x3[-1]):
        return float(k[i]), float(y[i])
    return float(xv), float(a * xv * xv + b * xv + c)


def low_minimum(k: np.ndarray, chi: np.ndarray, se: np.ndarray) -> dict:
    in_window = (k >= LOW_WINDOW[0]) & (k <= LOW_WINDOW[1])
    candidates = [i for i in range(1, len(k)-1) if in_window[i] and chi[i] < chi[i-1] and chi[i] <= chi[i+1]]
    if not candidates:
        return {"value": None, "chi": None, "status": "unresolved", "reason": "no interior local minimum in fixed 0.15–1.20 A^-1 window"}
    i = min(candidates, key=lambda j: chi[j])
    left = max(0, int(np.flatnonzero(in_window)[0]) - 1)
    right = min(len(k)-1, int(np.flatnonzero(in_window)[-1]) + 1)
    shoulders = [max(chi[left:i]), max(chi[i+1:right+1])]
    prominence = min(shoulders) - chi[i]
    sigma = math.sqrt(se[i] ** 2 + max(se[left:i+1].max(), se[i:right+1].max()) ** 2)
    if prominence <= 2.0 * sigma:
        return {"value": None, "chi": None, "status": "unresolved", "reason": "low-k trough prominence is not greater than two block standard errors"}
    kval, cval = parabolic_extremum(k, chi, i, "min")
    return {"value": kval, "chi": cval, "status": "resolved", "reason": None}


def high_peak_and_width(k: np.ndarray, chi: np.ndarray) -> tuple[dict, dict]:
    w = (k >= PEAK_WINDOW[0]) & (k <= PEAK_WINDOW[1])
    indices = np.flatnonzero(w)
    if len(indices) < 3:
        raise ValueError("reciprocal grid does not resolve the fixed peak window")
    i = int(indices[np.argmax(chi[indices])])
    if i <= indices[0] or i >= indices[-1]:
        return ({"value": None, "status": "unresolved", "reason": "overscreening peak is at the fixed-window boundary"},
                {"value": None, "status": "unresolved", "reason": "peak does not have an interior maximum"})
    kval, cmax = parabolic_extremum(k, chi, i, "max")
    half = cmax / 2.0
    lefts = [j for j in range(i) if (chi[j] - half) * (chi[j+1] - half) <= 0]
    rights = [j for j in range(i, len(k)-1) if (chi[j] - half) * (chi[j+1] - half) <= 0]
    if not lefts or not rights or cmax <= 0:
        return ({"value": kval, "status": "resolved", "reason": None},
                {"value": None, "status": "unresolved", "reason": "chi(k_max)/2 crossing is not bracketed on both sides"})
    def cross(j: int) -> float:
        dy = chi[j+1] - chi[j]
        if abs(dy) < 1e-15:
            return float((k[j] + k[j+1]) / 2)
        return float(k[j] + (half - chi[j]) * (k[j+1] - k[j]) / dy)
    km, kp = cross(lefts[-1]), cross(rights[0])
    return ({"value": kval, "status": "resolved", "reason": None},
            {"value": kp-km, "status": "resolved", "reason": None, "k_minus_Ainv": km, "k_plus_Ainv": kp})


def features(k: np.ndarray, chi: np.ndarray, se: np.ndarray) -> dict:
    low = low_minimum(k, chi, se)
    peak, width = high_peak_and_width(k, chi)
    return {"k_min_Ainv": low["value"], "chi_min": low["chi"],
            "k_min_status": low["status"], "k_min_reason": low["reason"],
            "chi_min_status": low["status"], "chi_min_reason": low["reason"],
            "k_max_Ainv": peak["value"], "k_max_status": peak["status"], "k_max_reason": peak["reason"],
            "delta_k_Ainv": width["value"], "delta_k_status": width["status"], "delta_k_reason": width["reason"],
            "k_minus_Ainv": width.get("k_minus_Ainv"), "k_plus_Ainv": width.get("k_plus_Ainv")}


def se_rows(blocks: np.ndarray) -> np.ndarray:
    return np.std(blocks, axis=0, ddof=1) / math.sqrt(len(blocks))


def uncertainty_obj(value, se, units, status="resolved", reason=None, **extra):
    return {"value": None if value is None else float(value),
            "standard_error": None if se is None else float(se),
            "units": units, "status": status, "reason": reason, **extra}


def run(input_path: Path, out: Path, vector_path: Path | None, block_length_ps: float, bootstrap_reps: int) -> None:
    t0 = time.monotonic()
    positions, box6, charges, times, indices = load_sample(input_path)
    if not math.isfinite(block_length_ps) or block_length_ps <= 0:
        raise ValueError("block-length-ps must be finite and positive")
    block_id = np.floor((times - times[0] + 1e-8) / block_length_ps).astype(int)
    block_labels = np.unique(block_id)
    if len(block_labels) < 8:
        raise ValueError("need at least eight populated contiguous time blocks")
    if len(block_labels) % 2:
        raise ValueError("the number of populated 1 ns blocks must be even for the 2 ns reblocking check")
    if not np.array_equal(block_labels, np.arange(block_labels[0], block_labels[-1] + 1)):
        raise ValueError("selected sample has an empty contiguous time block")
    nblocks = len(block_labels)
    block_counts = np.asarray([np.count_nonzero(block_id == bid) for bid in block_labels])
    if np.any(block_counts != block_counts[0]):
        raise ValueError("each contiguous 1 ns block must contain the same number of selected frames")
    used = len(times)
    box_a = float(np.mean(box6[0, :3]))
    volume_a3 = box_a ** 3
    vectors = read_vectors(vector_path)
    shell_idx, mode_counts = mode_shells(vectors)
    vector_sha256 = hashlib.sha256(vectors.astype("<i2", copy=False).tobytes()).hexdigest()
    powers = direct_structure_factors(positions, charges, box_a, vectors)
    shell_n = int(shell_idx.max())
    shell_power = np.empty((len(positions), shell_n), dtype=np.float64)
    for n in range(1, shell_n+1):
        shell_power[:, n-1] = np.mean(powers[:, shell_idx == n], axis=1)
    block_power = np.stack([shell_power[block_id == bid].mean(axis=0) for bid in block_labels])
    mean_power = shell_power.mean(axis=0)
    k_a = 2.0 * np.pi * np.arange(1, shell_n+1) / box_a
    k_m = k_a * 1e10
    volume_m3 = volume_a3 * 1e-30
    chi_factor = E_CHARGE**2 / (EPS0 * KB * TEMP_K * volume_m3 * k_m**2)
    chi_curve = mean_power * chi_factor
    block_chi = block_power * chi_factor
    se1 = se_rows(block_chi)
    complete_1ns_bins = nblocks
    complete = block_id < complete_1ns_bins
    block_id2 = np.floor((times[complete] - times[0] + 1e-8) / (2.0 * block_length_ps)).astype(int)
    labels2 = np.unique(block_id2)
    block_chi2 = np.stack([shell_power[complete][block_id2 == bid].mean(axis=0) * chi_factor for bid in labels2])
    se2 = se_rows(block_chi2) if len(block_chi2) > 1 else np.full(shell_n, np.nan)
    chi2 = block_chi2.mean(axis=0)

    dipoles = dipoles_and_m2(positions, charges, box_a)
    global_center = dipoles.mean(axis=0)
    eps_factor = E_CHARGE**2 * 1e-20 / (EPS0 * KB * TEMP_K * volume_m3 * 3.0)
    eps_frames = 1.0 + eps_factor * np.sum((dipoles - global_center) ** 2, axis=1)
    eps_blocks = np.asarray([eps_frames[block_id == bid].mean() for bid in block_labels])
    eps = float(eps_frames.mean())
    eps_leave_one_out = []
    for bid in block_labels:
        keep = block_id != bid
        mbar = dipoles[keep].mean(axis=0)
        eps_leave_one_out.append(1.0 + eps_factor * float(np.mean(np.sum((dipoles[keep]-mbar)**2, axis=1))))
    eps_leave_one_out = np.asarray(eps_leave_one_out)
    eps_jackknife_se = float(math.sqrt((nblocks-1)/nblocks * np.sum((eps_leave_one_out-eps_leave_one_out.mean())**2)))
    dipoles2 = dipoles[complete]
    global_center2 = dipoles2.mean(axis=0)
    eps_frames2 = 1.0 + eps_factor * np.sum((dipoles2-global_center2)**2, axis=1)
    eps_blocks2 = np.asarray([eps_frames2[block_id2 == bid].mean() for bid in labels2])
    eps2 = float(eps_frames2.mean())
    eps_jackknife2 = []
    for bid in labels2:
        keep = block_id2 != bid
        mbar = dipoles2[keep].mean(axis=0)
        eps_jackknife2.append(1.0 + eps_factor * float(np.mean(np.sum((dipoles2[keep]-mbar)**2, axis=1))))
    eps_jackknife2 = np.asarray(eps_jackknife2)
    eps_se2 = (float(math.sqrt((len(labels2)-1)/len(labels2) * np.sum((eps_jackknife2-eps_jackknife2.mean())**2)))
               if len(labels2)>1 else None)

    base_features = features(k_a, chi_curve, se1)
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    feature_names = ("k_min_Ainv", "chi_min", "k_max_Ainv", "delta_k_Ainv")
    boot: dict[str, list[float]] = {name: [] for name in feature_names}
    for _ in range(bootstrap_reps):
        pick = rng.integers(0, nblocks, size=nblocks)
        curve = block_chi[pick].mean(axis=0)
        bse = se_rows(block_chi[pick]) if nblocks > 1 else np.zeros(shell_n)
        f = features(k_a, curve, bse)
        for name in feature_names:
            val = f[name]
            if val is not None and math.isfinite(val):
                boot[name].append(float(val))
    grid_spacing = float(k_a[1] - k_a[0]) if len(k_a) > 1 else 2.0*math.pi/box_a
    resolution_floor_k = grid_spacing / math.sqrt(12.0)
    resolution_floor_width = grid_spacing / math.sqrt(6.0)
    def boot_se(name: str, floor: float) -> tuple[float | None, float, int]:
        vals = np.asarray(boot[name], dtype=np.float64)
        if len(vals) < max(100, int(0.8 * bootstrap_reps)):
            return None, None, len(vals)
        sd = float(vals.std(ddof=1))
        return max(sd, floor), sd, len(vals)
    kmin_se, kmin_boot_se, kmin_n = boot_se("k_min_Ainv", resolution_floor_k)
    chimin_se, chimin_boot_se, chimin_n = boot_se("chi_min", 0.0)
    kmax_se, kmax_boot_se, kmax_n = boot_se("k_max_Ainv", resolution_floor_k)
    width_se, width_boot_se, width_n = boot_se("delta_k_Ainv", resolution_floor_width)
    min_required_boot = max(100, int(0.8 * bootstrap_reps))
    if kmin_n < min_required_boot:
        for key in ("k_min_Ainv", "chi_min"):
            base_features[key] = None
        base_features["k_min_status"] = base_features["chi_min_status"] = "unresolved"
        base_features["k_min_reason"] = base_features["chi_min_reason"] = "fewer than 80% of fixed-seed block-bootstrap samples resolved the low-k trough"
    if kmax_n < min_required_boot:
        base_features["k_max_Ainv"] = None
        base_features["k_max_status"] = "unresolved"
        base_features["k_max_reason"] = "fewer than 80% of fixed-seed block-bootstrap samples resolved the overscreening peak"
    if width_n < min_required_boot:
        base_features["delta_k_Ainv"] = None
        base_features["delta_k_status"] = "unresolved"
        base_features["delta_k_reason"] = "fewer than 80% of fixed-seed block-bootstrap samples bracketed both half-maximum crossings"
    f2 = features(k_a, chi2, se2) if chi2 is not None else {}

    out.mkdir(parents=True, exist_ok=True)
    chi_path = out / "chi_k.csv"
    with chi_path.open("w", newline="", encoding="utf-8") as f:
        fields = ["n_index", "k_Ainv", "chi_parallel", "se_1ns", "se_2ns", "n_directions"]
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader()
        for i in range(shell_n):
            w.writerow({"n_index": i+1, "k_Ainv": f"{k_a[i]:.12g}", "chi_parallel": f"{chi_curve[i]:.12g}",
                        "se_1ns": f"{se1[i]:.12g}", "se_2ns": f"{se2[i]:.12g}", "n_directions": int(mode_counts[i])})
    def item(valkey: str, se, units: str, statuskey: str, reasonkey: str, extra: dict | None = None):
        val = base_features[valkey]
        status = base_features[statuskey]
        reason = base_features[reasonkey]
        more = {} if extra is None else extra
        return uncertainty_obj(val, se, units, status, reason,
                              independent_2ns_value=f2.get(valkey),
                              independent_2ns_status=f2.get(statuskey), **more)
    observables = {
        "eps_w": uncertainty_obj(eps, eps_jackknife_se, "dimensionless", independent_2ns_value=eps2,
                                  independent_2ns_standard_error=eps_se2,
                                  uncertainty_method="delete-one-1 ns-block jackknife, recomputing the global dipole mean; dipoles use the complete selected trajectory mean"),
        "k_min_Ainv": item("k_min_Ainv", kmin_se, "Angstrom^-1", "k_min_status", "k_min_reason",
                            {"bootstrap_standard_error": kmin_boot_se, "finite_k_resolution_floor": resolution_floor_k, "valid_bootstrap_replicates": kmin_n}),
        "chi_min": item("chi_min", chimin_se, "dimensionless", "chi_min_status", "chi_min_reason",
                         {"bootstrap_standard_error": chimin_boot_se, "valid_bootstrap_replicates": chimin_n}),
        "k_max_Ainv": item("k_max_Ainv", kmax_se, "Angstrom^-1", "k_max_status", "k_max_reason",
                            {"bootstrap_standard_error": kmax_boot_se, "finite_k_resolution_floor": resolution_floor_k, "valid_bootstrap_replicates": kmax_n}),
        "delta_k_Ainv": item("delta_k_Ainv", width_se, "Angstrom^-1", "delta_k_status", "delta_k_reason",
                              {"bootstrap_standard_error": width_boot_se, "finite_k_resolution_floor": resolution_floor_width,
                               "k_minus_Ainv": base_features["k_minus_Ainv"], "k_plus_Ainv": base_features["k_plus_Ainv"],
                               "valid_bootstrap_replicates": width_n})
    }
    result = {"schema": "ihf008-observables/v1", "temperature_K": TEMP_K,
              "selected_frames": int(used), "selected_source_frame_indices": [int(indices[0]), int(indices[-1])],
              "saved_interval_ps": float(np.median(np.diff(times))), "block_length_ps": block_length_ps,
              "blocks_1ns": int(nblocks), "blocks_2ns": 0 if block_chi2 is None else int(len(block_chi2)),
              "box_A": [float(x) for x in box6[0, :3]], "volume_A3": volume_a3,
              "reciprocal_sampling": {"vectors": "integer vectors from --vectors" if vector_path else "three Cartesian reciprocal axes per integer shell",
                                       "n_min": 1, "n_max": shell_n, "k_spacing_Ainv": grid_spacing,
                                       "mode_vectors_sha256": vector_sha256,
                                       "directions_per_shell": [int(x) for x in mode_counts]},
              "uncertainty": {"blocks_1ns": nblocks, "reblocking_check": "10 contiguous 2 ns blocks" if nblocks == 20 else f"{len(block_chi2)} contiguous 2 ns blocks",
                              "feature_bootstrap": {"resamples": bootstrap_reps, "seed": BOOTSTRAP_SEED, "unit": "contiguous 1 ns blocks", "resolution_floor_k_Ainv": resolution_floor_k, "resolution_floor_delta_k_Ainv": resolution_floor_width}},
              "observables": observables}
    (out / "observables.json").write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    input_hash = hashlib.sha256(input_path.read_bytes()).hexdigest()
    lines = ["IHF Case 008 direct reciprocal-space analysis", f"input={input_path}", f"input_sha256={input_hash}",
             f"frames_used={used}", f"source_frame_index_first_last={int(indices[0])},{int(indices[-1])}",
             f"time_range_ps={float(times[0]):.12g},{float(times[-1]):.12g}",
             f"saved_interval_ps={float(np.median(np.diff(times))):.12g}", f"block_length_ps={block_length_ps:.12g}",
             f"blocks_1ns={nblocks}", f"blocks_2ns={len(block_chi2)}",
             f"atoms={positions.shape[1]}", f"waters={positions.shape[1]//3}", f"box_A={box6[0,:3].tolist()}",
             f"box_angles_deg={box6[0,3:].tolist()}", f"volume_A3={volume_a3:.12g}", f"charge_sum_e={charges.sum():.12g}",
             f"reciprocal_vectors={'integer vectors from --vectors' if vector_path else '3 Cartesian axes x n=1..' + str(shell_n)}",
             f"mode_vectors_sha256={vector_sha256}", f"directions_per_shell={mode_counts.tolist()}",
             f"chi_csv_header=n_index,k_Ainv,chi_parallel,se_1ns,se_2ns,n_directions",
             f"temperature_K={TEMP_K}", "position_units=Angstrom", "charge_units=elementary_charge",
             "chi_formula=e^2*S(k)/(epsilon0*kB*T*V*k^2), SI prefactor",
             "epsilon_uncertainty=delete-one-contiguous-block jackknife with global recentering",
             f"low_k_window_Ainv={LOW_WINDOW[0]},{LOW_WINDOW[1]}", f"overscreening_peak_window_Ainv={PEAK_WINDOW[0]},{PEAK_WINDOW[1]}",
             f"bootstrap_seed={BOOTSTRAP_SEED}", f"bootstrap_replicates={bootstrap_reps}",
             f"elapsed_seconds={time.monotonic()-t0:.6f}", "status=complete"]
    (out / "analysis.log").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", type=Path, required=True, help="trajectory_sample.npz")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--vectors", type=Path, help="optional CSV of reciprocal integer vectors nx,ny,nz")
    ap.add_argument("--block-length-ps", type=float, default=BLOCK_LENGTH_PS)
    ap.add_argument("--bootstrap-replicates", type=int, default=BOOTSTRAP_REPLICATES)
    args = ap.parse_args()
    try:
        run(args.input, args.out, args.vectors, args.block_length_ps, args.bootstrap_replicates)
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
