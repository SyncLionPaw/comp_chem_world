# 任务：残基相关与距离矩阵分析

## 背景

输入为 `/app/assets/` 中 WT 与 V72I 的相关矩阵、平均距离矩阵，以及 `README_residue_numbering`。每个矩阵均为无表头的 526×526 空白分隔数组；矩阵索引从 0 起，且等于成熟 Hsp60 编号，PDB/源文件编号比成熟编号大 1。第 0 行对应成熟 Ala0（PDB Ala1）。相关矩阵来自各自元轨迹中占比最高的簇。结构域范围为：赤道域 0–133、410–525；中间域 134–188、374–409；顶端域 189–373。

## 任务

根据 WT 与 V72I 的单体相关性和平均距离数据构建残基网络，比较最短路径边使用量，并解释候选变构路线及 β13（成熟残基 375–380）的变化。结合数据判断路径意义；阈值显示图中的断连不代表完整接触图中无路，路径使用量变化也不等同于结构接触的出现或消失。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 matplotlib、NetworkX、NumPy、pandas、ParmEd、pillow、PROPKA、SciPy。不要自行安装额外软件包，也不要通过网络获取依赖。

为使两种变体的网络结果可直接比较，采用以下固定定义：距离不超过 6.0 Å 的无向接触边，边长为 `-log(max(abs(correlation), 1e-12))`；在完整图上计算加权全源最短路径边使用量，等长路径平均分摊，再除以完整图的最大边使用量。显示阈值使用 0.30 或 0.35，并据此输出完整阈值边集。不要以显示子图代替完整图路径证据。

### 输入与产物细则

`findings.json` 须严格使用 `spm-allostery/v1`：顶层仅含 `schema_version,method,beta13,regional_coverage,full_graph_path`。`method` 对象仅含 `contact_cutoff_angstrom,correlation_to_length,correlation_floor,graph,shortest_path_policy,usage_normalization,display_threshold`，取值分别为 `contact_cutoff_angstrom`=6.0、`correlation_to_length`=`negative_log_abs_floor`、`correlation_floor`=1e-12、`graph`=`undirected`、`shortest_path_policy`=`equal_split_all_pairs`、`usage_normalization`=`maximum_edge_usage`、`display_threshold`=0.30 或 0.35（这些固定串用于记录本节方法）。`beta13` 对象仅含整数 `wt_internal_display_edges,v72i_internal_display_edges` 和字符串 `interpretation`；解释类别须与边数比较一致（`display_usage_decreased`、`display_usage_increased` 或 `display_usage_unchanged`）。`regional_coverage` 必须恰含 `c_terminal_equatorial_to_intermediate,intermediate_to_apical,beta13_to_apical,atp_lid_region_390_409`，且 WT 显示图须有相应证据。`full_graph_path` 仅含 `WT,V72I` 两项；每项仅含整数 `source_mature,target_mature`、整数数组 `path_mature` 和数值 `shortest_distance`，分别提供从成熟残基 517 到顶端域的完整接触图最短路径。

`analysis.py` 必须能以 `python analysis.py --assets <目录> --output <目录> --threshold <数值>` 读取四个矩阵并重建两个 CSV，同时支持可选参数 `--input-manifest <文件>`。清单为 JSON 对象，且仅含 `schema_version,base_input_sha256,challenge_input_sha256,mutation`；版本为 `spm-input-challenge/v1`。`base_input_sha256` 与 `challenge_input_sha256` 都是以文件名为键、十六进制文件校验值为值的映射，形如 `{"corrmat_c0_WT.dat":"…","distmat_c0_WT.dat":"…","corrmat_c0_V72I.dat":"…","distmat_c0_V72I.dat":"…"}`。`mutation` 仅含 `matrix,removed_contact_edge,old_distance_angstrom,new_distance_angstrom`，记录被移除接触边及其距离变化。脚本必须按清单中的输入重新计算，不得忽略清单或依赖同目录辅助文件。

报告应说明建图与路径比较，说明与 `findings.json` 一致的接触截断和边长定义，并区分完整接触图证据与阈值显示图。CSV 必须列出 `source,target,normalized_weight`，编号采用成熟残基号，每条无向边仅写一次且 `source < target`；权重应保留满足数值一致性检查所需的精度。

在 `final/` 提交 `spm_WT.csv`、`spm_V72I.csv`、`analysis.py`、`findings.json` 和 `report.md`。CSV 权重须对应指定方法下的完整阈值边集；脚本重放结果须与 CSV 一致。报告解释 β13 的边使用变化及生物学含义，并谨慎区分路径使用量与结构接触。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/assets/` | 给定输入与资源目录。 |

| 路径 | 内容 |
| --- | --- |
| `/app/final/spm_WT.csv` | WT 路径网络 |
| `/app/final/spm_V72I.csv` | V72I 路径网络 |
| `/app/final/analysis.py` | 网络重建程序 |
| `/app/final/findings.json` | 结构化网络结果 |
| `/app/final/report.md` | 科学解读 |
