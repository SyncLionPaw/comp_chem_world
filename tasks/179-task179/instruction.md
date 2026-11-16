# Task: Generate an isolated water molecule

## Background

Create a neutral, isolated H₂O molecule with a near-equilibrium geometry. Python 3.12’s standard library is sufficient; this task does not require DFT or simulation.

Follow the descriptions below for inputs and available resources; independently acquire materials where required.

## Task

Provide the molecular geometry and a small script that regenerates it.

## Requirements

- Environment: use the container Python on `PATH`; required scientific packages are preinstalled. Do not install additional packages or fetch dependencies from the network.

Use exactly one O and two H atoms with finite Cartesian coordinates in Å. Each O–H distance must be within 0.060 Å of the trusted equilibrium reference, and the H–O–H angle must be within 6.0°. Any coordinate frame or H ordering is acceptable. The generator must reproduce the submitted bond lengths and angle within 1e-6 Å and 1e-6°, respectively.

### Input and deliverable details

- final/water.xyz: standard XYZ with atom count, comment line, and three atom rows.
- final/generate_water.py: self-contained Python script; python generate_water.py must write water.xyz in the current directory from any working directory. Use only the standard library.

## Files

Public input files:

| File path | Description |
| --- | --- |
| — | No predefined research data are supplied. |

| Path | Contents |
| --- | --- |
| `/app/final` | Required result; use the contents and format specified above. |
