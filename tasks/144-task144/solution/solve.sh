#!/bin/bash
set -euo pipefail
RUNTIME_DIR="$(mktemp -d "${TMPDIR:-/tmp}/bench22-runtime.XXXXXXXX")"
trap 'rm -rf "${RUNTIME_DIR}"' EXIT
cat > "${RUNTIME_DIR}/kernel.py" <<'BENCH22_EMBED_KERNEL_PY'
from __future__ import annotations

import json
import math
from pathlib import Path

from scipy import constants as C


def positive(value, name):
    value = float(value)
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be finite and positive")
    return value


def spin_rates(temperature_k, gap_ev, soc_cm1, gamma_cm1):
    temperature_k = positive(temperature_k, "temperature_K")
    gamma_cm1 = positive(gamma_cm1, "gamma_cm1")
    gap_ev, soc_cm1 = float(gap_ev), float(soc_cm1)
    if not math.isfinite(gap_ev) or not math.isfinite(soc_cm1) or soc_cm1 < 0:
        raise ValueError("gap and SOC must be finite; SOC must be nonnegative")
    cm1_to_joule = C.h * C.c * 100
    gap, coupling, width = gap_ev * C.e, soc_cm1 * cm1_to_joule, gamma_cm1 * cm1_to_joule
    base = 2 * coupling**2 * width / (C.hbar * (gap**2 + width**2))
    thermal = math.exp(-abs(gap) / (C.k * temperature_k))
    if gap_ev >= 0:
        return base, base * thermal / 3
    return base * thermal, base / 3


def radiative_rate(gap_ev, dipole_au, n_ref):
    energy = float(gap_ev) * C.e
    dipole = float(dipole_au) * C.e * C.physical_constants["Bohr radius"][0]
    n = float(n_ref)
    if not all(math.isfinite(x) for x in (energy, dipole, n)) or energy < 0 or n <= 0:
        raise ValueError("radiative inputs must be finite with nonnegative gap and positive n_ref")
    return energy**3 * dipole**2 / (3 * math.pi * C.epsilon_0 * C.hbar**4 * C.c**3) * n * (n*n + 2)**2 / 9


def main():
    cfg = json.loads(Path("inputs/benchmark.json").read_text(encoding="utf-8"))
    temperatures = [positive(x, "temperature_K") for x in cfg["temperature_K"]]
    gammas = [positive(x, "gamma_cm1") for x in cfg["gamma_cm1"]]
    radiative = [radiative_rate(x["gap_eV"], x["dipole_au"], x["n_ref"]) for x in cfg["radiative"]]
    spin_rows = []
    for t in temperatures:
        for gap in cfg["signed_gap_eV"]:
            for soc in cfg["soc_cm1"]:
                for gamma in gammas:
                    isc, risc = spin_rates(t, gap, soc, gamma)
                    spin_rows.append({"T_K": t, "gap_eV": gap, "soc_cm1": soc,
                                      "gamma_cm1": gamma, "isc_s1": isc, "risc_s1": risc})
    ic_up = []
    for row in cfg["ic"]:
        t = positive(row["temperature_K"], "temperature_K")
        positive(row["down_s1"], "down_s1")
        if not math.isfinite(float(row["gap_eV"])) or float(row["gap_eV"]) < 0:
            raise ValueError("IC gap must be finite and nonnegative")
        ic_up.append(row["down_s1"] * math.exp(-row["gap_eV"] * C.e / (C.k * t)))
    result = {"radiative_s1": radiative, "spin_rows": spin_rows, "ic_up_s1": ic_up}
    Path("result.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
BENCH22_EMBED_KERNEL_PY
cat > "${RUNTIME_DIR}/validation.py" <<'BENCH22_EMBED_VALIDATION_PY'
from __future__ import annotations

import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from scipy import constants as C

kernel, benchmark, output = map(Path, sys.argv[1:4])
cfg = json.loads(benchmark.read_text(encoding="utf-8"))
result = json.loads((kernel.parent / "result.json").read_text(encoding="utf-8"))
zero_soc = [abs(value) for row in result["spin_rows"] if row["soc_cm1"] == 0
            for value in (row["isc_s1"], row["risc_s1"])]
balance = []
for row in result["spin_rows"]:
    if row["isc_s1"] > 0 and row["risc_s1"] > 0:
        expected = math.exp(-row["gap_eV"] * C.e / (C.k * row["T_K"])) / 3
        balance.append(abs((row["risc_s1"] / row["isc_s1"]) / expected - 1))
ratios = []
lookup = {(row["T_K"], row["gap_eV"], row["soc_cm1"], row["gamma_cm1"]): row
          for row in result["spin_rows"]}
for t in cfg["temperature_K"]:
    for gap in cfg["signed_gap_eV"]:
        for gamma in cfg["gamma_cm1"]:
            ratios.append(lookup[(t, gap, 5.0, gamma)]["isc_s1"] /
                          lookup[(t, gap, 0.5, gamma)]["isc_s1"])
probes = []
with tempfile.TemporaryDirectory(prefix="rate-kernel-invalid-") as raw:
    root = Path(raw)
    for field in ("temperature_K", "gamma_cm1"):
        for bad in (0, -1):
            case = root / f"{field}-{bad}"
            (case / "inputs").mkdir(parents=True)
            shutil.copy2(kernel, case / "kernel.py")
            altered = json.loads(json.dumps(cfg))
            altered[field][0] = bad
            (case / "inputs/benchmark.json").write_text(json.dumps(altered), encoding="utf-8")
            run = subprocess.run([sys.executable, "kernel.py"], cwd=case, capture_output=True,
                                 text=True, timeout=30)
            if run.returncode == 0 or (case / "result.json").exists():
                raise SystemExit(f"invalid input accepted: {field}={bad}")
            probes.append({"field": field, "value": bad, "exit_code": run.returncode})
payload = {
    "schema_version": "1.0",
    "commands": ["python kernel.py"],
    "baseline_exit_code": 0,
    "checks": {
        "zero_soc_max_abs_s-1": max(zero_soc, default=0.0),
        "soc_squared_ratio_min": min(ratios),
        "soc_squared_ratio_max": max(ratios),
        "detailed_balance_max_relative_error": max(balance, default=0.0),
    },
    "invalid_input_probes": probes,
}
output.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n", encoding="utf-8")
BENCH22_EMBED_VALIDATION_PY
mkdir -p /app/final
cp "$RUNTIME_DIR/kernel.py" /app/final/kernel.py
(cd /app && python /app/final/kernel.py)
mv /app/result.json /app/final/result.json
python "$RUNTIME_DIR/validation.py" /app/final/kernel.py /app/inputs/benchmark.json /app/final/validation.json
