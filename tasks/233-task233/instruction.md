# Short NVT Ti Off-Centering and Observation Identifiability

## Background

In BaTiO3 the Ti ion sits off-centre within its oxygen cage, and the direction of that off-centre displacement is the local order parameter. The supplied records are four short NVT runs at 20, 80, 130 and 250 K, each with 11 sampled frames of a 320-atom cell (64 Ti, 64 Ba, 192 O) and the matching property output and input template.

The trajectories include cell and Step metadata; the matching property tables report step, time, potential energy and kinetic temperature. A run input template is supplied for each temperature.

## Task

For every actual Ti/frame, apply cubic periodic boundary conditions and average the six nearest O relative vectors; the negative centroid is the Ti off-centre displacement. Retain all 4x11x64 vectors. Assign each displacement the nearest of the eight normalized <111> sign-vector labels, treating a magnitude at or below the resolution as invalid.

Choose `resolution_A` in [0.01, 0.2] and `residence_frames` in 1..3, and report the selected observation summary for each temperature.

## Requirements

- Assess all thresholds 0.02/0.05/0.1/0.2 Angstrom plus your chosen threshold, strides 1/2/3, and residences 1/2/3 consecutive sampled frames.
- Invalid gaps reset the run and the accepted state; confirm a new label only after the chosen residence; never count the initial accepted state as a change.
- Keep labels, all eligible and invalid denominators, occupancies and sampled-change counts for every temperature.
- Verify each properties file against its target temperature. The XML temperature entry is an unresolved template and its planned 100000 steps do not establish 200 ps of coverage in these observations.
- These observations do not establish equilibrium, an independent sample count, a physical hopping rate, completion of the planned 200 ps, or a unique order-disorder/displacive mechanism. Extra latent label excursions used in identifiability reasoning are not simulated physical evidence.
- Use a numerical tolerance of atol 2e-7 + rtol 2e-6, which is arithmetic agreement, not physical uncertainty; integer labels/counts and full denominators must be exact.

Submit the results according to the listed output convention.

The specified results can be reproduced with:

```
python3 /app/public/replay.py --inputs /app/inputs --spec /app/public/example-spec.json --out /app/final
```

## Files

| Path | Description |
| --- | --- |
| `/app/inputs/` | Supplied trajectories, property records and input templates. |
| `/app/final/` | Submitted results and required execution evidence. |
| `/app/public/README.md` | Calculation methods and result-submission requirements. |
