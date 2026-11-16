"""Author-only reference solution. Does not read private labels or call the grader."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile

import numpy as np

PKG = Path(__file__).resolve().parent.parent
CASE = os.environ.get('CASE_ID', 'case-02')
VERSION = 'af615ce0e81bbb860e77923762c505567affa8d1; bundled explicit tensor dispatch adapter'


def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def write_json(p, obj):
    p.write_text(json.dumps(obj, indent=2, allow_nan=False) + '\n')


def read_xyz(p):
    frames = []
    with p.open() as f:
        while True:
            line = f.readline()
            if not line:
                break
            n = int(line)
            comment = f.readline().strip()
            rows = [f.readline().split() for _ in range(n)]
            frames.append(([a[0] for a in rows], np.array([[float(x) for x in a[1:4]] for a in rows]), comment))
    return frames


def write_xyz(p, frames, mu=None, alpha=None):
    with p.open('w') as f:
        for k, (species, xyz, comment) in enumerate(frames):
            if mu is not None:
                comment += ' dipole="' + ' '.join(format(v, '.17g') for v in mu[k]) + '"'
                comment += ' polarizability="' + ' '.join(format(v, '.17g') for v in alpha[k].reshape(-1)) + '"'
            f.write(str(len(species)) + '\n' + comment + '\n')
            for symbol, pos in zip(species, xyz):
                f.write(symbol + ' ' + ' '.join(format(v, '.17g') for v in pos) + '\n')


def solve(inputs, out, work):
    source = Path(os.environ.get('NEP_SOURCE_ROOT', str(PKG / 'environment/assets/vendor/nep-runtime'))).resolve()
    exe = work / 'nep_predict'
    compiler = shlex.split(os.environ.get('CXX', 'g++'))
    cmd = compiler + ['-O2', '-std=c++14', '-I' + str(source / 'src'), '-o', str(exe)]
    cmd += [str(source / name) for name in ['predict.cpp', 'src/nep.cpp', 'src/neighbor_nep.cpp', 'src/ewald_nep.cpp']]
    with (out / 'build.log').open('w') as log:
        log.write('SDKROOT=' + os.environ.get('SDKROOT', '(compiler default)') + '\n')
        log.write('command=' + shlex.join(cmd) + '\n'); log.flush()
        subprocess.run(compiler + ['--version'], stdout=log, stderr=log, check=True)
        subprocess.run(cmd, stdout=log, stderr=log, check=True)
        log.write('exit=0\n')
    engine = {'name': 'NEP_CPU', 'version': VERSION, 'precision': 'float64', 'build_command': shlex.join(cmd)}

    def predict(model, xyz, mode, label):
        model = inputs / model
        txt = work / (label + '.txt')
        runtime_model = model
        if mode == 'polarizability':
            # Upstream model files use plain nep4; NEP_CPU requires explicit
            # polarizability dispatch. Change only the type token in a temp copy.
            original = model.read_bytes()
            token = original.split(None, 1)[0]
            if token == b'nep4':
                runtime_model = work / (model.name + '.polarizability')
                adapted = b'nep4_polarizability' + original[len(token):]
                assert adapted[len(b'nep4_polarizability'):] == original[len(token):]
                runtime_model.write_bytes(adapted)
            elif token != b'nep4_polarizability':
                raise ValueError('Unexpected polarizability model header: ' + repr(token))
        command = [str(exe), str(runtime_model), str(xyz), mode, str(txt)]
        with (out / 'run.log').open('a') as log:
            log.write('run=' + label + '\nmodel_sha256=' + digest(model) + '\ninput_sha256=' + digest(xyz) + '\ncommand=' + shlex.join(command) + '\n'); log.flush()
            log.write('runtime_model_sha256=' + digest(runtime_model) + '\n'); log.flush()
            subprocess.run(command, stdout=log, stderr=log, check=True)
            log.write('exit=0\n')
        a = np.loadtxt(txt, ndmin=2)
        assert np.isfinite(a).all()
        return a

    if CASE in ('case-01', 'case-02'):
        if CASE == 'case-01':
            rows = [('h2o', 'water_monomer', 'h2o'), ('h2o_dimer', 'water_dimer', 'h2o-dimer'), ('h5o2plus', 'water_zundel', 'h5o2plus'), ('liquid_water', 'bulk_water', 'liquid-water')]
            jobs = [(key, 'nep_dipole_' + model + '.txt', 'test-positions-' + xyz + '.xyz', 'dipole') for key, model, xyz in rows]
            conventions = {'h5o2plus': 'relative-to-COM', 'liquid_water': 'per-molecule (cell dipole / 32)'}
        else:
            rows = [('alpha_h2o', 'water_monomer', 'alpha-h2o'), ('alpha_h2o_dimer', 'water_dimer', 'alpha-h2o-dimer'), ('alpha_h5o2plus', 'water_zundel', 'alpha-h5o2plus')]
            jobs = [(key, 'nep_polarizability_' + model + '.txt', 'test-positions-' + xyz + '.xyz', 'polarizability') for key, model, xyz in rows]
            jobs += [('qm7b_dipole', 'nep_dipole_QM7B.txt', 'test-positions-qm7b-dipole.xyz', 'dipole'), ('qm7b_polarizability', 'nep_polarizability_QM7B.txt', 'test-positions-qm7b-polarizability.xyz', 'polarizability')]
            conventions = {'molecular_polarizability': 'molecule totals in bohr^3, row-major symmetric tensors', 'offdiag': 'independent xy,xz,yz; bundled adapter maps six NEP components to symmetric nine-component tensors', 'qm7b': 'per-atom error reporting; stored predictions are molecule totals'}
        paths = {}
        for key, model, xyz, mode in jobs:
            arr = predict(model, inputs / xyz, mode, key)
            if key == 'liquid_water':
                arr = arr / 32
            n = 1443 if key.startswith('qm7b') else 500
            assert arr.shape == (n, 3 if mode == 'dipole' else 9), (key, arr.shape)
            paths[key] = 'pred-' + key + '.npz'
            np.savez(out / paths[key], **{mode: arr})
        engine['log_sha256'] = {name: digest(out / name) for name in ('build.log', 'run.log')}
        write_json(out / 'results.json', {'engine': engine, 'conventions': conventions, 'predictions': paths})
        return

    frames = read_xyz(inputs / 'test-positions-h2o-200.xyz')
    assert len(frames) == 200
    rng = np.random.default_rng(615)
    rotations = []
    rotated = []
    for species, xyz, comment in frames:
        axis = rng.normal(size=3); axis /= np.linalg.norm(axis)
        angle = rng.uniform(0.3, np.pi)
        x, y, z = axis
        skew = np.array([[0, -z, y], [z, 0, -x], [-y, x, 0]])
        R = np.eye(3) + np.sin(angle) * skew + (1 - np.cos(angle)) * (skew @ skew)
        rotations.append(R)
        rotated.append((species, xyz @ R.T, comment))
    rotated_path = out / 'rotated-positions.xyz'
    write_xyz(rotated_path, rotated)
    arrays = {}
    for label, xyz in [('unrotated', inputs / 'test-positions-h2o-200.xyz'), ('rotated', rotated_path)]:
        mu = predict('nep_dipole_water_monomer.txt', xyz, 'dipole', label + '-dipole')
        alpha = predict('nep_polarizability_water_monomer.txt', xyz, 'polarizability', label + '-polarizability')
        assert mu.shape == (200, 3) and alpha.shape == (200, 9)
        arrays[label] = (mu, alpha.reshape(-1, 3, 3))
        write_xyz(out / ('inference-' + label + '.xyz'), frames if label == 'unrotated' else rotated, mu, alpha)
    mu_u, al_u = arrays['unrotated']; mu_r, al_r = arrays['rotated']; R = np.array(rotations)
    expected_mu = np.einsum('fij,fj->fi', R, mu_u)
    expected_alpha = R @ al_u @ R.transpose(0, 2, 1)
    dm = np.abs(expected_mu - mu_r); da = np.abs(expected_alpha - al_r) / (np.abs(expected_alpha) + 1e-12)
    log = (out / 'run.log').read_text() + '\nrun=unrotated\nrun=rotated\n'
    for key, p in [('input_sha256', inputs / 'test-positions-h2o-200.xyz'), ('rotated_xyz_sha256', rotated_path), ('inference_unrotated_sha256', out / 'inference-unrotated.xyz'), ('inference_rotated_sha256', out / 'inference-rotated.xyz')]:
        log += key + '=' + digest(p) + '\n'
    (out / 'inference.log').write_text(log)
    engine['log_sha256'] = digest(out / 'inference.log')
    write_json(out / 'equivariance.json', {'engine': engine, 'rotation_protocol': {'seed': 615, 'distribution': 'isotropic normal axis, uniform angle in [0.3, pi), origin-centered', 'n_rotations': 200, 'center': 'origin'}, 'frames': [{'frame': k, 'R': R[k].tolist(), 'mu_unrotated': mu_u[k].tolist(), 'mu_rotated': mu_r[k].tolist(), 'alpha_unrotated': al_u[k].reshape(-1).tolist(), 'alpha_rotated': al_r[k].reshape(-1).tolist()} for k in range(200)], 'residual_summary': {'max_abs_mu': float(dm.max()), 'rms_mu': float(np.sqrt(np.mean(dm**2))), 'max_rel_alpha': float(da.max()), 'rms_alpha': float(np.sqrt(np.mean(da**2)))}})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    if out.exists() and any(out.iterdir()):
        raise SystemExit('Output must be empty; reference solution never overwrites an existing submission.')
    out.mkdir(parents=True, exist_ok=True)
    inputs = Path(os.environ.get('INPUT_ROOT', str(PKG / 'environment/assets/inputs'))).resolve()
    with tempfile.TemporaryDirectory(prefix='bench20-reference-') as temp:
        solve(inputs, out, Path(temp))


if __name__ == '__main__':
    main()
