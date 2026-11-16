#!/usr/bin/env python3
"""Parse CP2K author-side workflow stages from native output (not a scorer).

The parser associates records with ENERGY| Total FORCE_EVAL boundaries.  It
reports syntax and local consistency only; it cannot validate the executable,
input, geometry identity, scientific result, or HPC provenance.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re

FLOAT = r'[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[EeDd][-+]?\d+)?'
NUMBER = rf'(?:{FLOAT}|[-+]?(?:nan|inf(?:inity)?))'
ENERGY_RE = re.compile(rf'^\s*ENERGY\|\s*Total FORCE_EVAL(?:\s*\([^)]*\))?\s+energy\s+\[(?:a\.u\.|hartree)\]\s*:?\s*({NUMBER})\s*$', re.I)
STATE_RE = re.compile(rf'^\s*TDDFPT\|\s+(\d+)\s+({NUMBER})\s+({NUMBER})\s+({NUMBER})\s+({NUMBER})\s+({NUMBER})\s*$', re.I)
TRANSITION_STATE_RE = re.compile(rf'^\s*(\d+)\s+({NUMBER})\s+eV\s*$', re.I)
TRANSITION_ROW_RE = re.compile(rf'^\s*(\d+)\s+(\d+)\s+({NUMBER})\s*$', re.I)
TABLE_RULE_RE = re.compile(r'^\s*-{3,}\s*$')


def num(s):
    return float(s.replace('D', 'E').replace('d', 'e'))


def _force_blocks(lines, start, end):
    blocks = []
    i = start
    while i < end:
        title = lines[i]
        kind = ('atomic_au' if 'ATOMIC FORCES in [a.u.]' in title else
                'forces_hartree_bohr' if re.search(r'FORCES\| Atomic forces \[hartree/bohr\]', title) else None)
        if not kind:
            i += 1
            continue
        header_line = i + 1
        rows, ids, values = [], [], []
        i += 1
        while i < end:
            line = lines[i]
            if kind == 'atomic_au':
                m = re.match(rf'\s*(\d+)\s+\d+\s+[A-Za-z]+\s+({NUMBER})\s+({NUMBER})\s+({NUMBER})\s*$', line, re.I)
                cols = (2, 3, 4)
            else:
                m = re.match(rf'\s*FORCES\|\s+(\d+)\s+({NUMBER})\s+({NUMBER})\s+({NUMBER})(?:\s+{NUMBER})?\s*$', line, re.I)
                cols = (2, 3, 4)
            if m:
                ids.append(int(m[1])); tokens = [m[j] for j in cols]
                values.append([num(x) for x in tokens]); rows.append(i + 1)
                i += 1
            elif ids and not line.strip():
                i += 1
                break
            elif ids:
                break
            else:
                # CP2K may place blank lines, Atom/Kind column headings, and
                # separator rules between the title and the first force row.
                # Search a bounded table preamble; stop at a new known section.
                if i - header_line > 30 or re.search(r'^(?:\s*(?:ENERGY\||OPT\||SCF\||\*{3}|![-*]))', line):
                    break
                i += 1
        blocks.append(dict(format=kind, line_start=header_line, line_end=(rows[-1] if rows else header_line),
                           atom_ids=ids, forces=values))
    return blocks


def _transition_contributions(lines, start, end, td_states):
    """Parse optional CP2K Excitation analysis MO-amplitude tables.

    This is a presentation-level extraction. The output does not identify a
    physical state from signed amplitudes, and the table does not print spin,
    channel, or an amplitude unit in the fixtures examined here.
    """
    titles = [i for i in range(start, end)
              if re.search(r'^\s*-\s*Excitation analysis\s*-\s*$', lines[i], re.I)]
    tables = []
    for table_index, title_line in enumerate(titles):
        # The report has a title, rule, two-line column heading, rule, rows,
        # and a closing rule. Keep the captured line range exact.
        opening_rule = next((i for i in range(title_line + 1, min(end, title_line + 8))
                             if TABLE_RULE_RE.match(lines[i])), None)
        if opening_rule is None:
            tables.append(dict(status='unknown', reason='missing_opening_table_rule',
                               line_start=title_line + 1, line_end=title_line + 1,
                               raw_title=lines[title_line].strip(), states=[]))
            continue
        content_start = opening_rule + 1
        # The next dashed rule after the header is the table's data boundary.
        data_rule = next((i for i in range(content_start, end)
                          if TABLE_RULE_RE.match(lines[i])), None)
        if data_rule is None:
            tables.append(dict(status='unknown', reason='missing_column_header_boundary',
                               line_start=title_line + 1, line_end=end,
                               raw_title=lines[title_line].strip(), states=[]))
            continue
        closing_rule = next((i for i in range(data_rule + 1, end)
                             if TABLE_RULE_RE.match(lines[i])), None)
        if closing_rule is None:
            tables.append(dict(status='unknown', reason='missing_closing_table_rule',
                               line_start=title_line + 1, line_end=end,
                               raw_title=lines[title_line].strip(), states=[]))
            continue
        raw_column_labels = [lines[i].strip() for i in range(content_start, data_rule)]
        header_rows = [line.split() for line in raw_column_labels if line.strip()]
        expected_columns = ('state number', 'occupied orbital', 'virtual orbital', 'excitation amplitude')
        normalized_columns = ([' '.join(pair).lower() for pair in zip(*header_rows)]
                              if len(header_rows) == 2 and len(header_rows[0]) == len(header_rows[1]) else [])
        column_labels_valid = normalized_columns == list(expected_columns)
        states, malformed_lines = [], []
        current = None
        for i in range(data_rule + 1, closing_rule):
            raw = lines[i]
            if not raw.strip():
                continue
            state_match = TRANSITION_STATE_RE.match(raw)
            row_match = TRANSITION_ROW_RE.match(raw)
            if state_match:
                current = dict(state=int(state_match[1]), energy_eV=num(state_match[2]),
                               raw_energy=state_match[2], line=i + 1,
                               contributions=[], line_end=i + 1)
                states.append(current)
            elif row_match and current is not None:
                current['contributions'].append(dict(
                    occupied_mo=int(row_match[1]), virtual_mo=int(row_match[2]),
                    signed_amplitude=num(row_match[3]), raw_amplitude=row_match[3],
                    raw_label='Excitation amplitude', spin=None, channel=None,
                    amplitude_unit=None, line=i + 1))
                current['line_end'] = i + 1
            else:
                malformed_lines.append(i + 1)
        ids = [s['state'] for s in states]
        duplicate_ids = sorted({x for x in ids if ids.count(x) > 1})
        td_ids = [s['state'] for s in td_states]
        duplicate_td_ids = sorted({x for x in td_ids if td_ids.count(x) > 1})
        alignment = dict(table_state_ids=ids, td_state_ids=td_ids,
                         missing_td_state_ids=[x for x in td_ids if x not in ids],
                         extra_table_state_ids=[x for x in ids if x not in td_ids],
                         duplicate_table_state_ids=duplicate_ids,
                         duplicate_td_state_ids=duplicate_td_ids)
        finite = all(math.isfinite(s['energy_eV']) and
                     all(math.isfinite(c['signed_amplitude']) and
                         c['occupied_mo'] > 0 and c['virtual_mo'] > 0
                         for c in s['contributions']) for s in states)
        duplicate_transitions = []
        for state in states:
            pairs = [(c['occupied_mo'], c['virtual_mo']) for c in state['contributions']]
            duplicate_transitions.extend(dict(state=state['state'], occupied_mo=o, virtual_mo=v)
                                         for o, v in sorted(set(pairs)) if pairs.count((o, v)) > 1)
        # Match rows by their explicit state number only. Energies are exposed
        # with their raw printed precision; no tolerance or identity claim is
        # inferred from either energy or the signed amplitudes.
        td_energy_by_id = {s['state']: s['energy_eV'] for s in td_states}
        for state in states:
            state['td_state_energy_eV'] = td_energy_by_id.get(state['state'])
            state['printed_energy_delta_eV'] = (state['energy_eV'] - state['td_state_energy_eV']
                                                if state['td_state_energy_eV'] is not None else None)
        aligned = (not duplicate_ids and not duplicate_td_ids and not alignment['missing_td_state_ids'] and
                   not alignment['extra_table_state_ids'] and ids == td_ids)
        status = ('parsed' if column_labels_valid and states and not malformed_lines and finite and
                  not duplicate_transitions and aligned else 'unknown')
        reason = None
        if not column_labels_valid: reason = 'unexpected_column_labels'
        elif not states: reason = 'empty_excitation_analysis_table'
        elif malformed_lines: reason = 'unparsed_nonempty_table_rows'
        elif not finite: reason = 'nonfinite_or_invalid_transition_value'
        elif duplicate_ids or duplicate_transitions: reason = 'duplicate_state_or_transition_rows'
        elif not aligned: reason = 'table_state_rows_do_not_match_td_state_rows'
        tables.append(dict(status=status, reason=reason, table_index=table_index,
                           line_start=title_line + 1, line_end=closing_rule + 1,
                           raw_title=lines[title_line].strip(), raw_column_labels=raw_column_labels,
                           spin=None, channel=None, amplitude_unit=None,
                           state_alignment=alignment, finite_values=finite,
                           duplicate_transitions=duplicate_transitions,
                           malformed_line_numbers=malformed_lines, states=states))
    if not tables:
        return dict(status='unknown', reason='no_excitation_analysis_table_in_evaluation', tables=[])
    if len(tables) != 1:
        return dict(status='unknown', reason='multiple_excitation_analysis_tables_in_evaluation', tables=tables)
    if tables[0]['status'] != 'parsed':
        return dict(status='unknown', reason=tables[0].get('reason') or 'invalid_excitation_analysis_table', tables=tables)
    return dict(status='parsed', reason=None, tables=tables, science_validated=False,
                identity_claim='No state identity or scientific acceptance inferred from signed amplitudes.')


def _opt_convergence(lines, step_line, end):
    metrics = ('Maximum step size', 'RMS step size', 'Maximum gradient', 'RMS gradient')
    result = {}
    for metric in metrics:
        key = metric.lower().replace(' ', '_')
        value = limit = None
        converged = None
        for i in range(step_line, end):
            line = lines[i]
            m = re.match(rf'\s*OPT\|\s*{re.escape(metric)}\s+({NUMBER})\s*$', line, re.I)
            if m: value = num(m[1])
            m = re.match(rf'\s*OPT\|\s*Convergence limit for {re.escape(metric)}\s+({NUMBER})\s*$', line, re.I)
            if m: limit = num(m[1])
            m = re.match(rf'\s*OPT\|\s*{re.escape(metric)} is converged\s+(YES|NO)\s*$', line, re.I)
            if m: converged = m[1].upper() == 'YES'
        consistent = not (converged is True and value is not None and limit is not None and value > limit)
        result[key] = dict(value=value, limit=limit, is_converged=converged,
                           value_at_or_below_limit=(value <= limit if value is not None and limit is not None else None),
                           flag_numeric_consistency=consistent)
        result[key]['numeric_finite'] = (value is not None and limit is not None and
                                         math.isfinite(value) and math.isfinite(limit) and value >= 0 and limit >= 0)
    return result


def parse_text(text, expected_atoms=None, expected_states=None, stage='auto'):
    lines = text.splitlines()
    energy_marks = [(i, ENERGY_RE.match(line)) for i, line in enumerate(lines)]
    energy_marks = [(i, m) for i, m in energy_marks if m]
    opt_steps = [(i, int(m[1])) for i, line in enumerate(lines)
                 if (m := re.match(r'\s*OPT\| Step number\s+(\d+)', line, re.I))]
    markers_done = [i for i, line in enumerate(lines) if 'GEOMETRY OPTIMIZATION COMPLETED' in line]
    reevaluate = [i for i, line in enumerate(lines) if 'Reevaluating energy at the minimum' in line]
    inferred_stage = stage if stage != 'auto' else ('GEO_OPT' if opt_steps or markers_done else 'ENERGY')
    header_atom_match = re.search(r'- Atoms:\s*(\d+)', text)
    header_atom_count = int(header_atom_match[1]) if header_atom_match else None
    evaluations = []
    previous = -1
    opt_cursor = 0
    for idx, (end_line, em) in enumerate(energy_marks):
        begin = previous + 1
        chunk = lines[begin:end_line + 1]
        text_chunk = '\n'.join(chunk)
        abs_lines = range(begin, end_line + 1)
        scf = [{'line': i + 1, 'kind': 'not_converged' if re.search(r'SCF run\s+not converged', lines[i], re.I) else 'converged',
                'text': lines[i].strip()} for i in abs_lines if re.search(r'SCF run\s+(?:not )?converged in', lines[i], re.I)]
        outer = [{'line': i + 1, 'text': lines[i].strip()} for i in abs_lines if re.search(r'outer SCF loop (?:converged|NOT converged)', lines[i], re.I)]
        td = [{'line': i + 1, 'text': lines[i].strip()} for i in abs_lines if re.search(r'TDDFPT run (?:converged|NOT converged)', lines[i], re.I)]
        linear = [{'line': i + 1, 'text': lines[i].strip(), 'converged': 'converged' in lines[i].lower() and 'not converged' not in lines[i].lower()}
                    for i in abs_lines if re.search(r'linear solver (?:converged|not converged)', lines[i], re.I)]
        states = []
        for i in abs_lines:
            m = STATE_RE.match(lines[i])
            if m:
                states.append(dict(state=int(m[1]), energy_eV=num(m[2]), dipole=[num(m[j]) for j in (3, 4, 5)],
                                    oscillator_strength=num(m[6]), line=i + 1))
        transitions = _transition_contributions(lines, begin, end_line + 1, states)
        energy = num(em[1])
        scf_energy = [(i + 1, num(m[1])) for i in abs_lines if (m := re.match(rf'^\s*Total energy:\s*({NUMBER})\s*$', lines[i], re.I))]
        role = 'minimum_endpoint' if any(begin <= x <= end_line for x in reevaluate) else 'evaluation'
        next_end = energy_marks[idx + 1][0] if idx + 1 < len(energy_marks) else len(lines)
        # CP2K prints force tables and OPT step banners after ENERGY; bind that
        # post-energy tail to its own evaluation up to the next energy boundary.
        forces = _force_blocks(lines, end_line + 1, next_end)
        # Step banners occur after the force record. Bind each banner to the most recent evaluation.
        item = dict(index=idx, role=role, line_start=begin + 1, line_end=end_line + 1,
                    post_energy_line_range=[end_line + 2, next_end] if next_end > end_line + 1 else None,
                    energy_total_Ha=energy, finite_energy=math.isfinite(energy), scf_energies_Ha=[v for _, v in scf_energy],
                    scf_energy_lines=[n for n, _ in scf_energy], scf_events=scf, outer_scf_events=outer,
                    td_events=td, linear_solver_events=linear, states=states,
                    transition_contributions=transitions, force_blocks=forces,
                    errors=[dict(line=i + 1, text=lines[i].strip()) for i in abs_lines if '[ABORT]' in lines[i] or re.search(r'SCF run\s+not converged', lines[i], re.I)],
                    warnings=[dict(line=i + 1, text=lines[i].strip()) for i in abs_lines if '*** WARNING' in lines[i]])
        if scf_energy and states and inferred_stage == 'S1_GEO_OPT':
            item['same_evaluation_s1_check'] = dict(e0_Ha=scf_energy[-1][1], s1_total_Ha=energy,
                implied_omega_eV=(energy - scf_energy[-1][1]) * 27.211386245988,
                printed_omega_eV=states[0]['energy_eV'],
                delta_eV=(energy - scf_energy[-1][1]) * 27.211386245988 - states[0]['energy_eV'],
                interpretation='Informational only; compare values from this evaluation and account for printed precision.')
        elif scf_energy and states:
            item['same_evaluation_energy_state_delta_unclassified'] = dict(
                total_energy_Ha=energy, printed_scf_total_Ha=scf_energy[-1][1],
                difference_eV=(energy - scf_energy[-1][1]) * 27.211386245988,
                interpretation='Stage-dependent total-energy semantics; identify calculation and state meaning from the input before assigning S1.')
        evaluations.append(item)
        # Any OPT step lines between this ENERGY record and the next ENERGY belongs to this eval.
        while opt_cursor < len(opt_steps) and opt_steps[opt_cursor][0] < begin:
            opt_cursor += 1
        while opt_cursor < len(opt_steps) and opt_steps[opt_cursor][0] < next_end:
            line_no, step = opt_steps[opt_cursor]
            force_ends = [b['line_end'] for b in forces]
            if force_ends and line_no + 1 > max(force_ends):
                item['opt_step'] = dict(step=step, line=line_no + 1, after_force=True,
                                        convergence=_opt_convergence(lines, line_no, next_end))
            opt_cursor += 1
        previous = end_line
    for ev in evaluations:
        ev['convergence_flags'] = dict(scf=bool(ev['scf_events']) and all(x['kind'] == 'converged' for x in ev['scf_events']),
            outer_scf=(None if not ev['outer_scf_events'] else all(not re.search(r'\bnot\s+converged\b', x['text'], re.I) for x in ev['outer_scf_events'])),
            td=bool(ev['states']) and bool(ev['td_events']) and all(not re.search(r'\bnot\s+converged\b', x['text'], re.I) for x in ev['td_events']),
            linear_response=(not ev['states']) or (bool(ev['linear_solver_events']) and all(x['converged'] for x in ev['linear_solver_events'])))
        ids = [x['state'] for x in ev['states']]
        ev['state_checks'] = dict(count=len(ids), duplicate_ids=sorted({x for x in ids if ids.count(x) > 1}),
            missing_expected_ids=([x for x in range(1, expected_states + 1) if x not in ids] if expected_states is not None else []),
            ordered=ids == sorted(ids), finite=all(math.isfinite(v) for s in ev['states'] for v in [s['energy_eV'], *s['dipole'], s['oscillator_strength']]),
            nonnegative_energy_and_f=all(s['energy_eV'] >= 0 and s['oscillator_strength'] >= 0 for s in ev['states']))
        for block in ev['force_blocks']:
            ids = block['atom_ids']
            block['checks'] = dict(finite=all(math.isfinite(v) for row in block['forces'] for v in row),
                atom_count_matches=(expected_atoms is None or len(ids) == expected_atoms),
                atom_ids_ordered_unique=ids == list(range(1, len(ids) + 1)),
                complete=(expected_atoms is None or ids == list(range(1, expected_atoms + 1))))
        ev['stage_diagnostic'] = _stage_check(inferred_stage, ev, expected_atoms, expected_states)
    warnings = [{'line': i + 1, 'text': line.strip()} for i, line in enumerate(lines) if '*** WARNING' in line]
    errors = [{'line': i + 1, 'text': line.strip()} for i, line in enumerate(lines)
              if '[ABORT]' in line or re.search(r'SCF run\s+not converged', line, re.I) or
              re.search(r'(?:outer SCF loop|TDDFPT run)\s+not converged', line, re.I)]
    tail_start = energy_marks[-1][0] + 1 if energy_marks else 0
    unresolved_tail_events = [{'line': i + 1, 'text': lines[i].strip()} for i in range(tail_start, len(lines))
                              if re.search(r'(?:SCF run\s+(?:not )?converged in|SCF WAVEFUNCTION OPTIMIZATION|TDDFPT run\s+(?:not )?converged|^\s*TDDFPT\||linear solver|Reevaluating energy at the minimum)', lines[i], re.I)]
    if evaluations:
        evaluations[-1]['unresolved_tail_events'] = unresolved_tail_events
    normal_end = any('PROGRAM ENDED AT' in x for x in lines)
    aborted = any('[ABORT]' in x for x in lines)
    stage_file = _file_stage_check(inferred_stage, evaluations, bool(markers_done), normal_end, aborted,
                                   not unresolved_tail_events, expected_atoms, header_atom_count)
    return dict(parser='case07-native-workflow/v1', stage=inferred_stage, stage_classified=inferred_stage in ('GS_GEO_OPT', 'S1_GEO_OPT', 'ENERGY_SPECTRUM', 'ENERGY'), expected_atoms=expected_atoms,
        header_atom_count=header_atom_count,
        expected_states=expected_states, evaluations=evaluations,
        geometry_optimization_completed=bool(markers_done), geometry_completion_lines=[x + 1 for x in markers_done],
        minimum_reevaluation_lines=[x + 1 for x in reevaluate], program_ended=normal_end,
        aborted=aborted, unresolved_tail_events=unresolved_tail_events,
        stage_file_diagnostic=stage_file, errors=errors, warnings=warnings,
        grouping_note='Convergence messages are preserved within each ENERGY-boundary evaluation; repeated SCF headers do not create evaluations.',
        limitations=['Syntax analysis only; no binary, input, restart, geometry identity, or scientific acceptance validation.',
                     'A minimum endpoint is a distinct energy evaluation; geometry identity must be established externally.',
                     'OPT step banner is associated with the preceding energy evaluation; banner text is not a force convergence test.',
                     'TDDFPT/ENERGY record ordering and total-energy state meaning require stage and input identity; the parser does not infer S1 outside S1_GEO_OPT.',
                     'Excitation analysis amplitude tables are optional presentation data; missing/malformed tables are unknown, and signed amplitudes do not establish state identity. Spin, channel and amplitude units are only reported when directly present in raw output.',
                     'Synthetic 500-state input checks parser contracts only; no native case07 500-state ENERGY spectrum fixture was available.'],
        science_validated=False)


def _stage_check(stage, ev, expected_atoms, expected_states):
    """Syntactic expectations only; deliberately does not assert scientific validity."""
    forces = ev['force_blocks']
    good_forces = bool(forces) and all(b['checks']['finite'] and b['checks']['complete'] and
                                       b['checks']['atom_ids_ordered_unique'] for b in forces)
    good_states = (expected_states is not None and ev['state_checks']['count'] == expected_states and
                   not ev['state_checks']['duplicate_ids'] and not ev['state_checks']['missing_expected_ids'] and
                   ev['state_checks']['ordered'] and ev['state_checks']['finite'] and ev['state_checks']['nonnegative_energy_and_f'])
    e0_ok = bool(ev['scf_energies_Ha']) and math.isfinite(ev['scf_energies_Ha'][-1])
    outer_ok = ev['convergence_flags']['outer_scf'] is not False
    if stage == 'ENERGY_SPECTRUM':
        required = {'finite_total_energy': ev['finite_energy'], 'finite_converged_e0': e0_ok,
                    'scf_converged': ev['convergence_flags']['scf'], 'outer_scf_ok_or_not_reported': outer_ok,
                    'no_evaluation_errors': not ev['errors'], 'states_complete': good_states,
                    'td_converged': ev['convergence_flags']['td']}
    elif stage == 'S1_GEO_OPT':
        required = {'finite_total_energy': ev['finite_energy'], 'finite_converged_e0': e0_ok,
                    'scf_converged': ev['convergence_flags']['scf'], 'outer_scf_ok_or_not_reported': outer_ok,
                    'no_evaluation_errors': not ev['errors'], 'td_states_complete': good_states,
                    'td_converged': ev['convergence_flags']['td']}
        if ev['role'] != 'minimum_endpoint':
            required.update(force_block_complete=good_forces,
                            linear_response_converged=ev['convergence_flags']['linear_response'])
    elif stage == 'GS_GEO_OPT':
        required = {'finite_total_energy': ev['finite_energy'], 'finite_converged_e0': e0_ok,
                    'scf_converged': ev['convergence_flags']['scf'], 'outer_scf_ok_or_not_reported': outer_ok,
                    'no_evaluation_errors': not ev['errors'],
                    'force_block_complete': True if ev['role'] == 'minimum_endpoint' else good_forces}
    else:
        required = {'supported_stage': stage == 'ENERGY', 'finite_total_energy': ev['finite_energy']}
    return dict(requirements=required, syntax_requirements_met=all(required.values()),
                scope='Parser diagnostic only; not science acceptance.')


def _file_stage_check(stage, evaluations, opt_completed, program_ended, aborted, no_unresolved_tail,
                      expected_atoms, header_atom_count):
    opt_stage = stage in ('GS_GEO_OPT', 'S1_GEO_OPT')
    steps = [e for e in evaluations if 'opt_step' in e]
    endpoint_ok = bool(evaluations) and evaluations[-1]['role'] == 'minimum_endpoint' and evaluations[-1]['stage_diagnostic']['syntax_requirements_met']
    requirements = {'normal_program_end': program_ended, 'no_abort': not aborted,
                    'has_at_least_one_energy_evaluation': bool(evaluations),
                    'all_evaluation_requirements_met': bool(evaluations) and all(e['stage_diagnostic']['syntax_requirements_met'] for e in evaluations),
                    'no_unresolved_tail_events': no_unresolved_tail}
    if expected_atoms is not None:
        requirements['header_atom_count_matches_expected'] = header_atom_count == expected_atoms
    if opt_stage:
        last_step = steps[-1] if steps else None
        opt_metrics = (last_step['opt_step']['convergence'] if last_step else {})
        all_last_metrics_yes = bool(opt_metrics) and all(v['is_converged'] is True and
                                                         v['flag_numeric_consistency'] for v in opt_metrics.values())
        requirements.update(geometry_optimization_completed=opt_completed, has_accepted_opt_steps=bool(steps),
                           accepted_steps_have_following_force_and_pass=requirements['all_evaluation_requirements_met'] and all(
                               e['force_blocks'] and e['opt_step'].get('after_force') for e in steps),
                           reported_opt_step_metrics_are_finite=bool(steps) and all(
                               all(v['numeric_finite'] and v['is_converged'] is not None
                                   for v in e['opt_step']['convergence'].values())
                               for e in steps if any(v['value'] is not None or v['limit'] is not None or
                                                     v['is_converged'] is not None for v in e['opt_step']['convergence'].values())),
                           reported_opt_flags_numerically_consistent=bool(steps) and all(
                               all(v['flag_numeric_consistency'] for v in e['opt_step']['convergence'].values())
                               for e in steps),
                           final_accepted_step_all_four_opt_flags_yes=all_last_metrics_yes,
                           final_minimum_endpoint_passes=endpoint_ok)
    return dict(requirements=requirements, syntax_complete=all(requirements.values()),
                science_validated=False, scope='File syntax completeness only; no science or geometry identity validation.')


def parse_file(path, expected_atoms=None, expected_states=None, stage='auto'):
    raw = Path(path).read_bytes()
    result = parse_text(raw.decode(errors='replace'), expected_atoms, expected_states, stage)
    result.update(path=str(path), sha256=hashlib.sha256(raw).hexdigest())
    return result


def _json_safe(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    return value


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('logs', nargs='+', type=Path)
    ap.add_argument('--expected-atoms', type=int)
    ap.add_argument('--expected-states', type=int)
    ap.add_argument('--stage', choices=('auto', 'GS_GEO_OPT', 'S1_GEO_OPT', 'ENERGY_SPECTRUM'), default='auto')
    ap.add_argument('--output', type=Path)
    args = ap.parse_args()
    obj = {str(p): parse_file(p, args.expected_atoms, args.expected_states, args.stage) for p in args.logs}
    rendered = json.dumps(_json_safe(obj), indent=2, allow_nan=False) + '\n'
    if args.output: args.output.write_text(rendered)
    else: print(rendered, end='')


if __name__ == '__main__':
    main()
