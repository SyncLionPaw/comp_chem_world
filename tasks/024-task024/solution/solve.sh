#!/bin/sh
set -eu
python3 - --assets "${APP:-/app}/assets" --output "${APP:-/app}/final" <<'__P04_SCIENTIFIC_SOLUTION__'
#!/usr/bin/env python3
"""Public-input-only conditional fate reconstruction; no grading references."""
import argparse
import csv
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

ME = "{http://www.chem.leeds.ac.uk/mesmer}"
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
M = "{http://schemas.openxmlformats.org/officeDocument/2006/math}"
KB, NA = 1.380649e-23, 6.02214076e23


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--assets", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--x-o2", type=float, default=0.2095)
    p.add_argument("--no-ppbv", type=float, default=1.0)
    p.add_argument("--temperature", type=float, default=300)
    p.add_argument("--molar", action="store_true")
    a = p.parse_args()
    doc = ET.fromstring(zipfile.ZipFile(a.assets / "41467_2023_40675_MOESM1_ESM.docx").read("word/document.xml"))
    paragraphs = list(doc.iter(W + "p"))
    texts = ["".join(node.itertext()) for node in paragraphs]
    si_index = next(i for i, t in enumerate(texts) if "Keq,add is the equilibrium constant" in t)
    si = texts[si_index]
    assert all(t in si for t in ("1.310-15", "9.1510-12", "4.9103", "1.5103", "2.210-1"))
    equation_index = next(i for i in range(si_index - 5, si_index) if list(paragraphs[i].iter(M + "f")))
    fraction = next(paragraphs[equation_index].iter(M + "f"))
    assert "".join(fraction.find(M + "num").itertext()) == "kadd"
    assert "".join(fraction.find(M + "den").itertext()) == "k-add"
    # These mantissa/exponent tokens are checked in the supplied SI, not inferred thermochemistry.
    keq, kno = 1.3 * 10**-15, 9.15 * 10**-12
    rates = {}
    for path in a.assets.rglob("Toluene-ipso-HR-*-mesmer_out.xml"):
        root = ET.parse(path).getroot()
        pt = root.find(".//" + ME + "PTpair")
        block = root.find(".//" + ME + "analysis/" + ME + "rateList")
        channels = [e for e in block.findall(ME + "firstOrderRate") if e.get("toRef") in ("ringopen-prod1", "ringopen-prod2")]
        channels.sort(key=lambda e: e.get("toRef"))
        rates[float(pt.get("T"))] = {
            "temperature_K": float(pt.get("T")), "source_pressure_Torr": float(pt.get("P")),
            "bath_gas": pt.get("bathGas"), "source_file": "assets/" + path.relative_to(a.assets).as_posix(),
            "analysis_locator": "analysis/rateList/firstOrderRate",
            "channels": [{"fromRef": e.get("fromRef"), "toRef": e.get("toRef"), "rate_per_s": float(e.text)} for e in channels],
            "k_mer_per_s": sum(float(e.text) for e in channels),
        }
    assert len(rates) == 23 and a.temperature in rates

    def calculate(t, x, no_ppbv):
        density = 101325 / (KB * t) / 1e6
        kmer = rates[t]["k_mer_per_s"]
        o2, no = x * density, no_ppbv * 1e-9 * density
        q, sink = keq * o2, kno * no
        return {"temperature_K": t, "pressure_Pa": 101325, "x_O2": x, "NO_ppbv": no_ppbv,
                "air_molecules_cm3": density, "O2_molecules_cm3": o2, "NO_molecules_cm3": no,
                "k_mer_per_s": kmer, "K_eq_cm3_per_molecule": keq, "k_NO_cm3_per_molecule_s": kno,
                "q_BPR_over_Balkyl": q, "k_NO_pseudo_per_s": sink,
                "k_eff_MR_per_Balkyl_s": q*kmer, "k_eff_NO_per_Balkyl_s": q*sink,
                "MR_fraction_two_sinks": kmer/(kmer+sink), "k_MR_per_equilibrated_pool_s": q/(1+q)*kmer,
                "source_pressure_Torr": 760, "scenario_kind": "fixed_K_eq_and_k_NO"}

    selected = calculate(a.temperature, a.x_o2, a.no_ppbv)
    baseline = rates[300]["k_mer_per_s"]
    analysis = {
        "schema_version": "1.0", "conditions": {k: selected[k] for k in ("temperature_K", "pressure_Pa", "x_O2", "NO_ppbv")},
        "parameters": {
            "K_eq": {"value": keq*NA/1000 if a.molar else keq, "unit": "L/mol" if a.molar else "cm3/molecule", "basis": "supplied_SI", "independently_verified": False},
            "k_RO2_NO": {"value": kno*NA/1000 if a.molar else kno, "unit": "L/mol/s" if a.molar else "cm3/molecule/s", "basis": "supplied_SI"}},
        "SI_provenance": {"source_file": "assets/41467_2023_40675_MOESM1_ESM.docx", "part": "word/document.xml", "equation_paragraph_zero_based": equation_index, "parameters_paragraph_zero_based": si_index},
        "native_rate_records": [rates[t] for t in sorted(rates)],
        "quantities": {k: v for k, v in selected.items() if k not in ("temperature_K", "pressure_Pa", "x_O2", "NO_ppbv", "scenario_kind", "source_pressure_Torr")},
        "comparisons": {"prior_ceiling_per_BPR_s": 0.03, "prior_reference_species": "BPR", "prior_comparison_temperature_K": 300,
                        "MR_over_prior_BPR_ceiling": baseline/0.03, "k_oxy_per_Balkyl_s": 0.22,
                        "MR_effective_over_oxy_Balkyl": selected["k_eff_MR_per_Balkyl_s"]/0.22,
                        "SI_effective_MR_per_s": 4900, "SI_effective_NO_per_s": 1500},
        "competition": {"MR_over_NO": selected["k_mer_per_s"]/selected["k_NO_pseudo_per_s"] if selected["k_NO_pseudo_per_s"] else None,
                        "MR_fraction_two_sinks": selected["MR_fraction_two_sinks"],
                        "NO_crossover_ppbv": selected["k_mer_per_s"]/(kno*selected["air_molecules_cm3"]*1e-9),
                        "common_K_eq_O2_factor_cancels": True, "sinks": ["MR", "NO"], "other_sinks_excluded": True},
        "temperature_model": {"K_eq": "fixed_SI", "k_RO2_NO": "fixed_SI", "source_pressure_Torr": 760, "thermodynamic_prediction": False, "bath_gas_composition_recomputed": False},
        "approximation": {"QSSA_MR_expression": "k_add*O2*k_mer/(k_return+k_mer+k_NO*NO)",
                          "return_must_dominate_sink_sum": True, "k_return_known": False,
                          "K_eq_independently_verified": False, "effective_reference_species": "B-alkyl",
                          "effective_is_total_pool_inverse_lifetime": False,
                          "pool_MR_expression": "K_eq*O2*k_mer/(1+K_eq*O2)",
                          "explanation": "The SI parameters are supplied. k_return must dominate both sinks; its absence prevents validation of rapid pre-equilibrium. Flux/[B-alkyl] differs from flux/([B-alkyl]+[BPR]); the native N2 bath is used as a scenario approximation."},
    }
    units = {"k_B_J_per_K": KB, "N_A_per_mol": NA, "Pa_per_atm": 101325,
             "cm3_per_m3": 1e6, "cm3_per_L": 1000, "mole_fraction_per_ppbv": 1e-9,
             "K_eq_L_per_mol": keq*NA/1000, "k_NO_L_per_mol_s": kno*NA/1000,
             "molar_to_molecular_factor": NA/1000,
             "molar_to_molecular_expression": "mol_per_L*N_A/cm3_per_L",
             "concentration_relation": "molecules/cm3 = mol/L * N_A / 1000"}
    a.output.mkdir(parents=True, exist_ok=True)
    for name, obj in (("fate_analysis.json", analysis), ("unit_conventions.json", units)):
        (a.output/name).write_text(json.dumps(obj, indent=2, allow_nan=False)+"\n")
    scenarios = [calculate(t, x, no) for t in sorted(rates) for x in sorted({0.10, 0.2095, 0.30, a.x_o2}) for no in sorted({0, 0.1, 1, 10, a.no_ppbv})]
    with (a.output/"fate_sensitivity.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(scenarios[0])); w.writeheader(); w.writerows(scenarios)
    (a.output/"conclusion.md").write_text(
        f"# Conditional BPR fate\n\nAt {a.temperature:g} K, 1 atm, x(O2)={a.x_o2:g}, NO={a.no_ppbv:g} ppbv, the MR and NO coefficients per B-alkyl are {selected['k_eff_MR_per_Balkyl_s']:.6g}/s and {selected['k_eff_NO_per_Balkyl_s']:.6g}/s. The MR fraction of these two sinks is {selected['MR_fraction_two_sinks']:.6g}.\n\n"
        f"The 300 K BPR-to-BPR comparison is {baseline:.6g}/0.03 = {baseline/0.03:.6g}. Comparing the B-alkyl effective coefficient to that prior BPR ceiling mixes species bases.\n\n"
        "The SI's 4900/1500 per second are supplied conditional values, not a measured full mechanism. Other sinks are excluded. K_eq and k_NO are held fixed in the temperature sweep; no independent thermodynamic temperature law is claimed. The native rates use 760 Torr N2; changes to bath composition are not recomputed.\n\n"
        "Pre-equilibrium requires k_return >> k_mer + k_NO[NO]; k_return is unknown. QSSA gives k_add[O2]*k_mer/(k_return+k_mer+k_NO[NO]). The effective B-alkyl coefficient is not the inverse lifetime of the total radical pool. K_eq is not independently verified from F12 thermochemistry.\n")


if __name__ == "__main__":
    main()
__P04_SCIENTIFIC_SOLUTION__
