# OceanX 修复方案（带版本控制）

**方案版本：v1.2（2026-10-03）**
**状态：Owner 已确认 v1，包括第 4 节的细节决定，可以交给 Codex 执行。v1.1 没有改任何包，只并入了原交接文档，并把 R3 出现异常时的做法改为只报告。v1.2 给 A1 补了一种情况，见第 3 节。**
基于提交 `88cab8b`。问题记录见 `OCEANX_E10_DIAGNOSIS_2026-10-03.md`。
分工：Claude 负责方案和审核，Codex 负责执行，Owner 负责提交每个版本。

## 1. 这个文件怎么用

- 改动按“包”做，一个包对应一次提交。Codex 做完一个包后填写下面的进度表，由 Owner 提交，再把提交号填进表里。
- 要回退某个包，就 `git revert` 它的提交。不改历史，不强推。
- 方案内容有变化时，在“方案版本记录”里加一行并升版本号；不要直接改已批准的条目。
- 表里没有的事情不做。遇到方案没覆盖的情况，写进本文件末尾的 Log，等 Claude 处理。
- 这些东西不能碰：
  - 数据、`download/data_manifest.json`、评分标准和参考答案；
  - 研究策略 `v2-nested` 和 60 次调用上限；
  - 学习库和 skill 里的学习区域；
  - 沙箱的严格程度和网络权限。
- 隐私：CMOMS 是私有数据。不提交它的数据或由它算出的任何内容，也不发给外部服务。评分标准、参考答案不给 agent 看。
- 运行进行中不改代码。每次重跑用新的实验名。行为有变化时，同步更新 `RUNNING.md` 或 `README.md`。
- 每个包先写一个修复前会失败的测试，再做最小改动，然后跑全量测试：

  ```bash
  PYTHONPATH=src python -m pytest tests benchmarking/tests -q -p no:cacheprovider
  ```

  `benchmarking/tests/test_run_claude.py::test_timeout_kills_children_retains_outputs` 对时间敏感，失败时先重跑一次再判断。

## 2. 进度表

| 包 | 内容 | 状态 | 提交 | Claude 审核 |
|---|---|---|---|---|
| A1 | 报告不被没改报告的尝试覆盖 | v1.2 已提交 origin；服务器同步见 Log | 991466e（A1） | 通过，v1.2 已复核。见 Log。 |
| A2 | 节点绑定不再悄悄失败 | 已本地提交；未推送 | a3b9a4d（A2） | 通过，可以提交。见 Log。 |
| A3 | 草稿图不算正式结果（交互模式） | 已审核；Owner 授权提交 | 本提交（A3） | 通过，可以提交。见 Log。 |
| A4 | 只有用户明确要图才补图 | 待做 | | |
| B | 无界面和 benchmark 运行只交付普通图片，不暴露绘图接口 | 待做 | | |
| E | 文献咨询由 Coordinator 按需决定；咨询不做数据分析 | 待做 | | |
| D | 已保存数据的清单 | 待做 | | |
| C | 完整的绘图接口说明（交互模式） | 待做 | | |
| F | 记录与披露（不改行为） | 待做 | | |
| R3 | 服务器开跑前检查，然后重跑 E10（`methods-oceanx-flash-r3`） | 等 Owner 通知 | | |

执行顺序：A1 → A2 → A3 → A4 → B → E → D → C → F → R3。A1 没合入之前不要启动任何运行。

## 3. 方案版本记录

| 版本 | 日期 | 变化 |
|---|---|---|
| v1 | 2026-10-03 | 第一版。依据 Owner 的四个决定，见第 4 节。Owner 已确认全文，包括五项细节决定。 |
| v1.1 | 2026-10-03 | 并入 `CODEX_HANDOFF.md` 里仍然有用的部分（规则、基准、运行步骤、检查表、Log），并删除该文件。R3 出现异常时改为只报告，不再有预先批准的修复。各个包的内容不变。 |
| v1.2 | 2026-10-03 | A1 补充一种情况：沿用原报告、又没有结束语时，回执也要写明这次尝试没有新产出，并给出原因。v1 的文字漏了这种情况。另外明确：额外情况只写进本文件的 Log，不再另建 `CODEX_HANDOFF.md`。 |

## 4. Owner 的决定

1. benchmark 只交付普通图片，并且不暴露 OceanX 的绘图接口。
2. 补图不单独限制调用次数。绘图接口的说明给够，任务就不该用到 60 次。
3. 做“已保存数据的清单”。
4. 文献查询不是必做步骤，由 Coordinator 决定。

以下几项没有批准：评审打分角色、研究树深度或委派次数上限、补图或文献 Expert 的调用上限、共用 kernel、可视化 Expert、新的通用数据格式、滚动调度。

Owner 同时确认了五项细节（2026-10-03），执行时不用再问：

- 普通图片模式用环境变量 `OCEANX_FIGURE_DELIVERY=static` 开启，由 benchmark 启动脚本设置。桌面版没有这个开关，行为不变。
- 节点 `outputs/` 目录下的图片文件都算已交付的图，试验性的图放在 `scratch/`。
- Search Expert 在咨询里只查资料，不分析任务数据。
- 数据清单每个目录最多列 12 个文件，总量约 4,000 字符。
- 完整的绘图说明放在文件里，提示里只留简短规则和文件位置。

## 5. 对诊断文档的审核结论

| 条目 | 核对代码后的结论 | 对应的包 |
|---|---|---|
| P01 上一次的工作没有被接上 | 成立。重复尝试和子节点只拿到目录路径。 | D |
| P02 benchmark 沿用了交互图的交付要求 | 成立。 | B |
| P03 绘图说明不完整 | 成立。说明里只有 3 个例子，`ScientificPanel` 有 11 种图层方法；`heatmap` 和 `categories` 不接受 Expert 猜的参数；`spatial_map` 只允许一个 `field2d` 图层。 | C |
| P04 补图按完整尝试执行 | 成立。按决定 2，不加调用上限。 | A1、B、C |
| P05 “本次是否更新了报告”的判据 | 成立，而且 `88cab8b` 让它更糟，见 9.1。 | A1 |
| P06 文献咨询是预设步骤 | 成立，见 `OCEAN_EXPLORATION_POLICY` 和 `research_team_policy`。 | E |
| P07 咨询扩展成了数据分析 | 服务器证据成立。代码上也允许：Search Expert 有两个运行代码的工具。 | E |
| P08 尝试没绑定到节点 | 原因已有数据支持，见下面的说明。 | A2 |
| P09 调用上限不等于交付状态 | 成立。 | F、R3 报告 |
| P10 对比口径 | 成立。 | B、F |
| 4.8 测试图成了正式结果 | 已确认。`TaskResultStore._agent_views` 会列出所有 `.nc` 仍然存在的已声明视图。 | A3 |
| 9.1 兜底会覆盖报告 | 已在 `88cab8b` 上复现：补图任务没动 `report.md`，最后只说一句话，完整报告就被这句话替换了。 | A1 |
| 9.2–9.4 | 成立。 | F |
| 9.5 内层 30 秒停止等待 | 成立。按 Owner 之前的决定不改。 | 无 |

**P08 的依据：**
- 未绑定那次尝试的目录是 `ocean-process-731940c582`。
- 它正好等于 `expert_agent_key(task_f07113931f5e4442be824e5fcaa74ccf, ocean_process_expert, node_id="B1.3.1.1.1")`。
- 未绑定的尝试只能从委派文字里的第一个节点号得到标识，所以委派文字里写了这个节点。
- 因此失败的只可能是 `tree.has_node`。节点又是在同一分钟内创建的，说明绑定检查发生在节点写入之前。

## 6. 各个包的做法

### A. 交付的正确性

**A1. 没改报告的尝试不能覆盖已有报告。** 位置：`research/graphs.py` 的 `expert` → `receipt`。

- 本次尝试改了 `report.md`：照常交付，行为不变。
- 本次没改，但有结束语：只有下面三种情况，才把结束语存为报告。
  - 节点还没有非空的报告；
  - 角色是 `scientific_discussion_partner`；
  - 结束语本身就是一份报告，即 `report_summary(closing)` 非空。
- 其他情况下，只要节点已有非空报告，就原样交付它：
  - 回执带上它的路径和它自己的 Summary；
  - 挂到研究树时用这份 Summary；
  - 回执末尾加一行 `This attempt left the report unchanged and ended with: <closing>`。这一行只给 Coordinator 看，不传给 `attach_result`。
  - （v1.2）没有结束语时，回执末尾改为加 `This attempt left the report unchanged and gave no closing answer: <原因>.`。原因和 `_missing_report` 用同一套说法：`it reached its 60-call limit` 或 `it stopped after N model calls`，由同一个辅助函数给出。不这样做的话，一次用满调用却没有产出的重复尝试，回执会和成功交付一模一样。
- `_earlier_attempt` 的提示补一句：原报告仍然是这个问题的报告，只改这次工作改变的部分，不要重写。
- 测试：以上三种情况，写在 `tests/test_oceanx/test_native_subagents.py`。（v1.2）再加两种：沿用原报告且没有结束语；沿用原报告且第 60 次调用只输出了工具乱码。

**A2. 节点绑定不再悄悄失败。** 位置：`research/delegation.py`。

- 工作区里已有“等待节点写入”的改动（`NODE_WAIT_SECONDS`、`_awaited_node`）和两个测试，保留。
- 新增：`task` 调用显式传了 `node_id`，等待结束后树里仍然没有这个节点时，不启动 Expert，返回错误消息：
  `Not started: research-tree node <id> does not exist. Add or select it with update_research_tree, then delegate again.`
- 只从描述文字里推断出来的节点号不拒绝，仍按未绑定运行。文字里可能碰巧出现像节点号的字符。
- 不在回执阶段猜节点来补挂报告。
- 测试：显式的未知节点被拒绝，并且没有调用 handler；推断出的未知节点照常运行。

**A3. 草稿图不算正式结果（交互模式）。**

- `TaskResultStore._agent_views` 跳过文件名以 `_` 或 `.` 开头的输出。
- 在绘图说明里写明这条规则（见 C）。
- 测试写在 `tests/test_oceanx/test_explicit_figure_delivery.py`。

**A4. 只有用户明确要图才补图。**

- 两种模式下，`COORDINATOR_VISUAL_DELIVERY_POLICY` 都写明：那一次补图只针对用户问题里明确要求的图。
- Coordinator 自己在委派里写的要求不算。

### B. 无界面和 benchmark 运行：只交付普通图片

**开关**

- 环境变量 `OCEANX_FIGURE_DELIVERY`，取值 `interactive`（默认，桌面版行为不变）或 `static`。
- 只在一个辅助函数里读取它。
- `benchmarking/server/run_oceanx.py::backend_environment` 把它设为 `static`。
- `arm_record` 记录 `figure_delivery`。

**什么算交付**

- `static` 模式下，节点 `outputs/` 目录里任意层级的图片文件都算已交付的图。支持 `.png`、`.jpg`、`.jpeg`、`.svg`、`.pdf`。
- 试验性的图放在工作目录 `scratch/`。

**登记**

- `TaskResultStore.list` 只在 `static` 模式下把这些文件列为 `kind="file"` 的结果，写法参照 `_agent_view_record`：
  - `agent_run_id` 是 Agent 的标识。
  - `content` 包含 `agent_key`、`result_key`、`output_path`、`render_status: "static"`、`preview_file`、`workspace_files`。
  - 附一个带大小和 sha256 的 `TaskResultFile`。
- 跳过以 `_` 或 `.` 开头的文件。
- `collect_oceanx.py` 现在就会把 `preview_file` 当作图收集，并改写引用。只补一个收集测试，不另写一套扫描。
- `cache_cleanup._published_paths` 像保护已发布视图一样保护这些文件。

**回执**

- `static` 模式下，`receipt` 列出该节点的这些记录。
- `format_expert_receipt` 输出 `Saved figures (cite these paths):`，后面是每张图的绝对路径和标题。

**不暴露绘图接口**

`static` 模式下，下面每一处都换成不出现接口名的版本：

| 位置 | `static` 模式下的内容 |
|---|---|
| `runtime.py::OCEAN_EXPERT_WORKSTREAM_POLICY` | 最终图用 matplotlib 存成 PNG，放在 `OCEAN_OUTPUT_DIR`，这个文件就是交付物。在 `report.md` 里紧跟结论引用文件名。保留“图的科学表达由 Expert 负责”和“陆地、域外要掩膜”的规则，不出现接口名。 |
| `graphs.py::build` | 去掉这几处：`Result API reference` 一行、`ScientificFigure.save` 一句、`Figure API (...)` 整块、调色板一行、`[agent/result1]` 绑定段落、`.preview.png` 说明。加上存 PNG 的说明。 |
| `native_backend.py::task_backend` | 不写 `.runtime/result-api.md`。 |
| `tools.py` 里 `ocean_expert_run_code` 的描述 | 改为“最终图存为 PNG，放在 OCEAN_OUTPUT_DIR”。 |
| `COORDINATOR_VISUAL_DELIVERY_POLICY`、Coordinator 的两段后缀、`runtime.py` 里“只引用 Published results”的规则 | 回执的 Saved figures 里列出了图，就算交付。引用图时用那里列出的路径，不编造路径。 |
| `STANDARD_EXPERT_POLICY` | 去掉 `.preview.png` 那一句。 |
| skill `scientific-figure-design` | 不放进准备好的 skill 库（`prepare_skill_library`）。 |

kernel 启动代码和结果运行器里对 `ScientificFigure` 的 import 可以保留，模型看不到它们。

**测试**

- `static` 模式下，Expert 和 Coordinator 的提示、工具描述、skill 库里都不出现这些字样：`ScientificFigure`、`Figure API`、`result-api`、`Published results`、`bracket`、`Workbench`、`.preview.png`。
- `outputs/` 下的 PNG 在 `static` 模式下被列为 `file` 结果，在交互模式下不列。
- 回执里列出它的路径。
- 收集器的测试夹具里，它出现在 “Collected figures” 下。
- `backend_environment` 和 `arm.json` 都带有这个模式。
- 交互模式原有的测试保持通过，不做改动。

### E. 文献咨询按需进行

- `runtime.py::OCEAN_EXPLORATION_POLICY`：把“开头就启动一次文献咨询”那句改成下面的意思。
  - 先做现有数据能回答的问题。
  - 只有当研究问题依赖某个定义、方法或已发表的机制，而数据说明里没有讲清楚时，才咨询 Search Expert。
  - 咨询与数据问题并行，不排在数据问题前面。
- `research_team_policy`：咨询是可选的，不再写“一次独立的 Search Expert 咨询”。
- `team/profiles.py` 里 Search Expert 的说明加上范围限制：
  - 咨询只读资料并汇报，不分析任务数据。
  - 资料有冲突，或者需要数值验证才能判断时，说明情况后停下，由 Coordinator 把验证派给数据 Expert。
  - 只有委派明确要求复现或下载数据时，才运行代码。
- Coordinator 的提示要保持在 `tests/test_oceanx/test_bounded_delivery_policy.py` 的长度限制（5,000 字符）以内，并更新该文件里对措辞的断言。

### D. 已保存数据的清单

- **目的**：重复尝试和子节点直接知道前面的节点存了什么，不用重新查看文件。
- **位置**：在 `ExpertCodeExecutionService` 上加一个方法。它在沙箱里以只读方式对某个 Agent 的 `outputs/` 和 `scratch/` 运行 `analysis_probe.py`，做法参照 `get_task_dataset_context`。
- **每个文件的内容**：
  - 数组文件：变量、各维度的名字和大小、`units`、`long_name`，以及文件的 `title` 或 `description`。
  - 表格文件：列名和行数。
  - `.npz` 文件：数组名、形状、类型，只读文件头。这部分要在探测脚本里新增。对象数组标注为“需要 `allow_pickle`”。
- **缓存**：存到 `<agent>/.runtime/data-index.json`，以所列文件的路径、大小、修改时间为键，有变化才重算。
- **进入提示**：
  - `graphs.py` 的 `_earlier_work` 和 `_earlier_attempt` 在每个目录路径后面加上清单。
  - 每个目录最多 12 个文件，先列 `outputs/`，再列 `scratch/` 里最新的。
  - 每个文件约 200 字符，总量约 4,000 字符，并注明省略了多少个文件。
  - 探测失败时只留目录路径，记一条日志，不阻止 Expert 启动。
- **规则**：在 `OCEAN_EXPERT_WORKSTREAM_POLICY` 里加一句：每个保存的变量写上 `units` 和 `long_name`，文件写一行 `title`。
- **测试**：
  - 探测脚本能描述同一目录里的 NetCDF、CSV 和 `.npz`。
  - 缓存被复用。
  - 提示里的清单不超过上面的限制。
  - 探测失败不影响 `build`。

### C. 完整的绘图接口说明（交互模式）

- 提示、`.runtime/result-api.md` 和 skill 用同一份说明，这份说明由 `scientific_view.py` 生成。内容包括：
  - 构造函数；
  - 每种 `plot_kind` 及其限制；
  - `panel(...)`；
  - `ScientificPanel` 每个公开图层方法的准确签名，用 `inspect.signature` 取得；
  - 每种 `plot_kind` 一个可运行的例子；
  - 草稿规则（A3）。
- 系统提示里只留简短规则和文件位置：“完整说明在 <路径>，画第一张图之前读一遍”。“完整”这个说法由下面的测试来保证。
- 测试：
  - 说明里列出了每个公开图层方法和每种 `plot_kind`。
  - 每个例子都能在临时的 `OCEAN_OUTPUT_DIR` 里运行并保存。
  - skill 里的例子同样能运行。

### F. 记录与披露（不改行为）

- `evaluation/evaluate.py::code_failures` 的说明改成只描述类别，不归因：只读拒绝可能是沙箱在正确地保护其他节点的文件，超时可能是代码本身慢。
- `RUNNING.md` 和 `EVALUATION.md` 写明四点：
  - OceanX 的 benchmark 运行只保存普通 PNG 图，不暴露绘图接口。
  - Expert 的最后一次调用可能多发一次请求；上下文压缩请求单独计数。两者都记在账本里。
  - 研究预算是运行设置，会改变 Coordinator 的行为。
  - Finch 没有文献搜索；Claude 取决于它的工具配置；OceanX 按需咨询。

## 7. R3：怎么跑、看什么、出了异常怎么办

R3 只在 A 到 F 全部提交、通过 Claude 审核，并且 Owner 通知之后才跑。
它带着 B、E 这些行为变化，所以和 r1、r2 不是严格的 A/B 对比，报告里要写明这一点。

### 7.1 已有的提交和基准

| 提交 | 内容 |
|---|---|
| `8df7791` | 可写目录里的只读路径不再生效；Linux 上 kernel 能启动；kernel 的输出写进 `kernel/kernel.log`。 |
| `e9f490e` | kernel 测试改用解析后的解释器路径。 |
| `6cbd4f0` | 每个研究节点一个目录和一个 kernel；kernel 在每次尝试结束时关闭；Expert 被告知上级节点和依赖节点的目录。 |
| `88cab8b` | 第 60 次调用直接写报告，输出是工具乱码时重试一次；没写报告时把结束语存为报告；重复尝试被指向之前的报告和文件；回执显示已用时间，预算用到 75% 后不再开新委派；开跑前检查 kernel；运行记录给出失败分类。 |

| | r1（`f82bc4a`） | r2（`6cbd4f0`） |
|---|---|---|
| 观察时刻 | 约 70 分钟 | 约 66.6 分钟，当时仍在运行 |
| 模型调用 | 581 次，83% 的时间有调用在跑 | 440 次，72% |
| 代码执行 | 326 次，61 次失败，其中 34 次是 kernel 启动失败、1 次超时。之后扫描到 355 次：321 次是 shell，kernel 没有一次成功。 | 215 次：194 次成功、20 次失败、1 次超时；44 次用 kernel，171 次用 shell。 |
| 只读错误 | 32 行，其中 26 行在自己的 `outputs` | 0 |
| Agent 目录 | 整棵树只有 3 个 | 每个节点各一个 |
| 交付问题 | B1.3.1 尝试了 3 次；B1.4.1.1 用满 60 次调用，没有报告。 | B1.3.1.1.1 第一次尝试没绑定到节点，被重派；B1.3.1.1 的补图用了 54 次请求、约 6.4 分钟。 |
| 其他 | | 文献咨询约 17.8 分钟、53 次请求，其中两次执行等待共约 9 分 40 秒；研究树深 5 层。 |

这些都是运行中途的快照。完整数字以 inventory 重新生成的 `run_record` 为准。

### 7.2 运行步骤

在 Linux 服务器上做，环境是 `oceanx-bench`，目录是 `/home/mafzhang/code/OceanX`。

1. pull，确认 `git log -1` 是 Owner 指定的提交。
2. 开跑前检查，必须输出 `"environment_ready": true`：

   ```bash
   python benchmarking/server/check_setup.py --agent oceanx
   ```

3. 跑只在 Linux 上执行的测试。macOS 会跳过它们，所以必须在这里通过：

   ```bash
   PYTHONPATH=src python -m pytest tests/test_sandbox tests/test_oceanx/test_persistent_kernels.py tests/test_oceanx/test_sandbox_self_check.py -q -p no:cacheprovider
   ```

4. 在 `benchmarking/.env` 里只改下面这些，其他设置和 r1、r2 保持一致：
   - `BENCH_EXPERIMENT=methods-oceanx-flash-r3`
   - `BENCH_SUITE=evolution`、`BENCH_EVOLUTION_SET=`、`BENCH_TASKS=E10`
   - `BENCH_MODEL=deepseek-flash`、`BENCH_TIMEOUT_SECONDS=10800`
   - `BENCH_OCEANX_MAX_PARALLEL_EXPERTS=2`、`BENCH_RESUME=false`

   然后在 tmux 里运行 `python benchmarking/server/run_oceanx.py`。
5. 核对 `inputs/queries.jsonl` 里 E10 的问题文字和数据集与 r1、r2 相同。不同就不能对比：报告这一点，然后停下。
6. 给 r1、r2、r3 各生成一次运行记录，把命令里的 `r3` 换成对应的名字：

   ```bash
   python benchmarking/evaluation/evaluate.py inventory --runs /import/home3/share/oceanx-bench/methods-oceanx-flash-r3/runs/OceanX --out /import/home3/share/oceanx-bench/methods-oceanx-flash-r3/eval/inventory
   ```

7. 数一下 r3 里 kernel 和 shell 各执行了几次、有多少个 Agent 目录（只读）：

   ```bash
   python - /import/home3/share/oceanx-bench/methods-oceanx-flash-r3/runs/OceanX <<'EOF'
   import sys
   from pathlib import Path
   root = Path(sys.argv[1])
   runs = [p for p in root.glob("*/attempt-*/workspace/*/*/agents/*/.runtime/executions/*") if p.is_dir()]
   shell = sum((p / "code" / "command.sh").is_file() for p in runs)
   agents = {p.parents[2] for p in runs}
   folders = [p for p in root.glob("*/attempt-*/workspace/*/*/agents/*") if p.name != "coordinator"]
   logs = [p for p in root.glob("*/attempt-*/workspace/*/*/agents/*/kernel/kernel.log") if p.stat().st_size]
   print(f"code runs {len(runs)}: kernel {len(runs) - shell}, shell {shell}; "
         f"agents with code {len(agents)}; agent folders {len(folders)}; non-empty kernel logs {len(logs)}")
   EOF
   ```

### 7.3 检查表

把 r1、r2、r3 的 `run_record.md` 放在一起看。

| # | 检查项 | 合格线 |
|---|---|---|
| 1 | 开跑前检查和 Linux 测试 | 全部通过 |
| 2 | kernel 启动失败 | 0 |
| 3 | 指向自己目录的只读失败 | 0 |
| 4 | 没有报告的尝试（所有节点合计） | 0 |
| 5 | 未绑定的尝试：Expert 的模型调用里 `node_id` 为空，文献咨询除外 | 0 |
| 6 | 报告被更短的结束语替换 | 0 |
| 7 | 同一节点的最多尝试次数 | 不超过 2 |
| 8 | 状态为 `completed`，有最终报告和 `answer.md` | 是 |
| 9 | 总时长 | 少于 180 分钟；约 135 分钟之后没有新委派 |
| 10 | Agent 目录和研究树节点 | 每个节点和角色一个目录，没有两个节点共用 |
| 11 | 图 | 报告：回执和收集结果里列出了哪些图；有没有补图任务，用户的问题是否明确要了这张图 |
| 12 | 文献咨询 | 报告：有没有发生；如果有，它的耗时和调用数、数据任务等了它多久、Search Expert 有没有对任务数据运行代码 |
| 13 | 重复尝试和子节点 | 报告：第一次分析执行之前用了多少次模型调用，与 r2 对比 |
| 14 | 第 60 次调用 | 报告：有没有结束语被存为报告，有没有触发纯文本重试 |
| 15 | 最长的串行链 | 报告：深度和每层的耗时 |
| 16 | 代码失败 | 报告：“代码”类失败占全部执行的比例；kernel 和 shell 各多少次 |
| 17 | 总时长和模型调用数 | 报告：与 r1、r2 对比 |

### 7.4 出了异常先看哪里

以下情况都只报告，不改代码。把证据写进 Log，由 Claude 决定怎么改。

| 现象 | 先看哪里 |
|---|---|
| 开跑前检查或 Linux 测试失败 | 错误信息里带着 kernel 自己的输出。`bwrap: execvp ... No such file or directory` 说明解释器路径没有被挂载；`Parent appears to have exited` 说明 kernel 又拿到了父进程号；`Read-only file system` 说明只读规则退回了旧行为。这时不要开跑。 |
| kernel 启动失败 | `code_executions.result_json` 里的 `error`，以及该 Agent 的 `kernel/kernel.log`。 |
| 只读失败 | stderr 里的路径。路径在自己的目录内，是代码退回了旧行为；在别的 Agent 目录或数据目录里，是设计如此，只需报告次数和节点。 |
| 有尝试没交报告 | 回执的 `Result:` 一行、第 60 次调用的原始回复、`backend.log` 里的模型服务错误。 |
| 同一节点尝试 3 次以上 | 每次回执的 `Result:` 一行。分清是 Coordinator 认为科学上还不完整，还是失败之后的重试。 |
| 超时、没有最终报告，或预算停止后仍有委派 | 运行 `grep -a -o "Research status: [^\"]*" -r <attempt>/state \| tail` 看预算有没有传到。再看有没有出现 `Not started: most of the research time budget`。 |
| 两个节点共用目录，或很多委派没绑定 | 研究树事件里 `binding` 为 `inferred` 和 `unbound` 的数量，以及显式 `node_id` 被拒绝的次数。 |
| 代码失败多 | 按类型分组：形状或广播、名字或键、import、其他，每类举两个例子。不要手写 skill、lesson 或工具，这些由 meta-agent 负责。 |

### 7.5 报告格式

在 Log 里写三部分：

1. 检查表，r1、r2、r3 并排。
2. 遇到的每个异常和它的证据：路径、计数、简短摘录。
3. 留给 Claude 的未决问题。

测量之前不对速度提升下结论。全部合格也不要自行启动正式运行、调整并发或推理设置。

## 8. Log

Codex 在这里追加记录，最新的放在最上面。每条写：日期、做了哪个包或遇到什么情况、证据、改动、测试结果。

### 2026-10-03 — Owner 授权提交 A3，然后开始 A4

- 本次提交仅包含审核通过的 A3：`task_results.py`、`expert_execution.py`、
  `research/graphs.py`、`test_explicit_figure_delivery.py`、`README.md` 和本方案。
  其余 benchmark/reset/Finch 改动保留，不纳入提交。
- 沿用下面已完成的独立审核与全量测试结果，不新增 A3 行为；C 包的措辞意见仍留给 C。
- 提交后只开始 A4，完成后停下等待审核与 Owner 提交，不启动 benchmark。

### 2026-10-03 — Claude 审核 A3：通过，可以提交

- **实现符合方案。**
  - `TaskResultStore._agent_views` 跳过文件名以 `_` 或 `.` 开头的已声明视图，子目录里的也一样。
  - 草稿文件和预览留在磁盘上，不删除。
  - 规则写进了 `FIGURE_API_CONTRACT`，提示和 `.runtime/result-api.md` 都会带上。
- **核对了会不会和 Expert 看到的信息矛盾。** 运行代码的工具只返回保存了哪些文件，不会说“已发布”。回执和 benchmark 收集器都通过 `TaskResultStore.list` 取结果，草稿在两处都被排除。
- **独立验证。** 去掉 `task_results.py` 的改动后，4 个草稿测试失败、3 个通过。全量测试 895 个通过、8 个跳过，测试前后工作区一致。
- **留给 C 包处理的一处措辞。** 草稿规则以 “In interactive mode” 开头，而 Expert 并不知道有“模式”这个概念。重写绘图说明时把它改成直接的用法：试验图用下划线开头的名字保存，最终图用普通名字。这不影响本次提交。
- A2 的提交 `a3b9a4d` 还没有推送。
- 下一个包是 A4。

### 2026-10-03 — Codex 完成 A3（待审核与 Owner 提交）

- A2 已按 Owner 指令单独本地提交为 `a3b9a4d`，提交名 `A2`，仅包含下面列出的四个文件。
  本轮没有推送或服务器操作，其余 benchmark/reset/Finch 改动仍原样保留。
- 先在 `test_explicit_figure_delivery.py` 写回归测试：`_draft.nc`、`.draft.nc` 以及
  子目录里的两种同名草稿，修复前都被列为正式结果：**4 failed、3 passed**。
- 最小过滤只在 `TaskResultStore._agent_views`：对声明的输出先验证相对路径，
  文件名以 `_` 或 `.` 开头就跳过，不读取它的 NetCDF，也不生成或返回结果记录。
  不删除草稿数据、预览或保存事件；普通文件名的交付流程保持不变。
- `FIGURE_API_CONTRACT` 新增一条共用的草稿规则，Expert 绘图提示引用这条规则；
  现有 `.runtime/result-api.md` 会随整个 contract 自动带上它。`README.md` 同步说明。
  没有提前实现 C 的完整接口说明，也没有改 A4、静态模式或科学分析逻辑。
- 针对性测试：**7 passed**（17.94 秒），覆盖根目录与子目录的两种草稿前缀、
  普通图正常交付、标题前缀不影响交付、重复列表与缓存，以及草稿与预览仍保留。
  原有“显式保存后后续执行失败，图仍保留”和“未声明的文件不列出”测试继续通过。
- 第 1 节全量命令：**895 passed、8 skipped**（131.29 秒）。
  日志：`/private/tmp/oceanx-a3-full-tests-20261003.log`。沿用原生 Python 3.12.0 临时环境，
  未修改依赖或产品沙箱；测试前后 **203 份 Python 文件的 SHA-256 清单完全一致**。
- `git diff --check` 通过，新增测试文件无 Ruff 提示。三个修改源码的 9 条 Ruff 提示
  与 `HEAD` 的提示逐项一致（未使用 import、import 顺序、旧时区写法及异常捕获），
  没有新增，未扩大范围去修复。
- **A3 保持未提交，停下等待审核与 Owner 提交。** 不开始 A4，不启动 benchmark、
  科学分析或付费模型调用，不操作服务器。

### 2026-10-03 — Owner 授权提交 A2，然后开始 A3

- 本次提交仅包含审核通过的 A2：`delegation.py`、`test_research_policy_loop.py`、
  `README.md` 和本方案。其余 benchmark/reset/Finch 改动保留，不纳入提交。
- 沿用下面已完成的独立审核与全量测试结果；不新增 A2 行为。
- 按 Owner 指令，提交后只开始 A3，完成后停下等待提交；不启动 benchmark。

### 2026-10-03 — Claude 审核 A2：通过，可以提交

- **实现符合方案。**
  - 等待结束后，显式的 `node_id` 仍不存在就返回方案规定的错误消息。
  - 拒绝发生在 `_prepare` 之前：不启动 Expert，不写委派记录，不改调用参数。
  - 只从描述推断出来的未知节点不拒绝。
  - 没有增加在回执阶段猜节点的逻辑。
- **独立验证。**
  - 去掉 `delegation.py` 的改动后，两个拒绝测试失败，其余通过。
  - 在真实的两层中间件链里（预算在外，绑定在内）：被拒绝的调用没有启动 Expert，研究树里没有它的 `delegated` 事件；合法节点照常运行。
  - 全量测试：891 个通过、8 个跳过。测试前后工作区一致。
  - `delegation.py` 没有 Ruff 提示。
- **记录两个小问题，都不在 A2 里处理。**
  1. 被拒绝的调用也被计入回执里的 `Expert assignments so far`。原因是预算中间件在调用开始时计数，它在绑定中间件外层。这个数字只是给 Coordinator 的参考，停止新委派靠的是时间，不受影响。如果 R3 里出现拒绝，再决定要不要改成只统计真正启动的委派。
  2. 桌面界面可能把重试的委派挂到被拒绝的那次调用上。`deep_runtime.py` 的 `pending_calls` 只在工具真正启动时才移除条目，被拒绝的调用会留在里面；之后参数相同的重试会匹配到这条旧记录，事件里带的是旧的调用编号。这只影响桌面界面的显示，不影响研究流程和 benchmark。预算拒绝早就有同样的情况。
- 下一个包是 A3。

### 2026-10-03 — Codex 完成 A2 拒绝部分（待 Owner 提交）

- 以已提交并推送 origin 的 A1 `991466e` 为基础，仅实现 A2，不开始 A3。
- 先写同步、异步回归测试：显式未知节点仍然调用了 handler，修复前结果为
  **2 failed、2 passed**；通过的两项确认推断未知节点仍按未绑定方式运行。
- 最小运行时改动仅在 `research/delegation.py`：保持 `NODE_WAIT_SECONDS` 和原等待流程，
  等待结束后，显式 `node_id` 仍不存在时返回方案指定的 `ToolMessage(status="error")`。
  在 `_prepare` 之前拒绝，不调用 handler、不创建委派或 attempt、不修改原调用参数。
  仅从描述推断的未知节点不拒绝；回执阶段没有增加猜节点或补挂报告的逻辑。
- `test_research_policy_loop.py` 覆盖同步、异步拒绝及推断未知节点继续运行；
  原“同轮新增节点被正确绑定”的测试保留，原“短等待后未绑定”的测试调整为
  推断未知节点场景并覆盖两条调用路径。已有合法节点、非 task 工具和上下文恢复测试通过。
  `README.md` 同步说明显式与推断节点的不同处理方式。
- 针对性测试（policy loop + native subagents）：**77 passed**（5.06 秒）。
  全量测试按第 1 节指定命令执行：**891 passed、8 skipped**（122.48 秒）。
  日志：`/private/tmp/oceanx-a2-full-tests-20261003.log`。沿用临时原生 Python 3.12.0 环境，
  未修改项目依赖或产品沙箱；测试前后 `src/`、`tests/`、`benchmarking/` 中的
  **203 份 Python 文件的 SHA-256 清单完全一致**。
- `git diff --check` 通过；`delegation.py` 无 Ruff 报错。测试文件的 import 顺序及
  单元素切片两条 Ruff 提示在 `HEAD` 上同样存在，无新增，未自行修复。
- 本轮其余 benchmark/reset/Finch 未提交改动原样保留。没有提交、推送、服务器操作，
  没有启动 benchmark、科学分析或付费模型运行。**停在 A2，等待 Owner 提交与 Claude 审核。**

### 2026-10-03 — Owner 授权提交 A1；服务器运行中，暂不拉取

- Owner 要求以 `A1` 为提交名推送 origin 并在服务器拉取。
- 提交范围仅为审核确认的 A1：`graphs.py`、`test_native_subagents.py`、`README.md`、
  本方案，以及 `RUNNING.md` 的报告交付段落。工作区其余 reset、Finch 等变动不纳入。
- 提交前复跑 A1 的针对性测试：**53 passed**（2.33 秒）；Claude 已完成当前工作区的
  独立全量复核，见下一条记录。本轮不新增运行时修改、不开始 A2、不启动 benchmark。
- 服务器只读检查：`/home/mafzhang/code/OceanX` 在 `main`，工作区干净，当前为
  `60a5ea5`；但存在 PID `810101` 的 `python benchmarking/server/run_claude.py`。
  按第 1 节“运行进行中不改代码”的规则，不能在它运行时 pull，且没有中断该运行的授权。
  先提交推送，再复查；若仍在运行，服务器同步留待 Owner 处理，不自行中断或重启。

### 2026-10-03 — Claude 复核 A1（含 v1.2）：通过，可以提交

- **v1.2 的补充符合方案。** `_attempt_stop_reason` 由 `_missing_report` 和沿用原报告的回执共用。沿用原报告且没有结束语时，回执末尾写明没有结束答复和停止原因。工具乱码不会被转发。
- **我用上次暴露缺口的场景重新跑了真实代码，三种情况的回执都正确，原报告都没有变化：**
  - 用满 60 次调用、最后输出乱码：`gave no closing answer: it reached its 60-call limit.`
  - 调用 3 次后停在工具调用上：`gave no closing answer: it stopped after 3 model calls.`
  - 只说一句结束语：`ended with: <结束语>`
- **`README.md` 的说法已改准确，`RUNNING.md` 同步。**
- **全量测试：888 个通过、8 个跳过。** 测试前后工作区一致，这个数字对应当前整个工作区，包括下面的并行改动。
- **A1 的文件：** `src/oceanx/research/graphs.py`、`tests/test_oceanx/test_native_subagents.py`、`README.md`、本文件，以及 `RUNNING.md` 里 “OceanX review delivery” 一节开头的那一段。
- **并行改动不属于 A1，也不在本方案内，建议单独提交。** 涉及 `benchmark_run.py`、三个 `run_*.py`、`finch_worker.py`、对应的测试，以及 `RUNNING.md` 里的 `--reset` 段落。内容是实验的 `--reset` 归档、运行期间持有实验锁、Finch 的交付检查和请求参数记录。我只粗看过：与本方案没有冲突，测试一起通过。没有做完整审核。
- 下一个包是 A2 的“拒绝”部分。

### 2026-10-03 — A1 v1.2 收尾检查：额外的并行改动

- 最终工作区检查发现本轮开始时还没有的 5 份额外变动：
  `server/benchmark_run.py`、`server/run_claude.py`、`server/run_oceanx.py`、
  `tests/test_benchmark_run.py`、`tests/test_run_claude.py`（均在 `benchmarking/` 下）。
  它们不是本轮 A1 修改，未编辑、回退或修复。
- 三份源码的修改时间为 18:58:29 JST；全量测试日志结束于 18:59:20 JST；
  两份测试文件分别修改于 19:00:03 和 18:59:37 JST。因此测试期间和结束后工作区
  仍在变化，**882 passed、8 skipped 是本次执行的结果，不是对最终整个工作区的
  一致快照验证**，尤其不覆盖结束后新增的测试修改。
- 按 Owner 要求仅记录，不扩大 A1。上述改动应由 Owner 另行审核处理；本轮停下等待提交。

### 2026-10-03 — Codex 补齐 A1 v1.2（待 Owner 提交）

- 按 Claude 的 A1 审核，仅补“提交前要补的两处”，不开始其他包。
- 先更新无结束语的回归断言，并加入第 60 次仅输出工具乱码的场景；补运行时逻辑前，
  两种情况均因缺少回执末尾的说明而失败：**2 failed、6 passed**。
- `graphs.py` 提取 `_attempt_stop_reason`，供 `_missing_report` 和沿用原报告的回执共同
  使用。沿用原报告且无可用结束语时，回执末尾注明没有结束答复及停止原因，
  工具乱码不转发；原报告内容、文件 revision、研究树 Summary 和报告路径均不受影响。
- 修正 `README.md` 原来“结束语一律保存为报告”的表述；`RUNNING.md` 同步注明
  没有结束语时的回执说明。三种已批准的报告保存例外保持不变。
- 针对性测试：**53 passed**。按第 1 节的全量命令执行：**882 passed、8 skipped**
  （136.81 秒）。沿用本机临时 Python 3.12.0 测试环境，获准在 Codex 执行限制外执行
  假模型及系统沙箱测试，未修改项目依赖或 OceanX 沙箱规则。
  完整输出：`/private/tmp/oceanx-a1-v12-full-tests-20261003.log`。
- `git diff --check` 通过；Ruff 仍是初版审核中确认的 4 条原有提示，无新增，不处理。
  本轮开始时已有的 Finch 源码和测试改动原样保留，未追加 Finch 修复。
- 仅在本节记录情况，没有重新创建 `CODEX_HANDOFF.md`。没有提交、推送、服务器同步，
  没有启动 benchmark、科学分析或付费模型运行。**停在 A1，等待 Owner 提交。**

### 2026-10-03 — Claude 审核 A1：通过，提交前补两处

**核对结果**

- 实现与方案一致：没改报告时沿用原报告；三种例外才把结束语存为报告；研究树拿到的是原报告的 Summary；结束语只出现在回执末尾。
- 我独立复现了 Codex 的数字：去掉 `graphs.py` 的改动后是 3 个失败、5 个通过；全量测试 879 个通过、8 个跳过（多出的 1 个跳过来自后来出现的 Finch 测试文件，与 A1 无关）。
- 结束语放在 `Report:` 一行之后，比我原先设想的位置更好：界面上的摘要不会混进这句话。
- 每次尝试都在 `report-history` 里留一份它交付的报告，沿用原报告时也留。可以接受。注意：`run_record` 里的“报告版本数”因此表示“交付过报告的尝试数”，内容可能相同。

**提交前要补的两处**

1. **没有产出的重复尝试要在回执里写明（v1.2，方案原文漏了）。**
   - 现状：节点已有报告，重复尝试用满 60 次调用、最后只输出工具乱码时，回执只有原报告的摘要和路径，和成功交付一模一样。我用真实代码确认了这一点。
   - 修改前这种情况的回执是 `Result: No report — it reached its 60-call limit ...`，所以这是一处退步。
   - 做法见第 6 节 A1 里标了“v1.2”的两条。现有测试里 `("report", "ocean_process_expert", "", False, "report")` 这一例要改成期望新的那一行。
2. **`README.md` 的一句话现在不准确。** “An Expert that ends without saving it delivers its closing reply, which the backend saves as `report.md`” 要改成和 `RUNNING.md` 新增段落一致的说法：问题已有报告时，沿用原报告，结束语只进回执。

**不用改的**

- 4 条 Ruff 提示在 `HEAD` 上就有，A1 没有新增，不处理。
- `test_finch_failure_replay.py` 不属于 A1，提交时分开处理。

**关于 `CODEX_HANDOFF.md`**

它被重新建出来，是因为转给 Codex 的那段话里还写着这个文件名，那是我的疏漏。它的两条记录已经原文搬到下面，文件已删除。以后的额外情况只写进本节。

### 2026-10-03 — Unrelated file appeared after A1's full test run（Codex，原文，自 `CODEX_HANDOFF.md` 搬入）

- The full-suite log finished at 18:44:33 JST with 879 passed and 7 skipped.
- The final working-tree check then found a new untracked file,
  `benchmarking/tests/test_finch_failure_replay.py`, modified at 18:45:33 JST.
  This file was not created or edited by the A1 work and was not in that test collection.
- It is outside A1; left untouched and not included in A1's verified changes. The
  Owner should keep it separate when committing this package. No Finch fix was attempted.

### 2026-10-03 — A1 validation: existing lint findings（Codex，原文，自 `CODEX_HANDOFF.md` 搬入）

- Ruff reports four findings in the two Python files touched by A1: import ordering
  in both files, an unused `ToolRegistry` import, and an unused `BLE001` suppression
  in `research/graphs.py`.
- Checking the exact `HEAD` contents with the same Ruff interpreter reproduces all
  four findings. A1 adds no finding; none of these pre-existing issues was modified.
- Decision deferred to the Owner/Claude; do not broaden A1 to include lint cleanup.

### 2026-10-03 — A1：保留未更新的报告（待 Owner 提交）

- 先写回归测试，未改运行时代码时结果为 **3 failed、5 passed**：完整报告被
  `The figure is saved.` 覆盖；无结束语时原报告未交付；续做提示缺少保留报告的规则。
- 最小运行时改动仅在 `src/oceanx/research/graphs.py`：未更新报告时读取已有报告；
  仅在 A1 批准的三种情况把结束语存为报告。其他情况下保持原文件和文件 revision 不变，
  回执与研究树使用原报告 Summary，结束语仅追加在 Coordinator 回执末尾。
  `_earlier_attempt` 明确只更新本次改变的部分，不重写原报告。
- `tests/test_oceanx/test_native_subagents.py` 新增 7 个参数化场景，覆盖三种例外、
  无结束语、实际更新报告、原文件不变、研究树摘要不混入结束语及 attempt 报告副本。
  同步更新 `RUNNING.md` 的交付说明。
- 针对性测试：**52 passed**。全量测试按第 1 节指定命令执行：**879 passed、7 skipped**
  （136.20 秒）。使用本机临时原生 Python 3.12.0 环境，未改项目依赖配置。
  首次受 Codex 执行限制导致端口及系统沙箱相关失败；获准在该限制外重跑后全量通过，
  未修改 OceanX 沙箱规则。完整输出：`/private/tmp/oceanx-a1-full-tests-permitted-20261003.log`。
- `git diff --check` 通过。额外发现的 4 条原有 Ruff 报错已与 `HEAD` 对照确认，
  按 Owner 本次要求记入 `CODEX_HANDOFF.md` 的 Log，未自行修复。
  全量测试结束后另出现未跟踪的 `test_finch_failure_replay.py`，不属于本次 A1，
  未修改且未纳入本次已验证范围，已在同一 Log 记录，提交时需单独处理。
- 没有提交、推送或服务器同步，没有启动 benchmark、科学分析或付费模型运行。
  **停在 A1，等待 Owner 提交和 Claude 审核，不开始 A2。**

### 2026-10-03 — 纳入全部本地改动，建立统一优化基线

Owner 要求将本地全部现有改动提交、推送并同步服务器，后续在该完整版本上优化。
本次纳入 A2 已有的节点等待机制及其两个测试；这不表示 A2 的拒绝逻辑已经实现。
计划与诊断文档、Finch 超时接入修复已分别随 `b3106c1`、`b2bc184` 提交，均属于同一条
`main` 历史，不是两个分叉版本。本轮不额外实施 A1–F，不重启或重跑 benchmark。
Finch 相关检查为32项通过、3项 Linux 测试跳过；节点等待机制在服务器同步后执行针对性测试。

### 2026-10-03 — 交接文档并入本文件

`CODEX_HANDOFF.md` 里仍然有用的内容已经并入本文件，原文件已删除。
`OCEANX_E10_DIAGNOSIS_2026-10-03.md` 里提到 `CODEX_HANDOFF.md` 的地方，对应内容在本文件第 5 到 7 节。

### 2026-10-03 — Documentation-only review handoff（Codex，原文）

- Updated the E10 issue record's historical/current version boundaries and added the
  scientific-delivery versus interactive-publication coupling analysis.
- Added pinned OpenScience source references, verified persistence/viewer behavior and
  explicit limitations; added the review questions and requested planning output above.
- Preserved Claude's existing binding patch, tests and section 4b. No runtime changes,
  server actions, new experiments, automated Claude invocation, or commit/push performed.
- Validation: document diff and whitespace checks only; no runtime tests rerun for these
  documentation edits. Server scheduling evidence and post-fix behavior remain to verify.
