# 任务：评估位点分辨的锂 K 边谱与局部环境

## 背景

提供了 Li4Ti5O12、Li5Ti5O12、Li6Ti5O12 和 Li7Ti5O12（分别含 8、10、12、14 个替代位点）的芯空穴 VASP 计算。每个位点含投影态密度文件 `vasprun.xml.gz` 和标出 Be 芯空穴中心的 POSCAR，并提供共用计算输入。

## 任务

重建位点分辨的锂 K 边谱，并评估中间锂化组成的位点是否支持约 58 eV 的额外特征。结构归属须综合谱、周期局部几何和端元对照；将其作为待检验假设，而非唯一鉴定。

## 要求

对 Be 的 p 投影态密度累加 px、py、pz 和两种自旋，以费米能为能量零点，并使用 FWHM 为 0.5 eV 的高斯展宽。每种组成先累加未归一化的位点谱，将总谱主峰平移至 61.5 eV，再将每条位点曲线按 56–67 eV 区间的最大值归一化。

根据 POSCAR 以 Be 为中心计算周期几何。统计 2.75 Å 内的 O，报告最近 Be–Li 距离；六配位时按升序报告最近的六个 Be–O 距离及 `d=(1/6)Σ|l_i-l_av|/l_av`。配位数低于六时报告实际数目，并将六距离列表和畸变指数设为 `null`。每种组成均提供一个规则六配位对照位点：`d<0.06`、最近 Be–Li `>2.60 Å`，且 57.5–58.6 eV 内无局部峰。对中间组成的归属须综合谱、几何和端元比较；单独肩峰或几何指标不足以支持结论。

在 `/app/final/results.json` 中，`spectra` 须包含 Li4–Li7 的全部位点，且每个位点有对齐的 `energy_eV`、`intensity` 数组。`assignment` 须包含按组成列出的 `sites_with_extra_prepeak`、布尔值 `present_in_endmembers`、简要 `site_description`，以及候选位点和每种组成至少一个六配位对照的 `site_geometry_evidence` 几何记录数组 `{composition, site, coordination, nearest_li_A, six_li_o_A, distortion_index}`。配位低于六时，距离列表和畸变指数为 `null`。在 `/app/final/methods.md` 说明投影选择及归属证据。

候选位点须有六个 O 近邻，畸变指数 ≥0.06，六条 Be–O 键中最长者 ≥2.34 Å，最近 Be–Li 距离 ≤2.60 Å，且在 57.5–58.6 eV 内存在可分辨的局部极大值。说明这些证据如何支持或限制畸变、面共享的 16c 位点归属，并保留其他解释的可能性。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/assets/` | Li4–Li7 的分位点 VASP 光谱与结构。 |

读取 `/app/assets/Li4` 至 `/app/assets/Li7` 下全部位点输入，包括各位点 `vasprun.xml.gz`、POSCAR 及组成级 INCAR/KPOINTS。提交 `/app/final/results.json` 和 `/app/final/methods.md`。
