#!/usr/bin/env bash
set -euo pipefail
APP="${APP:-/app}"
mkdir -p "$APP"
cat > "$APP/calculations.py" <<'PY_CALCULATIONS'
#!/usr/bin/env python3
"""Recompute Nernst-Einstein conductivity and Yeh-Hummer increments."""

import argparse
import csv
import json
import math
from pathlib import Path

E = 1.602176634e-19
KB = 1.380649e-23
ZETA = 2.837297
N_PAIR = 64
FORMULA = "N_pair*e^2*(D_cation+D_anion)/(V*k_B*T)"
FIELDS = ("T_K", "sigma_NE_S_m", "gamma", "delta_D_m2_s")


def calculate(input_path: Path) -> list[dict[str, float]]:
    with input_path.open(newline="", encoding="utf-8") as stream:
        source = list(csv.DictReader(stream))

    results = []
    for row in source:
        temperature = float(row["T_K"])
        length = float(row["L_A"]) * 1e-10
        viscosity = float(row["eta_mPa_s"]) * 1e-3
        d_cation = float(row["D_cation_1e-11_m2_s"]) * 1e-11
        d_anion = float(row["D_anion_1e-11_m2_s"]) * 1e-11
        sigma_gk = float(row["sigma_GK_S_m"])

        sigma_ne = N_PAIR * E**2 * (d_cation + d_anion) / (length**3 * KB * temperature)
        gamma = sigma_gk / sigma_ne
        delta_d = ZETA * KB * temperature / (6 * math.pi * viscosity * length)
        results.append({
            "T_K": temperature,
            "sigma_NE_S_m": sigma_ne,
            "gamma": gamma,
            "delta_D_m2_s": delta_d,
        })

    results.sort(key=lambda result: result["T_K"])
    return results


def write_outputs(input_path: Path, output_dir: Path) -> None:
    results = calculate(input_path)
    output_dir.mkdir(parents=True, exist_ok=True)

    with (output_dir / "results.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        for result in results:
            writer.writerow({field: format(result[field], ".17g") for field in FIELDS})

    gamma_above_one = [int(row["T_K"]) for row in results if row["gamma"] > 1]
    if gamma_above_one:
        above_one_summary = ", ".join(f"{temperature} K" for temperature in gamma_above_one)
        above_one_sentence = f" Gamma exceeds one at {above_one_summary}."
    else:
        above_one_sentence = " Gamma does not exceed one at any supplied temperature."

    analysis = {
        "formula_sigma_NE": FORMULA,
        "diffusion_input_status": "already_corrected",
        "apply_correction_again": False,
        "gamma_gt_one_T_K": gamma_above_one,
        "gamma_lt_one_T_K": [int(row["T_K"]) for row in results if row["gamma"] < 1],
        "gamma_is_ion_fraction": False,
        "units": {"L": "m", "eta": "Pa*s", "D": "m^2/s", "sigma": "S/m"},
        "interpretation": {
            "text": (
                "The supplied SI diffusion coefficients are already finite-size corrected, so they are used "
                "unchanged in the Nernst–Einstein estimate. The Yeh–Hummer increment is reported separately."
                + above_one_sentence +
                " The ratio gamma is not an ion-pair population or "
                "a fraction constrained to [0, 1]. Cross-species charge-current correlations can enhance or "
                "suppress the Green–Kubo conductivity. A gamma below one is not unique evidence for ion pairs, "
                "and significance claims require uncertainty estimates."
            ),
            "ratio_not_population": True,
            "cross_correlations_can_enhance_or_suppress": True,
            "gamma_below_one_does_not_identify_pairs": True,
            "uncertainty_required_for_significance": True,
        },
    }
    (output_dir / "analysis.json").write_text(
        json.dumps(analysis, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    write_outputs(args.input, args.output)


if __name__ == "__main__":
    main()
PY_CALCULATIONS
exec python3 "$APP/calculations.py" \
  --input "$APP/inputs/conductivity-audit.csv" \
  --output "$APP"
