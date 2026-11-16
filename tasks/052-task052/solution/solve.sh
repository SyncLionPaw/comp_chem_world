#!/bin/sh
set -eu
APP=${APP:-/app}
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
cat > "$WORK/implementation.py" <<'CCW_TASK52_IMPLEMENTATION_PY_EOF'
"""Reference implementation of the public Case 04 archived-chain API."""
import math
import numpy as np

SHAPES = ((96, 12), (96,), (48, 96), (48,), (24, 48), (24,), (1, 24), (1,))


def _params(checkpoint):
    if len(checkpoint) != 8:
        raise ValueError("checkpoint must contain the eight ordered tensors")
    out = []
    for value, shape in zip(checkpoint, SHAPES):
        a = np.asarray(value, dtype=np.float64)
        if a.shape != shape or not np.all(np.isfinite(a)):
            raise ValueError("checkpoint tensor shape or values are invalid")
        out.append(a)
    return out


def _angles(values):
    x = np.asarray(values, dtype=np.float64)
    if x.ndim == 1:
        x = x[None, :]
    if x.ndim != 2 or x.shape[1] != 6 or not np.all(np.isfinite(x)):
        raise ValueError("angles must be finite with shape (n, 6)")
    return (x + np.pi) % (2.0 * np.pi) - np.pi


def _evaluate(angles, params, need_gradient):
    x = _angles(angles)
    z = np.concatenate((np.sin(x), np.cos(x)), axis=1)
    acts = [z]
    pre = []
    for w, b in zip(params[0:6:2], params[1:6:2]):
        q = acts[-1] @ w.T + b
        pre.append(q)
        acts.append(np.maximum(q, 0.0))
    energy = (acts[-1] @ params[6].T + params[7]).reshape(-1)
    if not need_gradient:
        return energy, None
    batch = len(x)
    delta = np.ones((batch, 1), dtype=np.float64)
    grads = [None] * 8
    grads[6] = np.einsum("bi,bj->bij", delta, acts[3])
    grads[7] = delta.copy()
    delta = delta @ params[6]
    for layer in (2, 1, 0):
        delta = delta * (pre[layer] > 0.0)
        grads[2 * layer] = np.einsum("bi,bj->bij", delta, acts[layer])
        grads[2 * layer + 1] = delta.copy()
        delta = delta @ params[2 * layer]
    angle_grad = delta[:, :6] * np.cos(x) - delta[:, 6:] * np.sin(x)
    flattened = np.concatenate([g.reshape(batch, -1) for g in grads], axis=1)
    return energy, (flattened, angle_grad)


def forward_and_grad(angles, checkpoint):
    """Return scalar V and C-order flattened parameter gradient for one state."""
    x = np.asarray(angles, dtype=np.float64)
    if x.shape != (6,):
        raise ValueError("forward_and_grad accepts one six-angle state")
    energy, (gradient, _) = _evaluate(x, _params(checkpoint), True)
    return float(energy[0]), gradient[0]


def transition(state, proposal, u, ensemble, beta, gamma):
    """One Metropolis decision for an absolute proposed angle vector."""
    if ensemble not in ("target", "flat_probe"):
        raise ValueError("ensemble must be target or flat_probe")
    if not math.isfinite(float(u)) or not 0.0 < float(u) < 1.0:
        raise ValueError("u must be strictly between zero and one")
    if not math.isfinite(float(beta)) or not math.isfinite(float(gamma)) or gamma <= 1.0:
        raise ValueError("beta and gamma must be finite and gamma > 1")
    x = _angles(state)[0]
    y = _angles(proposal)[0]
    coefficient = float(beta) / (float(gamma) - 1.0) if ensemble == "target" else 0.0
    p = _params(_CHECKPOINT_FOR_TRANSITION)
    ex = _evaluate(x, p, False)[0][0]
    ey = _evaluate(y, p, False)[0][0]
    log_alpha = min(0.0, coefficient * (ey - ex))
    accepted = math.log(float(u)) < log_alpha
    return bool(accepted), (y if accepted else x)


# The verifier supplies the decoded checkpoint through this explicit setup hook.
_CHECKPOINT_FOR_TRANSITION = None


def set_checkpoint(checkpoint):
    global _CHECKPOINT_FOR_TRANSITION
    _CHECKPOINT_FOR_TRANSITION = checkpoint


def analyze(chains, checkpoint, blocksize):
    """Recompute expectations and pooled chain-block MCSE from supplied chains."""
    params = _params(checkpoint)
    if type(blocksize) is not int or blocksize < 1:
        raise ValueError("blocksize must be a positive integer")
    stats = {}
    for ensemble in ("target", "flat_probe"):
        chain_rows = chains[ensemble]
        if not isinstance(chain_rows, (list, tuple)) or len(chain_rows) != 2:
            raise ValueError("each ensemble must contain two chains")
        total_n = 0
        energy_sum = 0.0
        gradient_sum = np.zeros(7105, dtype=np.float64)
        block_count = 0
        block_mean = np.zeros(7105, dtype=np.float64)
        block_m2 = np.zeros(7105, dtype=np.float64)
        for chain in chain_rows:
            n = len(chain)
            if n == 0 or n % blocksize:
                raise ValueError("blocksize must divide each nonempty chain")
            total_n += n
            chain_sum = np.zeros(7105, dtype=np.float64)
            chain_energy = 0.0
            # Preserve chain/block boundaries and cap every gradient batch at 64 rows.
            for block_start in range(0, n, blocksize):
                block_stop = block_start + blocksize
                block_sum = np.zeros(7105, dtype=np.float64)
                for start in range(block_start, block_stop, 64):
                    stop = min(start + 64, block_stop)
                    energies, (gradients, _) = _evaluate(chain[start:stop], params, True)
                    block_sum += gradients.sum(axis=0)
                    chain_energy += float(energies.sum())
                chain_sum += block_sum
                block_value = block_sum / blocksize
                block_count += 1
                delta_block = block_value - block_mean
                block_mean += delta_block / block_count
                block_m2 += delta_block * (block_value - block_mean)
            gradient_sum += chain_sum
            energy_sum += chain_energy
        stats[ensemble] = {
            "energy_mean": energy_sum / total_n,
            "gradient_mean": gradient_sum / total_n,
            "block_count": block_count,
            "block_mean": block_mean,
            "block_m2": block_m2,
        }
    target = stats["target"]
    flat = stats["flat_probe"]
    if target["block_count"] < 2 or flat["block_count"] < 2:
        raise ValueError("at least two full blocks per ensemble are required")
    target_var = target["block_m2"] / (target["block_count"] - 1)
    flat_var = flat["block_m2"] / (flat["block_count"] - 1)
    mcse = np.sqrt(target_var / target["block_count"] + flat_var / flat["block_count"])
    return {
        "target_energy_mean": target["energy_mean"],
        "flat_energy_mean": flat["energy_mean"],
        "target_gradient_mean": target["gradient_mean"],
        "flat_gradient_mean": flat["gradient_mean"],
        "contrast": target["gradient_mean"] - flat["gradient_mean"],
        "mcse": mcse,
    }
CCW_TASK52_IMPLEMENTATION_PY_EOF
install -m 0644 "$WORK/implementation.py" "$APP/submission.py"
