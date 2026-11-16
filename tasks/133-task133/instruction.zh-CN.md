# 任务：TNEP 偶极模型盲验证（给定资料 Table 1）

## 背景

使用所给原始模型预测四个水体系的偶极，并按给定资料 Table 1 报告所采用的物理口径。

## 任务

确定模型与体系的对应关系、参考点及归一化处理，设计并实现推理流程。题目不提供操作步骤或已经选好的科学约定。

公开材料位于包内 `environment/assets/inputs/`：预训练模型，以及下列仅含坐标、元素、晶格的验证集。当前布局在运行时也可通过 `/app/inputs/` 访问。

| system_id | 构型文件 | 每帧原子数 |
|---|---|---|
| h2o | test-positions-h2o.xyz | 3 |
| h2o_dimer | test-positions-h2o-dimer.xyz | 6 |
| h5o2plus | test-positions-h5o2plus.xyz | 7 |
| liquid_water | test-positions-liquid-water.xyz | 96 |

每体系 500 帧。标签未提供；不得从外部获取验证集标签或据其构造预测。选择并记录自己的工具、执行方法及精度，预测须对应本包构型。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 NumPy。不要自行安装额外软件包，也不要通过网络获取依赖。

### 精度与证据

以给定资料的发表 RMSE 作为各体系的精度参照；必须满足 `|log10(RMSE / published_RMSE)| <= 0.5`。数值须有限，数组形状、物理约定和哈希须一致。须实际运行所选模型，对本包构型生成预测。

引擎和实现路线由你选择。按下文要求记录实际工具与版本、构建过程和推理运行。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/environment/inputs/` | 本题的来源材料与科学输入。 |

写入 `/app/final/`：

- `results.json`，含 `engine`、`conventions`、`predictions`。
- 每体系一个 NPZ，键 `dipole`，形状 `(500, 3)`，单位 e·bohr，帧序不变。物理参考点和归一化须与该体系的给定资料 Table 1 口径一致。
- 非空 `build.log`、`run.log`，与 `engine.log_sha256` 一致。

`engine` 提供 `name`、`version`、`build_command` 和两个日志文件的 文件校验值。`predictions` 把四个 system_id 映射到提交内的相对文件路径。

`conventions` 必须声明你的判断。为避免自由文本解析歧义，使用以下接口词表，题目不替你选择：

- `h5o2plus`：`absolute-origin` 或 `relative-to-COM`。
- `liquid_water`：`per-cell`、`per-molecule` 或 `per-atom`。

每个 `conventions` 字段仅填所选词条，并在 `conventions` 之外的独立说明字段记录来源依据。
