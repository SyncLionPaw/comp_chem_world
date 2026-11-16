# DeepVES Variational Enhanced Sampling

## Overview

This benchmark is based on the study "**Neural networks-based variationally enhanced sampling**" by Luigi Bonati, Yue-Yu Zhang and Michele Parrinello, published in *Proceedings of the National Academy of Sciences* (2019).

The study investigates variationally enhanced sampling with neural-network bias potentials. A variational objective adapts flexible biases to accelerate exploration of complex free-energy landscapes. The central question is how neural representations improve sampling while maintaining a well-defined statistical target. The tasks distinguish static reconstruction and archived-data analysis from fresh dynamical evidence.

**Reference:** Luigi Bonati, Yue-Yu Zhang and Michele Parrinello, *Proceedings of the National Academy of Sciences*, 2019. DOI: [10.1073/pnas.1907975116](https://doi.org/10.1073/pnas.1907975116).

## Tasks

| Task | Description |
| --- | --- |
| Task 49 | Optimise a static variational bias on the Wolfe–Quapp potential. |
| Task 50 | Analyse archived online VES trajectories and bias-coefficient histories. |
| Task 51 | Reconstruct a frozen alanine-dipeptide NN-VES checkpoint. |
| Task 52 | Analyse model-space expectations and Metropolis transitions in archived chains. |
| Task 53 | Compute static mechanical quantities for silicon snapshots under frozen neural biases. |
| Task 54 | Diagnose evidence relationships and information limits in anonymised DeepVES records. |
