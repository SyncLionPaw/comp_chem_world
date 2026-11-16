#!/bin/sh
set -eu
app=${APP:-/app}
input=${INPUT_DIR:-$app/inputs}
output=$app/final
mkdir -p "$output"
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT HUP INT TERM
cat > "$work/route.py" <<'ORACLE_PY'
"""Author-side chemistry admission reference; computed from structured input."""
import argparse,json,shutil
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--input-dir',type=Path);p.add_argument('--output-dir',type=Path);a=p.parse_args()
z=dict(zip(['H','C','N','O','F','P','S','Cl','Fe','Br','I','Xe'],[1,6,7,8,9,15,16,17,26,35,53,54]));allowed={'H','C','N','O','P','S','F','Cl','Br','I'};decisions=[]
for r in json.loads((a.input_dir/'requests.json').read_text())['requests']:
 n=sum(z[element]*count for element,count in r['element_counts'].items())-r['charge'];s=r['spin_multiplicity']-1
 if s<0 or s>n or (n-s)%2:verdict,reason='invalid_state','electron_spin_parity'
 elif set(r['element_counts'])-allowed:verdict,reason='unsupported','unsupported_element_in_published_web'
 elif r['connected_components']>1:verdict,reason='unsupported','published_web_requires_single_solute_molecule'
 elif (r['iodine_bond_degree'] or 0)>1:verdict,reason='unsupported','iodine_bond_pattern_outside_published_gaff_scope'
 else:verdict,reason='supported','closed_shell_bcc' if s==0 else 'open_shell_resp'
 method=('am1-bcc' if s==0 else 'resp') if verdict=='supported' else None
 decisions.append({'request_id':r['request_id'],'electrons':n,'verdict':verdict,'reason_codes':[reason],'charge_method':method,'launch_allowed':verdict=='supported','charge':r['charge'],'spin_multiplicity':r['spin_multiplicity']})
a.output_dir.mkdir(parents=True,exist_ok=True);(a.output_dir/'decisions.json').write_text(json.dumps({'scope':'published_AutoSolvateWeb_2025','decisions':decisions},indent=2)+'\n')
(a.output_dir/'analysis.md').write_text('按元素计数计算电子数并检查自旋奇偶；2025 年 Web 的单溶质 GAFF 适用域与新版 CLI 分开判断。闭壳层支持请求走 AM1-BCC，开壳层走 RESP；不支持或状态矛盾的请求均禁止启动计算。电子奇偶是必要条件，不保证对应电子态稳定。\n')
if Path(__file__).resolve()!=(a.output_dir/'route.py').resolve():shutil.copyfile(__file__,a.output_dir/'route.py')
ORACLE_PY
cp "$work/route.py" "$output/route.py"
python3 "$work/route.py" --input-dir "$input" --output-dir "$output"
