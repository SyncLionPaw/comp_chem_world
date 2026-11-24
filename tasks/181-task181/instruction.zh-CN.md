# 任务：使用现有水委员会运行新的 MLMD 轨迹

## 背景

本题提供两个仅含几何的起始结构，以及四个固定的 DeepMD 基线检查点。

输入与可用资源按下文说明；需要自行获取的资料仍由任务执行者获取。

## 任务

在 300 K 下，为周期性 192 原子水体系运行两条全新的 20,000 步 NVT 轨迹。模型 0 提供 MD 力；模型 1–3 仅用于委员会偏差诊断。分别以 701 和 1701 初始化速度。不得替换为其他模型 checkpoint。

## 要求

- 环境：使用容器 `PATH` 上的 Python；所需科学计算包已预装。不要自行安装额外软件包，也不要通过网络获取依赖。

使用 HPC 时，按 `hpc` 的统一流程执行：探测已授权的目标，提交作业，等待终态，回收原生输出，再核验科学结果。

使用给定 LAMMPS 模板，步长为 0.5 fs，并每 100 步输出 thermo、dump 和 deviation。每次运行覆盖 0–20,000 步，产生 201 份时间对齐样本；体系为 12.4 Å 周期立方体、含 192 个原子。保持原子 ID 与类型对应关系稳定，位置、力、thermo 与 deviation 数值均有限。deviation 文件表头含 max_devi_f，每个样本有七列：步数及六个非负值。dump 坐标为 wrapped 且没有 image flags；不得据此推断 unwrapped transport。保留原生 LAMMPS 日志。

仅替换模板中的数据、四个模型、插件路径槽位及随机种子，其他设置保持不变。四个模型路径须为不同的绝对路径，并按成员顺序对应；插件路径也须为绝对路径。路径须为单行，不含模板标记或 LAMMPS 命令分隔符，且只能使用英文字母、数字、句点、下划线、加号、冒号、斜线和连字符；不得含空格、//、. 或 .. 路径分量。

每次运行的 render-manifest.json 须含 start_geometry_id（字符串；replica-0 为 0000，replica-1 为 0010）、start_geometry_sha256、lammps_input_sha256、data_sha256、model_sha256_by_member（按成员顺序排列的四个小写 文件校验值）、seed（整数 701 或 1701）和 runtime_bindings。所有文件校验值均使用小写。三个哈希分别对应几何 include、渲染输入和 start.data 的精确字节。runtime_bindings.start_data 含 path 和 sha256；runtime_bindings.models 含四个有序对象，字段为 member_index、path 和 sha256，须与 lammps.in 中路径及固定模型哈希相符。execution-manifest.json 须含 schema task181-app-execution-manifest/v1 和 replicas 数组，依次包含 {"replica":"replica-0","files":{...}}、{"replica":"replica-1","files":{...}}。每个 files 对象将除 render-manifest.json 外的所有运行文件映射为小写 文件校验值。这些候选端清单不能认证执行来源，且不要求候选自报主机或调度器信息。

**执行环境。** 遵循主机执行配置并使用其支持的软件环境。

### 输入与产物细则

起始几何、四个 checkpoint 和 LAMMPS 模板位于 environment/assets/v2/fresh-run/。按源行顺序将每个几何 include 转为 LAMMPS atomic data：O/H 类型为 1/2，质量为 15.999/1.008，192 个原子、两种类型；各轴边界分别写作 0.0 12.4 xlo xhi、0.0 12.4 ylo yhi 和 0.0 12.4 zlo zhi。使用 Atoms # atomic 段，坐标与源文件相差不超过 5.1e-12 Å。将 DEEPMD_LAMMPS_PLUGIN 设为站点插件路径，并从各 replica 目录运行 LAMMPS。

提交 runs/task181-mlmd-v2/replica-{0,1}/{lammps.in,start.data,render-manifest.json,log.lammps,dump.lammpstrj,model_devi.out} 和 runs/task181-mlmd-v2/execution-manifest.json。

## 文件

公开输入文件：

| 文件路径 | 说明 |
| --- | --- |
| `/app/environment/assets/v2/` | 两组初始结构、四个 DeepMD 检查点及 LAMMPS 模板。 |

| 路径 | 内容 |
| --- | --- |
| `/app/runs/task181-mlmd-v2` | 提交结果；内容与格式按上文要求。 |
