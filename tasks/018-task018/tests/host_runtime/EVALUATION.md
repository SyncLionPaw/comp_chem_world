# Harbor 执行版的验证范围

## 六个本地 Agent 测评

2026-10-30—31，使用 Harbor 0.25.0、Claude Code 2.1.267 和 deepseek-flash，各完成一次有效测评。六题均无 Harbor trial exception。

| Case | Task | 原生 reward | 结果与依据 |
| --- | --- | --- | --- |
| C01 | task 14 | 1 | PASS：RESP 拟合与隔离重放通过 |
| C02 | task 15 | 1 | PASS：拓扑、参数、周期模型及有限能量检查通过 |
| C03 | task 16 | 0 | 模型 FAIL：候选代码写死控制序列 ID D3，改名重放触发 KeyError |
| C04 | task 17 | 1 | PASS：簇提取重放、壳层成员、周期坐标与来源检查通过 |
| C06 | task 19 | 1 | PASS：电子态/适用域路由及改名重放通过 |
| C07 | task 20 | 1 | PASS：1 fs、2 ps 数值恢复与隔离重放通过，力场保持 |

C03 的中英文题面均要求分析不能依赖数据集名称或行序。测试仅改变控制序列 ID、CSV 文件名和排列顺序，数值及科学策略不变；候选代码引用固定 D3 导致崩溃。这是保留的真实模型失败，未修改答案或放宽评分。

原始测评的任务内容校验值如下；这些是历史运行绑定，不代表后续说明编辑后重新调用了模型：

| Task | 原始 Harbor task checksum |
| --- | --- |
| task 14 | `627d15acc99b96e2c5f6682dc098fcfc2c8122e18bfa03dddd2515af086345fc` |
| task 15 | `05b237b17c6f6158f24c61d554fee12abc8825edb6553d66b44a2cb932a4ab89` |
| task 16 | `4f393db02e3f8a8c4a60cb290ce8b12dc526861d661e66e469d6bd9a0e83697c` |
| task 17 | `c8c1cf70db5b4870829bc5514dac5a6b2c5217ef123f14c2d4dfcea4367f1079` |
| task 19 | `30674e1f2a512fbdd2a2640a8907e705960ccc30623b955cade504edd5576aad` |
| task 20 | `e78c39c2702bed14061cffee6204f917619c97ac9c3e2cb53a77ebe639ebe4c6` |

此后仅补全 task 15、task 18 中英文“文件”板块的路径，科学要求和评分器保持不变。原始测评、C03 失败及修复/清理证据保留在本机 `jobs/`，没有改写为新运行；原始轨迹、候选答案、会话日志和操作者连接信息不随此执行包上传。

## 独立安装与 HPC MVP

2026-10-31，移除同级 compchembench 目录/Python 包依赖，将必要 HPC 接入代码放入 bench03_hpc。全新目录、全新虚拟环境 frozen 安装通过，旁边无同级 checkout，环境中也没有该包；17 项主机回归通过。独立目录中的 C06 Oracle 得到 reward=1，无 trial exception。这是本地抽验，不是全部六题重新执行 Oracle。

C05 用独立版做过单 allocation MVP：1 CPU、256 MiB、2 分钟调度上限，计算节点读取并核对公开 72 原子结构；Slurm COMPLETED / 0:0。独立证据采集和评分运行正常，故意缺少完整科研提交时返回预期 reward=0，无 Harbor trial exception。核验无活动作业及完整采集文件哈希后，本次远端目录已删除。

**C05 完整八阶段 MD/ORCA、正式完整 Oracle 与远程 Agent 科研作答均未验证通过。MVP 不代表完整科研 PASS。** 本次上传的是带上述验证范围说明的执行代码，不宣称全七题已获得正式发布资格。

## 运行前提

依赖 Docker、README 指定的基础镜像、`compchembench-connectivity:hpc` 镜像、测评者共享的公共提交 JSON 和外部模型配置。Task 不使用专用 HPC TOML 或主机 SSH 文件挂载；可信采证由 runner 使用候选实际不可变镜像启动独立 helper。任务的科学输入、参考解和评分器随代码提供；根级 jobs、.release-work、provenance 和 NAS 均不是执行输入。此次上传没有新增付费模型或完整 HPC 计算。

## 旧执行包

此次上传将旧 case-* / 专用 runner 结构替换为当前 task 14–20 的独立 Harbor 结构。旧执行包及当时收据仍可从 [更新前 Git 快照](https://github.com/Mayerxjchen/CompChemWorld/tree/336a55d984ac80fd1b6eed4ae8f72f78e06403f7/03_autosolvateweb-explicit-solvation) 访问，不将旧收据用于当前执行代码。

## 目录整理（2026-10-31）

执行版根目录仅保留 task 14–20。HPC 主机接入及其锁定依赖移至 task 18/tests/host_runtime；原始测评与清理收据完整移至 bench 外的本机记录目录。原六题 Agent 与 HPC MVP 记录保持原始版本绑定；目录迁移不视为新的 Agent 或远程科学计算。
