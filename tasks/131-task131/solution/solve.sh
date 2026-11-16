#!/bin/bash
set -euo pipefail
python3 - <<'PY'
import json
import os
import tempfile
from pathlib import Path

import numpy as np

FINAL = Path(os.environ.get("FINAL", "/app/final"))
ASSETS = Path(os.environ.get("ASSETS", "/app/environment/assets"))
FINAL.mkdir(parents=True, exist_ok=True)


def write_xyz(path, atoms, comment):
    lines = [str(len(atoms)), comment]
    for symbol, position in zip(atoms.get_chemical_symbols(), atoms.get_positions()):
        lines.append(f"{symbol} {position[0]:.8f} {position[1]:.8f} {position[2]:.8f}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def atoms_from_smiles(smiles, mmff):
    from ase import Atoms
    from rdkit import Chem
    from rdkit.Chem import AllChem

    mol = Chem.AddHs(Chem.MolFromSmiles(smiles))
    if AllChem.EmbedMolecule(mol, randomSeed=42) != 0:
        raise SystemExit(f"RDKit embedding failed for {smiles!r}")
    if mmff:
        AllChem.MMFFOptimizeMolecule(mol)
    return Atoms([a.GetSymbol() for a in mol.GetAtoms()],
                 positions=mol.GetConformer().GetPositions())


def calculator(multiplicity=1):
    from tblite.ase import TBLite

    return TBLite(method="GFN2-xTB", multiplicity=multiplicity, verbosity=0)


def optimize(atoms, multiplicity=1):
    from ase.optimize import BFGS

    atoms.calc = calculator(multiplicity)
    BFGS(atoms, logfile=None).run(fmax=0.02)
    return atoms


def vibrational_energies(atoms, rigid):
    from ase.vibrations import Vibrations

    with tempfile.TemporaryDirectory(prefix="cg19-vib-") as scratch:
        vib = Vibrations(atoms, name=os.path.join(scratch, "vib"))
        vib.run()
        values = np.asarray(vib.get_energies())
        vib.clean()
    return [complex(v).real for v in sorted(values, key=lambda v: abs(v), reverse=True)[:rigid]]


def frequencies_cm1(atoms, rigid):
    from ase.vibrations import Vibrations

    with tempfile.TemporaryDirectory(prefix="cg19-vib-") as scratch:
        vib = Vibrations(atoms, name=os.path.join(scratch, "vib"))
        vib.run()
        values = np.asarray(vib.get_frequencies())
        vib.clean()
    return sorted(float(v) for v in sorted(values.real, key=abs, reverse=True)[:rigid])


def thermo_model(atoms, energies, geometry, symmetrynumber, spin):
    from ase.thermochemistry import IdealGasThermo

    return IdealGasThermo(vib_energies=energies,
                          potentialenergy=float(atoms.get_potential_energy()),
                          atoms=atoms, geometry=geometry,
                          symmetrynumber=symmetrynumber, spin=spin)

SPECIES = {
    "CH4": {
        "geometry": "nonlinear",
        "symmetrynumber": 12,
        "spin": 0,
        "multiplicity": 1
    },
    "O2": {
        "geometry": "linear",
        "symmetrynumber": 2,
        "spin": 1,
        "multiplicity": 3
    },
    "CO2": {
        "geometry": "linear",
        "symmetrynumber": 2,
        "spin": 0,
        "multiplicity": 1
    },
    "H2O": {
        "geometry": "nonlinear",
        "symmetrynumber": 2,
        "spin": 0,
        "multiplicity": 1
    }
}
REACTION = {
    "id": "r01",
    "name": "Methane Combustion",
    "reactants": [
        {
            "name": "CH4",
            "coefficient": 1
        },
        {
            "name": "O2",
            "coefficient": 2
        }
    ],
    "products": [
        {
            "name": "CO2",
            "coefficient": 1
        },
        {
            "name": "H2O",
            "coefficient": 2
        }
    ]
}


def species_value(name):
    from ase.build import molecule
    from ase.optimize import BFGS

    spec = SPECIES[name]
    atoms = molecule(name)
    atoms.calc = calculator(spec["multiplicity"])
    BFGS(atoms, logfile=None).run(fmax=0.02)
    rigid = 3 * len(atoms) - (5 if spec["geometry"] == "linear" else 6)
    energies = vibrational_energies(atoms, rigid)
    model = thermo_model(atoms, energies, spec["geometry"],
                         spec["symmetrynumber"], spec["spin"])
    return float(model.get_enthalpy(temperature=298.15, verbose=False))


values = {name: species_value(name) for name in SPECIES}
total = 0.0
for side, sign in ((REACTION["reactants"], -1.0), (REACTION["products"], 1.0)):
    for entry in side:
        total += sign * entry["coefficient"] * values[entry["name"]]
(FINAL / "reaction.json").write_text(
    json.dumps({"reaction_enthalpy_eV": round(total, 4)}) + "\n", encoding="utf-8")
PY
