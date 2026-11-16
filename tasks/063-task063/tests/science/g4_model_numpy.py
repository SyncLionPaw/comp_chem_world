"""NumPy reference for the published G4 TorchScript Deep-LDA models.

This module consumes the fixed tensor export produced by
``export_g4_torch_models.py``. It does not train a model and it does not
differentiate through molecular coordinates; gradients are only with respect
to the twelve normalized descriptor inputs.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
import zipfile

import numpy as np


MODEL_IDS = ("a", "b", "c")
LAYER_WIDTHS = ((12, 10), (10, 8), (8, 6), (6, 4))


def load_weights(path: str | Path, model_id: str) -> dict[str, np.ndarray]:
    if model_id not in MODEL_IDS:
        raise ValueError(f"unknown published model id: {model_id!r}")
    expected_all = {
        f"{mid}_layer{i}_{leaf}"
        for mid in MODEL_IDS
        for i in range(4)
        for leaf in ("weight", "bias")
    } | {f"{mid}_lda" for mid in MODEL_IDS}
    with zipfile.ZipFile(path) as zf:
        members = [name[:-4] for name in zf.namelist() if name.endswith(".npy")]
        if len(members) != len(set(members)) or set(members) != expected_all:
            raise ValueError("model export archive has duplicate, missing, or unexpected tensor keys")
    with np.load(path, allow_pickle=False) as archive:
        if set(archive.files) != expected_all or len(archive.files) != len(expected_all):
            raise ValueError("model export has duplicate, missing, or unexpected tensor keys")
        result: dict[str, np.ndarray] = {}
        for i, (nin, nout) in enumerate(LAYER_WIDTHS):
            wk, bk = f"{model_id}_layer{i}_weight", f"{model_id}_layer{i}_bias"
            if wk not in archive or bk not in archive:
                raise ValueError(f"model export is missing {wk} or {bk}")
            w = np.asarray(archive[wk])
            b = np.asarray(archive[bk])
            if w.shape != (nout, nin) or b.shape != (nout,):
                raise ValueError(f"unexpected shape for {wk}/{bk}: {w.shape}/{b.shape}")
            if w.dtype != np.dtype("float32") or b.dtype != np.dtype("float32"):
                raise ValueError(f"unexpected dtype for {wk}/{bk}: {w.dtype}/{b.dtype}")
            if not np.isfinite(w).all() or not np.isfinite(b).all():
                raise ValueError(f"non-finite values in {wk}/{bk}")
            result[wk] = w
            result[bk] = b
        lk = f"{model_id}_lda"
        if lk not in archive:
            raise ValueError(f"model export is missing {lk}")
        lda = np.asarray(archive[lk])
        if lda.shape != (1, 4):
            raise ValueError(f"unexpected shape for {lk}: {lda.shape}")
        if lda.dtype != np.dtype("float32") or not np.isfinite(lda).all():
            raise ValueError(f"unexpected dtype or non-finite values for {lk}: {lda.dtype}")
        result[lk] = lda
    return result


def forward_and_gradient(
    descriptors: np.ndarray,
    weights: dict[str, np.ndarray],
    model_id: str,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Return raw s, transformed sw=s+s^3, ds/dd, and dsw/dd.

    Values are evaluated in float32 to match the source TorchScript tensors.
    """
    if model_id not in MODEL_IDS:
        raise ValueError(f"unknown published model id: {model_id!r}")
    x0 = np.asarray(descriptors, dtype=np.float32)
    if x0.ndim != 2 or x0.shape[1] != 12 or not np.isfinite(x0).all():
        raise ValueError("descriptors must be a finite [n,12] array")
    x = x0
    masks: list[np.ndarray] = []
    for i in range(4):
        for key in (f"{model_id}_layer{i}_weight", f"{model_id}_layer{i}_bias"):
            if key not in weights or weights[key].dtype != np.dtype("float32") or not np.isfinite(weights[key]).all():
                raise ValueError(f"invalid trusted model tensor {key}")
        z = x @ weights[f"{model_id}_layer{i}_weight"].T + weights[f"{model_id}_layer{i}_bias"]
        if i < 3:
            masks.append(z > 0.0)
            x = np.maximum(z, 0.0)
        else:
            h = z
    s = h @ weights[f"{model_id}_lda"].T
    s = np.asarray(s[:, 0], dtype=np.float32)
    sw = np.asarray(s + s * s * s, dtype=np.float32)
    lda = weights[f"{model_id}_lda"]
    if lda.shape != (1, 4) or lda.dtype != np.dtype("float32") or not np.isfinite(lda).all():
        raise ValueError(f"invalid trusted model tensor {model_id}_lda")

    # Back-propagate row-wise through the exact fixed affine/ReLU graph.
    grad = np.broadcast_to(weights[f"{model_id}_lda"], (len(x0), 1, 4))[:, 0, :].copy()
    for i in (3, 2, 1, 0):
        grad = grad @ weights[f"{model_id}_layer{i}_weight"]
        if i > 0:
            grad *= masks[i - 1]
    ds_dd = np.asarray(grad, dtype=np.float32)
    dsw_dd = np.asarray(ds_dd * (1.0 + 3.0 * s[:, None] * s[:, None]), dtype=np.float32)
    if not all(np.isfinite(v).all() for v in (s, sw, ds_dd, dsw_dd)):
        raise FloatingPointError("non-finite G4 model output or descriptor gradient")
    return s, sw, ds_dd, dsw_dd


def summarize_gradients(
    descriptors: np.ndarray, weights: dict[str, np.ndarray], model_id: str
) -> list[dict[str, Any]]:
    _, _, _, grad = forward_and_gradient(descriptors, weights, model_id)
    out: list[dict[str, Any]] = []
    for j in range(12):
        values = np.abs(grad[:, j])
        out.append({
            "model_id": model_id,
            "descriptor": f"d{j + 1}",
            "median_abs_dsw_dd": float(np.median(values)),
            "p10_abs_dsw_dd": float(np.quantile(values, 0.10)),
            "p90_abs_dsw_dd": float(np.quantile(values, 0.90)),
            "fraction_positive": float(np.mean(grad[:, j] > 0.0)),
            "fraction_negative": float(np.mean(grad[:, j] < 0.0)),
            "n_frames": int(len(values)),
        })
    return out
