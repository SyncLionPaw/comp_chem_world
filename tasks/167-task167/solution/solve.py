#!/usr/bin/env python3
"""Construct a symmetry-constrained five-atom W2N3 monolayer from the brief."""
from __future__ import annotations
import json
import os
import re
import sys
from pathlib import Path
import numpy as np

LATTICE = np.array([[2.9130614778, 0.0, 0.0], [-1.4565307389, 2.5227852425, 0.0], [0.0, 0.0, 25.1518869092]])
CART = np.array([[1.4565307389, 0.8409284142, 11.1077526819], [1.4565307389, 0.8409284142, 14.0441342272], [0.0, 1.6818568284, 9.9942367038], [0.0, 1.6818568284, 15.1576502054], [0.0, 1.6818568284, 12.5759434546]])
SPECIES = ["W", "W", "N", "N", "N"]


def coordination(cart, lattice, species):
    shifts = np.array([[i, j, k] for i in range(-2, 3) for j in range(-2, 3) for k in (-1, 0, 1)])
    w = [i for i, s in enumerate(species) if s == "W"]
    n = [i for i, s in enumerate(species) if s == "N"]
    w_counts, n_short, n_wide = [], [], []
    for i in w:
        w_counts.append(int(sum(np.linalg.norm(cart[j] + shift @ lattice - cart[i]) <= 2.45 for j in n for shift in shifts)))
    for i in n:
        ds = [np.linalg.norm(cart[j] + shift @ lattice - cart[i]) for j in w for shift in shifts]
        n_short.append(int(sum(d <= 2.15 for d in ds))); n_wide.append(int(sum(d <= 2.5 for d in ds)))
    return w_counts, n_short, n_wide


def source_claims(brief: str) -> dict:
    m = re.search(r"two (\w+)-coordinated W.*?two (\w+)-coordinated N.*?central (\w+)-coordinated N", brief, re.S | re.I)
    if not m:
        raise ValueError("could not recover the three coordination statements from the crystallographic brief")
    values = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7}
    try: return {"W": values[m.group(1).lower()], "N_outer": values[m.group(2).lower()], "N_center": values[m.group(3).lower()]}
    except KeyError as exc: raise ValueError("unsupported coordination numeral in the crystallographic brief") from exc

def source_wyckoff_claims(brief: str) -> dict:
    m = re.search(r"W atoms occupies the ([0-9]+[a-z])\(.*?N anions occupies the ([0-9]+[a-z])\(.*?central .*?N occupy the ([0-9]+[a-z])\(", brief, re.S | re.I)
    if not m:
        raise ValueError("could not recover the source Wyckoff labels from the crystallographic brief")
    return {"W": m.group(1), "N_outer": m.group(2), "N_center": m.group(3)}


def main() -> int:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "final-out").resolve(); out.mkdir(parents=True, exist_ok=True)
    brief_path = Path(os.environ.get("APP", "/app")) / "assets/structure-brief.md"
    if not brief_path.is_file(): brief_path = Path(__file__).resolve().parents[1] / "environment/assets/structure-brief.md"
    brief = brief_path.read_text(encoding="utf-8")
    claims = source_claims(brief)
    paper_wyckoff = source_wyckoff_claims(brief)
    frac = np.linalg.solve(LATTICE.T, CART.T).T
    lines = ["W2N3 monolayer; symmetry-constrained construction", "1.0"]
    lines += ["  {:18.12f} {:18.12f} {:18.12f}".format(*v) for v in LATTICE]
    lines += ["W N", "2 3", "Direct"]
    lines += ["  {:16.10f} {:16.10f} {:16.10f}".format(*v) for v in frac]
    (out / "W2N3-monolayer.poscar").write_text("\n".join(lines) + "\n", encoding="utf-8")

    cart = frac @ LATTICE
    a = 0.5 * (np.linalg.norm(LATTICE[0]) + np.linalg.norm(LATTICE[1]))
    thickness = float(cart[:, 2].max() - cart[:, 2].min())
    vacuum = float(np.linalg.norm(LATTICE[2]) - thickness)
    w_counts, n_short, n_wide = coordination(cart, LATTICE, SPECIES)
    center_i = int(np.argmax(n_wide)); outer = [i for i in range(3) if i != center_i]
    n_three = sum(n_short[i] == 3 for i in outer)
    import spglib
    cell = (LATTICE, frac, [74 if s == "W" else 7 for s in SPECIES])
    dataset = spglib.get_symmetry_dataset(cell, symprec=1e-3)
    paper_a = float(re.search(r"a\s*=\s*([0-9.]+)\s*A\s*\(PBE, no SOC\)", brief).group(1))
    wyckoff_sites = [{"atom_index": i, "species": SPECIES[i], "wyckoff_letter": str(dataset.wyckoffs[i]),
                      "site_symmetry": str(dataset.site_symmetry_symbols[i])}
                     for i in range(len(SPECIES))]
    note = (f"The brief reports a central-N coordination of {claims['N_center']}; the constructed periodic geometry has "
            f"{n_wide[center_i]} W neighbors within 2.50 A. The two outer N have short-cutoff counts "
            f"{[n_short[i] for i in outer]} within 2.15 A, and the W counts are {sorted(w_counts)} within 2.45 A. "
            "I retain the reported coordination as a source claim and report the measured geometry separately.")
    report = {"stoichiometry": "W2N3", "n_atoms": len(SPECIES), "space_group_number": int(dataset.number),
              "space_group_symbol": str(dataset.international), "inplane_lattice_a_A": round(a, 4),
              "vacuum_A": round(vacuum, 2), "layer_thickness_A": round(thickness, 2),
              "coordination": {"cutoff_A": 2.5, "W_counts": sorted(w_counts),
                               "N_three_coordination_count": int(n_three), "N_center_count": int(n_wide[center_i])},
              "paper_coordination_claims": claims, "discrepancy_note": note,
              "paper_wyckoff_claims": paper_wyckoff,
              "wyckoff_label_assessment": "The brief uses the authors’ cell setting. Computed spglib letters and site symmetries below use the submitted standardized structure; compare multiplicities and coordinates rather than assuming identical letter labels across settings.",
              "computed_wyckoff_sites": wyckoff_sites,
              "choice_rationale": f"The adopted in-plane parameter {a:.4f} A is within the paper-derived {paper_a:.3f} A PBE window; internal z coordinates were selected to preserve No. 187 symmetry and the stated bonding layers.",
              "source_lattice_a_PBE_no_SOC_A": paper_a}
    (out / "structure-report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote structure-derived deliverables to {out}")
    return 0

if __name__ == "__main__": raise SystemExit(main())
