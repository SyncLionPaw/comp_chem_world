# 任务：比较模拟盒子组成与 SANS 长度尺度

## 背景

周期 XYZ 文件 `environment/assets/frame_late.xyz` 描述 LiTFSI 水溶液立方盒子，注释行给出边长（Å）。`experimental_sans.txt` 提供 SANS 峰范围，并以 `2π/q` 定义实空间重复尺度。

## 任务

确定盒子组成与质量摩尔浓度，将 SANS 峰范围换算为重复尺度，并与盒子边长比较。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 NumPy。不要自行安装额外软件包，也不要通过网络获取依赖。

质量摩尔浓度为每千克水中的 LiTFSI 摩尔数；`n_H2O_per_Li` 为水与锂的数量比。`sans_repeat_A` 按 `[2π/q_max, 2π/q_min]` 排列。`correlation_lengths_along_edge` 为盒子边长除以 q 窗口中点对应的重复尺度。若盒子边长大于该尺度，`cell_spans_multiple_repeats` 为 true；Li 与 TFSI 数量相等时 `charge_neutral` 为 true。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/environment/assets/` | 模拟晶胞与散射参考数据。 |

将结果写入 `/app/final/composition.json`：计数为整数，测量值为所述单位下的数值，标志使用 JSON 布尔值。字段：

`n_atoms`, `n_Li`, `n_TFSI`, `n_H2O`, `molality_mol_kg`, `n_H2O_per_Li`, `box_length_A`, `sans_repeat_A`, `correlation_lengths_along_edge`, `cell_spans_multiple_repeats`, `charge_neutral`。
