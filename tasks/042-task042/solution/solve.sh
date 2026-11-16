#!/usr/bin/env bash
set -euo pipefail

APP_ROOT="${APP:-/app}"
INPUT_ROOT="$APP_ROOT/inputs/short-training"
TRACE_DIR="$APP_ROOT/training-trace"
MODEL_DIR="$APP_ROOT/model"

if [[ "$APP_ROOT" == "/" || ! -d "$INPUT_ROOT/train/set.000" ]]; then
  echo "Expected a task app root containing inputs/short-training/train/set.000" >&2
  exit 2
fi
if [[ "$APP_ROOT" != "/app" && "${TASK42_CONFIG_ONLY:-0}" != "1" ]]; then
  echo "Refusing to run training outside /app" >&2
  exit 2
fi

# Clear only generated outputs so a prior checkpoint can never be resumed.
rm -rf "$TRACE_DIR" "$MODEL_DIR"
mkdir -p "$TRACE_DIR" "$MODEL_DIR"

# Fresh-from-initialization 20-step recipe based on the public historical
# architecture template. No checkpoint or holdout validation set is loaded.
cat > "$TRACE_DIR/train.json" <<'JSON'
{
  "model": {
    "type_map": ["H", "O", "N", "C", "Cl"],
    "descriptor": {
      "type": "se_e2_a",
      "sel": [82, 22, 28, 38, 12],
      "rcut_smth": 5.0,
      "rcut": 6.0,
      "neuron": [16, 16],
      "resnet_dt": false,
      "axis_neuron": 16,
      "seed": 3701679480
    },
    "fitting_net": {
      "neuron": [16, 16],
      "resnet_dt": true,
      "seed": 421202728
    }
  },
  "learning_rate": {
    "type": "exp",
    "start_lr": 0.0005,
    "stop_lr": 5e-08,
    "decay_steps": 5000
  },
  "loss": {
    "start_pref_e": 0.02,
    "limit_pref_e": 1,
    "start_pref_f": 1000,
    "limit_pref_f": 1,
    "start_pref_v": 0.0,
    "limit_pref_v": 0.0
  },
  "training": {
    "stop_batch": 20,
    "disp_file": "lcurve.out",
    "disp_freq": 1,
    "save_freq": 20,
    "save_ckpt": "model.ckpt",
    "disp_training": true,
    "time_training": true,
    "profiling": false,
    "training_data": {
      "systems": ["/app/inputs/short-training/train"],
      "batch_size": 1
    },
    "seed": 1718821493
  }
}
JSON

python3 - "$TRACE_DIR/train.json" "$INPUT_ROOT" "$APP_ROOT" <<'PY'
import json, sys
from pathlib import Path
cfg = json.loads(Path(sys.argv[1]).read_text())
inputs = Path(sys.argv[2])
app = Path(sys.argv[3])
manifest = json.loads((app / "inputs/sample-manifest.json").read_text())
system = json.loads((app / "inputs/system-spec-304.json").read_text())
assert cfg["training"]["stop_batch"] == 20
assert cfg["training"]["training_data"]["systems"] == ["/app/inputs/short-training/train"]
assert "validation_data" not in cfg["training"]
assert len(manifest["train"]) == 64 and len(manifest["holdout"]) == 16
assert cfg["model"]["type_map"] == system["deepmd_type_map_0_based"]
for name in ("coord.npy", "energy.npy", "force.npy", "box.npy"):
    assert (inputs / "train/set.000" / name).is_file(), name
print("CONFIG_OK: fresh initialization; 64-frame training system only; stop_batch=20")
PY

if [[ "${TASK42_CONFIG_ONLY:-0}" == "1" ]]; then
  echo "CONFIG_ONLY: training was not started"
  exit 0
fi

(
  cd "$TRACE_DIR"
  python3 - <<'PY' > runtime.json
import importlib.metadata, json, platform
print(json.dumps({
    "python": platform.python_version(),
    "deepmd_kit": importlib.metadata.version("deepmd-kit"),
    "training_seed": 1718821493,
    "stop_batch": 20,
    "initialization": "fresh; no checkpoint supplied",
    "training_system": "/app/inputs/short-training/train"
}, indent=2))
PY
  if ! dp train train.json > train.log 2>&1; then
    tail -n 100 train.log >&2 || true
    exit 1
  fi
)

test -s "$TRACE_DIR/lcurve.out"
python3 - "$TRACE_DIR" <<'PY'
from pathlib import Path
import sys
trace = Path(sys.argv[1])
steps = []
for line in (trace / "lcurve.out").read_text().splitlines():
    fields = line.split()
    if not fields:
        continue
    try:
        step = float(fields[0])
    except ValueError:
        continue
    steps.append(step)
if not steps or min(steps) < 0 or max(steps) > 20:
    raise SystemExit("lcurve.out does not show a bounded 1–20-step training run")
if not any(p.is_file() and p.stat().st_size > 0 for p in trace.glob("model.ckpt*")):
    raise SystemExit("DeepMD training did not produce a nonempty model.ckpt* checkpoint")
PY

if ! dp freeze -c "$TRACE_DIR/model.ckpt" -o "$MODEL_DIR/graph.pb" > "$TRACE_DIR/freeze.log" 2>&1; then
  cat "$TRACE_DIR/freeze.log" >&2
  exit 1
fi
cp "$INPUT_ROOT/train/type.raw" "$MODEL_DIR/type.raw"
cp "$INPUT_ROOT/train/type_map.raw" "$MODEL_DIR/type_map.raw"
test -s "$MODEL_DIR/graph.pb"

if ! python3 - "$APP_ROOT" <<'PY' > "$TRACE_DIR/inference-and-metrics.log" 2>&1
import hashlib
import json
import sys
from pathlib import Path
import numpy as np
from deepmd.infer import DeepPot

app = Path(sys.argv[1])
inputs = app / "inputs"
holdout = inputs / "short-training/holdout"
train = inputs / "short-training/train/set.000"
manifest_path = inputs / "sample-manifest.json"
manifest = json.loads(manifest_path.read_text())
natoms = int(manifest["natoms"])
sample_ids = [row["sample_id"] for row in manifest["holdout"]]
if len(sample_ids) != 16 or len(set(sample_ids)) != 16:
    raise ValueError("sample manifest must contain 16 distinct holdout frames")

# Freeze first, then use only holdout coordinates for graph inference.
coords = np.load(holdout / "set.000/coord.npy", allow_pickle=False).reshape(16, natoms, 3)
boxes = np.load(holdout / "set.000/box.npy", allow_pickle=False).reshape(16, 9)
types = np.loadtxt(holdout / "type.raw", dtype=np.int32)
if coords.shape != (16, natoms, 3) or boxes.shape != (16, 9) or types.shape != (natoms,):
    raise ValueError("holdout input shapes do not match the public sample manifest")
model = DeepPot(str(app / "model/graph.pb"))
pred_e, pred_f, _ = model.eval(coords, boxes, types)
pred_e = np.asarray(pred_e, dtype=np.float64).reshape(-1)
pred_f = np.asarray(pred_f, dtype=np.float64).reshape(16, natoms, 3)
if pred_e.shape != (16,) or not np.isfinite(pred_e).all() or not np.isfinite(pred_f).all():
    raise ValueError("frozen graph returned invalid holdout predictions")
np.savez_compressed(
    app / "predictions.npz",
    sample_id=np.asarray(sample_ids, dtype="U16"),
    energy=pred_e,
    force=pred_f,
)

# Labels and comparison observations are read only after training and freezing.
label_e = np.load(holdout / "set.000/energy.npy", allow_pickle=False).reshape(16)
label_f = np.load(holdout / "set.000/force.npy", allow_pickle=False).reshape(16, natoms, 3)

def metrics(energy, force):
    de = (np.asarray(energy, dtype=np.float64).reshape(16) - label_e) / natoms
    df = np.asarray(force, dtype=np.float64).reshape(16, natoms, 3) - label_f
    return {
        "raw_energy_rmse_eV_atom": float(np.sqrt(np.mean(de ** 2))),
        "centered_energy_rmse_eV_atom": float(np.sqrt(np.mean((de - de.mean()) ** 2))),
        "force_component_rmse_eV_A": float(np.sqrt(np.mean(df ** 2))),
        "energy_bias_eV_atom": float(np.mean(de)),
    }

models = {"candidate": metrics(pred_e, pred_f)}
for i in range(4):
    name = f"author_{i:03d}"
    with np.load(inputs / f"author-predictions/model.{i:03d}.npz", allow_pickle=False) as author:
        if not np.array_equal(np.asarray(author["sample_id"]), np.asarray(sample_ids, dtype="U16")):
            raise ValueError(f"{name} sample IDs do not match the public holdout order")
        models[name] = metrics(author["energy"], author["force"])
train_e = np.load(train / "energy.npy", allow_pickle=False).reshape(-1)
models["baseline"] = metrics(
    np.full(16, float(np.mean(train_e))),
    np.zeros_like(label_f),
)

tol = 1e-12
best_energy = next(i for i in range(4)
                   if models[f"author_{i:03d}"]["centered_energy_rmse_eV_atom"]
                   <= min(models[f"author_{j:03d}"]["centered_energy_rmse_eV_atom"] for j in range(4)) + tol)
best_force = next(i for i in range(4)
                  if models[f"author_{i:03d}"]["force_component_rmse_eV_A"]
                  <= min(models[f"author_{j:03d}"]["force_component_rmse_eV_A"] for j in range(4)) + tol)
energy_author = f"author_{best_energy:03d}"
force_author = f"author_{best_force:03d}"
candidate = models["candidate"]
if (candidate["centered_energy_rmse_eV_atom"]
        <= models[energy_author]["centered_energy_rmse_eV_atom"] + tol
        and candidate["force_component_rmse_eV_A"]
        <= models[force_author]["force_component_rmse_eV_A"] + tol):
    route = "candidate"
    reason = ("On these 16 public holdout frames, the newly trained candidate is no worse within "
              "the 1e-12 tie tolerance than the best supplied author observation for both centered-energy "
              "and force-component error. This finite, visible comparison does not establish blind or production accuracy.")
elif best_energy == best_force:
    route = energy_author
    reason = (f"On these 16 public holdout frames, {energy_author} has the lowest centered-energy and "
              "force-component errors among the supplied author observations. This is a finite visible-sample "
              "comparison, not evidence of blind generalization or production accuracy.")
else:
    route = "none"
    reason = (f"The best centered-energy observation is {energy_author}, while the best force-component "
              f"observation is {force_author}; the candidate does not match or improve on both minima. "
              "These 16 visible holdout frames do not support one route, so none is recommended for this "
              "limited comparison. No blind or production accuracy is established.")

metrics_json = {
    "schema": "short-training-audit/v1",
    "natoms": natoms,
    "units": {
        "energy": "eV total",
        "energy_metric": "eV/atom",
        "force": "eV/Angstrom",
        "force_metric": "component eV/Angstrom",
    },
    "sample_manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
    "models": models,
    "decision": {
        "best_author_energy_centered": energy_author,
        "best_author_force_component": force_author,
        "energy_offset_changes_centered_rmse": False,
        "force_rmse_definition": "component",
        "validation_is_blind": False,
        "production_accuracy_established": False,
        "chosen_route": route,
        "reason": reason,
    },
}
(app / "metrics.json").write_text(json.dumps(metrics_json, indent=2, ensure_ascii=False) + "\n")

lines = [
    "# Short-training comparison",
    "",
    "A new TensorFlow DeePMD model was trained from a fresh initialization for at most 20 optimizer steps using only the 64 designated training frames. The public 16-frame holdout was used only after freezing the model, for prediction and finite comparison.",
    "",
    "The recipe uses an initial learning rate of 0.0005. This differs from the paper text's 0.001 and should be understood as a bounded diagnostic choice, not an attempted full reproduction.",
    "",
    "## Holdout comparison",
    "",
    "All energy metrics below are per atom; force RMSE is over Cartesian force components. Raw energy error includes the mean offset, while centered energy RMSE removes that offset. The baseline is the training-set mean total energy with zero forces.",
    "",
    "| Model | Raw energy RMSE (eV/atom) | Centered energy RMSE (eV/atom) | Energy bias (eV/atom) | Force-component RMSE (eV/Å) |",
    "|---|---:|---:|---:|---:|",
]
for name in ("candidate", "author_000", "author_001", "author_002", "author_003", "baseline"):
    row = models[name]
    lines.append(f"| {name} | {row['raw_energy_rmse_eV_atom']:.8g} | {row['centered_energy_rmse_eV_atom']:.8g} | {row['energy_bias_eV_atom']:.8g} | {row['force_component_rmse_eV_A']:.8g} |")
lines += [
    "",
    f"Best supplied author for centered energy: `{energy_author}`. Best supplied author for force-component error: `{force_author}`.",
    "",
    f"Recommended route: `{route}`. {reason}",
    "",
    "The 16 holdout labels and author predictions are visible and reused in this comparison, so this is not a blind test. A 20-step run on 64 frames is a limited training diagnosis; neither these comparisons nor the selected route establish production accuracy or reproduce the paper's complete training.",
    "",
]
(app / "report.md").write_text("\n".join(lines))
print("Wrote predictions, metrics, and report from the newly frozen graph.")
PY
then
  cat "$TRACE_DIR/inference-and-metrics.log" >&2
  exit 1
fi

# The output must be generated by the new run, never copied from the historical example.
for path in "$MODEL_DIR/graph.pb" "$MODEL_DIR/type.raw" "$MODEL_DIR/type_map.raw" \
            "$APP_ROOT/predictions.npz" "$APP_ROOT/metrics.json" "$APP_ROOT/report.md"; do
  test -s "$path"
done
