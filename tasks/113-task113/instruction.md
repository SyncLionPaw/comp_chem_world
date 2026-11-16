# Task: Calculate LiFePO4 average intercalation voltage

## Background

The average lithium intercalation voltage of olivine LiFePO4 follows from the energy difference between lithiated and delithiated host, referenced to lithium metal. Consistent relaxation with one interatomic model makes the comparison internally consistent.

## Task

Using `CHGNet-PES-MatPES-PBE-2025.2.10`, calculate the average Li intercalation voltage of LiFePO4. Start from the supplied fully lithiated cathode and Li-metal structures; construct the empty host by removing Li.

## Requirements

- Environment: use the container Python on `PATH`. Preinstalled packages include ASE, MatGL, NumPy, pymatgen, SciPy. Do not install additional packages or fetch dependencies from the network.

Relax the full cathode, generated empty host and Li-metal reference with the same model. Derive all energies from those relaxations, not tabulated values. Report voltage in V, lithium chemical potential in eV per atom, full-minus-empty cathode energy difference in eV, and the total Li-metal contribution in eV consistently. Use the standard average-voltage relation for transferring the number of Li removed between cathode and metal reference. Do not use task-specific external solutions.

The absolute tolerances are 0.02 V for voltage, 0.01 eV per atom for Li chemical potential, 0.08 eV for the full-minus-empty energy difference, and 0.04 eV for the metal contribution. Each comparison uses the larger of that tolerance and 1e−5 times the absolute reference value.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/inputs/lifepo4.cif` | lithiated cathode. |
| `/app/inputs/li_metal.cif` | metal reference. |

**Deliverables**

Write `/app/final/voltage_results.json`. A compact JSON object or short text report is acceptable if each value has an unambiguous label and unit. For JSON, the preferred structure is:

```text
{
  "voltage_V": <number>,
  "mu_metal_eV": <number>,
  "energy_difference_eV": <number>,
  "metal_contribution_eV": <number>
}
```

Time budget: 1,800 s.
