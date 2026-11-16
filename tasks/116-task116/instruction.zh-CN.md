# 任务：解释 TiS₂/LiTiS₂ 的 Bader 电荷变化

## 背景

提供了 GGA 和 HSE06 下原胞 TiS₂、LiTiS₂ 的 Bader ACF.dat 及对应 POSCAR。`CHARGE` 表示 Bader 盆中的电子数，不是氧化态；未提供 HSE06 重算或 `LORBIT` 投影布居。

## 任务

按泛函定量锂化引起的元素分辨 Bader 电子数变化。评估两个 S 原子的总增益是否大于 Ti 增益，以及这些 Bader 数值能否单独证明硫不参与氧化还原。

## 要求

对四个体系分别按元素计算平均 `CHARGE`。每个泛函内以 LiTiS₂ 减 TiS₂ 定义锂化变化；报告单个 S 的 `S_mean` 和原胞两个 S 的 `S_total=2*S_mean`。在 GGA、HSE06 中分别比较 Ti 增益和 `S_total`。不得将投影布居与 Bader 值混入同一差值。用增益比较描述电荷重分布。无论哪一项增益较大，Bader 电子数本身都不足以判定硫的氧化还原不活跃。

写 `/app/charges.json`，schema version 2，包含体系 `TiS2_GGA`、`TiS2_HSE06`、`LiTiS2_GGA`、`LiTiS2_HSE06` 及元素平均值；`deltas.GGA/HSE06` 中的 `Ti`、`S_mean`、`S_total`；结论 `GGA_S_total_gain_exceeds_Ti`、`HSE06_S_total_gain_exceeds_Ti`、`bader_alone_shows_sulfur_redox_inactive`；以及固定方法标签 `charge_quantity=bader_basin_electrons`、`sulfur_aggregation=mean_and_two_atom_total`。用提供的 renderer 生成 `/app/report.md`。

电子数比较的绝对容差为 0.002 个电子。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/environment/assets/` | Bader 布居及对应结构。 |

读取 `/app/environment/assets/<system_id>/` 下四个体系的 `ACF.dat` 和 `POSCAR`。提交 `/app/charges.json` 和 `/app/report.md`。
