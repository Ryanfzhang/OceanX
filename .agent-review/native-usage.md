# 后端「原生 LangGraph / DeepAgents 使用度」审计

审计对象：`/Users/ryanzhang/Code/OceanMind-v2`（commit 89a456a，工作区干净）
审计方式：只读静态审计 + 上游包源码核对（PyPI sdist/wheel：deepagents 0.7.9、langgraph 1.2.11、langgraph-api 0.13.3；langchain 以环境内 1.4.0 与最新 1.4.6 wheel 交叉核对）+ 2 个一次性动态探针（`~/miniconda3/envs/oceanx`，未写入仓库）。
未修改任何产品代码/测试/配置；本文件是唯一新增文件。

## 结论（摘要）

- 「native 迁移」是**真实的**，不是包装话术：旧 orchestrator/调度器已删除（`git ls-files src/oceanx/team` 只剩 `__init__/models/profiles`），执行路径只有一条——桌面端内嵌 Agent Server 跑 `coordinator` 图（`langgraph.json:2-5`、`src/oceanx/research/server.py:26-31`、`src/oceanx/agent.py:51-71`）。
- 原生能力用得很实：`create_deep_agent`、`register_harness_profile`、native `task` 子图、`skills=` 发现、native summarization、`astream_events`、Agent Server checkpointer/run、`ModelCallLimitMiddleware`、`ModelRetryMiddleware`、`permissions=`、`BaseSandbox`/`CompositeBackend` 都在用（第 1 节）。
- 但存在 **3 组 S1**：① `deepagents` 私有符号 6 个（4 个 sandbox helper + `_models` + `_permissions`，升级必碎）；② 自研「后台 Expert」越过原生 tool-call/超步边界，原生 `Command` 更新被丢弃、checkpoint 在父超步结束后才写（正确性风险，动态探针已复现机制、未复现损坏）；③ 权限只覆盖原生文件工具，`execute`/内核可直接写 `/skills` 快照（README 的「read-only」不成立于 shell 层）。
- **S2** 集中在：全局可变并发池/取消集合/团队视图状态与原生 checkpoint 无关联；`ModelCallLimitMiddleware` 计数被重复 `handler()` 绕过（「60 次有效调用」上限可被突破）；取消先提交终态再等服务器（可能 UI 已取消而 run 仍在写盘）。
- 大部分自研（SSE 投影、receipt、事件总线、技能快照、操作幂等表、metering）有正当产品/沙箱/UI 理由，建议保留；少数可用原生替代（`interrupt`/`Command(resume)`、公开 `permissions=` + 包装 middleware、`response_format`、`with_retry`）。
- 文档漂移 3 处（第 7 节），`scripts/probe_expert_round.py` 是半迁移遗留的坏脚本。

### 「原生 vs 自研」总表

| 能力 | 现状 | 证据 | 判断 |
|---|---|---|---|
| `create_deep_agent` | 用了 | `deep_runtime.py:11,349-373` | 原生 ✅ |
| `StateGraph` | 用了（外层单节点包装 + Expert 子图） | `graphs.py:1033,1314` | 原生 ✅（包装理由见 2.18） |
| native `task` 子图 | 用了（`CompiledSubAgent`） | `graphs.py:1174-1176` → `deep_runtime.py:367-373` | 原生 ✅ |
| `skills=` 发现 + `SkillsMiddleware` | 用了 | `deep_runtime.py:369`、`native_skills.py:102-106` | 原生 ✅ |
| native summarization | 用了（`create_deep_agent` 自动挂载） | `deep_runtime.py:367-373`；上游 `deepagents/graph.py:840-845` | 原生 ✅ |
| Agent Server checkpointer / run / auth | 用了 | `gateway.py:77-97`、`server.py:26-31`、`auth.py:5-14` | 原生 ✅ |
| `astream_events(v2)` | 用了 | `deep_runtime.py:180` | 原生 ✅ |
| `ModelCallLimitMiddleware` / `ModelRetryMiddleware` | 用了（继承/包装） | `graphs.py:417-428`、`provider_retry.py:14,27-32` | 原生 ✅ + 扩展 |
| `permissions=`（公共参数） | 传了但被自研 FS middleware 覆盖，实际靠私有 `_permissions` | `deep_runtime.py:369-373` | ⚠️ 半原生 |
| `interrupt` / `Command(resume)` | 未用；自研 interaction 表 | `router.py:2124-2161`、`schema.sql:212-227` | 自研（可替代） |
| `Send` 并行 | 未用；靠「同一 turn 多个 task + 自研后台 job」 | `deep_runtime.py:54-56`、`background_experts.py:245-302` | 自研（部分必要） |
| 后台 Expert 队列/等待 | 自研 | `background_experts.py:89-302` | 自研（S1/S2，见 2.2） |
| 并发池 `_Slots` + 全局 `_EXPERT_SLOTS` | 自研 | `graphs.py:97-151,1254` | 自研（S2） |
| 专家 receipt/handoff 文本格式 | 自研 | `services.py:41-81`、`graphs.py:1135-1148` | 自研（正当，S3） |
| 技能快照 / lesson 注入 | 自研（在原生 skills 之上） | `native_skills.py:25-99`、`graphs.py:865-874` | 自研（正当，S2 权限缺口） |
| 事件总线 / SSE→protocol v2 投影 | 自研 | `backend/events.py:91-130`、`deep_runtime.py:180-346`、`router.py:2646+` | 自研（正当，S3 脆弱） |
| checkpoint 数据库投影（operation/tool_call） | 自研 | `store.py:145-153,264-275,3216-3270`、`tools.py:130-180` | 自研（正当补充） |
| 取消机制 | 自研 task.cancel + 原生 cancel_on_disconnect | `router.py:2836-2889`、`gateway.py:85-97` | 混合（S2） |
| 团队视图 / 专家 transcript | 自研 in-memory 镜像 | `router.py:285,2938-3030,3316-3345` | 自研（S2，与 README 冲突） |

---

## 1. 确实使用了原生能力（逐项证据）

1. **`create_deep_agent`**：`src/oceanx/deep_runtime.py:11,349-373`；`build_deep_agent_graph()` 只建图，注释明确「Agent Server supplies persistence and executes it」（`:349-353`）。
2. **原生 harness profile**：`register_harness_profile(...)` + `HarnessProfile`/`GeneralPurposeSubagentProfile`（`deep_runtime.py:14-18,60-70`）；关闭默认 generalist、覆写 `task` 工具描述。`deepagents.profiles` 在上游被标注为 public beta（`deepagents/profiles/__init__.py:1-10`）。
3. **原生 `task` 子图**：`graphs.py:1174-1176` 用 `{"runnable": await expert(...)}` 构造 `CompiledSubAgent`，交给 `SubAgentMiddleware`（`deep_runtime.py:367-369`）；Expert 自己也是 `StateGraph`（`graphs.py:1031-1155`）。
4. **原生 skills 发现**：`deep_runtime.py:369 skills=["/skills/"]`，配合 `CompositeBackend` 的 `/skills/`、`/references/` 路由（`native_skills.py:102-106`）；模型只用 `read_file` 读技能（README:178 属实）。
5. **原生 summarization**：`create_deep_agent` 内部自动挂 `create_summarization_middleware`（上游 `deepagents/graph.py:840-845`），OceanX 未替换；只对 `lc_source=="summarization"` 的流事件做「计量但不展示」（`deep_runtime.py:197,204-234`）——这是投影而非第二套摘要。
6. **Agent Server / checkpointer / auth**：`gateway.py:19-23`（`langgraph_sdk.get_client`）、`:77-84`（`runs.create(..., multitask_strategy="enqueue", stream_mode=["events","values"])`）、`server.py:21-31`（`run_server(..., graphs=..., http=..., auth=...)`，`disable_persistence=False`）、`auth.py:5-14`（`langgraph_sdk.Auth`）。`config/recursion_limit` 保留 DeepAgents 默认 9,999（`deep_runtime.py:147-156`、`gateway.py:79-82`）。
7. **`astream_events` v2**：`deep_runtime.py:180`；用 `parent_ids` 屏蔽 native task 子图的内部事件，只投影外层 tool 收据（`:183-195`）——这是对原生事件流的正确消费方式。
8. **原生 middleware**：`ExpertCallBudgetMiddleware(ModelCallLimitMiddleware)`（`graphs.py:417-439`，`super().__init__(run_limit=..., exit_behavior="end")`）、`ModelRetryMiddleware`（`provider_retry.py:14,27-32`）、`AgentMiddleware` 的 `wrap_tool_call/awrap_tool_call/wrap_model_call` 钩子（`graphs.py:410-414,487-503`、`delegation.py:162-166,219-251`、`background_experts.py:257-302`、`tool_calls.py:63-72`）。
9. **原生 sandbox/文件后端**：`OceanSandbox(BaseSandbox)` + `ResearchSandbox`（`native_backend.py:54,223`）、`CompositeBackend`/`FilesystemBackend`/`StateBackend`（`native_skills.py:13,102-106`）、`FilesystemPermission`（`native_skills.py:109-110`）。
10. **原生 `Command`**：只消费不生产——`deep_runtime.py:105-124` 解包 Agent Server 序列化后的 `Command.update.messages`；`background_experts.py:58-76` 保留/追加 native `Command`。**没有** `interrupt()`、`HumanInTheLoopMiddleware`、`Send`、`AsyncSubAgent`、`store=`、`memory=`（全仓 grep 仅命中注释与 `interrupted` 字样；`deep_runtime.py` 也未传这些参数）。
11. **原生并行**：同一 Coordinator turn 内多个 `task` 调用由 LangGraph tool 节点并行执行（`deep_runtime.py:54-56` 的提示词 + `background_experts.py:245-302` 的并发接收）；不是 `Send` fan-out。

结论：第 1 项清单里除 `interrupt`/`Send` 外都在用，原生使用度**高**。

---

## 2. 自研逻辑逐项判断

### 2.1 自研 SSE / 事件投影（deep_runtime.py:180-346 + gateway.py:26-37,70-100 + router.py:2646+）
产品需要 Electron protocol v2，Agent Server 的 SSE/序列化格式不可直接给 UI；`gateway.decode()` 重建 `AIMessageChunk`/消息、`_tool_output()` 解包 `Command`（`deep_runtime.py:105-124`）都是形式转换而非第二执行引擎。**正当（保留）**。
脆弱点（S3）：turn 归属靠 `pending_calls` 按 name+args 启发式配对（`deep_runtime.py:242-283`），模型改参数或 middleware 丢参数时会退化；`lc_source` 是 langchain 内部标记（`langchain/agents/middleware/summarization.py:135`），上游改名会让摘要文本泄漏成答案。

### 2.2 自研「后台 Expert」队列 `RunningExperts` + `await_experts`（background_experts.py:89-302）
原生 `task` 是同步语义，「一套 batch 等最慢一个」是已被记录的产品痛点（该文件 `:1-13` 的 Q08 数据），所以**动机正当**。但实现越过原生边界，属于 S1（正确性风险，详见 5.3）：
- `_Job.work = asyncio.ensure_future(work)` 让 native `task` 工具的执行体在 tool 节点返回**之后**继续跑（`background_experts.py:115-121,260-283`）；
- 子图完成时，native `task` 用 `Command(update=...)` 把子状态写回父图（上游 `deepagents/middleware/subagents.py:509-516`），而 OceanX 在「仍在跑」分支只返回新造 `ToolMessage`（`background_experts.py:275-280`），**原生 Command 的 state update 被丢弃**；
- `_kept_waiting()` 直接给 AIMessage 注入一个模型从未生成的 `await_experts` tool_call（`background_experts.py:285-302`）——这会让 trace/metering/重放看到一个伪造的模型决策。
- `background_experts.py:8-13` 与 README:85「native synchronous task tool」措辞不一致（同步只对 Expert 自身，Coordinator 侧已被改成异步轮询）。

### 2.3 自研并发池 `_Slots` + 全局 `_EXPERT_SLOTS`（graphs.py:97-151）
限制本地 CPU/内存是真实需求（`:90-94` 注释），但**全局可变量**导致跨任务串扰（S2，见 5.1）；且 `resize` 来自「最新一次请求」（`graphs.py:1254`），并发任务的 Expert 限流不再遵守各自请求的设置。

### 2.4 自研 receipt / handoff 文本（services.py:41-81、graphs.py:1070-1148）
native task 只回最后一条 AIMessage 文本；UI 需要 `Published results`/`Saved figures`/`Report:` 三段式（`services.py:52-72`），且 `response_format` 不能用于 `CompiledSubAgent`（上游 `subagents.py:423-427` 会报错），所以**自研有正当理由**。风险 S3：`parse_expert_receipt()` 用正则回读自己生成的格式（`services.py:75-81`），格式一变 UI 静默退化。

### 2.5 自研技能快照 + lesson 注入（native_skills.py:25-99、graphs.py:865-876）
原生 `skills=` 只接受 sources（目录前缀），而项目需要「不可变内容寻址快照 + 仅在保留区域写入已批准 lessons」（`native_skills.py:25-35,60-98`）。**正当**。但权限模型不完整（S1，见第 6 节）。

### 2.6 retry
in-agent 用原生 `ModelRetryMiddleware`（`provider_retry.py:27-32`）✅；agent 之外的 `call_with_retries()`（`provider_retry.py:35-46`）是自研重试，功能上与 langchain 的 `with_retry`/tenacity 重复，**可被替代，S3**。

### 2.7 事件总线 `EventBus`（backend/events.py:91-130）
多传输（stdio/WebSocket）、每传输独立 sequence、workspace 广播——原生没有对应物。**正当（保留）**。

### 2.8 操作幂等 / checkpoint 投影表（schema.sql:145-153,264-275；store.py:3216-3270；tools.py:130-180）
`operation_checkpoints`/`tool_call_records` 记录**工具副作用**的幂等收据，`_operation_id()` 用 (request, turn, tool_call) 哈希（`router.py:2903-2905`）。这不是 LangGraph 会话 checkpoint 的替代，而是崩溃窗口补丁；原生 `durability="sync"` 只能缩小窗口，不能替代文件副作用幂等，**正当**。注意 `model_call_observations`/`code_executions` 是 telemetry/审计，非生命周期。

### 2.9 自研取消（router.py:2836-2889 + gateway.py:85-97）
`task.cancel()` 取消本地前台 Task，靠 `join_stream(cancel_on_disconnect=True)` 让服务器取消 run（`gateway.py:85-93`），注释也承认「DeepAgentEngine deliberately has no parallel cancel_active API」（`router.py:2845-2851`）。方向正确，但**先**写 durable cancellation 终态、再依赖 disconnect 生效（`router.py:2854-2885`），存在「UI 已 cancelled、服务器 run 仍在写文件」的窗口。S2，未验证。

### 2.10 自研 interaction（paper selection 等）
`_request_paper_selection()`（router.py:2124-2161）经 `task_interactions` 表（schema.sql:212-227、store.py:1278-1327）向 UI 提问并阻塞等待；原生 `interrupt()` + `Command(resume=...)` 在 Agent Server 上是原生支持的。当前实现自管 pending/interrupted 状态（`store.py:4096-4106`）——**可被原生替代（S3）**，但桌面协议/重连语义是合理理由，建议列 backlog 而非立即改。

### 2.11 metering `CallMeter`（research/metering.py:22-83）
用原生 `AsyncCallbackHandler` 记录每次模型调用到本地 SQLite（LANGSMITH_TRACING=false，`launcher.py:31` 环境里显式关闭），属于产品 telemetry，**正当**。`INSIDE_EXPERT` ContextVar（`metering.py:11,30-31`）依赖「子图继承父回调 + asyncio task 复制上下文」，在后台化下正确性未验证（S3）。

### 2.12 预算 / wind-down middleware（graphs.py:218-503）
在原生 `ModelCallLimitMiddleware` 上扩展，方向正确；但 `after_model` 读 `run_model_call_count`（`graphs.py:431-439,451,463`），该键在 langchain 里是 `PrivateStateAttr`（`langchain/agents/middleware/model_call_limit.py:34`），属于半私有状态；且重复调用 `handler()` 会绕过计数（S2，见 5.6）。

### 2.13 自研 tree / toolbook / lessons 域状态（research/tree.py、tree_store.py、lessons.py、toolbook.py）
与 agent 生命周期解耦，README:80-84 明确「tree 记录科学问题，不调度 agent」；`tree_tools.py:96-119` 的注释「it never starts, monitors, resumes or cancels agents」与实现一致。**正当**。

### 2.14 Expert transcript / 团队视图（router.py:285,2938-3030,3316-3345）
`_native_task_activity` 是 in-memory dict，快照 docstring 写「never persist a scheduler」（`router.py:2938-2941`），但 `_task_agent_transcript()` 仅从这份内存拼 Expert transcript（`router.py:3316-3345`）。重启后原生 checkpoint 还在、团队视图没了；且 `task_workflows` 表（schema.sql:245-262）持久化了请求级状态，构成**第二套（粗粒度）生命周期镜像**，与 README:104/122 的「不镜像」措辞冲突。S2（功能可接受，文档/架构需澄清）。

### 2.15 自研 sandbox 后端（native_backend.py）
必须复用现有 OS sandbox/内核，`BaseSandbox` 子类化是官方推荐姿势（上游 `sandbox.py:1-10`）。为让 native `read/grep/edit` 走 `_text_helper`、大文件编辑落在本 sandbox 临时目录（`native_backend.py:106-110,168-189`）而覆写，**理由正当**；代价是引入 4 个私有 helper（S1，见第 3 节 P1）。`ResearchSandbox` 把文件工具与 `execute` 拆成两个后端实例（`native_backend.py:223-268`），实现「LS/read 不算科学执行」——正当。

### 2.16 `_configure_native_harness`（deep_runtime.py:60-70）
用原生 profile 注册来改 `task` 描述、关 generalist。**正当（原生用法）**，只是 profile 是 beta API（S3）。

### 2.17 display-only `task` schema（delegation.py:116-135,152-166）
为了给原生 `task` 加 `node_id` 参数，OceanX 复制 native tool 的 `args_schema` 造了一个永不执行的展示 tool，再在 `awrap_tool_call` 里把 `node_id` 从 args 剥离（`delegation.py:169-178`）。做法可行但依赖 native tool 的 `args_schema` 形状（S3）；好在执行仍走 native tool（`delegation.py:129-130,232-249`）。

### 2.18 外层 `StateGraph` 包装（graphs.py:1033-1155,1314-1318）
Agent Server 需要一个可 `compile` 的图和 runtime 才能拿 request config（`graphs.py:1245-1249` 注释）；Expert 用 `StateGraph` 才能作为 `CompiledSubAgent` 返回受控状态。**原生用法，非造轮子**；但 Coordinator 的整个 DeepAgent 跑在一个 node 里（`graphs.py:1258`），使 run 级 checkpoint 只能以「节点完成」为粒度，见 5.3。

---

## 3. 私有 API 依赖（全部命中）

| # | 位置 | 私有符号 | 上游状态（0.7.9/1.2.11 实测） | 碎裂风险 |
|---|---|---|---|---|
| P1 | `native_backend.py:27-33` | `_build_edit_tmpfile_cmd`、`_get_backend_read_file_type`、`_map_edit_error`、`_parse_read_output`（从 `deepagents.backends.sandbox` 导入） | 全部存在，均为模块私有，`backends/__init__.py:12-23` 未导出 | **最高**：`import oceanx.native_backend` 直接 ImportError → 所有 Expert 建图失败 |
| P2 | `deep_runtime.py:355` | `from deepagents._models import get_model_provider` | 存在；模块名带下划线 | **高**：每次建图时 ImportError |
| P3 | `deep_runtime.py:372` | `FilesystemMiddleware(..., _permissions=permissions)` | 存在；上游 docstring 明说「Marked private for now … may move to the backend layer」（`filesystem.py:1669-1674`） | **高**：升级后 TypeError |
| P4 | `graphs.py:21-24` | `FilesystemState`、`SummarizationState`、`SkillsState`（`DeepAgentState` 是公开的） | 模块可导入；`skills.py:1058 __all__` 只导出 `SkillMetadata/SkillsMiddleware`，filesystem/summarization 无 `__all__` | 中高：`langgraph.json` 的 graph factory 一 import 就失败 |
| P5 | `native_skills.py:14` | `from deepagents.middleware.permissions import FilesystemPermission` | 可导入；但根包已公开导出（`deepagents/__init__.py:9`） | 中：纯搬迁即碎，易修 |
| P6 | `services.py:159`、`metering.py`（构造 `configurable`） | 依赖 `configurable["ls_agent_type"] == "subagent"` | deepagents 内部 subagent 标记（上游 `subagents.py:313-324,567,595`） | **中且危险**：改名不报错，只会让 Expert 全部退化为 Coordinator 的 thread_id → 文件/内核目录隔离静默失效 |
| P7 | `deep_runtime.py:197`、`metering.py:45` | `lc_source == "summarization"` | langchain 内部标记（`langchain/agents/middleware/summarization.py:135`） | 中：摘要文本可能被当成正式答案展示 |
| P8 | `server.py:26-31` | `from langgraph_api.cli import run_server` | 0.13.3 签名核对通过（`langgraph_api/cli.py:171-194` 含 `allow_blocking`/`disable_persistence`）；但它是 CLI 实现模块而非库 API | 中：仅 deliberate bump 时需重核 |
| P9 | `gateway.py:26-37`、`deep_runtime.py:105-124` | Agent Server 事件/`Command` 序列化形状 | SDK 流式协议，半稳定 | 中：投影层需要跟随 SDK 变化 |

**升级 deepagents 时最先碎的 4 处（按顺序）**：P1 → P2 → P3 → P4；P6 是「不报错但语义变坏」的最隐蔽一处。
**更稳的公共替代**：
- P1：`BaseSandbox` 只覆写 `aexecute`/`aupload_files`，读用公开 `BackendProtocol` 返回类型自实现；编辑用公开 `aedit` 语义 + 自己实现 replace 脚本（约 100 行，但契约稳定）；或把 `_EDIT_TMPFILE_TEMPLATE`、staging 目录作为上游 feature request。
- P2：provider 已知——直接用 `load_model_profile(...).provider`（`graphs.py:977`、`model_config.py`）或上游公开的 `resolve_model` 结果 class 映射，不必碰 `_models`。
- P3：保留 `create_deep_agent(permissions=...)` 生成的原生 FS middleware，不要整体替换；`tools=` 已是公开参数（`filesystem.py:1635`），若必须改 eviction 阈值，可在外层再包一个 `wrap_tool_call` 做写路径 deny（公共 API），或给上游提「public permissions kwarg」。
- P4：外层 `StateGraph` 只需 `messages` + 自有字段；返回子图 state 时过滤掉不需要的键，就能不 import 中间件 state 类（或用 `DeepAgentState` + 显式白名单）。
- P6：改用原生 `CompiledSubAgent` 的显式身份传递（`build()` 时已有 `run`），不要依赖 tracing tag。
- P9：投影层加一个「上游形状」契约测试（用固定 SSE/Command 样本），升级时先跑它。

---

## 4. 半迁移遗留 / 双路径

1. **旧 orchestrator 已删干净（正面结论）**：`git ls-files src/oceanx/team` 仅 `__init__.py/models.py/profiles.py`；历史 commit `d496fcb` 删除了 orchestrator/multi_agent。工作区里只剩未跟踪的 `src/oceanx/team/__pycache__/orchestrator.*.pyc`（本地缓存，不是代码残留）。
2. **坏掉的开发探针**：`scripts/probe_expert_round.py:20` `from oceanx.research.graphs import ExpertPreparation, build`（不存在）、`:48` `h.research.order(...)`、`:50` `ExpertPreparation(config, order)`、`:53` `h.research.save_answer(...)` —— 该脚本今天必然 ImportError/AttributeError，是旧调度接口的遗留（S3）。
3. **无用的 graph 导出**：`graphs.py:1321-1334` 导出 `physics/statistics/literature/discussion`，但 Agent Server 只注册 `coordinator`（`server.py:8`、`langgraph.json:2-5`），生产无引用，仅测试导入（`tests/test_oceanx/test_native_subagents.py` 等）（S3）。
4. **双引擎路径**：生产只有 ServerGraphStream → Agent Server 一条（`agent.py:51-71`、`launcher.py:15-66`、`host.py:216-217`）；本地编译图只存在于测试 fixture（`tests/test_oceanx/graph_fixture.py:1-20`，docstring 明确「In-process unit-test harness only」）。**不存在生产双路径**，`agent.py`/`gateway.py` 是同一路径的封装与适配。
5. **同一职责两套表达**：native checkpoint（会话）+ `task_workflows`/`_native_task_activity`/`task_interactions`（UI 生命周期与交互）。后者不是调度器，但确实是「第二套生命周期投影」，README:104「Scheduling, cancellation and child completion remain native … does not mirror them」需要限定（S2，见 2.14）。

---

## 5. 并发 / 取消 / 全局状态与原生 checkpoint 一致性

1. **`_EXPERT_SLOTS` / `_SEARCH_EXPERT_SLOTS` 是模块级全局**（`graphs.py:126-151`），按 event loop 缓存，取消/超限语义依赖可变 `active` 计数；`_expert_slots(limit)` 会把**最新请求**的 `max_parallel_experts` 写到全局（`graphs.py:130-142,1254`）。并发两个 task 时，A 的设置会改 B 的限流；重启后计数归零（与 checkpoint 无关，可接受），但**跨任务串扰是真实的 S2**。`MAX_PARALLEL_EXPERTS`/`MAX_PARALLEL_SEARCH_EXPERTS` 在 import 时从 env 读取（`graphs.py:76-93`），benchmark 只能靠进程级 env 生效——生产内嵌服务器与桌面设置混用同一进程。
2. **其他全局可变状态**：`services._active_host`（`services.py:17,94-97`，`app.py:19-24` 赋值）、router 的 `_native_task_activity`/`_cancelling_agent_requests`/`_team_snapshot_revisions`/`_agent_tasks`（`router.py:281-298`）、`metering.INSIDE_EXPERT` ContextVar（`metering.py:11`）、`delegation._CURRENT` ContextVar（`delegation.py:87`）。它们都**不进入 graph state/checkpoint**：进程重启后服务器 run/checkpoint 仍在，团队视图、取消意图、pending receipt 状态却丢失。S2。
3. **checkpoint 与「后台 Expert」**（机制已动态复核，结论：能写、但越界）：
   - 内层 DeepAgent 建图时 `checkpointer=None`（`deep_runtime.py:349-373`、`graphs.py:976-985` 未传），OceanX 也**没有显式**传 checkpointer；
   - 但 LangGraph 会把父图的 checkpointer 放进每个 task 的 `configurable`（`langgraph/pregel/_algo.py:914-916`、`_algo.py:1084-1086`），因此 `coordinate` 里 `agent.ainvoke(state, config=config)`（`graphs.py:1258`）仍会写到**嵌套 namespace** 的 checkpoint；
   - 我用最小复现验证：内层图 `compile()`（无 checkpointer）在节点里以父 config `ainvoke` → 生成 6 个 checkpoint（主线程 + `node:<uuid>` namespace），且内层任务在**父图返回之后**才完成，未抛异常（探针 `/tmp/bg_checkpoint_probe.py`，仓库外，未保留）；即「后台 Expert 在父超步结束后继续写自己的嵌套 checkpoint」在 pinned 版本下成立，但它的 checkpoint 链与父超步分离，**跨任务并发/崩溃时的一致性未验证**（S1 风险点，需 Agent Server + sqlite checkpointer 的并发回归测试）。
4. **checkpoint 声明 vs 实际读取**：OceanX 只在投影末尾 `graph.aget_state()` 读**外层** thread（`deep_runtime.py:161-164` → `gateway.py:60-62`）；Expert 的 conversation 从未从 checkpoint 读，UI transcript 来自 router 内存（`router.py:3316-3345`）。README:122「Agent Server checkpoints are the source of truth for participant conversation state」目前只在「一次 run 完成后的外层状态」成立，**不是**实时/子图粒度的 source of truth。
5. **取消**：前台 `asyncio.Task.cancel()`（`router.py:2845-2851`）→ 关闭 `join_stream` → 服务器 `cancel_on_disconnect` 取消 run（`gateway.py:85-93`）；durable 终态先提交（`router.py:2854-2885`）。若服务器在 disconnect 生效前已推进到下个工具/写文件，会出现「记录 cancelled 但仍有副作用」，S2，未验证。
6. **模型调用预算与并发**：`ExpertCallBudgetMiddleware.after_model` 以 `state["run_model_call_count"]`（PrivateStateAttr）为准（`graphs.py:431-439`）；而 `wrap_model_call` 在「交付失败/工具调用损坏」时二次调用 `handler()`（`graphs.py:487-495`、`tool_calls.py:66-72`），**同一次 model node 内的第二次真实模型调用不会增加计数**。我在 pinned langchain 上用 `run_limit=1` + 双 `handler()` 探针复现：真实模型被调用 2 次、限流仍按 1 次计（探针 `/tmp/budget_probe3.py`）。因此 README:148/154「at most 60 effective model calls / each native task receives its own allowance」可被突破（最坏 +2 次/触发），S2。

---

## 6. 权限与「read-only」声明（S1）

`skill_permissions()` 只在原生文件工具层 deny 写 `/skills/**`、`/references/**`（`native_skills.py:109-110`，由 `FilesystemMiddleware(_permissions=...)` 强制执行，`deep_runtime.py:372`）。但 Expert 同时拥有 `execute` 和持久 Python 内核（`deep_runtime.py:367-373` + `native_backend.py:68-101`），而快照库位于 `work_root/.runtime/skills`（`graphs.py:870`、`native_backend.py:300-305`），`work_root` 正是 sandbox 的 `writable_roots`（`native_backend.py:77`）。因此 shell/内核可以直接改写该任务自己的技能快照，绕过 tool 层 deny。上游 `FilesystemMiddleware` 明确不对 `execute` 做 permission 检查，并要求 `_permissions` 只用于 route 范围内的路径（`filesystem.py:1698-1703`）——`/skills/**` 恰好是 route，所以这个组合能通过上游校验。影响限于单任务快速、单机本地，但 README:169/178「Skills remain read-only」在 shell 层不成立。（S1，安全/正确性声明风险；可修：把快照移到 `read_roots` 之外的只读位置，或在 `aexecute` 前做路径 deny）。

---

## 7. README 声明与实现差异

1. **README:148/154「60 次有效调用」**：被 5.6 的二次 `handler()` 突破（`graphs.py:487-495`、`tool_calls.py:66-72`）。
2. **README:165「Coordinator and executing Experts have … `delete` and `execute`」**：Coordinator 的 allowlist 是 `COORDINATOR_FILESYSTEM_TOOLS`（`graphs.py:163-170,969-975`），**不含** `delete`/`execute`；Discussion Partner 只有 4 个只读工具（`graphs.py:969-975`）。README 与实现不符（Coordinator 实际不能删文件/执行命令，这是有意的安全设计，只是文档没写清）。
3. **README:104/122「不镜像生命周期 / checkpoint 是参与者会话的 source of truth」**：`_native_task_activity`、`task_workflows`、`task_interactions` 与 Expert transcript 自内存重建（`router.py:285,2455,2938-3030,3316-3345`；`schema.sql:212-262`）构成第二套投影；Expert 子图 checkpoint 存在但从不读取（见 5.3/5.4）。措辞应改为「checkpoint 是执行状态来源；UI 生命周期是事件投影，进程内缓存」。
4. **README:178/264/85 属实**：`skills=` 发现、native summarization、native task 工具执行路径都与代码一致（`deep_runtime.py:369`；`graph.py:840-845` 上游自动挂载；`graphs.py:1174-1176`）。

---

## 8. 建议（按优先级）

**S1（升级/正确性，先做）**
1. 消除 `deepagents` 私有符号：P1（4 个 sandbox helper）、P2（`_models`）、P3（`_permissions`）、P4（中间件 state 类）。加一个 CI smoke：`python -c "import oceanx.research.graphs, oceanx.native_backend"` + 用固定样本跑 `build_deep_agent_graph`。
2. 把「后台 Expert」显式化：要么接受 native 同步 `task`（用同一 turn 并行 + `await_experts` 之外的原生方案），要么让 job 在受控的 server run 内、并在 Job 完成时把 native `Command` 交回父图；同时将 `_kept_waiting` 的伪造 tool_call 改为带显式标记的 middleware 行为，避免污染 trace。
3. 修权限闭环：技能快照放到 sandbox `writable_roots` 之外（或 `aexecute` 前置 deny），使 README 的 read-only 成立。
4. 给 Agent Server + sqlite checkpointer 写并发回归：多 task 并行、后台 Expert、取消、重启后 checkpoint 链一致性（当前未验证）。

**S2（语义/一致）**
5. `_EXPERT_SLOTS` 改为每 Coordinator run 的池（放进 run 内上下文），`max_parallel_experts` 只影响本 run；全局池最多作为进程上限。
6. 预算计数改为在 `wrap_model_call` 里显式记录真实模型调用（或用 `ModelCallLimitMiddleware` 的 thread/run 计数 + 不二次调用），使 60 次上限可审计。
7. 取消走 Agent Server 原生 run cancel（`runs.cancel`），durable 终态在确认 run terminal 后提交。
8. 团队视图/Expert transcript 要么 persist（事件表）要么从 native task/checkpoint 派生；README 措辞同步修正。

**S3（清理/文档）**
9. 删除或修复 `scripts/probe_expert_round.py`；删除 `graphs.py:1321-1334` 无注册的导出（或登记到 `langgraph.json`）。
10. 为 `parse_expert_receipt`、`_tool_output`、SSE 序列化形状加契约测试；把 `lc_source` 依赖标注为上游契约。
11. 用原生 `interrupt`/`Command(resume)` 替换 interaction（backlog）；agent 外重试用 `with_retry`/tenacity。
12. 修正 README:165（Coordinator 工具集）与 148/154（有效调用数）等 3 处漂移。

---

## 附：未验证项

- 后台 Expert 在真实 Agent Server + sqlite checkpointer 下并发写嵌套 namespace 是否会污染/堆积 checkpoint（仅最小复现了「越界写入不报错」）。
- 取消时服务器端 run 是否 100% 在 durable cancelled 提交前停止副作用。
- `INSIDE_EXPERT` ContextVar 在后台化 + 多 Expert 并发下的计量归属是否始终正确。
- `.venv` 为 x86_64 且不可执行（`Bad CPU type`），审计改用 `~/miniconda3/envs/oceanx`（deepagents 0.7.9 / langgraph 1.2.11 实测可导入全部模块）；未运行完整 `pytest tests/test_oceanx`。
