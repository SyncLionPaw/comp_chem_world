# 任务：由分子名称生成可复现三维结构

## 背景

SMILES 字符串只确定连接关系，不包含几何结构。生成三维结构是后续任何能量或性质计算的起点，而固定嵌入随机种子可使所得构象可复现。


## 任务

生成乙醇的三维原子坐标，并以标准 XYZ 格式保存该结构。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 ASE、NumPy、RDKit。不要自行安装额外软件包，也不要通过网络获取依赖。

- 从本题提供的名称到 SMILES 查找表中取得该化合物的 SMILES。
- 用 `Chem.AddHs` 添加显式氢，再以 `AllChem.EmbedMolecule(mol, randomSeed=42)` 嵌入单个构象，其余参数采用默认值。
- 不要再对嵌入结果做任何几何优化。
- 保留该流程产生的原子顺序和笛卡尔坐标系。坐标以 Å 为单位逐分量比较，绝对容差为 0.001 Å，相对容差为 0.00001。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/environment/assets/name_lookup.json` | 化合物名称到 SMILES 的查找表。 |

从 `/app/environment/assets/name_lookup.json` 读取名称到 SMILES 的查找表。

将结构以标准 XYZ 格式写入 `/app/final/out.xyz`。
