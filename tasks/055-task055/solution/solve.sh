#!/usr/bin/env bash
set -euo pipefail
app_root="${APP:-/app}"
output_dir="$app_root/final"
mkdir -p "$output_dir"
exec python3 - --inputs "$app_root/environment/assets" --output "$output_dir" <<'CCB_ANALYSIS'
"""Reference quadrature using only the public kernel and input parameters."""
import argparse
import json
from pathlib import Path
import numpy as np

parser = argparse.ArgumentParser()
parser.add_argument('--inputs', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
params = json.loads((args.inputs / 'author/inputs/elastic-angular.json').read_text())
args.output.mkdir(parents=True, exist_ok=True)
grids = [np.polynomial.legendre.leggauss(n) for n in (256, 512)]
result = {'rows': [], 'strongest_forward_a': min(params['screening_parameters']), 'elastic_only': True}
quad = {'rows': []}
for a in params['screening_parameters']:
    levels = [{'nodes': x.tolist(), 'weights': w.tolist()} for x, w in grids]
    x, w = grids[-1]
    kernel = (1 - x + a)**-2
    s = float(np.dot(w, kernel)/2)
    m = float(np.dot(w, (1-x)*kernel)/2)
    result['rows'].append({'a': a, 'serta_rate': s, 'mrta_rate': m, 'rate_ratio': m/s})
    quad['rows'].append({'a': a, 'levels': levels})
(args.output / 'results.json').write_text(json.dumps(result)+'\n')
(args.output / 'quadratures.json').write_text(json.dumps(quad)+'\n')
CCB_ANALYSIS
