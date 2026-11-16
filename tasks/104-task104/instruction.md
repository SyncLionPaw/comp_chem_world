# Task: Evaluate site-resolved Li K-edge spectra and local environments

## Background

Core-hole VASP calculations are supplied for Li4Ti5O12, Li5Ti5O12, Li6Ti5O12 and Li7Ti5O12 (8, 10, 12 and 14 substituted sites). Each site has a projected-DOS `vasprun.xml.gz` and a POSCAR marking the Be core-hole center, with shared calculation inputs.

## Task

Reconstruct the site-resolved Li K-edge spectra and assess whether intermediate-lithiation sites support an additional feature near 58 eV. Base any structural assignment on spectra, periodic local geometry and end-member comparisons; treat it as a hypothesis rather than a unique identification.

## Requirements

Sum Be p-projected DOS over px, py, pz and both spins, reference energy to the Fermi level, and apply Gaussian broadening with 0.5 eV FWHM. For each composition, sum unnormalized site spectra, shift the total main peak to 61.5 eV, then normalize each shifted site curve to its maximum in 56–67 eV.

From each POSCAR, use periodic geometry about Be. Count O within 2.75 Å, report nearest Be–Li distance and, for six-coordinate sites, the six shortest Be–O distances in ascending order and `d=(1/6)Σ|l_i-l_av|/l_av`. Below coordination six, report the actual coordination and set the six-distance list and distortion to `null`. For each composition include a regular six-coordinate comparison site with `d<0.06`, nearest Be–Li `>2.60 Å`, and no local maximum at 57.5–58.6 eV. Evaluate any intermediate-composition assignment using the spectra, geometry and end members together; a shoulder or one descriptor alone is insufficient.

Write `/app/final/results.json`: `spectra` must contain every site under Li4–Li7, each with aligned `energy_eV` and `intensity` arrays. In `assignment`, include `sites_with_extra_prepeak` keyed by composition, `present_in_endmembers` (boolean), a concise `site_description`, and a `site_geometry_evidence` array of records `{composition, site, coordination, nearest_li_A, six_li_o_A, distortion_index}` for candidates and at least one six-coordinate comparison site per composition. Use `null` for the distance list and distortion when coordination is below six. Write `/app/final/methods.md` describing the projection and evidence.

For a candidate site, require six O neighbors, distortion index ≥0.06, longest of the six Be–O bonds ≥2.34 Å, nearest Be–Li ≤2.60 Å, and a resolved local maximum in 57.5–58.6 eV. Explain how the evidence bears on a distorted, face-sharing 16c assignment without treating it as unique.

## Files

Public input files:

| File path | Description |
| --- | --- |
| `/app/assets/` | Site-resolved VASP spectra and structures for Li4–Li7. |

Read every site input under `/app/assets/Li4` through `/app/assets/Li7`, including each site’s `vasprun.xml.gz` and POSCAR and the composition-level INCAR/KPOINTS. Submit `/app/final/results.json` and `/app/final/methods.md`.
