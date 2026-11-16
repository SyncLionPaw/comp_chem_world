"""Safe, declarative protocol primitives for Case 04 (public inputs only).

This module intentionally has no reference-answer or grader-runtime dependency.
Candidate runners and the independent verifier construct their own fits from a
validated JSON protocol; candidate code and pickle files are never imported.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import ConstantKernel, Matern, RBF, WhiteKernel
from sklearn.model_selection import KFold, LeaveOneGroupOut
from sklearn.preprocessing import StandardScaler

_HERE = Path(__file__).resolve()
CASE = next((p for p in _HERE.parents if p.name == "case-04-uncertainty-applicability-domain"
             and (p / "environment/assets/master_s115_blindarm.csv").is_file()), None)
if CASE is None:
    CASE = next((p for p in _HERE.parents if (p / "task.toml").is_file()
                 and (p / "environment/assets/master_s115_blindarm.csv").is_file()), None)
if CASE is None:
    ROOT = _HERE.parents[1]
    CASE = ROOT / "packages/case-04-uncertainty-applicability-domain"
else:
    ROOT = next((p for p in CASE.parents if (p / "packages" / CASE.name).resolve() == CASE.resolve()), CASE.parents[1])
ASSETS = CASE / "environment/assets"
SCHEMA = "case04-protocol/v2"
INPUT_PROFILE = "frozen-blind-s118-s119/v1"
FEATURE_BASIS = "s120-drop-row-index-plus-qhbarrier/v1"
PUBLIC_ASSET_SHA256 = {
    "master_s115_blindarm.csv": "0491a107e23a9f7113376a378aafefacca58e75fc276413063c09413e4d668bb",
    "SC-012-D0SC04896H-s120.csv": "37d52b584033c1f7932537241c635b1f93878220500156455aef2e305a3677de",
    "SC-012-D0SC04896H-s113.npy": "283a0daa6a2a3eebc056d358a02a1e10191b659fbe03538f47b30f3d78747160",
    "SC-012-D0SC04896H-s114.npy": "800116bf2a4d89d90d254f41b6df8e5617d99427aae4ed7358396ee5a112ca24",
    "SC-012-D0SC04896H-s117.npy": "2f40cce1d8819093da3009d7880364a25cac06ffd0368f79946a5de5ef9c59f4",
    "SC-012-D0SC04896H-s118.npy": "a0621d32a62ccff1bd675c1b410dbcc679dcb7b62241077158a4e19b654d140a",
    "SC-012-D0SC04896H-s119.npy": "189f3abea25fa3d4a008dc45b82fbeee69680db1164f0cd72d79b79a107ebdb1",
    "S12_replicate_barrier_pairs.csv": "8dbabac18ff105aaa63e73998d8f1745bc2e6e02724cfedc7727c53593510cec",
}


def _int(value: Any, name: str, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f"{name} must be an integer in [{low}, {high}]")
    return value


def _finite(value: Any, name: str, low: float | None = None, high: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ValueError(f"{name} must be finite numeric")
    out = float(value)
    if low is not None and out < low or high is not None and out > high:
        raise ValueError(f"{name} is outside its supported range")
    return out


class InputBindingConflict(ValueError):
    """An explicit declaration contradicts the prescribed frozen scientific input."""


_ANNOTATION_FIELDS = {"note", "notes", "description", "provenance", "metadata"}


def _execution_only(value):
    """Annotations remain in the declaration but never become executable parameters."""
    if isinstance(value, dict): return {key: _execution_only(item) for key, item in value.items() if key not in _ANNOTATION_FIELDS}
    if isinstance(value, list): return [_execution_only(item) for item in value]
    return value


def _frozen_source(value, expected, path):
    if not isinstance(value, str) or not value.strip(): raise ValueError(f"{path} must name a public source")
    aliases = {alias: filename for filename in PUBLIC_ASSET_SHA256 for alias in
               (filename, f"assets/{filename}", f"/app/assets/{filename}", filename.removeprefix("SC-012-D0SC04896H-"))}
    source = aliases.get(value)
    if source is None: raise NotImplementedError(f"unrecognized source binding at {path}: {value!r}")
    if source != expected: raise InputBindingConflict(f"{path}: submitted={value!r}; frozen source={expected!r}")
    return source


def _fixed_source_assertions(execution):
    """Validate optional repeated source facts before removing them from execution."""
    verified = []
    if "target" in execution:
        target = _keys(execution["target"], set(), {"source", "column"}, "target")
        if "source" in target:
            source = _frozen_source(target["source"], "master_s115_blindarm.csv", "target.source")
            verified.append({"path": "target.source", "source": source})
        if "column" in target:
            if not isinstance(target["column"], str): raise ValueError("target.column must be a column name")
            if target["column"] != "exp_activation_energy": raise InputBindingConflict(f"target.column: submitted={target['column']!r}; frozen column='exp_activation_energy'")
            verified.append({"path": "target.column", "column": target["column"]})
        del execution["target"]
    if "groups" in execution:
        fixed = {"substrate": "SC-012-D0SC04896H-s117.npy", "nucleophile": "SC-012-D0SC04896H-s114.npy", "reaction": "SC-012-D0SC04896H-s113.npy"}
        groups = _keys(execution["groups"], set(), set(fixed), "groups")
        for role, expected in fixed.items():
            if role in groups:
                source = _frozen_source(groups[role], expected, f"groups.{role}")
                verified.append({"path": f"groups.{role}", "source": source})
        del execution["groups"]
    return verified


def _keys(obj: Any, required: set[str], optional: set[str], name: str) -> dict[str, Any]:
    if not isinstance(obj, dict):
        raise ValueError(f"{name} must be an object")
    missing = required - set(obj)
    if missing:
        raise ValueError(f"{name} fields missing: {sorted(missing)}")
    extra = set(obj) - required - optional - _ANNOTATION_FIELDS
    if extra:
        raise NotImplementedError(f"unsupported {name} fields: {sorted(extra)}")
    return obj


class DeclaredProtocol(dict):
    """Execution defaults are separate from the original declaration digest."""
    def __init__(self, execution, declaration, source_assertions=()):
        super().__init__(execution)
        self.declaration = declaration
        self.source_assertions = list(source_assertions)


def _fixed_protocol_defaults(declaration):
    p = json.loads(json.dumps(declaration, allow_nan=False))
    if not isinstance(p, dict): raise ValueError("protocol must be an object")
    p.setdefault("schema", SCHEMA); p.setdefault("input_profile", INPUT_PROFILE)
    p.setdefault("logo", {"group_roles": ["substrate", "nucleophile"], "pool": "frozen_train"})
    p.setdefault("multicondition", {"routes": ["all_train", "single_reaction_only"], "group_vector": "reaction"})
    fixed = {"logo": {"group_roles": ["substrate", "nucleophile"], "pool": "frozen_train"},
             "multicondition": {"routes": ["all_train", "single_reaction_only"], "group_vector": "reaction"},
             "model": {"type": "gpr", "normalize_y": False},
             "cv": {"kind": "kfold", "shuffle": True, "repeats": 1},
             "permutation": {"rng": "RandomState"},
             "ad": {"distance": "rms_euclidean", "quantile_method": "linear"}}
    for section, defaults in fixed.items():
        if section in p and isinstance(p[section], dict):
            for key, value in defaults.items(): p[section].setdefault(key, value)
    kernel = p.get("model", {}).get("kernel") if isinstance(p.get("model"), dict) else None
    if isinstance(kernel, dict) and kernel.get("family") == "rbf": kernel.setdefault("matern_nu", None)
    if isinstance(p.get("ad"), dict) and p["ad"].get("rule") == "nearest_neighbor": p["ad"].setdefault("k", 1)
    return p


def load_and_validate_protocol(path: str | Path | dict[str, Any]) -> dict[str, Any]:
    def no_duplicate_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result
    p = json.loads(Path(path).read_text(), object_pairs_hook=no_duplicate_pairs, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(f"nonfinite protocol JSON number {value}"))) if not isinstance(path, dict) else path
    declaration = getattr(p, "declaration", p)
    p = _fixed_protocol_defaults(declaration)
    source_assertions = _fixed_source_assertions(p)
    p = _execution_only(p)
    _keys(p, {"schema", "input_profile", "features", "model", "preprocessing", "cv", "permutation", "logo", "multicondition", "ad"}, set(), "protocol")
    if p["schema"] != SCHEMA:
        raise NotImplementedError(f"unsupported protocol schema: {p.get('schema')!r}")
    if p["input_profile"] != INPUT_PROFILE:
        raise NotImplementedError(f"unsupported input_profile: {p['input_profile']!r}")
    f = _keys(p["features"], {"indices"}, {"basis"}, "features")
    if "basis" in f:
        if not isinstance(f["basis"], str):
            raise ValueError("features.basis must be a string")
        if f["basis"] != FEATURE_BASIS:
            raise NotImplementedError(f"unsupported features.basis: {f['basis']!r}")
    indices = f["indices"]
    if not isinstance(indices, list) or not 1 <= len(indices) <= 34:
        raise ValueError("features.indices must select 1..34 columns")
    for i in indices:
        _int(i, "feature index", 0, 33)
    if len(set(indices)) != len(indices):
        raise ValueError("features.indices must not contain duplicates")
    m = _keys(p["model"], {"type", "kernel", "alpha", "optimizer", "n_restarts_optimizer", "seed", "normalize_y"}, set(), "model")
    if m["type"] != "gpr" or m["normalize_y"] is not False:
        raise NotImplementedError("supported model is GPR with normalize_y=false")
    _finite(m["alpha"], "model.alpha", 0.0)
    if m["optimizer"] not in ("fmin_l_bfgs_b", None):
        raise NotImplementedError("unsupported optimizer")
    _int(m["n_restarts_optimizer"], "model.n_restarts_optimizer", 0, 5)
    _int(m["seed"], "model.seed", 0, 2**32 - 1)
    k = _keys(m["kernel"], {"family", "constant_value", "constant_bounds", "length_scale", "length_scale_bounds", "noise_level", "noise_level_bounds", "matern_nu"}, set(), "model.kernel")
    if k["family"] not in ("matern", "rbf"):
        raise NotImplementedError("kernel family must be matern or rbf")
    if k["family"] == "matern":
        nu = _finite(k["matern_nu"], "kernel.matern_nu")
        if nu not in (0.5, 1.5, 2.5):
            raise NotImplementedError("Matern nu must be 0.5, 1.5, or 2.5")
    if k["family"] == "rbf" and k["matern_nu"] is not None:
        raise ValueError("rbf protocol must set matern_nu to null")
    for name in ("constant_value", "length_scale", "noise_level"):
        if _finite(k[name], f"kernel.{name}", 0.0) <= 0:
            raise ValueError(f"kernel.{name} must be greater than zero")
    for name in ("constant_bounds", "length_scale_bounds", "noise_level_bounds"):
        b = k[name]
        if b != "fixed":
            if not isinstance(b, list) or len(b) != 2:
                raise ValueError(f"kernel.{name} must be 'fixed' or two positive bounds")
            lo, hi = (_finite(v, f"kernel.{name}", 0.0) for v in b)
            if lo <= 0 or hi <= lo:
                raise ValueError(f"kernel.{name} bounds must be positive and strictly ascending; use 'fixed' for fixed parameters")
    pp = _keys(p["preprocessing"], {"feature_scaling", "target_scaling"}, set(), "preprocessing")
    if pp["feature_scaling"] not in ("none", "standard") or pp["target_scaling"] not in ("none", "standard"):
        raise NotImplementedError("scaling must be none or standard")
    cv = _keys(p["cv"], {"kind", "n_splits", "shuffle", "seed", "repeats"}, {"row_order"}, "cv")
    if "row_order" in cv:
        if not isinstance(cv["row_order"], str):
            raise ValueError("cv.row_order must be a string")
        if cv["row_order"] not in ("frozen_vector", "global_index_ascending"):
            raise NotImplementedError(f"unsupported cv.row_order: {cv['row_order']!r}")
    if cv["kind"] != "kfold" or cv["shuffle"] is not True or _int(cv["repeats"], "cv.repeats", 1, 1) != 1:
        raise NotImplementedError("supported CV is shuffled KFold with one repeat")
    _int(cv["n_splits"], "cv.n_splits", 2, 20)
    _int(cv["seed"], "cv.seed", 0, 2**32 - 1)
    pm = _keys(p["permutation"], {"count", "seed", "rng"}, set(), "permutation")
    _int(pm["count"], "permutation.count", 10, 100)
    _int(pm["seed"], "permutation.seed", 0, 2**32 - 1)
    if pm["rng"] != "RandomState":
        raise NotImplementedError("permutation rng must be RandomState")
    logo = _keys(p["logo"], {"group_roles", "pool"}, set(), "logo")
    if (not isinstance(logo["group_roles"], list) or len(logo["group_roles"]) != 2
            or set(logo["group_roles"]) != {"substrate", "nucleophile"} or logo["pool"] != "frozen_train"):
        raise NotImplementedError("LOGO roles/pool are fixed to released public group vectors and training rows")
    mc = _keys(p["multicondition"], {"routes", "group_vector"}, set(), "multicondition")
    if (not isinstance(mc["routes"], list) or len(mc["routes"]) != 2
            or set(mc["routes"]) != {"all_train", "single_reaction_only"}
            or mc["group_vector"] != "reaction"):
        raise NotImplementedError("unsupported multi-condition routes")
    ad = _keys(p["ad"], {"rule", "k", "scaling", "quantile", "distance", "quantile_method"}, set(), "ad")
    if ad["rule"] not in ("nearest_neighbor", "knn_mean_distance"):
        raise NotImplementedError("unsupported AD rule")
    _int(ad["k"], "ad.k", 1 if ad["rule"] == "nearest_neighbor" else 2, 1 if ad["rule"] == "nearest_neighbor" else 10)
    if ad["scaling"] not in ("none", "standard") or ad["distance"] != "rms_euclidean" or ad["quantile_method"] != "linear":
        raise NotImplementedError("unsupported AD scaling/distance/quantile method")
    _finite(ad["quantile"], "ad.quantile", 0.80, 0.99)
    # Ensure R2 is defined on every CV split and all AD neighborhoods exist.
    if p["cv"]["n_splits"] < 2:
        raise ValueError("CV requires at least two folds")
    return DeclaredProtocol(p, declaration, source_assertions)


def canonical_protocol_digest(protocol: dict[str, Any]) -> str:
    canonical = json.dumps(getattr(protocol, "declaration", protocol), sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(canonical).hexdigest()


def load_public_inputs() -> dict[str, Any]:
    for filename, expected in PUBLIC_ASSET_SHA256.items():
        actual = hashlib.sha256((ASSETS / filename).read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError(f"public input asset digest mismatch: {filename}")
    master = pd.read_csv(ASSETS / "master_s115_blindarm.csv")
    xbase_frame = pd.read_csv(ASSETS / "SC-012-D0SC04896H-s120.csv", index_col=0)
    if xbase_frame.shape[1] != 33 or xbase_frame.columns.has_duplicates or not all(isinstance(v, str) and v for v in xbase_frame.columns):
        raise ValueError("s120 must contain exactly 33 uniquely named descriptor columns after dropping its row-index column")
    xbase_index = pd.to_numeric(pd.Index(xbase_frame.index), errors="raise").to_numpy(float)
    if len(xbase_index) != len(master) or not np.array_equal(xbase_index, np.arange(len(master), dtype=float)):
        raise ValueError(f"s120 row-index column mismatch: n={len(xbase_index)}, expected n={len(master)} and indices 0..{len(master)-1} in order")
    xbase = xbase_frame.to_numpy(float)
    extra = pd.to_numeric(master["activation_energy_qh_grimme_ts"], errors="raise").to_numpy(float)
    X = np.column_stack((xbase, extra))
    feature_names = [str(v) for v in xbase_frame.columns] + ["activation_energy_qh_grimme_ts"]
    feature_sources = [f"SC-012-D0SC04896H-s120.csv:{name}" for name in feature_names[:33]]
    feature_sources.append("master_s115_blindarm.csv:activation_energy_qh_grimme_ts")
    y = pd.to_numeric(master["exp_activation_energy"], errors="raise").to_numpy(float)
    train_raw = np.load(ASSETS / "SC-012-D0SC04896H-s119.npy", allow_pickle=False)
    test_raw = np.load(ASSETS / "SC-012-D0SC04896H-s118.npy", allow_pickle=False)
    if train_raw.dtype.kind not in "iu" or test_raw.dtype.kind not in "iu" or train_raw.ndim != 1 or test_raw.ndim != 1:
        raise ValueError("frozen split arrays must be one-dimensional integer arrays")
    train, test = train_raw.astype(int), test_raw.astype(int)
    if X.shape != (443, 34) or not np.isfinite(X).all() or len(train) != 354 or len(test) != 89:
        raise ValueError("public frozen input profile has unexpected shape")
    if np.intersect1d(train, test).size or set(np.r_[train, test].tolist()) != set(range(443)):
        raise ValueError("frozen train/test vectors are not an exact partition")
    if not np.isnan(y[test]).all() or not np.isfinite(y[train]).all():
        raise ValueError("public master is not correctly blinded")
    groups = {}
    for role, filename in (("reaction", "SC-012-D0SC04896H-s113.npy"), ("nucleophile", "SC-012-D0SC04896H-s114.npy"), ("substrate", "SC-012-D0SC04896H-s117.npy")):
        raw = np.load(ASSETS / filename, allow_pickle=False)
        if raw.dtype.kind not in "iu" or raw.ndim != 1 or len(raw) != len(master):
            raise ValueError(f"group vector {filename} must be one-dimensional integer labels aligned to master")
        groups[role] = raw.astype(int)
    return {"master": master, "X": X, "y": y, "train": train, "test": test, "groups": groups,
            "feature_names": feature_names, "feature_sources": feature_sources}


def select_features(X: np.ndarray, protocol: dict[str, Any]) -> np.ndarray:
    basis = protocol["features"].get("basis")
    if basis is None:
        raise NotImplementedError("features.basis is required to identify the declared feature matrix")
    if basis != FEATURE_BASIS:
        raise NotImplementedError(f"unsupported features.basis: {basis!r}")
    return np.asarray(X[:, protocol["features"]["indices"]], dtype=float)


def summarize_permutation(identity: dict[str, float], null_scores: list[dict[str, float]],
                          reference: str | None) -> dict[str, Any]:
    """Summarize identity and independently fitted null scores without mixing them."""
    if not null_scores:
        raise ValueError("at least one null permutation is required")
    true_r2, true_mae = float(identity["r2"]), float(identity["mae"])
    null_r2 = np.asarray([float(v["r2"]) for v in null_scores], dtype=float)
    null_mae = np.asarray([float(v["mae"]) for v in null_scores], dtype=float)
    if not np.isfinite([true_r2, true_mae]).all() or not np.isfinite(null_r2).all() or not np.isfinite(null_mae).all():
        raise ValueError("permutation summaries must be finite")
    mean_sep = float(true_r2 - null_r2.mean())
    max_sep = float(true_r2 - null_r2.max())
    if reference not in (None, "mean_null", "maximum_null"):
        raise NotImplementedError(f"unsupported r2_separation_reference: {reference!r}")
    sep = mean_sep if reference == "mean_null" else max_sep
    p_plus_one = float((1 + np.count_nonzero(null_r2 >= true_r2)) / (len(null_r2) + 1))
    return {"true_r2": true_r2, "true_mae": true_mae, "r2_permutations": null_r2.tolist(),
            "mae_permutations": null_mae.tolist(), "permutation_results": [
                {"r2": float(r["r2"]), "mae": float(r["mae"])} for r in null_scores],
            "r2_separation": sep, "r2_separation_mean_null": mean_sep,
            "r2_separation_maximum_null": max_sep, "r2_pvalue_plus_one": p_plus_one,
            "r2_separation_reference": reference}


def summarize_group_mae(group_mae: list[float] | np.ndarray,
                         group_sizes: list[int] | np.ndarray) -> dict[str, float]:
    maes, sizes = np.asarray(group_mae, float), np.asarray(group_sizes, float)
    if maes.ndim != 1 or sizes.shape != maes.shape or len(maes) == 0 or (sizes <= 0).any() or not np.isfinite(maes).all():
        raise ValueError("group MAEs and positive group sizes must be aligned finite vectors")
    sem = float(maes.std(ddof=1) / math.sqrt(len(maes))) if len(maes) > 1 else 0.0
    return {"macro_group_mae": float(maes.mean()), "macro_group_sem": sem,
            "micro_row_mae": float(np.average(maes, weights=sizes))}


def summarize_fold_mae(fold_mae: list[float] | np.ndarray,
                       row_errors: list[float] | np.ndarray) -> dict[str, float]:
    folds, errors = np.asarray(fold_mae, float), np.asarray(row_errors, float)
    if folds.ndim != 1 or errors.ndim != 1 or len(folds) == 0 or len(errors) == 0 or not np.isfinite(folds).all() or not np.isfinite(errors).all():
        raise ValueError("fold MAEs and row errors must be nonempty finite vectors")
    sd = float(folds.std(ddof=1)) if len(folds) > 1 else 0.0
    return {"fold_mae_mean": float(folds.mean()), "fold_mae_sd": sd,
            "fold_mae_sem": float(sd / math.sqrt(len(folds))), "row_micro_mae": float(errors.mean())}


def summarize_replicate_pairs(pair_values: list[str] | tuple[str, ...]) -> dict[str, Any]:
    differences = []
    for value in pair_values:
        nums = [float(v) for v in re.findall(r"[-+]?(?:\d*\.\d+|\d+\.?\d*)", str(value))]
        if len(nums) >= 2:
            differences.append(round(abs(nums[1] - nums[0]), 2))
    if len(differences) != 4 or not np.isfinite(differences).all():
        raise ValueError(f"replicate source contains {len(differences)} valid pairs; expected 4 finite pairs")
    halfwidths = [12.7062047361747 * d / 2.0 for d in differences]
    return {"pair_differences_kcal_mol": differences,
            "student_t_95_halfwidths_kcal_mol": halfwidths,
            "uniform_bound_kcal_mol": float(max(halfwidths))}


def summarize_calibration(row_index: list[int] | np.ndarray,
                          prediction: list[float] | np.ndarray,
                          sigma: list[float] | np.ndarray,
                          truth: list[float] | np.ndarray) -> dict[str, Any]:
    rows, pred, sd, y = (np.asarray(v) for v in (row_index, prediction, sigma, truth))
    if not (rows.ndim == pred.ndim == sd.ndim == y.ndim == 1) or not (len(rows) == len(pred) == len(sd) == len(y)):
        raise ValueError("calibration rows, predictions, sigmas and truths must be aligned vectors")
    if len(rows) == 0 or not np.isfinite(pred.astype(float)).all() or not np.isfinite(sd.astype(float)).all() or not np.isfinite(y.astype(float)).all() or (sd.astype(float) <= 0).any():
        raise ValueError("calibration values must be finite with positive sigma")
    err, sig = np.abs(pred.astype(float) - y.astype(float)), sd.astype(float)
    coverage = {f"{z:g}sigma": float(np.mean(err <= z * sig)) for z in (1, 1.96, 2, 2.576)}
    order = np.lexsort((rows.astype(int), sig))
    risk = {}
    for fraction in (.5, .75, .9):
        exact = fraction * len(err)
        lower, upper = math.floor(exact), math.ceil(exact)
        counts = {max(1, int(lower)), max(1, int(round(exact)))}
        if exact - lower == 0.5:
            counts.add(max(1, int(upper)))
        risk[f"lowest_sigma_{int(fraction * 100)}pct"] = [
            {"n": n, "mae": float(err[order[:n]].mean()), "overall_mae": float(err.mean())} for n in sorted(counts)]
    return {"errors": err, "coverage": coverage, "overall_oof_mae": float(err.mean()), "risk_filter": risk}


def _bounds(value: Any):
    return "fixed" if value == "fixed" else tuple(float(v) for v in value)


def build_model(protocol: dict[str, Any]):
    m, k = protocol["model"], protocol["model"]["kernel"]
    base = Matern(length_scale=k["length_scale"], length_scale_bounds=_bounds(k["length_scale_bounds"]), nu=k["matern_nu"]) if k["family"] == "matern" else RBF(length_scale=k["length_scale"], length_scale_bounds=_bounds(k["length_scale_bounds"]))
    kernel = ConstantKernel(k["constant_value"], _bounds(k["constant_bounds"])) * base + WhiteKernel(k["noise_level"], _bounds(k["noise_level_bounds"]))
    gp = GaussianProcessRegressor(kernel=kernel, alpha=float(m["alpha"]), optimizer=m["optimizer"],
                                  n_restarts_optimizer=int(m["n_restarts_optimizer"]), random_state=int(m["seed"]), normalize_y=False)
    if protocol["preprocessing"]["feature_scaling"] == "standard":
        from sklearn.pipeline import make_pipeline
        gp = make_pipeline(StandardScaler(), gp)
    return gp


def fit_predict_with_sigma(protocol: dict[str, Any], X_train: np.ndarray, y_train: np.ndarray, X_test: np.ndarray):
    xtr, xte = np.asarray(X_train, float), np.asarray(X_test, float)
    yt = np.asarray(y_train, float).reshape(-1)
    if len(yt) != len(xtr) or not np.isfinite(xtr).all() or not np.isfinite(xte).all() or not np.isfinite(yt).all():
        raise ValueError("fit inputs must be aligned and finite")
    target_scale = 1.0
    target_mean = 0.0
    if protocol["preprocessing"]["target_scaling"] == "standard":
        scaler = StandardScaler().fit(yt.reshape(-1, 1))
        target_mean, target_scale = float(scaler.mean_[0]), float(scaler.scale_[0])
        fit_y = scaler.transform(yt.reshape(-1, 1)).ravel()
    else:
        fit_y = yt
    model = build_model(protocol).fit(xtr, fit_y)
    if hasattr(model, "named_steps"):
        transformed = model.named_steps["standardscaler"].transform(xte)
        gp = model.named_steps["gaussianprocessregressor"]
    else:
        transformed, gp = xte, model
    mean, sigma = gp.predict(transformed, return_std=True)
    return target_mean + np.asarray(mean) * target_scale, np.asarray(sigma) * target_scale


def make_cv_splits(protocol: dict[str, Any], n_rows: int):
    cv = protocol["cv"]
    return list(KFold(n_splits=cv["n_splits"], shuffle=True, random_state=cv["seed"]).split(np.arange(n_rows)))


def training_rows_for_protocol(protocol: dict[str, Any], frozen_train: np.ndarray):
    rows = np.asarray(frozen_train, dtype=int)
    order = protocol["cv"].get("row_order", "frozen_vector")
    return np.sort(rows) if order == "global_index_ascending" else rows.copy()


def resolve_training_order(protocol: dict[str, Any], frozen_train: np.ndarray,
                           calibration_fold_receipts: list[dict[str, Any]]):
    """Resolve one global training view from declaration or calibration split receipts.

    Legacy protocols are inferred only from exact KFold membership receipts. No model
    predictions, metrics, other routes, or hidden targets participate in the choice.
    """
    raw = np.asarray(frozen_train, dtype=int)
    candidates = {
        "frozen_vector": raw,
        "global_index_ascending": np.sort(raw),
    }
    declared = protocol["cv"].get("row_order")

    def matches(rows):
        if len(calibration_fold_receipts) != protocol["cv"]["n_splits"]:
            return False
        by_fold = {}
        for receipt in calibration_fold_receipts:
            fid = receipt.get("fold")
            if isinstance(fid, bool) or not isinstance(fid, int) or fid in by_fold:
                return False
            by_fold[fid] = receipt
        if set(by_fold) != set(range(protocol["cv"]["n_splits"])):
            return False
        for fid, (tr, te) in enumerate(make_cv_splits(protocol, len(rows))):
            record = by_fold[fid]
            got_tr, got_te = record.get("train_global_indices"), record.get("test_global_indices")
            if not isinstance(got_tr, list) or not isinstance(got_te, list):
                return False
            for values in (got_tr, got_te):
                if any(isinstance(v, bool) or not isinstance(v, int) for v in values):
                    return False
                if len(values) != len(set(values)):
                    return False
            if set(got_tr) != set(rows[tr].tolist()) or set(got_te) != set(rows[te].tolist()):
                return False
        return True

    if declared is not None:
        chosen = candidates[declared]
        if calibration_fold_receipts and not matches(chosen):
            raise ValueError("calibration fold receipts conflict with declared cv.row_order")
        return chosen.copy(), declared, {"resolution": "declared", "matching_orders": [declared]}

    matches_found = [name for name, rows in candidates.items() if matches(rows)]
    # Identical vectors (possible for synthetic inputs) describe one effective view.
    if np.array_equal(candidates["frozen_vector"], candidates["global_index_ascending"]):
        if not matches_found:
            raise ValueError("calibration fold receipts match neither supported training order")
        return raw.copy(), "frozen_vector", {"resolution": "inferred_equivalent", "matching_orders": matches_found}
    if len(matches_found) == 2:
        raise NotImplementedError("calibration fold receipts do not uniquely identify a supported training order")
    if len(matches_found) == 0:
        raise ValueError("calibration fold receipts match neither supported training order")
    name = matches_found[0]
    return candidates[name].copy(), name, {"resolution": "inferred_from_calibration_receipts", "matching_orders": matches_found}


def make_logo_splits(rows: np.ndarray, groups: np.ndarray):
    rows = np.asarray(rows, int)
    local_groups = np.asarray(groups, int)[rows]
    return [(rows[tr], rows[te], int(local_groups[te[0]])) for tr, te in LeaveOneGroupOut().split(rows, groups=local_groups)]


def permutation_targets(protocol: dict[str, Any], y: np.ndarray):
    rng = np.random.RandomState(protocol["permutation"]["seed"])
    return [np.asarray(y, float).copy()] + [rng.permutation(y) for _ in range(protocol["permutation"]["count"])]


def compute_ad(protocol: dict[str, Any], X_train: np.ndarray, X_test: np.ndarray):
    cfg = protocol["ad"]
    tr, te = np.asarray(X_train, float), np.asarray(X_test, float)
    scaler = StandardScaler().fit(tr) if cfg["scaling"] == "standard" else None
    if scaler is not None:
        tr, te = scaler.transform(tr), scaler.transform(te)
    if len(tr) <= cfg["k"]:
        raise ValueError("training pool is too small for declared AD neighborhood")
    def distances(a, b):
        return np.sqrt(np.mean((a[:, None, :] - b[None, :, :]) ** 2, axis=2))
    train_d = distances(tr, tr)
    np.fill_diagonal(train_d, np.inf)
    test_d = distances(te, tr)
    k = cfg["k"]
    if cfg["rule"] == "nearest_neighbor":
        train_score = train_d.min(axis=1)
        test_score = test_d.min(axis=1)
    else:
        train_score = np.partition(train_d, k - 1, axis=1)[:, :k].mean(axis=1)
        test_score = np.partition(test_d, k - 1, axis=1)[:, :k].mean(axis=1)
    threshold = float(np.quantile(train_score, cfg["quantile"], method="linear"))
    return test_score, threshold, test_score > threshold
