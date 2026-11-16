#!/bin/bash
set -euo pipefail
python3 - <<'PY'
import json
import os
import tempfile
from pathlib import Path

import numpy as np

FINAL = Path(os.environ.get("FINAL", "/app/final"))
ASSETS = Path(os.environ.get("ASSETS", "/app/environment/assets"))
FINAL.mkdir(parents=True, exist_ok=True)
SMILES = json.loads((ASSETS / "name_lookup.json").read_text(encoding="utf-8"))['2-acetoxybenzoic acid']

from rdkit import Chem

mol = Chem.MolFromSmiles(SMILES)
if mol is None:
    raise SystemExit(f"RDKit cannot parse {SMILES!r}")
(FINAL / "smiles.txt").write_text(Chem.MolToSmiles(mol) + "\n", encoding="utf-8")
PY
