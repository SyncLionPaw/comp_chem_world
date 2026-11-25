# 任务：运行三个全新的周期水 CP2K 标注计算

## 背景

本题提供三个周期水几何结构，每个含 192 个原子，并分别提供晶胞和 CP2K 输入模板。

输入与可用资源按下文说明；需要自行获取的资料仍由任务执行者获取。

## 任务

对每个几何运行一次全新的 CP2K ENERGY_FORCE 计算。使用 BLYP-D3、TZV2P-GTH、GTH-BLYP、500 Ry 截断和 60 Ry 相对截断。保持几何、晶胞和原子顺序不变；每份模板仅将 @PROJECT_NAME@ 替换为对应作业名。

## 要求

- 环境：使用容器 `PATH` 上的 Python；所需科学计算包已预装。不要自行安装额外软件包，也不要通过网络获取依赖。

使用 HPC 时，见 `/app/AGENTS.md`：用 SSH 别名 `hpc`，远程工作目录使用唯一的 `~/submit-jobs/<task>-<utc>-<rand>/`，再核验科学结果。

每份原生输出须含一个有限 Hartree 总能量、一个完整的 192 行 Hartree/Bohr 力块、正向 SCF 收敛记录、正常结束标记，以及与输入相符的几何和晶胞回显。力行保持输入顺序。

以 UTF-8 JSON 提交 final/native-labels.json，所有数值须有限。顶层结构为：

    {
      "schema": "task180-native-labels/v2",
      "unit_conversion": {
        "hartree_to_ev": 27.211386245988,
        "hartree_per_bohr_to_ev_per_angstrom": 51.422067476325886
      },
      "records": []
    }

records 恰含三个对象，按作业编号 0、10、19 排序。每条记录须包含 label_job_ordinal、exit_status（复制对应 exit-status.json）、input_sha256、geometry_sha256、native_output_sha256、atom_count、composition、cell_angstrom（按顺序排列的输入晶胞 3×3 矩阵）、scf、normal_end、method、energy_hartree、energy_eV、forces_hartree_per_bohr 和 forces_eV_per_angstrom。三个文件校验值字段均为对应渲染输入、几何 include 和原生输出精确字节的小写哈希。固定值为 atom_count 192、composition {"O":64,"H":128}、scf CONVERGED、normal_end true 及 method BLYP-D3 / TZV2P-GTH / GTH-BLYP / 500 Ry / REL_CUTOFF 60。力为输入顺序下的有限 192×3 数组。将原生 binary64 值按上述常数转换并保留足以往返的位数；转换值容差为 4 ULP。无论候选构建/运行 profile 如何，均按冻结的数值分档将同几何结果与固定原生参考比较：PASS 要求 |ΔE| ≤ 0.01 eV、力分量 RMS 差 ≤ 0.001 eV/Å、最大力分量差 ≤ 0.005 eV/Å；GRAY 使用 refs.json 中更宽的上限，超出则为 FAIL。构建/运行 profile 字段（包括编译器、CPU、日期和数据目录文本）仅作诊断。三组均 PASS 得 1 分；含 GRAY 且无 FAIL 得 0.5 分；UNQUALIFIED 或分档不完整得 0 分；数值 FAIL 拒绝提交。候选自报的执行元数据不能认证计算运行的位置或方式。

**执行环境。** 遵循主机执行配置并使用其支持的软件环境。

### 输入与产物细则

输入位于 environment/assets/v2/native-labels/label/cp2k-inc-{0000,0010,0019}/，各含 coord_n_cell.inc 与 cp2k.inp。项目名依次用 task180_label_0000、task180_label_0010 和 task180_label_0019。每个作业将渲染输入、原样几何 include、原生输出和进程退出状态写入 exit-status.json，成功时为 {"exit_code":0}保存到 runs/cp2k-label-v2/label-{0000,0010,0019}/{cp2k.inp,coord_n_cell.inc,output,exit-status.json}。另提交 final/native-labels.json。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/environment/assets/v2/` | 三组水体系初始几何及 CP2K 输入模板。 |

| 路径 | 内容 |
| --- | --- |
| `/app/final/native-labels.json` | 提交结果；内容与格式按上文要求。 |
| `/app/runs/cp2k-label-v2` | 提交结果；内容与格式按上文要求。 |
