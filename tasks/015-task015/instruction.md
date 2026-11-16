# Construct a consistent periodic solvent model using the supplied six-site acetonitrile parameters

## Background
A periodic solvent model requires consistent connectivity, parameters and coordinates. The supplied PREP/frcmod files define six-site acetonitrile.

## Task
Build and validate neutral naphthalene in the supplied solvent.

## Requirements

- Environment: use the container Python on `PATH`; required scientific packages are preinstalled. Do not install additional packages or fetch dependencies from the network.

Use neutral singlet C10H8, AM1-BCC/GAFF, and supplied ch3cn.prep/frcmod. Build one 18-atom naphthalene plus 1,680 acetonitrile molecules in a 56 Å cubic box (10,098 atoms; packing need not be unique). Validate mapping, connectivity, all bonded/nonbonded terms, charge, periodic coordinates, intermolecular clashes, and finite initial energy/forces; resolve missing parameters/packing errors, explain warnings and retain actual build evidence. Read supplied XYZ/parameters. Write system.prmtop, matching inpcrd/PDB, solute mol2/parameters, native logs, model.json and analysis.md in /app/final/. Public output-contract defines model fields/units; CLI must build from inputs in a clean directory.

The command-line rebuild is a reproducibility requirement. Automated checks validate the submitted artifacts and do not replay this task’s build command.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/inputs/` | Solute geometry and solvent parameters. |
| `/app/output-contract.yaml` | Output format and evidence requirements. |

/app/inputs/: geometry/parameters; /app/output-contract.yaml: model contract; /app/final/: model and evidence.
