#!/usr/bin/env bash
# Run after uv run init, on the same Docker daemon used by Harbor.
set -euo pipefail

repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo_root"
command -v docker >/dev/null || { echo 'Docker is required.' >&2; exit 1; }
docker info >/dev/null
for store in wheelhouse asset-store; do
    test -f "shared/$store/.restore-state.json" || {
        echo 'Run uv run init before prebuilding task environments.' >&2
        exit 1
    }
done

# Build serially so downloads and scientific package compilation do not compete
# with agent trials. Harbor reuses these layers on the same Docker daemon.
for task in 042 061 071 072 073 074 110 112 113; do
    context="tasks/$task-task$task/environment"
    image="comp-chem-world-repair-$task:local"
    docker build --progress=plain --tag "$image" "$context"
    case "$task" in
        042) check='import torch, deepmd; assert torch.version.cuda is None' ;;
        061) check='import amset, joblib, BoltzTraP2' ;;
        071) check='import numpy, scipy, parmed, propka' ;;
        072|074) check='import numpy, scipy, matplotlib' ;;
        073) check='import numpy, pandas' ;;
        110) check="from mace.calculators import mace_off; mace_off(model='small', device='cpu', default_dtype='float64')" ;;
        112) check="from mace.calculators import mace_mp; mace_mp(model='mace-matpes-pbe-0', device='cpu')" ;;
        113) check="import matgl; matgl.load_model('CHGNet-PES-MatPES-PBE-2025.2.10')" ;;
    esac
    docker run --rm --network none --entrypoint python "$image" -c "$check"
done
