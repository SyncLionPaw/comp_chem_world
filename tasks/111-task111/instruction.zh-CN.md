# 任务：实现 RDKit 内部坐标约束

## 背景

从混合的距离、角度和带符号二面角约束生成构象，需要传播约束并采样几何，同时保持分子图和立体化学。精确的公共 API、数值规则和错误语义见 `/app/SPEC.md`。

## 任务

补全 `/app/rdkit_ic_constraints/`，实现适用于 RDKit 分子及规定几何约束的 `build_constraint_bounds` 和 `embed_with_constraints`。

## 要求

- 环境：使用容器 `PATH` 上的 Python。已预装 NumPy、pillow、RDKit、SciPy。不要自行安装额外软件包，也不要通过网络获取依赖。

支持距离、角度、带符号二面角及模糊距离约束，包括跨界二面角区间和 OR 备选。返回可靠且三角一致的距离下/上界矩阵；生成满足约束的完整、确定性构象系综，并保留原子顺序、分子图和立体化学。不得改变输入分子。按规定顺序区分输入验证错误、证书确认的不可行约束和未证实的生成失败。只能使用环境中已安装的依赖。

精确函数签名、输入 schema、数值包络/投影走廊、矩阵传播、支持的分子范围、容差、可重复性、异常层级和检查要求均以 `/app/SPEC.md` 为准。按该文档使用公共规格工具和测试。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/SPEC.md` | 公开函数与几何规范。 |
| `/app/rdkit_ic_constraints/` | 公开约束类型。 |
| `/app/rdkit_ic_spec/` | 参考接口及示例。 |
| `/app/public_tests/` | 公开测试。 |

规范：`/app/SPEC.md`。实现目录：`/app/rdkit_ic_constraints/`。只读公共规格模块与测试：`/app/rdkit_ic_spec/`、`/app/public_tests/`。提交完成的程序包。时间预算：28,800 秒。
