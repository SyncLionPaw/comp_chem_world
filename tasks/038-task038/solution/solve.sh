#!/usr/bin/env bash
set -euo pipefail
work=$(mktemp -d "${TMPDIR:-/tmp}/bench06-oracle.XXXXXXXX")
trap 'rm -rf "$work"' EXIT
ASSETS=${ASSETS_DIR:-/app/environment/assets}
OUT=${OUTPUT_DIR:-/app/final}
[ -d "$ASSETS" ] || { echo "missing public assets: $ASSETS" >&2; exit 2; }
mkdir -p "$OUT"
cat > "$work/analysis.py" <<'BENCH06_PY_38_0'
"""Author reference submission computed from public kinetics, not checker constants."""
import json,math,sys
from pathlib import Path

def solve(assets,out):
    out.mkdir(parents=True,exist_ok=True);d=json.loads((assets/'kinetics.json').read_text());b=d['barriers_eV'];u=d['conditional_barrier_perturbations_eV'];f=d['fermi_levels_eV'];beta=1/(8.617333262145e-5*d['temperature_K'])
    result={'K_vs_water_OS_log10_rate':-(b['K_OS']-b['water_OS'])*beta/math.log(10),
            'K_IS_vs_OS_log10_rate':(b['K_OS']-b['K_IS'])*beta/math.log(10),
            'water_fermi_shift_eV':f['water_anion']['mean']-f['water_neutral']['mean'],
            'K_fermi_shift_eV':f['K_anion']['mean']-f['K_neutral']['mean'],
            'OS_barrier_gap_lower_eV':(b['K_OS']-u['K'])-(b['water_OS']+u['water']),
            'K_pathway_gap_lower_eV':(b['K_OS']-u['K'])-(b['K_IS']+u['K']),
            'uncertainty_semantics':'conditional_bounds_not_Fermi_spread_CI'}
    # State the reasoning explicitly; verification has an independent acquired-source rubric.
    facts={
      'K_slower_OS_than_water':('conditional','specified_equal_prefactor_and_barrier_bounds',['result:/OS_barrier_gap_lower_eV','input:/assumptions/0','input:/assumptions/1'],'最坏独立扰动后的OS差仍正，在共同前因子假设下K更慢。'),
      'K_IS_faster_than_K_OS':('conditional','specified_equal_prefactor_and_barrier_bounds',['result:/K_pathway_gap_lower_eV','input:/assumptions/0','input:/assumptions/1'],'K的两路径差下界仍正，模型共同前因子下IS相对更快。'),
      'fermi_spread_is_SEM':('not_established','missing_effective_sample_count',['input:/fermi_levels_eV','input:/not_provided/0'],'缺有效样本量和相关时间，时间涨落不能换成均值标准误。'),
      'strict_constant_electrode_potential':('not_established','Fermi_is_not_electrode_inner_potential',['result:/water_fermi_shift_eV','result:/K_fermi_shift_eV','input:/not_provided/1'],'小Fermi差只是有限代理量；内电势未测，不能证明严格恒电势。'),
      'barrier_bounds_are_measured_uncertainty':('not_established','conditional_sensitivity_only',['input:/assumptions/1','input:/not_provided/2'],'指定±界限是敏感性情景，没有路径特异电容修正的统计数据。'),
      'experimental_TOF_determined':('not_established','relative_model_rates_not_measured_TOF',['input:/assumptions/0','input:/barriers_eV'],'相对Eyring比值不能替代实验前因子、覆盖度及绝对TOF。'),
      'short_range_causality_proven':('not_established','kinetic_ordering_not_causal_control',['input:/not_provided/1','input:/not_provided/2'],'稳健路径排序不是控制配位与电场混杂的因果干预。')}
    claims={name:{'verdict':v,'scope':scope,'evidence':evidence,'rationale':reason} for name,(v,scope,evidence,reason) in facts.items()};result['claims']=claims
    (out/'robustness.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');(out/'analysis.py').write_text(Path(__file__).read_text())
    report='条件敏感性计算：共同前因子下OS相对速率按ln k之差计算。\n'
    report += f"K/水外球能垒差下界={result['OS_barrier_gap_lower_eV']:.8g} eV；K两路径能垒差下界={result['K_pathway_gap_lower_eV']:.8g} eV。\n"
    report += '输入中的条件扰动界限为 ' + json.dumps(u, ensure_ascii=False) + ' eV；不是测得能垒CI。\n'
    report += 'Fermi涨落不是SEM；体系Fermi能与电极内电势有不同适用性，不能推导严格恒电势、实测速率或短程因果。\n\n'
    report+='<!-- scientific-claims:start -->\n'+json.dumps(claims,ensure_ascii=False,indent=2)+'\n<!-- scientific-claims:end -->\n';(out/'report.md').write_text(report)

if __name__=='__main__':solve(Path(sys.argv[1]),Path(sys.argv[2]))
BENCH06_PY_38_0
python3 "$work/analysis.py" "$ASSETS" "$OUT"
