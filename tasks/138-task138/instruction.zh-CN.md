# 任务：固定势能的导数、Hessian 与单位一致性

## 背景

随包提供一个已训练的 NewtonNet checkpoint，对应两个过渡态几何：`001`（10 原子）
和 `000`（16 原子），并给出模型规格与原子坐标。能量、力与解析 Cartesian Hessian
均来自同一个固定势能。在把这样的势能用于曲率相关工作之前，需要先证明它的导数关系
和单位是自洽的。

## 任务

评估这个固定势能的能量、力与解析 Cartesian Hessian 对两个几何是否相互一致、单位
是否正确，并给出数值证据。参考关系为：力是能量的负梯度；Hessian 的每一列是力向量
对该坐标的负导数；能量与力在刚体平移下不变；在绕 z 轴的正旋转下 Hessian 按
`R H Rᵀ` 变换（力按 `F Rᵀ` 变换）。不要根据本说明直接给出科学结论，请用你自己的
计算得出。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 ASE、JAX、matplotlib、NetworkX、NumPy、pandas、pillow、PyTorch、PyYAML、scikit-learn、SciPy、sympy。不要自行安装额外软件包，也不要通过网络获取依赖。

- 必须计算解析 Hessian；有限差分只作为验证证据，不能替代解析结果。
- 计算前先声明验证方案：有限差分步长取 5e-5、1e-4 或 2e-4 angstrom；每个几何选
  三个不同坐标分量且覆盖 x、y、z；平移向量长度取 0.05–0.20 angstrom；绕 z 轴的
  正旋转取 60、90 或 120 度。
  `validation_plan.json` 可按几何 ID 添加 `rotated_coordinates_angstrom`，明确给出各旋转 Hessian 实际使用的旋转坐标。
- 保持随包的帧顺序与 Cartesian 坐标顺序。单位用 eV、eV/angstrom 和
  eV/angstrom^2。
- 每个解析 Hessian 的对称偏离须不超过 2e-5 eV/angstrom^2；报告中每个残差都必须能
  按其定义式复现，精度要求见契约。残差按完整精度报告，不要四舍五入。
- 记录每次模型评估及其坐标哈希；坐标重复时复用已有的能量/力结果。全部计算限于
  4 次 Hessian 调用和 40 次能量/力评估。

### 输入与产物细则

输入位于 `/app/assets`：两个几何
（`case01_ts_geometries_001_000.extxyz`）、checkpoint、模型规格以及
`output-contract.json`（其中固定了文件名、schema、字段顺序、哈希与行数）。

把契约要求的交付物写入 `/app/final`：`validation_plan.json`、`efh.json`、四个
Hessian 矩阵、`diagnostics.csv`、`model_call_log.csv` 和 `report.md`。报告需说明
所做的检查、各残差的含义以及实际观测结果，包括你发现的任何不一致。

按各量的声明单位，能量及平移残差的绝对比较容差为 2e−8，力与 Hessian 比较及旋转残差的绝对比较容差为 2e−7。梯度有限差分比较采用绝对/相对容差 2e−6/1e−5，力与 Hessian 的比较采用 2e−4/1e−3。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/assets` | 给定科学输入或资源；格式和单位见任务要求。 |

| 路径 | 内容 |
| --- | --- |
| `/app/final` | 提交结果；内容与格式按上文要求。 |
