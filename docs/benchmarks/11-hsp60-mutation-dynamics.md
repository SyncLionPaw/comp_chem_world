# Hsp60 Mutation Dynamics

## Overview

This benchmark is based on the study "**Pathogenic mutation impairs functional dynamics of Hsp60 in mono- and oligomeric states**" by Luca Torielli et al., published in *Nature Communications* (2025).

The study investigates the pathogenic V72I mutation of the Hsp60 chaperonin across monomeric and oligomeric assemblies. Molecular dynamics and structural analyses connect protein flexibility, allosteric communication, and catalytic aspartate protonation. The central question is how a local mutation reorganises motions and catalytic geometry across larger functional complexes.

**Reference:** Luca Torielli et al., *Nature Communications*, 2025. DOI: [10.1038/s41467-025-57958-5](https://doi.org/10.1038/s41467-025-57958-5).

## Tasks

| Task | Description |
| --- | --- |
| Task 70 | Analyse WT/V72I monomer flexibility and allosteric communication. |
| Task 71 | Assess structure-dependent protonation of the Asp50/Asp397 catalytic dyad. |
| Task 72 | Analyse residue-correlation and distance matrices with consistent residue numbering. |
| Task 73 | Compare catalytic geometry across assembly and ligand/protonation conditions. |
| Task 74 | Relate catalytic-dyad geometry to apical conformations in double-ring and football assemblies. |
| Task 75 | Investigate proton-exchange barriers in small catalytic-dyad models with and without bridging water. |

Prepare the shared connectivity image once per required architecture using the
[base-image instructions](../compchembench/README.md#配置并构建-hpc-镜像).
Tasks 70–74 use ARM64; task 75 uses the AMD64 variant. Harbor builds each task
image from its environment on first run. If a required input is stored in Git
LFS, fetch it before running; see the [repository instructions](../README.md).

## Environment repair note (2026-11)

Tasks 071–074 use the native Linux architecture, with same-version offline runtime tools for ARM64 and AMD64. Task 072 derives chroot library paths from Python MULTIARCH. See [environment repairs and oracle checks](environment-repairs.md).
