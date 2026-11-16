# 任务：统计锂迁移路径上的 Li–Li 接触

## 背景

提供了 Li4+x、Li5+x 和 Li7−x 迁移路径上若干 POSCAR/CONTCAR 及 hop 级 INCAR/KPOINTS。未提供能量或机理解释，因此只能评估局部路径几何。

## 任务

统计每个图像中的短 Li–Li 接触，并描述其沿各采样路径的变化。另行评估这些逐 hop 几何是否足以证明体相完全混合的固溶体，区分“缺乏证据”和“热力学上不可能”。

## 要求

有 CONTCAR 时使用 CONTCAR，否则使用 POSCAR。按周期最小镜像距离计算，距离严格小于 2.60 Å 时计为接触，每对 Li 只计一次。包括端点和内部图像，并依据完整接触序列得出各路径结论。评估体相固溶体时，说明所需的结构和热力学证据，以及这些 hop 几何是否提供了这些证据；在 `methods.md` 中解释依据与局限。不得由几何推断能量、活化势垒或体相热力学稳定性。

在 `/app/final/results.json` 中提供 `Li4_plus_delta`、`Li5_plus_delta` 和 `Li7_minus_delta` 的 `contact_series`，每行含 `hop`、`image`、`n_pairs`。`kinetic_conclusion` 中提供布尔值 `li7_short_contacts_absent_at_endpoints`、`li7_short_contacts_present_on_interior_images`、`li4_and_li5_start_already_have_short_contacts` 和 `bulk_solid_solution_required`。Li7−x 的 hop 名使用 `NEB_Li7-x`；其他路径使用图像的父目录名。另提交 `/app/final/methods.md`。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/assets/` | 各图像几何及跃迁级 VASP 设置。 |

读取 `/app/assets/` 下的几何及 hop 级 INCAR/KPOINTS。提交 `/app/final/results.json` 和 `/app/final/methods.md`。
