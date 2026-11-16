"""New private reference implementation; the removed original is unavailable.

Compute Case 03 deliverables from public assets. No cached predictions are read.
"""
from __future__ import annotations

import json
import platform
from pathlib import Path

import numpy as np
import pandas as pd
import sklearn

from fit import predict_declared

ASSETS = Path('/app/assets')
OUT = Path('/app/final')
FILES = {
    'mechanistic': 'SC-012-D0SC04896H-s120.csv',
    'no_ts': 'SC-012-D0SC04896H-s138.csv',
    'fingerprint': 'SC-012-D0SC04896H-s131.csv',
}
SIZES = [32, 96, 192, 354]
REPEATS = 20
CV_SEED = 1729
SEED_POLICY = {
    'sampling': 'numpy.default_rng(31000 + 100*n_train + repeat_index); choice without replacement',
    'inner_cv': 'KFold(3, shuffle=True, random_state=1729) on ordered sampled rows',
    'full_pool': 'use all frozen training indices in released order',
}


def write_json(name, value):
    (OUT / name).write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    target_frame = pd.read_csv(ASSETS / 'SC-012-D0SC04896H-s115.csv', index_col=0)
    y = target_frame['exp_activation_energy'].to_numpy(dtype=float)
    pool = np.load(ASSETS / 'SC-012-D0SC04896H-s119.npy', allow_pickle=False).astype(int)
    test = np.load(ASSETS / 'SC-012-D0SC04896H-s118.npy', allow_pickle=False).astype(int)
    assert len(y) == 443 and len(pool) == 354 and len(test) == 89
    assert len(set(pool)) == 354 and len(set(test)) == 89
    assert not set(pool).intersection(test)
    assert set(pool).union(test) == set(range(443))
    assert np.isfinite(y).all()

    matrices = {}
    arms = {}
    for name, filename in FILES.items():
        frame = pd.read_csv(ASSETS / filename, index_col=0)
        assert frame.index.equals(target_frame.index)
        assert not any('exp' in c.lower() or 'activation_energy' in c.lower() for c in frame.columns)
        matrix = frame.to_numpy(dtype=float)
        assert matrix.shape[0] == 443 and np.isfinite(matrix).all()
        matrices[name] = matrix
        arms[name] = {
            'source_matrix_file': filename,
            'feature_columns': list(frame.columns),
            'scaler': 'standard',
            'pca': None,
            'target_scaler': 'none',
            'estimator': {
                'family': 'Ridge',
                'parameter_grid': {'alpha': [0.1, 1.0, 10.0, 100.0]},
            },
            'cv': {
                'n_splits': 3, 'shuffle': True, 'random_state': CV_SEED,
                'scoring': 'neg_mean_absolute_error',
            },
        }
    full_columns = arms['mechanistic']['feature_columns']
    no_ts_columns = arms['no_ts']['feature_columns']
    assert set(full_columns) - set(no_ts_columns) == {c for c in full_columns if c.endswith('_ts')}
    assert not set(no_ts_columns) - set(full_columns)
    assert arms['fingerprint']['feature_columns'] == [str(i) for i in range(1024)] + [f'pc_{i}' for i in range(1, 6)]

    records, prediction_rows, learning_rows = [], [], []
    errors = {}
    for size in SIZES:
        seen = set()
        for repeat in range(REPEATS):
            seed = 31000 + 100 * size + repeat
            train = pool.copy() if size == len(pool) else np.random.default_rng(seed).choice(pool, size=size, replace=False)
            subset_key = tuple(sorted(map(int, train)))
            if size < len(pool):
                assert subset_key not in seen, 'Repeated sampled subset'
                seen.add(subset_key)
            split_id = f'n{size}_repeat{repeat}'
            records.append({
                'paired_split_id': split_id, 'n_train': size,
                'repeat_index': repeat, 'seed': seed,
                'train_indices': train.tolist(), 'test_indices': test.tolist(),
            })
            for name, matrix in matrices.items():
                pred = predict_declared(matrix[train], y[train], matrix[test], arms[name])
                residual = pred - y[test]
                mae = float(np.mean(np.abs(residual)))
                errors[(size, repeat, name)] = mae
                learning_rows.append({
                    'representation': name, 'source_matrix_file': FILES[name],
                    'n_train': size, 'repeat_index': repeat,
                    'split_kind': 'fixed_test_resampled_train', 'paired_split_id': split_id,
                    'mae_kcal_mol': mae, 'rmse_kcal_mol': float(np.sqrt(np.mean(residual ** 2))),
                })
                for row_index, actual, predicted in zip(test, y[test], pred):
                    prediction_rows.append({
                        'representation': name, 'source_matrix_file': FILES[name],
                        'paired_split_id': split_id, 'n_train': size, 'repeat_index': repeat,
                        'row_index': int(row_index), 'y_true_kcal_mol': float(actual),
                        'y_pred_kcal_mol': float(predicted),
                    })

    pd.DataFrame(prediction_rows).to_csv(OUT / 'predictions.csv', index=False, float_format='%.17g')
    pd.DataFrame(learning_rows).to_csv(OUT / 'learning_curves.csv', index=False, float_format='%.17g')
    write_json('splits.json', {
        'train_pool_indices': pool.tolist(), 'test_indices': test.tolist(),
        'sizes': SIZES, 'repeats_per_size': REPEATS, 'seed_policy': SEED_POLICY,
        'scored_representations': list(FILES), 'records': records,
    })
    summaries = []
    for size in SIZES:
        for comparator in ('no_ts', 'fingerprint'):
            delta = np.array([errors[(size, repeat, comparator)] - errors[(size, repeat, 'mechanistic')]
                              for repeat in range(REPEATS)])
            summaries.append({
                'n_train': size, 'comparator': comparator,
                'difference_definition': 'comparator_mae_minus_mechanistic_mae',
                'mean': float(delta.mean()), 'repeat_differences': delta.tolist(),
                'conditional_repeat_percentile_95_interval': np.percentile(delta, [2.5, 97.5]).tolist(),
            })
    write_json('paired_summary.json', summaries)
    comparisons = {}
    for comparator in ('no_ts', 'fingerprint'):
        rows = [r for r in summaries if r['comparator'] == comparator]
        bracket = None
        for left, right in zip(rows, rows[1:]):
            if left['mean'] * right['mean'] < 0:
                bracket = [left['n_train'], right['n_train']]
                break
        if bracket is not None:
            status = 'observed'
            support = [f'n={n}' for n in bracket]
            reason = ('The mean paired MAE difference changes sign between these adjacent tested sizes. '
                      'This is an empirical mean crossover conditional on the fixed holdout; '
                      'the repeat intervals describe its uncertainty, not a population claim.')
        else:
            status = 'no_crossover_in_tested_range'
            support = [f'n={n}' for n in SIZES]
            reason = ('No strict sign change in the mean paired MAE difference occurs between adjacent '
                      'tested sizes. This does not establish a crossover outside this range; '
                      'repeat percentile intervals are conditional on the fixed holdout.')
        comparisons[comparator] = {
            'basis': 'mean', 'status': status, 'training_size_bracket': bracket,
            'supporting_summary_rows': support, 'reason': reason,
        }
    write_json('crossover.json', {'comparisons': comparisons})
    write_json('protocol.json', {
        'case_id': 'case-03-low-data-model-selection',
        'sizes': SIZES, 'repeats_per_size': REPEATS, 'seed_policy': SEED_POLICY,
        'scored_representations': list(FILES), 'comparison_design': 'controlled_representation',
        'model_spec': {'schema': 'case03-model-spec/v1', 'arms': arms},
        'same_sampled_training_indices_across_representations': True,
        'same_frozen_test_set_across_representations_and_repeats': True,
        'tuning_budget': {
            'same_across_scored_arms': True, 'candidate_models_per_arm': 4, 'inner_folds': 3,
            'description': 'Four Ridge alpha values, three identical shuffled inner folds per arm; select minimum mean fold MAE and refit on the entire sampled subset.',
        },
        'learned_preprocessing': {
            'fit_within_training_subset': True,
            'steps': ['StandardScaler fitted separately inside each inner training fold, then refitted on the entire sampled subset; fixed public solvent PCs retained.'],
        },
        'interval_scope': 'training_subset_repeat_conditional_on_frozen_test_set',
        'software_versions': {
            'python': platform.python_version(), 'numpy': np.__version__, 'scikit_learn': sklearn.__version__,
        },
    })
    (OUT / 'notes.md').write_text(
        '# Case 03 computed representation comparison\n\n'
        'This is a newly authored private replacement reference implementation; the removed original is unavailable.\n\n'
        'The scored target is exp_activation_energy from s115. The public s120, s138, and s131 matrices supply '
        'mechanistic, no-TS, and 1024-coordinate structural reaction-difference fingerprint descriptors, respectively. '
        'The five published solvent PCs are retained without refitting their upstream construction. '
        'No experimental targets or target-derived features are used as predictors.\n\n'
        'Each of four training sizes has twenty paired repeats, with ordered sampled indices recorded in splits.json. '
        'Below the full pool, subsets are sampled without replacement and checked for uniqueness within size. '
        'Full-pool repeats all use the complete released training pool and therefore produce identical fits '
        'under the fixed inner-CV seed; their repeat interval is degenerate by design. '
        'All arms share four Ridge candidates, three shuffled folds, fold-local standardization and MAE scoring. '
        'The best candidate is selected by mean fold MAE, breaking ties by grid order, and refitted once on the sampled subset. '
        'Test labels are used only after prediction for metrics.\n\n'
        'Paired differences are comparator MAE minus mechanistic MAE; positive differences favor mechanistic features. '
        'Intervals are the empirical 2.5th and 97.5th percentiles of twenty repeat differences, conditional on the frozen '
        '89-row holdout. They do not estimate population uncertainty. A crossover denotes a strict change in the '
        'mean paired difference between adjacent tested sizes, not a statistically established population crossover. '
        'All 443 labels are public; this holdout is not blind. No arm is required to win.\n'
    )


if __name__ == '__main__':
    main()
