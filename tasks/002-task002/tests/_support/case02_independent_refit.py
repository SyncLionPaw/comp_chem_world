"""Trusted numerical refits for Case 02 declarations; never executes candidate code."""
from __future__ import annotations

import itertools
import math
import re
from copy import deepcopy
import numpy as np
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import ConstantKernel, Matern, WhiteKernel
from sklearn.kernel_ridge import KernelRidge
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

class ReviewRequired(ValueError):
    """A possibly valid method is outside the installed independent-refit vocabulary."""


class CandidateProtocolError(ValueError):
    """A malformed or internally inconsistent candidate scientific declaration."""


def _normalize_fit_scope(value):
    """Accept equivalent public spellings for fold-local preprocessing."""
    aliases = {"each_training_fold", "training_fold_only", "training_folds_only"}
    if not isinstance(value, str) or value not in aliases:
        raise CandidateProtocolError("preprocessing must be fit using each training fold only")


_FAMILY_ALIASES = {"GPR": "GaussianProcessRegressor"}


def normalize_cv(raw, paired=False, expected_n_splits=None):
    """Return the canonical CV declaration shared by validation and replay."""
    if not isinstance(raw, dict):
        raise CandidateProtocolError("CV declaration must be an object")
    result = deepcopy(raw)
    allowed = ({"n_splits", "shuffle", "random_state_policy", "scoring", "selection_metric", "description", "note"}
               if paired else {"n_splits", "shuffle", "random_state", "scoring", "selection_metric", "folds", "description", "note"})
    unknown = set(raw) - allowed
    if unknown:
        raise ReviewRequired(f"uninterpreted CV options: {sorted(unknown)}")
    scoring_aliases = {"MAE", "mean_absolute_error", "neg_mean_absolute_error"}
    selection_aliases = {"MAE", "mean_fold_mae"}
    scoring = raw.get("scoring")
    if not isinstance(scoring, str):
        raise CandidateProtocolError("CV scoring must be a string")
    if scoring not in scoring_aliases:
        raise ReviewRequired(f"unsupported CV scoring: {scoring!r}")
    result["scoring"] = "MAE"
    n_splits = raw.get("n_splits")
    if type(n_splits) is not int or not 2 <= n_splits <= 10:
        raise CandidateProtocolError("CV n_splits must be an integer from 2 to 10")
    if paired:
        if raw.get("shuffle") is not True or raw.get("random_state_policy") != "seed":
            raise CandidateProtocolError("paired CV must use shuffled folds with seed-specific random state")
    elif raw.get("shuffle") is not True or type(raw.get("random_state")) is not int:
        raise CandidateProtocolError("CV must declare shuffled folds and an integer random_state")
    if "selection_metric" in raw:
        if not isinstance(raw["selection_metric"], str) or raw["selection_metric"] not in selection_aliases:
            raise CandidateProtocolError("selection_metric contradicts MAE minimization")
        result["selection_metric"] = "MAE"
    if paired:
        extra = set(raw) - {"n_splits", "shuffle", "random_state_policy", "scoring",
                            "selection_metric", "description", "note"}
        if extra:
            raise ReviewRequired(f"uninterpreted paired CV options: {sorted(extra)}")
    if expected_n_splits is not None and raw.get("n_splits") != expected_n_splits:
        raise CandidateProtocolError("CV split count conflicts with explicit folds")
    return result


def normalize_arm(raw, paired=False):
    """Deep-copy an arm into the one protocol view consumed by all stages."""
    if not isinstance(raw, dict):
        raise CandidateProtocolError("model_spec arm must be an object")
    result = deepcopy(raw)
    allowed_arm = {"matrix_file", "feature_columns", "estimator", "preprocessing", "target_transform",
                   "seed", "cv", "cv_folds", "cv_folds_source", "budget", "seed_policy", "tie_break", "description", "note"}
    extra_arm = set(result) - allowed_arm
    if extra_arm:
        raise ReviewRequired(f"unsupported model arm options: {sorted(extra_arm)}")
    if "tie_break" in result:
        supported_ties = {
            "first minimum in row-major declared grid order (alpha outer, gamma inner)",
            "first minimum in declared parameter-grid order",
            "first minimum in row-major declared grid order",
        }
        if not isinstance(result["tie_break"], str) or result["tie_break"] not in supported_ties:
            raise ReviewRequired(f"unsupported tie_break declaration: {result['tie_break']!r}")
    if "cv_folds_source" in result:
        if not paired:
            raise ReviewRequired("cv_folds_source is only defined for paired seed-specific folds")
        if result["cv_folds_source"] != "cv_splits_seed<seed>.json":
            raise ReviewRequired(f"unsupported paired cv_folds_source: {result['cv_folds_source']!r}")
    estimator = result.get("estimator")
    if not isinstance(estimator, dict):
        raise CandidateProtocolError("model_spec estimator must be an object")
    family = estimator.get("family")
    if family is None:
        raise CandidateProtocolError("model_spec estimator.family is required")
    if not isinstance(family, str):
        raise CandidateProtocolError("model_spec estimator.family must be a string")
    if family not in {"Ridge", "KernelRidge", "GaussianProcessRegressor", "GPR"}:
        raise ReviewRequired(f"unsupported estimator family: {family!r}")
    estimator["family"] = _FAMILY_ALIASES.get(family, family)
    estimator_allowed = {
        "Ridge": {"family", "parameter_grid"},
        "KernelRidge": {"family", "parameter_grid", "kernel"},
        "GaussianProcessRegressor": {"family", "parameter_grid", "kernel", "normalize_y", "optimizer", "n_restarts_optimizer"},
    }[estimator["family"]]
    extra_estimator = set(estimator) - estimator_allowed
    if extra_estimator:
        raise ReviewRequired(f"unsupported {estimator['family']} options: {sorted(extra_estimator)}")
    preprocessing = result.get("preprocessing")
    if not isinstance(preprocessing, dict):
        raise CandidateProtocolError("preprocessing must be an object")
    if isinstance(preprocessing, dict) and "fit_scope" in preprocessing:
        scopes = {"each_training_fold", "training_fold_only", "training_folds_only"}
        if not isinstance(preprocessing["fit_scope"], str) or preprocessing["fit_scope"] not in scopes:
            raise CandidateProtocolError("preprocessing must be fit using each training fold only")
        preprocessing["fit_scope"] = "training_folds_only"
    if isinstance(preprocessing, dict):
        extra_preprocessing = set(preprocessing) - {"scaler", "fit_scope"}
        if extra_preprocessing:
            raise ReviewRequired(f"unsupported preprocessing options: {sorted(extra_preprocessing)}")
    transform = result.get("target_transform")
    if not isinstance(transform, str):
        raise CandidateProtocolError("target_transform must be a string")
    if transform not in {"none", "normalize_y"}:
        raise ReviewRequired(f"unsupported target transform: {transform!r}")
    cv_forms = []
    if "cv_folds" in result:
        cv_forms.append(result["cv_folds"])
    cv = result.get("cv")
    if isinstance(cv, dict) and "folds" in cv:
        cv_forms.append(cv["folds"])
    if cv_forms:
        canonical = []
        for form in cv_forms:
            if not isinstance(form, list):
                raise CandidateProtocolError("explicit CV folds must be a list")
            folds = []
            for fold in form:
                if not isinstance(fold, dict):
                    raise CandidateProtocolError("each CV fold must be an object")
                train = fold.get("train_local", fold.get("train_positions"))
                valid = fold.get("validation_local", fold.get("validation_positions"))
                if "train_local" in fold and "train_positions" in fold and fold["train_local"] != fold["train_positions"]:
                    raise CandidateProtocolError("conflicting train-local fold declarations")
                if "validation_local" in fold and "validation_positions" in fold and fold["validation_local"] != fold["validation_positions"]:
                    raise CandidateProtocolError("conflicting validation fold declarations")
                extras = set(fold) - {"train_local", "train_positions", "validation_local", "validation_positions", "description", "note"}
                if extras:
                    raise ReviewRequired(f"uninterpreted CV fold options: {sorted(extras)}")
                folds.append({"train_local": train, "validation_local": valid})
            canonical.append(folds)
        if any(form != canonical[0] for form in canonical[1:]):
            raise CandidateProtocolError("conflicting explicit CV fold declarations")
        result["cv_folds"] = canonical[0]
    if isinstance(cv, dict):
        result["cv"] = normalize_cv(cv, paired=paired, expected_n_splits=len(result["cv_folds"]) if "cv_folds" in result else None)
    return result


def _family(spec):
    estimator_spec = spec.get("estimator")
    if not isinstance(estimator_spec, dict) or not isinstance(estimator_spec.get("family"), str):
        raise CandidateProtocolError("model_spec estimator.family is required")
    return _FAMILY_ALIASES.get(estimator_spec["family"], estimator_spec["family"])


def _split_arguments(text):
    """Split a call's argument text on top-level commas only."""
    parts, depth, current = [], 0, []
    for char in text:
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
        if char == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
    parts.append("".join(current))
    return [part.strip() for part in parts if part.strip()]


def _positional_and_keywords(text):
    positional = []
    keywords = {}
    for part in _split_arguments(text):
        if "=" in part:
            key, value = part.split("=", 1)
            key = key.strip()
            if key in keywords:
                raise CandidateProtocolError(f"duplicate GPR kernel keyword: {key}")
            keywords[key] = value.strip().strip('"').strip("'")
        else:
            positional.append(part)
    return positional, keywords


def _bounds_keyword(keywords, key):
    """Parse a declared bound: absent, "fixed", or a numeric (lower, upper) pair."""
    raw = keywords.get(key)
    if raw is None:
        return None
    text = str(raw).strip()
    if text == "fixed":
        return "fixed"
    match = re.fullmatch(r"[\(\[]\s*([^,]+?)\s*,\s*([^\)\]]+?)\s*[\)\]]", text)
    if not match:
        raise ReviewRequired(f"unsupported {key} declaration")
    try:
        lower, upper = float(match.group(1)), float(match.group(2))
    except ValueError as exc:
        raise CandidateProtocolError(f"invalid {key} in GPR kernel") from exc
    if not (math.isfinite(lower) and math.isfinite(upper)) or lower <= 0 or upper <= 0 or lower > upper:
        raise CandidateProtocolError(f"{key} must be finite positive bounds with lower <= upper")
    return (lower, upper)


_NU_PLACEHOLDER_RE = re.compile(r"^<?[A-Za-z_][A-Za-z0-9_]*>?$")


_KERNEL_RE = re.compile(
    r"^\s*ConstantKernel\((.*?)\)\s*\*\s*Matern\((.*?)\)\s*\+\s*WhiteKernel\((.*?)\)\s*$"
)


def _number_keyword(keywords, key, default):
    raw = keywords.get(key)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise CandidateProtocolError(f"invalid {key} in GPR kernel") from exc
    if not math.isfinite(value) or value <= 0:
        raise CandidateProtocolError(f"{key} must be finite and positive")
    return value


def _object_kernel_component(entry, name, default, declared_bounds=None):
    if isinstance(entry, (int, float)) and not isinstance(entry, bool):
        initial, bounds = float(entry), None
    elif isinstance(entry, dict):
        value_key, bounds_key = {
            "constant_value": ("constant_value", "constant_value_bounds"),
            "length_scale": ("length_scale", "length_scale_bounds"),
            "white_noise_level": ("white_noise_level", "white_noise_level_bounds"),
        }[name]
        allowed = {"initial", "bounds", value_key, bounds_key}
        unknown = set(entry) - allowed
        if unknown:
            raise ReviewRequired(f"unsupported GPR kernel {name} options: {sorted(unknown)}")
        value_keys = [key for key in ("initial", value_key) if key in entry]
        if len(value_keys) > 1 and entry[value_keys[0]] != entry[value_keys[1]]:
            raise CandidateProtocolError(f"conflicting GPR kernel {name} initial values")
        initial = entry.get("initial", entry.get(value_key, default))
        bound_keys = [key for key in ("bounds", bounds_key) if key in entry]
        if len(bound_keys) > 1 and entry[bound_keys[0]] != entry[bound_keys[1]]:
            raise CandidateProtocolError(f"conflicting GPR kernel {name} bounds")
        bounds = entry.get("bounds", entry.get(bounds_key))
    else:
        raise CandidateProtocolError(f"GPR kernel {name} must be a number or an object")
    try:
        initial = float(initial)
    except (TypeError, ValueError) as exc:
        raise CandidateProtocolError(f"GPR kernel {name} initial value is invalid") from exc
    if not math.isfinite(initial) or initial <= 0:
        raise CandidateProtocolError(f"GPR kernel {name} initial value must be finite and positive")
    if declared_bounds is not None:
        if bounds is not None and bounds != declared_bounds:
            raise CandidateProtocolError(f"conflicting GPR kernel {name} bounds")
        bounds = declared_bounds
    if bounds is not None and bounds != "fixed":
        if (not isinstance(bounds, (list, tuple)) or len(bounds) != 2
                or not all(type(value) in (int, float) and math.isfinite(value) for value in bounds)
                or bounds[0] <= 0 or bounds[1] <= 0 or bounds[0] > bounds[1]):
            raise CandidateProtocolError(f"GPR kernel {name} bounds are invalid")
        bounds = tuple(float(value) for value in bounds)
    return initial, bounds


def _kernel(spec, params):
    """Build the declared constant*Matern+WhiteNoise kernel, honoring declared bounds."""
    estimator = spec["estimator"]
    kernel_spec = estimator.get("kernel")
    if isinstance(kernel_spec, dict):
        # Accept explicitly named sklearn component objects as well as flat values.
        kernel_spec = dict(kernel_spec)
        allowed_kernel_keys = {
            "constant_kernel", "matern", "white_kernel", "constant_value",
            "constant_value_bounds", "length_scale", "length_scale_bounds",
            "white_noise_level", "white_noise_level_bounds", "noise_level",
            "noise_level_bounds",
        }
        unknown = set(kernel_spec) - allowed_kernel_keys
        if unknown:
            raise ReviewRequired(f"unsupported GPR kernel options: {sorted(unknown)}")
        for first, second in (("white_noise_level", "noise_level"),
                              ("white_noise_level_bounds", "noise_level_bounds")):
            if first in kernel_spec and second in kernel_spec and kernel_spec[first] != kernel_spec[second]:
                raise CandidateProtocolError(f"conflicting GPR {first} and {second} declarations")
        for component, value_key, bounds_key in (
                ("constant_kernel", "constant_value", "constant_value_bounds"),
                ("matern", "length_scale", "length_scale_bounds"),
                ("white_kernel", "noise_level", "noise_level_bounds")):
            if component not in kernel_spec:
                continue
            entry = kernel_spec[component]
            if not isinstance(entry, dict):
                raise CandidateProtocolError(f"GPR {component} must be an object")
            allowed_component = {value_key, bounds_key, "initial", "bounds"}
            if component == "matern":
                allowed_component.add("nu")
            unknown_component = set(entry) - allowed_component
            if unknown_component:
                raise ReviewRequired(f"unsupported GPR {component} options: {sorted(unknown_component)}")
            for key in (value_key, bounds_key):
                if key in entry:
                    if key in kernel_spec and kernel_spec[key] != entry[key]:
                        raise CandidateProtocolError(f"conflicting GPR {key} declarations")
                    kernel_spec[key] = entry[key]
            for source_key, target_key in (("initial", value_key), ("bounds", bounds_key)):
                if source_key in entry:
                    if target_key in kernel_spec and kernel_spec[target_key] != entry[source_key]:
                        raise CandidateProtocolError(f"conflicting GPR {target_key} declarations")
                    kernel_spec[target_key] = entry[source_key]
        constant, constant_bounds = _object_kernel_component(
            kernel_spec.get("constant_value", 1.0), "constant_value", 1.0,
            kernel_spec.get("constant_value_bounds"))
        length_scale, length_bounds = _object_kernel_component(
            kernel_spec.get("length_scale", 1.0), "length_scale", 1.0,
            kernel_spec.get("length_scale_bounds"))
        noise_level, noise_bounds = _object_kernel_component(
            kernel_spec.get("white_noise_level", kernel_spec.get("noise_level", 1.0)),
            "white_noise_level", 1.0,
            kernel_spec.get("white_noise_level_bounds", kernel_spec.get("noise_level_bounds")))
        nu = params.get("matern_nu")
        fixed_nu = kernel_spec.get("matern", {}).get("nu") if isinstance(kernel_spec.get("matern"), dict) else None
        if fixed_nu is not None:
            if type(fixed_nu) not in (int, float) or not math.isfinite(fixed_nu) or fixed_nu <= 0:
                raise CandidateProtocolError("GPR matern.nu must be finite and positive")
            if nu is not None and float(fixed_nu) != float(nu):
                raise CandidateProtocolError("GPR fixed matern.nu conflicts with grid value")
            nu = float(fixed_nu)
        if nu is None:
            raise CandidateProtocolError("GPR Matern nu must be supplied by a matern_nu grid axis")
        constant_kwargs = {"constant_value_bounds": constant_bounds} if constant_bounds is not None else {}
        matern_kwargs = {"length_scale_bounds": length_bounds} if length_bounds is not None else {}
        white_kwargs = {"noise_level_bounds": noise_bounds} if noise_bounds is not None else {}
        return (ConstantKernel(constant, **constant_kwargs)
                * Matern(length_scale=length_scale, nu=nu, **matern_kwargs)
                + WhiteKernel(noise_level=noise_level, **white_kwargs))
    if not isinstance(kernel_spec, str):
        raise CandidateProtocolError("GPR kernel declaration must be a string or structured object")
    match = _KERNEL_RE.fullmatch(kernel_spec)
    if not match:
        raise ReviewRequired("unsupported declared GPR kernel")
    constant_pos, constant_kw = _positional_and_keywords(match.group(1))
    matern_pos, matern_kw = _positional_and_keywords(match.group(2))
    white_pos, white_kw = _positional_and_keywords(match.group(3))
    if (set(constant_kw) - {"constant_value", "constant_value_bounds"}
            or set(matern_kw) - {"nu", "length_scale", "length_scale_bounds"}
            or set(white_kw) - {"noise_level", "noise_level_bounds"}
            or len(constant_pos) > 1 or len(matern_pos) > 1 or len(white_pos) > 1
            or len(matern_pos) > 0 and "length_scale" in matern_kw
            or len(white_pos) > 0 and "noise_level" in white_kw
            or len(constant_pos) > 0 and "constant_value" in constant_kw):
        raise ReviewRequired("unsupported GPR kernel arguments")
    constant = float(constant_pos[0]) if constant_pos else _number_keyword(constant_kw, "constant_value", 1.0)
    length_scale = float(matern_pos[0]) if matern_pos else _number_keyword(matern_kw, "length_scale", 1.0)
    noise_level = float(white_pos[0]) if white_pos else _number_keyword(white_kw, "noise_level", 1.0)
    base_nu = None
    if matern_kw.get("nu") is not None:
        raw_nu = str(matern_kw["nu"]).strip()
        try:
            base_nu = float(raw_nu)
        except ValueError:
            if not _NU_PLACEHOLDER_RE.fullmatch(raw_nu):
                raise CandidateProtocolError("invalid nu in GPR kernel") from None
            base_nu = None  # placeholder such as <nu> or matern_nu, resolved from the grid axis
    if "length_scale" in matern_kw:
        length_scale = _number_keyword(matern_kw, "length_scale", 1.0)
    nu = params.get("matern_nu", base_nu)
    if base_nu is not None and nu is not None and float(base_nu) != float(nu):
        raise CandidateProtocolError("GPR fixed Matern nu conflicts with grid value")
    if nu is None:
        raise CandidateProtocolError("GPR Matern nu must be a concrete value or a matern_nu grid axis")
    constant_bounds = _bounds_keyword(constant_kw, "constant_value_bounds")
    length_bounds = _bounds_keyword(matern_kw, "length_scale_bounds")
    noise_bounds = _bounds_keyword(white_kw, "noise_level_bounds")
    constant_kwargs = {"constant_value_bounds": constant_bounds} if constant_bounds is not None else {}
    matern_kwargs = {"length_scale_bounds": length_bounds} if length_bounds is not None else {}
    white_kwargs = {"noise_level_bounds": noise_bounds} if noise_bounds is not None else {}
    return (ConstantKernel(constant, **constant_kwargs)
            * Matern(length_scale=length_scale, nu=nu, **matern_kwargs)
            + WhiteKernel(noise_level=noise_level, **white_kwargs))


def _grid(spec):
    estimator_spec = spec.get("estimator")
    family = _family(spec)
    params = estimator_spec.get("parameter_grid")
    if family not in {"Ridge", "KernelRidge", "GaussianProcessRegressor"}:
        raise ReviewRequired(f"unsupported estimator family: {family}")
    if not isinstance(params, (dict, list)) or not params:
        raise CandidateProtocolError("model_spec estimator.parameter_grid must be a nonempty object or explicit list")
    if family == "Ridge":
        allowed = {"alpha"}
    elif family == "KernelRidge":
        allowed = {"alpha", "kernel", "gamma", "degree", "coef0"}
    else:
        allowed = {"alpha", "matern_nu", "nu"}
        if type(estimator_spec.get("n_restarts_optimizer", 0)) is not int or estimator_spec.get("n_restarts_optimizer", 0) < 0:
            raise CandidateProtocolError("invalid GPR optimizer restart count")
        optimizer = estimator_spec.get("optimizer", "fmin_l_bfgs_b")
        if optimizer is not None and not isinstance(optimizer, str):
            raise CandidateProtocolError("GPR optimizer must be a string or null")
        if optimizer is not None and optimizer != "fmin_l_bfgs_b":
            raise ReviewRequired("unsupported GPR optimizer")
        if type(estimator_spec.get("normalize_y", True)) is not bool:
            raise CandidateProtocolError("GPR normalize_y must be a boolean")
        allowed_estimator = {"family", "parameter_grid", "kernel", "normalize_y", "optimizer", "n_restarts_optimizer"}
        unknown_estimator = set(estimator_spec) - allowed_estimator
        if unknown_estimator:
            raise ReviewRequired(f"unsupported GPR estimator options: {sorted(unknown_estimator)}")

    def canonical_key(key):
        return "matern_nu" if family == "GaussianProcessRegressor" and key == "nu" else key

    def validate(key, values):
        if key not in allowed:
            raise ReviewRequired("unsupported estimator parameter")
        if not isinstance(values, list) or not values:
            raise CandidateProtocolError(f"empty parameter grid: {key}")
        if any(type(v) not in (str, int, float, bool) for v in values):
            raise CandidateProtocolError(f"invalid parameter value type: {key}")
        if key == "alpha":
            lower_ok = (lambda value: value >= 0) if family in {"Ridge", "GaussianProcessRegressor"} else (lambda value: value > 0)
            if any(type(v) not in (int, float) or not math.isfinite(v) or not lower_ok(v) for v in values):
                raise CandidateProtocolError(f"invalid alpha values for {family}")
        if key == "gamma" and any(type(v) not in (int, float) or not math.isfinite(v) or v <= 0 for v in values):
            raise CandidateProtocolError("gamma values must be finite and positive")
        if key == "matern_nu" and any(type(v) not in (int, float) or not math.isfinite(v) or v <= 0 for v in values):
            raise CandidateProtocolError("GPR matern_nu values must be finite and positive")
        if key == "degree" and any(type(v) is not int or v < 1 for v in values):
            raise CandidateProtocolError("invalid integer parameter values")
        if key == "kernel":
            if any(not isinstance(v, str) for v in values):
                raise CandidateProtocolError("kernel grid values must be strings")
            if any(v not in {"linear", "rbf", "poly", "sigmoid", "cosine", "laplacian"} for v in values):
                raise ReviewRequired("unsupported KernelRidge kernel")
        if key in {"degree", "coef0"} and family != "KernelRidge":
            raise CandidateProtocolError(f"{key} is only valid for KernelRidge")
        if key == "coef0" and any(type(v) not in (int, float) or not math.isfinite(v) for v in values):
            raise CandidateProtocolError("coef0 values must be finite numbers")

    if isinstance(params, list):
        if any(not isinstance(item, dict) or not item for item in params):
            raise CandidateProtocolError("explicit parameter grid entries must be nonempty objects")
        normalized = []
        for item in params:
            entry = {}
            for raw_key, value in item.items():
                key = canonical_key(raw_key)
                if key in entry:
                    raise CandidateProtocolError(f"duplicate parameter in grid entry: {raw_key}")
                validate(key, [value])
                entry[key] = value
            normalized.append(entry)
        return normalized
    normalized_axes = {}
    for raw_key, values in params.items():
        key = canonical_key(raw_key)
        if key in normalized_axes:
            raise CandidateProtocolError(f"duplicate parameter in grid: {raw_key}")
        validate(key, values)
        normalized_axes[key] = values
    return [dict(zip(normalized_axes, values))
            for values in itertools.product(*(normalized_axes[k] for k in normalized_axes))]


def candidate_count(spec):
    return len(_grid(normalize_arm(spec)))


def canonical_estimator(spec, paired=False):
    """Canonical family and ordered candidate models for paired-arm comparison."""
    arm = normalize_arm(spec, paired=paired)
    family = _family(arm)
    grid = _grid(arm)
    estimator = arm["estimator"]
    candidates = []
    for params in grid:
        kernel = None
        if family == "GaussianProcessRegressor":
            built = _kernel(arm, params)
            kernel = {key: value for key, value in built.get_params(deep=True).items()
                      if isinstance(value, (str, int, float, bool, tuple, type(None)))}
        defaults = {}
        if family == "KernelRidge":
            defaults["kernel"] = params.get("kernel", estimator.get("kernel", "rbf"))
        candidates.append((params, kernel, defaults))
    settings = {
        "normalize_y": estimator.get("normalize_y", True),
        "optimizer": estimator.get("optimizer", "fmin_l_bfgs_b"),
        "n_restarts_optimizer": estimator.get("n_restarts_optimizer", 0),
    } if family == "GaussianProcessRegressor" else {}
    return family, candidates, settings


def _model(spec, params, seed):
    family = _family(spec)
    if family == "Ridge":
        estimator=Ridge(**params)
    elif family == "KernelRidge":
        estimator_params = dict(params)
        kernel = estimator_params.pop("kernel", None)
        if kernel is None:
            kernel = spec.get("estimator", {}).get("kernel", "rbf")
        if not isinstance(kernel, str) or kernel not in {"linear", "rbf", "poly", "sigmoid",
                                                         "cosine", "laplacian", "additive_chi2", "chi2"}:
            raise ReviewRequired(f"unsupported KernelRidge kernel: {kernel!r}")
        estimator=KernelRidge(kernel=kernel, **estimator_params)
    else:
        estimator=GaussianProcessRegressor(kernel=_kernel(spec, params),normalize_y=spec["estimator"].get("normalize_y",True),
          alpha=params.get("alpha",1e-10),optimizer=spec["estimator"].get("optimizer","fmin_l_bfgs_b"),
          n_restarts_optimizer=spec["estimator"].get("n_restarts_optimizer",0),random_state=seed)
    scaler=spec.get("preprocessing",{}).get("scaler","standard")
    if not isinstance(scaler, str):
        raise CandidateProtocolError("preprocessing scaler must be a string")
    if scaler not in {"standard","none"}:
        raise ReviewRequired(f"unsupported preprocessing scaler: {scaler}")
    steps=[]
    if scaler=="standard": steps.append(("scale",StandardScaler()))
    steps.append(("model",estimator))
    return Pipeline(steps)


def refit(spec, X_train, y_train, X_test, folds, seed):
    """Tune on explicit train-local folds and refit; returns predictions and audit details."""
    spec = normalize_arm(spec)
    folds = spec.get("cv_folds", folds)
    if not isinstance(spec,dict) or not isinstance(spec.get("estimator"),dict):
        raise CandidateProtocolError("malformed model_spec arm")
    if not isinstance(spec.get("preprocessing", {}), dict) or not isinstance(spec.get("budget", {}), dict):
        raise CandidateProtocolError("preprocessing and budget declarations must be objects")
    X=np.asarray(X_train,float); y=np.asarray(y_train,float); Xt=np.asarray(X_test,float)
    if X.ndim!=2 or Xt.ndim!=2 or X.shape[1]!=Xt.shape[1] or len(y)!=len(X) or not all(np.isfinite(a).all() for a in (X,y,Xt)):
        raise CandidateProtocolError("invalid model input arrays")
    if not isinstance(folds,list) or len(folds)<2: raise ReviewRequired("explicit inner-CV splits required")
    split=[]; allidx=set(range(len(X))); validation_coverage=[]
    cv = normalize_cv(spec.get("cv"), expected_n_splits=len(folds))
    if cv.get("n_splits") != len(folds):
        raise CandidateProtocolError("CV split count does not match explicit folds")
    if cv.get("shuffle") is not True:
        raise ReviewRequired("declared CV shuffle method is unsupported")
    if type(cv.get("random_state")) is not int:
        raise CandidateProtocolError("CV random_state must be an integer independent of the estimator seed")
    preprocessing=spec.get("preprocessing",{})
    _normalize_fit_scope(preprocessing.get("fit_scope"))
    transform=spec.get("target_transform")
    if not isinstance(transform, str):
        raise CandidateProtocolError("target_transform must be a string enum")
    if transform not in {"none","normalize_y"}:
        raise ReviewRequired("unsupported target transform")
    if _family(spec)=="GaussianProcessRegressor":
        if (spec["estimator"].get("normalize_y",True) is True)!=(transform=="normalize_y"):
            raise CandidateProtocolError("GPR normalize_y disagrees with declared target_transform")
    elif transform!="none":
        raise ReviewRequired("target transform is unsupported for this estimator family")
    candidate_count = spec.get("budget",{}).get("candidate_parameterizations")
    if type(candidate_count) is not int or candidate_count != len(_grid(spec)):
        raise CandidateProtocolError("declared search budget does not match the full parameter grid")
    for fold in folds:
        if (not isinstance(fold, dict)
                or not isinstance(fold.get("train_local"), list)
                or not isinstance(fold.get("validation_local"), list)
                or any(type(i) is not int for i in fold["train_local"] + fold["validation_local"])):
            raise CandidateProtocolError("each explicit CV fold must contain integer train_local and validation_local arrays")
        tr=np.asarray(fold["train_local"],int); va=np.asarray(fold["validation_local"],int)
        if not len(tr) or not len(va) or len(set(tr))!=len(tr) or len(set(va))!=len(va) or set(tr)&set(va) or set(tr)|set(va)!=allidx:
            raise CandidateProtocolError("CV fold must partition training-row positions")
        split.append((tr,va)); validation_coverage.extend(va.tolist())
    if len(validation_coverage)!=len(X) or set(validation_coverage)!=allidx:
        raise CandidateProtocolError("inner CV validation positions must cover each training row exactly once")
    grid=_grid(spec); scores=[]
    for params in grid:
        fs=[]
        for tr,va in split:
            model=_model(spec,params,seed); model.fit(X[tr],y[tr]); fs.append(float(np.mean(np.abs(model.predict(X[va])-y[va]))))
        scores.append(float(np.mean(fs)))
    best=min(range(len(grid)),key=lambda i:(scores[i],i))
    model=_model(spec,grid[best],seed); model.fit(X,y); pred=np.asarray(model.predict(Xt),float)
    if pred.shape!=(len(Xt),) or not np.isfinite(pred).all(): raise CandidateProtocolError("nonfinite independent refit predictions")
    return pred,{"grid":grid,"cv_mae":scores,"selected_index":best,"selected_params":grid[best]}


def prediction_matches_refit(submitted, expected, spec, X_train, y_train, X_test,
                             folds, seed, audit=None):
    """Check one whole vector against a bounded C/F replay, at unchanged tolerance.

    NumPy reductions depend on the fast memory axis; optimized GPR can amplify
    rounding differences. Both layouts use the same inputs, folds and protocol.
    Never mix per-row values from different fits or execute candidate code.
    """
    submitted = np.asarray(submitted, dtype=float)
    if submitted.shape != expected.shape or not np.isfinite(submitted).all():
        return False
    if np.allclose(submitted, expected, rtol=0.0, atol=1e-7):
        return True
    if (_family(spec) != "GaussianProcessRegressor"
            or spec["estimator"].get("optimizer", "fmin_l_bfgs_b") is None):
        return False
    alternate, alternate_audit = refit(
        spec, np.array(X_train, dtype=float, order="F"), y_train,
        np.array(X_test, dtype=float, order="F"), folds, seed)
    matched = bool(np.allclose(submitted, alternate, rtol=0.0, atol=1e-7))
    if audit is not None:
        if matched:
            audit.update(alternate_audit)
        audit["layout_replay"] = {
            "matched_fortran_vector": matched,
            "initial_max_abs_difference": float(np.max(np.abs(submitted - expected))),
            "fortran_max_abs_difference": float(np.max(np.abs(submitted - alternate))),
            "absolute_tolerance": 1e-7,
            "whole_vector_comparison": True,
        }
    return matched
