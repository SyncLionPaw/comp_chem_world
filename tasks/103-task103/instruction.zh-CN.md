# 任务：由 VASP 输出重建锂迁移能量剖面

## 背景

已提供 Li33Ti40O96、Li41Ti40O96 和 Li55Ti40O96 中锂迁移的 VASP NEB 输出，包含压缩 OUTCAR 能量记录及 hop 级 INCAR/KPOINTS；未提供结构和路径分析文件。

## 任务

将每种组成的已给 hop 接成一条采样能量剖面。根据 OUTCAR 记录为每种组成选定一致的末态能量定义，并求相对首个图像的最高采样能量。

## 要求

使用所有含 OUTCAR 的图像并保持给定 hop/图像顺序。相邻 hop 在共享端点对齐；以首图能量为零，将相对能量换算为 meV，并把采样最大值报告为势垒。在 `methods.md` 说明所用能量、对齐方法和单位换算；不得推断未提供的结构或路径数据。

在 `/app/final/results.json` 中为 `Li4_plus_delta`、`Li5_plus_delta` 和 `Li7_minus_delta` 提供 `path_profile`；每行包含 `hop`、`image` 和有限数值 `energy_meV`，并在 `barriers_meV` 中给出各剖面的最大值。Li7−x 的 `hop` 使用 `NEB_Li7-x`；其他路径使用图像的父目录名。另提交 `/app/final/methods.md`。

每种组成的整条路径统一使用一种 OUTCAR 能量标签：`energy(sigma→0)` 或 `energy without entropy`。逐图像比较容差为 8 meV。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/assets/` | VASP 原生能量记录与 NEB 设置。 |

从 `/app/assets/` 读取输入。提交 `/app/final/results.json` 和 `/app/final/methods.md`。
