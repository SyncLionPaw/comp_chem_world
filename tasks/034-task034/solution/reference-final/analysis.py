#!/usr/bin/env python3
"""Deterministic analysis of new WT/A2 N130-rpL5 trajectories.

Reads run_metadata.json plus the native topology and LAMMPS text dumps in the
current directory, and writes analysis/ outputs.  No random numbers are used
beyond a fixed atom-subset selection seed.
"""
import csv
import json
import math
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree

A2_TYPES = (33, 34, 35, 37, 39, 40, 41, 42, 43)
RPL5_MIN, RPL5_MAX = 44, 60
T975_DF2 = 4.302652729911275


def parse_data(path):
    lines = Path(path).read_text().splitlines()
    i = lines.index('Atoms') + 2
    ids, mol, typ, charge, pos = [], [], [], [], []
    while i < len(lines) and lines[i].strip() and not lines[i].startswith(('Bonds', 'Velocities')):
        p = lines[i].split()
        if len(p) >= 7:
            ids.append(int(p[0])); mol.append(int(p[1])); typ.append(int(p[2]))
            charge.append(float(p[3])); pos.append([float(x) for x in p[4:7]])
        i += 1
    return dict(id=np.asarray(ids), mol=np.asarray(mol), type=np.asarray(typ),
                charge=np.asarray(charge), pos=np.asarray(pos))


def parse_dump(path):
    text = Path(path).read_text().splitlines()
    frames, i = [], 0
    while i < len(text):
        if not text[i].startswith('ITEM: TIMESTEP'):
            i += 1
            continue
        step = int(text[i + 1]); i += 2
        n = int(text[i + 1]); i += 2
        box = []
        for j in range(3):
            lo, hi = map(float, text[i + 1 + j].split()[:2]); box.append([lo, hi])
        i += 4
        cols = text[i].split()[2:]; i += 1
        arr = np.asarray([text[i + k].split() for k in range(n)], dtype=float); i += n
        ci = {c: j for j, c in enumerate(cols)}
        key = 'xu' if 'xu' in ci else 'x'
        frames.append(dict(
            step=step, box=np.asarray(box),
            id=arr[:, ci['id']].astype(np.int64),
            mol=arr[:, ci['mol']].astype(np.int64),
            type=arr[:, ci['type']].astype(np.int64),
            pos=arr[:, ci[key]:ci[key] + 3]))
    return frames


def pd_molecules(mol):
    uniq, counts = np.unique(mol, return_counts=True)
    return uniq[counts > 100]


def wrap(pos, lo, lengths):
    return (pos - lo) % lengths


def rg_values(pos, mol, pd_ids):
    values = []
    for m in pd_ids:
        p = pos[mol == m]
        c = p.mean(axis=0)
        values.append(float(np.sqrt(np.mean(np.sum((p - c) ** 2, axis=1)))))
    return np.asarray(values)


def inter_chain_rdf(pos, mol, box, lo, subset, rmax=30.0, dr=0.5):
    p = wrap(pos[subset], lo, np.asarray(box))
    m = mol[subset]
    pairs = cKDTree(p, boxsize=np.asarray(box)).query_pairs(rmax, output_type='ndarray')
    nb = int(rmax / dr)
    edges = np.arange(nb + 1) * dr
    if len(pairs) == 0:
        return edges[:-1] + dr / 2, np.zeros(nb), 0.0
    keep = m[pairs[:, 0]] != m[pairs[:, 1]]
    pairs = pairs[keep]
    if len(pairs) == 0:
        return edges[:-1] + dr / 2, np.zeros(nb), 0.0
    d = p[pairs[:, 1]] - p[pairs[:, 0]]
    d -= np.asarray(box) * np.round(d / np.asarray(box))
    r = np.linalg.norm(d, axis=1)
    hist, _ = np.histogram(r, bins=nb, range=(0, rmax))
    _, counts = np.unique(m, return_counts=True)
    possible = len(m) * (len(m) - 1) - np.sum(counts * (counts - 1))
    shell = 4 * np.pi / 3 * (edges[1:] ** 3 - edges[:-1] ** 3)
    volume = float(np.prod(box))
    g = hist / (possible / 2) / (shell / volume)
    coord = 2.0 * float(np.sum(r < 12.0)) / len(m)
    return edges[:-1] + dr / 2, g, coord


def a2_rpl5_contacts(pos, typ, box, lo, cutoff=12.5):
    a2 = np.isin(typ, A2_TYPES)
    rp = (typ >= RPL5_MIN) & (typ <= RPL5_MAX)
    pa = wrap(pos[a2], lo, np.asarray(box))
    pr = wrap(pos[rp], lo, np.asarray(box))
    counts = cKDTree(pr, boxsize=np.asarray(box)).query_ball_point(pa, cutoff, return_length=True)
    return counts


def parse_log(path):
    rows = []
    header = None
    for line in Path(path).read_text().splitlines():
        parts = line.split()
        if len(parts) >= 6 and parts[0] == 'Step':
            header = parts
        elif header and parts and parts[0].isdigit() and len(parts) >= 6:
            try:
                vals = [float(x) for x in parts]
            except ValueError:
                continue
            if len(vals) == len(header):
                rows.append(dict(zip(header, vals)))
    return rows


def mean_ci(values):
    arr = np.asarray(values, dtype=float)
    mean = float(arr.mean())
    if len(arr) < 2:
        return mean, mean, mean, 0.0
    sem = float(arr.std(ddof=1) / math.sqrt(len(arr)))
    half = T975_DF2 * sem
    return mean, mean - half, mean + half, sem


def fmt(x):
    return f'{x:.10g}'


def main():
    meta = json.loads(Path('run_metadata.json').read_text())
    out = Path('analysis'); out.mkdir(exist_ok=True)
    topo = parse_data(meta['topology'])
    pd_ids = pd_molecules(topo['mol'])
    subset_rng = np.random.default_rng(meta.get('rdf_subset_seed', 20261027))
    pd_idx = np.where(np.isin(topo['mol'], pd_ids))[0]
    if len(pd_idx) > meta.get('rdf_subset', 2000):
        pd_idx = np.sort(subset_rng.choice(pd_idx, size=meta['rdf_subset'], replace=False))

    structure_rows = []
    contact_rows = []
    rdf_summary = {}
    diagnostics = {'conditions': {}, 'sampling': {}, 'limitations': []}
    for condition, spec in meta['conditions'].items():
        rgs, coords, contact_means = [], [], []
        g_stack = []
        frame_count = 0
        for seed, traj in zip(spec['seeds'], spec['trajectories']):
            frames = parse_dump(traj)
            used = [f for f in frames if spec['start_step'] <= f['step'] <= spec['end_step']]
            if not used:
                raise SystemExit(f'no production frames for {condition} seed {seed}')
            seed_rg, seed_coord, seed_contacts, seed_g = [], [], [], []
            for f in used:
                box = np.asarray(f['box'][:, 1] - f['box'][:, 0])
                lo = np.asarray(f['box'][:, 0])
                rg = rg_values(f['pos'], f['mol'], pd_ids)
                _, g, coord = inter_chain_rdf(f['pos'], f['mol'], box, lo, pd_idx,
                                              meta['rdf_rmax'], meta['rdf_dr'])
                c = a2_rpl5_contacts(f['pos'], f['type'], box, lo, meta['a2_cutoff'])
                structure_rows.append([condition, seed, f['step'], fmt(float(rg.mean())),
                                       fmt(float(rg.std(ddof=1))), fmt(coord)])
                contact_rows.append([condition, seed, f['step'], fmt(float(c.mean())),
                                     str(int(c.sum())), str(len(c))])
                seed_rg.append(float(rg.mean())); seed_coord.append(coord)
                seed_contacts.append(float(c.mean())); seed_g.append(g)
                frame_count += 1
            rgs.append(float(np.mean(seed_rg)))
            coords.append(float(np.mean(seed_coord)))
            contact_means.append(float(np.mean(seed_contacts)))
            g_stack.append(np.mean(seed_g, axis=0))
            log = parse_log(spec['logs'][spec['seeds'].index(seed)])
            prod = [r for r in log if spec['start_step'] <= r.get('Step', -1) <= spec['end_step']]
            if prod:
                pe = np.asarray([r.get('PotEng', r.get('PE', 0.0)) for r in prod])
                temp = np.asarray([r.get('Temp', 0.0) for r in prod])
                diagnostics['conditions'].setdefault(condition, []).append({
                    'seed': seed, 'frames': len(used), 'production_steps': len(prod),
                    'pe_mean': float(pe.mean()), 'pe_std': float(pe.std(ddof=1)) if len(pe) > 1 else 0.0,
                    'temp_mean': float(temp.mean()), 'temp_std': float(temp.std(ddof=1)) if len(temp) > 1 else 0.0,
                    'pe_drift_per_step': float(np.polyfit(np.arange(len(pe)), pe, 1)[0]) if len(pe) > 1 else 0.0,
                })
        g_mean = np.mean(np.stack(g_stack), axis=0)
        rdf_summary[condition] = g_mean.tolist()
        diagnostics['sampling'][condition] = {'seeds': spec['seeds'], 'frames': frame_count,
                                              'start_step': spec['start_step'], 'end_step': spec['end_step'],
                                              'production_time_ps': (spec['end_step'] - spec['start_step']) * 0.1 / 1000.0}

    r_wt = np.arange(int(meta['rdf_rmax'] / meta['rdf_dr'])) * meta['rdf_dr'] + meta['rdf_dr'] / 2
    with (out / 'pd_structure.csv').open('w', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(['condition', 'seed', 'step', 'rg_mean_A', 'rg_sd_A', 'interchain_coordination_12A'])
        w.writerows(structure_rows)
    with (out / 'a2_rpl5_contacts.csv').open('w', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(['condition', 'seed', 'step', 'contacts_per_a2', 'total_contacts', 'a2_atoms'])
        w.writerows(contact_rows)
    with (out / 'interchain_rdf.csv').open('w', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(['r_A', 'g_WT', 'g_A2'])
        for i, r in enumerate(r_wt):
            w.writerow([fmt(float(r)), fmt(float(rdf_summary['WT'][i])), fmt(float(rdf_summary['A2'][i]))])

    metrics = {}
    for name, key, unit in (('PD_radius_of_gyration', 'rg', 'A'),
                            ('PD_interchain_coordination_12A', 'coord', 'beads per PD bead'),
                            ('A2_rpL5_contacts_12p5A', 'contacts', 'rpL5 beads per A2 bead')):
        vals = {'WT': [], 'A2': []}
        for condition in ('WT', 'A2'):
            spec = meta['conditions'][condition]
            for seed, traj in zip(spec['seeds'], spec['trajectories']):
                frames = parse_dump(traj)
                used = [f for f in frames if spec['start_step'] <= f['step'] <= spec['end_step']]
                per = []
                for f in used:
                    box = np.asarray(f['box'][:, 1] - f['box'][:, 0]); lo = np.asarray(f['box'][:, 0])
                    if key == 'rg':
                        per.append(float(rg_values(f['pos'], f['mol'], pd_ids).mean()))
                    elif key == 'coord':
                        per.append(inter_chain_rdf(f['pos'], f['mol'], box, lo, pd_idx,
                                                   meta['rdf_rmax'], meta['rdf_dr'])[2])
                    else:
                        c = a2_rpl5_contacts(f['pos'], f['type'], box, lo, meta['a2_cutoff'])
                        per.append(float(c.mean()))
                vals[condition].append(float(np.mean(per)))
        wt_mean, wt_lo, wt_hi, wt_sem = mean_ci(vals['WT'])
        a2_mean, a2_lo, a2_hi, a2_sem = mean_ci(vals['A2'])
        diff = a2_mean - wt_mean
        diff_se = math.sqrt(wt_sem ** 2 + a2_sem ** 2)
        diff_lo, diff_hi = diff - T975_DF2 * diff_se, diff + T975_DF2 * diff_se
        direction = 'supports_effect' if diff_lo > 0 or diff_hi < 0 else 'no_resolved_effect'
        metrics[name] = {'wt_mean': wt_mean, 'wt_ci': [wt_lo, wt_hi],
                         'a2_mean': a2_mean, 'a2_ci': [a2_lo, a2_hi],
                         'difference': diff, 'difference_ci': [diff_lo, diff_hi],
                         'difference_se': diff_se, 'unit': unit,
                         'direction': direction,
                         'wt_seed_values': vals['WT'], 'a2_seed_values': vals['A2']}
    summary = {'metrics': metrics, 'rdf': {'r_A': r_wt.tolist(), 'g_WT': rdf_summary['WT'], 'g_A2': rdf_summary['A2']},
               'sampling': diagnostics['sampling'], 'limitations': [
                   'Short production windows (reduced-sampling Oracle) cannot resolve long-time diffusion or full condensate convergence.',
                   'A2 equilibration after charge removal is monitored but not proven complete.',
                   'PD-chain spatial metrics use the author-equilibrated 108-chain configuration as the starting state; finite-size effects remain.']}
    (out / 'summary.json').write_text(json.dumps(summary, indent=2, sort_keys=True) + '\n')
    (out / 'diagnostics.json').write_text(json.dumps(diagnostics, indent=2, sort_keys=True) + '\n')
    print(json.dumps({'status': 'ok', 'metrics': list(metrics), 'frames': diagnostics['sampling']}, sort_keys=True))


if __name__ == '__main__':
    main()
