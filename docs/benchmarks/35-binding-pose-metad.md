# Open Binding Pose Metadynamics

## Overview

This benchmark is based on the study "**Open Binding Pose Metadynamics: An Effective Approach for the Ranking of Protein–Ligand Binding Poses**" by Dominykas Lukauskis et al., published in *Journal of Chemical Information and Modeling* (2022).

The study presents Open Binding Pose Metadynamics for evaluating and ranking protein–ligand binding poses. Ligand displacement and contact persistence under metadynamics bias provide measures of pose stability beyond a single static structure. The central question is how enhanced sampling can distinguish plausible binding poses and improve pose ranking.

**Reference:** Dominykas Lukauskis et al., *Journal of Chemical Information and Modeling*, 2022. DOI: [10.1021/acs.jcim.2c01142](https://doi.org/10.1021/acs.jcim.2c01142).

## Tasks

| Task | Description |
| --- | --- |
| Task 226 | Compute trajectory contact persistence, ligand displacement and composite pose-stability scores. |
| Task 227 | Specify a metadynamics protocol and assess Gaussian hill-height choices using source evidence. |
| Task 228 | Calculate multi-replica ensemble statistics and finite-trajectory convergence diagnostics. |
| Task 229 | Rerank poses across targets and perform paired statistical comparisons. |
| Task 230 | Compare MM-GBSA and OpenBPMD ranking performance and examine bounded failure explanations. |
