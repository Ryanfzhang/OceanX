# Coordinator dependency evaluation

## Predeclared scope

Use the production Coordinator graph and deepseek-v4-pro, with the original Campeche query
and /Users/ryanzhang/Code/CMEMS_oceanmind. Run five isolated first-dispatch probes sequentially,
then one control query with explicitly independent dataset observation and published-literature
questions. The probe stops before the first dispatch batch executes; no Expert analysis runs.
This is a comparison of dispatch decisions, not a full research-quality or latency benchmark.

## Evaluation criteria

- Count a dependency violation when parallel assignments require an unsettled definition or
  result being produced by another assignment, without an agreed common basis or an explicitly
  independent alternative-comparison design.
- Shared data alone is not a dependency. Explicit independent alternative comparisons are valid.
- A single assignment has no between-assignment parallel dependency; still separately assess
  whether it is a bounded subquestion and whether it prescribes methods/outputs.
- The control checks whether independent work can still be dispatched together. A serial control
  is conservative, not a scientific error, but weakens evidence of useful parallel scheduling.
- No automatic first-round single-Expert constraint follows from the counts. Five runs of one
  query do not establish behavior across research topics.

Code changes replace the Coordinator delegation paragraph, clarify cross-disciplinary supporting
work for Experts, and separate evidence insufficiency from interrupted execution in status display.
Existing quotas, error limits, review and kernel handling are unchanged.

## Results

### 结论：依赖调度符合本次标准，研究委派的完整目标仍未达到

六轮均使用 deepseek-v4-pro，首轮实际模型输入均包含此次新的委派段。六轮均成功捕获首批委派，实际 Expert 启动数全部为 0；测试批次正常退出。不把静态提示词测试等同于行为测试。

五轮原问题中，3 轮只派物理，2 轮派物理＋文献；未观察到把未确定的统计定义与依赖它的物理分析并行派出的情况（0/5）。独立对照正确并行派出物理＋文献（1/1）。共享数据本身不算依赖。

**但 4/5 原问题运行仍把接近根问题的范围交给物理专家，另一轮虽然收窄范围，仍指定具体诊断。没有一轮完整达到“窄子问题、方法由 Expert 选择”的目标。** 这不是“少派了人所以成功”；三次已经只有一个物理任务，问题仍然存在，因此本次证据不支持把“首轮单专家”当作粒度问题的修复。

这是对实际公开委派内容的人工评估，不是后台对科学问题新增的分类器。五次同题样本及一次明确独立的对照不能证明泛化，也没有足够的改前重复样本来计算提示词修改的因果效果。本轮没有在看到坏结果后继续改提示词或增加硬限制。

- **campeche-1**：单物理；无跨任务依赖；异常刻画与多机制相对贡献一起交付，接近根问题，仍有结果/方法清单。
- **campeche-2**：单物理；树把统计后续留待物理结果之后；首任务仍覆盖异常、形成、维持，指定输运与局地残差分解。
- **campeche-3**：物理＋文献，问题独立；物理缩小到目标刻画及初步特征，但明确列出涡度、温盐垂向结构和水团示踪量。
- **campeche-4**：物理＋文献，问题独立；公开说明将 B1–B3 合为一个物理任务，委派包含温度趋势、平流公式、残差与持续时间。
- **campeche-5**：单物理；将现象定义、形成、维持一起交付。具体算法较开放，但仍不是先回答一个窄问题，再决定下一步。
- **independent-control**：对照：物理处理数据季节结构，文献处理既有研究；不依赖新分析结果，正确并行。仅验证并行能力，不代表委派内容全面合格。

### Research tree 的证据边界

第 2 轮树草稿明确把统计后续放在物理结果之后；第 3 轮树草稿把后续机制诊断留到现象定义之后。这些公开计划与首轮调度可用于检查依赖。

但是第 4 轮公开说明、以及第 5 轮树草稿，都把现象刻画、形成和维持三个分支合并交给同一个物理 Expert。这说明“画了多个分支”不等于“按子问题逐步探索”。

本测试在首次委派工具执行前停止，**没有 Expert 结果，没有第二轮方向决定，不能评价树根据新证据更新是否有效**。最后一批工具中的 write_file 同样被拦截，其内容在证据文档中标为“拟写入的树草稿”，不声称已持久化或已执行。

### 耗时与 token（Coordinator 首次委派前，非完整研究）

| 运行 | 墙钟秒 | 模型调用数 | 输入 tokens | 输出 tokens | 输入内 cache_read | 模型调用秒合计 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| campeche-1 | 86.69 | 14 | 160,591 | 7,715 | 148,480 | 81.39 |
| campeche-2 | 213.28 | 19 | 366,636 | 17,191 | 346,496 | 174.98 |
| campeche-3 | 142.00 | 18 | 247,875 | 12,304 | 234,880 | 131.40 |
| campeche-4 | 102.55 | 9 | 97,273 | 9,643 | 86,656 | 97.08 |
| campeche-5 | 182.87 | 14 | 188,446 | 17,284 | 173,184 | 175.49 |
| independent-control | 52.88 | 7 | 67,785 | 5,378 | 58,496 | 50.94 |

合计 81 次模型调用，输入 1,128,606、输出 69,515，总计 1,198,121 tokens；其中 cache_read 1,048,192 **已经包含在输入中，不重复相加，也不能把它当成未缓存输入等价计费**。六轮墙钟相加 780.26 秒（约 13.0 分钟），不含轮次之间独立服务启动/退出等全部调度开销。

模型调用耗时来自 model_call_observations.duration_seconds；不能全部归为模型生成，包含服务/网络等待。总 token 也不是实际账单。

本次运行记录还显示执行环境搜索开销：例如第 2 轮先使用缺少库的默认 Python，随后多次查找解释器，最终采用 envs/ocean/bin/python 读取元数据。这个观察来自实际工具调用，不是静态推测；本轮没有修改执行环境。上表包含这部分开销，不应解读成单纯“构思委派”耗时。附录的模型数据摘要亦未经科学审核，不代表报告认可其中全部数据事实。

### 代码和前端改动

- 替换 Coordinator 委派段：先选子问题，再选专家；共享数据不等于依赖；依赖尚未知结果的问题不并行；不按专业名单各派一份。
- Expert 共用职责明确包括本子问题需要的数据检查、统计和图件。角色/Skill 是专长，不是方法的排他权限。
- 正常交付“证据不足”的 Coordinator 结论，执行状态为 completed，活动说明保留“现有证据无法确立所要求的结论”；不把它当作运行失败。
- 真正 incomplete 的卡片与详情标题显示 **Partial result**，保留具体中断/未完成说明。failed、blocked 不被整体改写成完成。
- 正常结论必须在请求正式完成后才显示完成；提交失败不能被提前准备好的结论掩盖。
- 未改变配额、错误限制、审核、内核或前端协议枚举。未重新打包桌面应用；已打包的应用需更新构建后才包含这些修改。

### 验证

- 后端相关回归：**63 passed**（一条 xarray/netCDF NumPy 弃用警告）。
- 前端相关回归：**35 passed**，含部分结果、已交付结论和真实失败的显示检查。
- TypeScript：tsc --noEmit 通过。
- 相关文件 git diff --check 通过。
- 前端测试使用 oceanx 环境的 ARM Node；最初默认 x64 Node 与现有 arm64 Rollup 不匹配，切换解释器后通过，未重装依赖。
- Coordinator 原题 5 次＋独立对照 1 次全部捕获派发后停止，未启动 Expert。

### 证据

[公开委派原文与树草稿](/Users/ryanzhang/Code/OceanX-v2/docs/testing/coordinator-dependency-messages-20260914.md) 保留全部六轮公开消息与委派参数，不含模型私有推理。

原始运行目录：output/coordinator-dependencies-20260914/。result.json 记录边界与退出结果，state/workspace.sqlite3 的 model_call_observations 提供逐调用计量。模型输入快照已核对六轮均收到新段落；不将原始私有推理字段复制到分析报告。
