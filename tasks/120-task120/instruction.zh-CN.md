# 任务：分子名称到规范 SMILES 的转换

## 背景

不同化学信息学工具写出的同一分子可以有不同的 SMILES 表示，因此跨数据库比较结构需要一种规范化形式。RDKit 定义的规范化 SMILES 对给定分子是唯一的。


## 任务

确定 2-乙酰氧基苯甲酸（阿司匹林）的规范化 SMILES。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 NumPy、RDKit。不要自行安装额外软件包，也不要通过网络获取依赖。

- 从本题提供的名称到 SMILES 查找表中取得该化合物的 SMILES，不要依赖记忆中的结构。
- 以 RDKit 产出的规范化形式给出 SMILES：先解析该字符串，再用 RDKit 的规范化写入器重新序列化。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/environment/assets/name_lookup.json` | 化合物名称到 SMILES 的查找表。 |

从 `/app/environment/assets/name_lookup.json` 读取名称到 SMILES 的查找表。

将规范化 SMILES 写入 `/app/final/smiles.txt`。
