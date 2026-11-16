"""Optional reference implementation for the declared Case 03 model protocol."""
from __future__ import annotations

import numpy as np
from sklearn.decomposition import PCA
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.kernel_ridge import KernelRidge
from sklearn.linear_model import Ridge
from sklearn.model_selection import KFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


def predict_declared(X_train, y_train, X_test, arm_spec):
    """Fit the declared grid on inner folds, then refit its selected estimator."""
    if arm_spec.get("scaler") not in ("none", "standard") or arm_spec.get("target_scaler") not in ("none", "standard"):
        raise ValueError("unsupported scaler declaration")
    estimator_spec = arm_spec["estimator"]
    family = estimator_spec["family"]
    allowed = {"Ridge": Ridge, "KernelRidge": KernelRidge,
               "GaussianProcessRegressor": GaussianProcessRegressor}
    if family not in allowed:
        raise ValueError("unsupported estimator family")
    grid = estimator_spec["parameter_grid"]
    keys = sorted(grid)
    param_sets = [{}]
    for key in keys:
        param_sets = [dict(item, **{key: value}) for item in param_sets for value in grid[key]]
    cv = arm_spec["cv"]
    splitter = KFold(n_splits=cv["n_splits"], shuffle=cv["shuffle"], random_state=cv["random_state"])

    def pipeline(params):
        steps = []
        if arm_spec["scaler"] == "standard":
            steps.append(("scale", StandardScaler()))
        pca = arm_spec.get("pca")
        if pca is not None:
            steps.append(("pca", PCA(**{"svd_solver": "randomized", **pca})))
        if family == "GaussianProcessRegressor":
            model = GaussianProcessRegressor(**params, optimizer=None, copy_X_train=True)
        else:
            model = allowed[family](**params)
        steps.append(("model", model))
        return Pipeline(steps)

    scores = []
    for params in param_sets:
        fold_errors = []
        for train_idx, valid_idx in splitter.split(X_train):
            model = pipeline(params)
            y_fit = y_train[train_idx]
            if arm_spec["target_scaler"] == "standard":
                mean, scale = float(np.mean(y_fit)), float(np.std(y_fit)) or 1.0
                y_model = (y_fit - mean) / scale
            else:
                mean, scale, y_model = 0.0, 1.0, y_fit
            model.fit(X_train[train_idx], y_model)
            fold_pred = np.asarray(model.predict(X_train[valid_idx]), dtype=float) * scale + mean
            fold_errors.append(float(np.mean(np.abs(fold_pred - y_train[valid_idx]))))
        scores.append(float(np.mean(fold_errors)))

    selected = min(range(len(param_sets)), key=lambda i: (scores[i], i))
    params = param_sets[selected]
    model = pipeline(params)
    if arm_spec["target_scaler"] == "standard":
        mean, scale = float(np.mean(y_train)), float(np.std(y_train)) or 1.0
        y_model = (y_train - mean) / scale
    else:
        mean, scale, y_model = 0.0, 1.0, y_train
    model.fit(X_train, y_model)
    pred = np.asarray(model.predict(X_test), dtype=float) * scale + mean
    if pred.shape != (len(X_test),) or not np.isfinite(pred).all():
        raise ValueError("fit produced invalid predictions")
    return pred
