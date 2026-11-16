#!/usr/bin/env python3
"""Read the campaign settings and native-style outputs to diagnose the EPC chains."""
from __future__ import annotations
import json, os, re, sys, tarfile, tempfile
from pathlib import Path


def parse_summary(text):
    fields = {}
    for key, pattern in {
        "lambda": r"lambda\s*=\s*([\d.]+)",
        "omega_log_cm1": r"omega_log \(cm-1\)\s*=\s*([\d.]+)",
        "tc_mu016_K": r"mu_star\s*=\s*0\.16\s*:\s*Tc\s*=\s*([\d.]+)",
    }.items():
        match = re.search(pattern, text)
        if match: fields[key] = float(match.group(1))
    return fields


def integrate_a2f(path):
    rows = [tuple(map(float, line.split()[:2])) for line in path.read_text().splitlines() if line.strip() and not line.lstrip().startswith("#")]
    return 2.0 * sum(0.5 * (y0 / w0 + y1 / w1) * (w1 - w0) for (w0, y0), (w1, y1) in zip(rows, rows[1:]))


def maximum_linewidth(path):
    rows = [line.split() for line in path.read_text().splitlines() if line.strip() and not line.lstrip().startswith("#")]
    values = [(float(row[2]), float(row[3])) for row in rows if len(row) >= 4]
    return max(values, key=lambda pair: pair[1])


def main() -> int:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "final-out").resolve(); out.mkdir(parents=True, exist_ok=True)
    asset = Path(os.environ.get("APP", "/app")) / "assets/epc-campaign.tar.gz"
    if not asset.is_file(): asset = Path(__file__).resolve().parents[1] / "environment/assets/epc-campaign.tar.gz"
    with tempfile.TemporaryDirectory() as td:
        with tarfile.open(asset) as archive: archive.extractall(td)
        root = Path(td) / "epc-campaign"
        settings = json.loads((root / "settings.json").read_text())["runs"]
        diagnoses = {}
        for run_id, cfg in settings.items():
            scf, post = cfg["scf"], cfg.get("post")
            pathologies = []
            scf_text = (root / f"{run_id.replace('-', '')}_scf.out").read_text() if (root / f"{run_id.replace('-', '')}_scf.out").exists() else ""
            if scf.get("converged") is not True or "convergence NOT achieved" in scf_text:
                pathologies.append("unconverged_scf")
            if float(scf.get("cell_height_z_A", 0)) < 15.0:
                pathologies.append("insufficient_vacuum")
            if post:
                baseline = settings["run-A"]["post"]
                if post.get("k_mesh_epw") and min(post["k_mesh_epw"]) < min(baseline["k_mesh_epw"]): pathologies.append("insufficient_k_mesh")
                if post.get("q_mesh_epw") and min(post["q_mesh_epw"]) < min(baseline["q_mesh_epw"]): pathologies.append("insufficient_q_mesh")
                if post.get("sk_ev") is not None and post["sk_ev"] > baseline["sk_ev"]: pathologies.append("excessive_smearing")
            observed = []
            if post and post.get("frequencies"):
                freq_path = root / post["frequencies"]
                gamma_rows = [line.split() for line in freq_path.read_text().splitlines()
                              if line.strip() and not line.lstrip().startswith("#")]
                gamma = next((row[2:] for row in gamma_rows if len(row) > 2 and float(row[0]) == 0.0 and float(row[1]) == 0.0), [])
                if gamma:
                    observed.append(f"Gamma frequencies={','.join(gamma)} cm-1")
            if post and post.get("lambda_summary"):
                post_text = (root / post["lambda_summary"]).read_text()
                for label, pattern in (("lambda", r"lambda[^=]*=\s*([0-9.]+)"),
                                       ("Tc_K", r"Tc\s*=\s*([0-9.]+)\s*K"),
                                       ("omega_log_cm1", r"omega_log \(cm-1\)\s*=\s*([0-9.]+)")):
                    match = re.search(pattern, post_text, re.I)
                    if match: observed.append(f"{label}={match.group(1)}")
            evidence = (f"SCF converged={scf.get('converged')}, cell height={scf.get('cell_height_z_A')} A; "
                        f"post-processing settings={json.dumps(post, sort_keys=True)}; "
                        f"observed outputs={' ; '.join(observed) or 'no downstream result'}; inferred pathologies={pathologies}.")
            diagnoses[run_id] = {"trustworthy": not pathologies, "pathologies": pathologies, "evidence": evidence}

        trustworthy = [key for key, value in diagnoses.items() if value["trustworthy"] and settings[key]["post"]]
        if not trustworthy: raise ValueError("no converged chain with EPC outputs is available")
        selected = trustworthy[0]
        selected_post = settings[selected]["post"]
        summary = parse_summary((root / selected_post["lambda_summary"]).read_text())
        lam_int = integrate_a2f(root / selected_post["a2f"])
        gamma_omega, gamma_max = maximum_linewidth(root / selected_post["linewidths"])
        extracted = {**summary, "lambda_from_a2f_dat": round(lam_int, 6), "gamma_max_meV": gamma_max,
                     "gamma_max_mode_omega_cm1": gamma_omega}
    result = {"runs": diagnoses, "selected_chain": selected, "extracted": extracted}
    (out / "diagnosis.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote evidence-derived diagnosis to {out / 'diagnosis.json'}")
    return 0

if __name__ == "__main__": raise SystemExit(main())
