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
SMILES = json.loads((ASSETS / "name_lookup.json").read_text(encoding="utf-8"))['methanol']


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

atoms = optimize(atoms_from_smiles(SMILES, mmff=True))
write_xyz(FINAL / "out.xyz", atoms, 'methanol')
PY
