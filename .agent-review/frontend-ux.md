# OceanX 前端交互便利度与前端代码质量审计（只读）

审计对象：`frontend/ocean-desktop`（Electron + React 主客户端）、`frontend/packages/ocean-client`、`frontend/packages/ocean-ui`、`frontend/ocean_terminal`（遗留判定）、`frontend/plot_studio`。
路径简写：`renderer/` = `frontend/ocean-desktop/src/renderer/`，`desktop/` = `frontend/ocean-desktop/`，`main/` = `frontend/ocean-desktop/src/`，`packages/` = `frontend/packages/`。
分级：**S1** 影响主流程/第一印象；**S2** 明显摩擦、有替代路径；**S3** 打磨项。成本：低 <0.5d，中 1–2d，高 >2d。
按要求**不评审、不建议改动** agent 交互逻辑与 skill/tool 学习逻辑；以下建议全部落在 UI / 状态 / 协议投影层。

## 结论摘要

1. 主链路（项目→任务→流式→取消→结果→报告）是通的，`tsc` 双配置零错误；问题集中在"工作区被谁占屏、失败后能不能自愈、新手第一步点得动吗"。
2. **结果工作台常驻 42vw**：没打开任何结果时右侧也是一块活的 MapLibre 地图，对话被压到约 560px（1440 宽窗口），且启动即请求远程底图。
3. **崩溃/丢终态后 UI 不自愈**：`exit` 只清 context，不 reset `activeRequestId`；重连也不重新 `task.open`；仓库里已有带 180s 超时的 `PendingRequestHandlers` 却完全没接入 → 用户看到永久的"运行中/停止"。
4. **欢迎页三个"研究入口"是 `<article>`，完全不可点**；新手第一屏最显眼的三个卡片是死交互。
5. **失败无「重试/继续」按钮**，只提示用户手打 `continue`；输入框也不回填（`restoreSubmittedPrompt` 已写好但未使用）。
6. 中文模式只覆盖到左栏/欢迎/对话框；右栏结果、报告、图表、团队画布、结果错误文案仍是硬编码英文。
7. 键盘侧基本只有 Enter 发送 + 对话框 Esc：无命令面板（`CommandPalette` 已实现但未接入）、无 Cmd+K / Cmd+N、无 Esc 关闭结果面板；对话框没有 Tab 焦点陷阱（`installModalFocusManager` 已实现未接入）。
8. 代码质量的主要债不是"文件大"，而是 **App.tsx 一组件 49 个 useState / 21 ref / 18 effect + 129 行 handleFrame**，以及 **渲染进程几乎没用生成的协议类型**（唯一使用方是遗留 TUI）。
9. 测试面：40 个 vitest 文件，但 `App.tsx` 零测试；两个 e2e spec 在上一个提交被删除，快照/README/脚本仍在，`npm run e2e` 现在找不到任何用例。
10. 本机 `npm test` 起不来：Node 21.6.1 < vite 8/rolldown 要求的 `^20.19 || >=22.12`（`util.styleText` 缺失），仓库没有 `engines`/`.nvmrc`。

## 交互问题优先级表（按用户可感知度排序）

| P | 交互问题（证据） | 用户影响 | 改法（仅 UI/状态/投影） | 成本 |
|---|---|---|---|---|
| S1 | 结果工作台常驻第三列（`renderer/App.tsx:1202`、`renderer/components/SpatialWorkbench.tsx:732`），且挂载即初始化 MapLibre + 远程 carto 底图（`SpatialWorkbench.tsx:533-541`、`:28-31`、`renderer/styles.css:28`） | 未看结果时 42vw 是空白地图；对话仅约 560px；启动/离线都先付底图成本 | 默认收起，首次打开结果再展开；面板可折叠并记忆宽度（拖拽/按钮），空态不挂载地图 | 中 |
| S1 | 后端崩溃/终态事件丢失后卡死：`exit` 只设 context（`App.tsx:377`），`request.completed/failed` 才清 active/streaming（`App.tsx:387-420`）；自动重启仅 1 次无退避（`main/main.ts:532-535`）；带 TTL 的请求管理器未用（`renderer/pending-requests.ts:1-45`） | 传输层问题后永久"运行中"，发送被 Stop 取代，只能点侧栏同一任务才自愈 | `exit`/超时统一 reset（activeRequestId/streaming/stopping/pendingInteraction）；重连后按 `getBackendStatus().activeTaskId` 重新 `task.open`；接入 PendingRequestHandlers | 中 |
| S1 | 欢迎页"检索论文/分析数据/Autoresearch"三卡是 `<article>` 无 onClick（`renderer/components/OceanXWelcome.tsx:53-60`，定义 `:20-38`） | 新手点击无反应，第一印象失效 | 改成按钮并接真实动作；暂时做不了的置灰并标"即将推出" | 低 |
| S2 | 失败后无重试/继续按钮，只给一句提示（`App.tsx:402-406`）；输入框不回填（`App.tsx:640`；`restoreSubmittedPrompt` 在 `renderer/request-recovery.ts:3-8` 未用） | 一次模型/网络失败要用户复制原文重发，甚至去手打 "continue" | 失败气泡内嵌「重试/继续」，取消/失败时回填 prompt | 中 |
| S2 | 切换项目直接 SIGTERM 后端：`activateProject` 无确认（`App.tsx:522-568`），`sidecar.start()` 先 `await this.stop()`（`main/main.ts:413-418, 545-590`） | 长任务运行中手滑点另一个项目=中断后端，且无警告 | 运行中切项目弹确认（"后台任务将暂停"）；或改成多后端/只切视图 | 中 |
| S2 | 语言开关半失效：右栏/图表/报告/画布硬编码英文（`renderer/components/ScientificView.tsx:1108-1111`、`SpatialWorkbench.tsx:732-758`、`ReportWorkbench.tsx:27-30`、`AgentCollaborationCanvas.tsx:537`、`ConversationTranscript.tsx:297,314`） | 中文用户看到"图中文、右栏英文"的割裂 | 把这些组件接 `useUiLanguage`；先做结果面板与图表控件这两块最高频区域 | 中 |
| S2 | 流式答案塞在 260px 内部活动日志里（`ConversationTranscript.tsx:314`、`styles.css:185`），会话区无自动跟随/回到底部（全仓无 conversation-scroll 的滚动 effect） | 长回答要盯着小窗口内滚，完成后才"跳"成正式消息 | 答案流式直接渲染为 assistant 气泡；会话区贴底 + "回到底部"浮标 | 中 |
| S2 | 无命令面板 / 快捷键：仅 Enter 发送（`App.tsx:1162`）与对话框 Esc（`ModalDialog.tsx:20-25`）；`CommandPalette` 已实现但无产品引用（`packages/ocean-ui/src/command-palette.tsx`，仅 `command-filter.test.ts:3` 引用） | 任务多时只能鼠标；无 Cmd+K/Cmd+N/Cmd+Enter/Esc 关结果 | 接入命令面板（新建任务/切项目/打开设置/停止）；补 3 个高频快捷键 | 中 |
| S2 | 对话框无焦点陷阱：只做初始 focus + 恢复（`renderer/components/dialogs/ModalDialog.tsx:13-31`），Tab 可跑出对话框；`installModalFocusManager`（`packages/ocean-ui/src/modal-focus.ts`）无人调用 | 键盘用户/读屏用户在模态里迷路 | 在入口安装现成 focus manager，删掉 ModalDialog 里的重复实现 | 低 |
| S2 | 后台任务完成无系统通知/无声音：通知模块未接入（`packages/ocean-ui/src/notifications.ts`、`notification-stack.tsx`），侧栏只有小圆点（`ProjectTaskSidebar.tsx:113-122`） | 切走后不知道长任务已完成 | 任务完成触发系统通知/应用内 toast；窗口聚焦时不打扰 | 低 |
| S2 | 图表不能导出（`ScientificView.tsx` 无 download/export；仅 fallback 有原始文件下载 `SpatialWorkbench.tsx:815`） | 结果只能看不能进论文/汇报 | 图表 SVG/PNG 导出 + "复制到剪贴板"；报告图片下载已有可复用 | 中 |
| S3 | 任务不能重命名、不能搜索/筛选（无 rename 入口，`App.tsx:1151`；`styles.css:107` 还留着 `.conversation-title input` 重命名样式；`ProjectTaskSidebar.tsx:116-133` 全量渲染无过滤） | 任务一多只能肉眼找；建错名无法改 | 任务标题双击改名；侧栏搜索框 + 运行中/未读筛选 | 中 |
| S3 | 无拖拽导入：只能点 + 走原生对话框（`App.tsx:828-840, 1166`；全仓无 onDrop） | 导数据多一步 | 会话区/侧栏支持拖入文件/文件夹 | 低 |
| S3 | 错误反馈单槽且原始：`inlineStatus` 一个字符串（`App.tsx:1154`，26 处覆盖写入），失败直出后端 message（`App.tsx:406`） | 错误一闪被覆盖；看到的是原始异常/协议码 | 错误进时间线（可复制/可重试），区分用户可操作原因 | 中 |
| S3 | 性能：流式 delta 每 token 触发整树重渲染（`App.tsx:500` 全量 state 在根），两个 1s 计时器（`ConversationTranscript.tsx:168-173, 268-273`），全仓无 `React.memo/useDeferredValue` | 长历史 + KaTeX + 团队画布时输入/滚动发涩 | 流式文本单独订阅 + rAF 合帧；transcript 分片 memo；计时器合并到单一 tick | 中 |

---

## A. 交互便利度详述

### A1 首屏 / 空状态 / 新手引导 — **S1**

- **欢迎页死交互（S1）**：三个入口卡（`OceanXWelcome.tsx:53-60`）是 `<article>`，没有按钮语义也没有事件。这是"有没有项目"两种状态下最先看到的内容（`App.tsx:1152` 渲染 `OceanXWelcome`）。
- **欢迎页信息不足（S2）**：只有标题输入框（`OceanXWelcome.tsx:63-72`），没有示例问题、没有"最近任务/最近项目"直达、没有"从已有数据开始"。侧栏承担了全部历史导航（`ProjectTaskSidebar.tsx:89-136`）。
- **只有 `title="Create research task"` 还是硬编码英文**（`OceanXWelcome.tsx:72`），`aria-label="Welcome to OceanX"`（`:40`）同理。
- 好的部分：首屏会自动聚焦任务名（`OceanXWelcome.tsx:70`），无项目时降级为一个明确按钮（`:75`）。

### A2 项目与任务：创建/切换/恢复/重命名/删除 — **S1/S2**

- **创建**：欢迎页 Enter 提交（`OceanXWelcome.tsx:63-76`）+ 侧栏项目 `+`（`ProjectTaskSidebar.tsx:85-93`）。后端未就绪时会把标题挂起、ready 后补发（`App.tsx:611-636`），这一点做得不错。
- **切换成本高（S2）**：切换项目会重启后端（见上表）；切换任务会 `resetTaskPresentation()` 清空全部呈现状态再 `task.open`（`App.tsx:289-338`），没有缓存/骨架，每次都白屏到快照回来。没有加载骨架，只有"正在加载任务…"一行（`ConversationTranscript.tsx:396`）。
- **恢复（S2）**：渲染进程不持久化"上次打开的任务"。重开窗口时只恢复项目、不恢复任务：`App.tsx:506-516` 只用 `status.workspacePath`，完全忽略主进程已返回的 `activeTaskId`（`main/main.ts:632` 有该字段、`src/shared/bridge.ts:49` 声明了它）。关闭再打开 = 回到"选择任务"空态，后台还在跑。
- **重命名（S3）**：没有入口；`styles.css:106-107` 保留着 `.conversation-title input` 的样式，说明重命名功能被移除后样式没清。
- **删除**：任务/项目都有确认对话框，文案清楚且说明"只从侧栏移除，磁盘文件保留"（`ProjectRemoveDialog.tsx:20-24`、`TaskDeleteDialog.tsx:21`）。运行中的任务在侧栏隐藏删除按钮（`styles.css:72`），但会话工具栏的删除按钮仍常驻（`App.tsx:1151`）。
- **删除运行中任务/删除当前项目**都走"先切项目再补发 delete"的挂起逻辑（`App.tsx:1063-1079`），期间用户会看到别的任务闪一下，缺乏"正在删除…"的反馈。

### A3 对话体验：流式 / Markdown / 工具调用 / 滚动 / 停止 / 重连 — **S1/S2**

- **流式呈现位置不对（S2）**：流式文本进的是"研究动态"小窗（`ConversationTranscript.tsx:314`），`max-height: 260px` + 内部滚动（`styles.css:185`）；只有拿到 `finalItem` 才渲染为正式 assistant 气泡（`ConversationTranscript.tsx:505`）。长答案的阅读体验是"在小盒子里看字"。
- **无自动跟随（S2）**：`conversation-scroll`（`styles.css:110`）没有任何滚动 effect；只有内部日志会贴底（`ConversationTranscript.tsx:266`）和论文选择会 scrollIntoView（`:340`）。因此新消息/流式增长时外层不动，用户必须手动滚。
- **Markdown/KaTeX/代码块（OK）**：`react-markdown + remark-math + rehype-katex + remark-gfm`（`message-markdown.tsx:1-5`），代码块有深色样式（`styles.css:152`），表格横向滚动（`:154`），外链只允许 http(s)（`message-markdown.tsx:87-103`）。结果引用 `[[result:...]]` 会被投影成按钮（`:218-244`），这是本仓交互设计里做得最好的一处。
- **工具调用噪声控制（OK，但不可回看）**：`presentTranscript` 把同一 request 的 tool-use turn 折叠进 process（`renderer/conversation-presentation.ts:24-47`），完成态只渲染最终消息。代价是**完成后没有任何"查看过程/thinking"入口**：`Working` 在 `!group.active && !matchingTeam` 时直接返回 null（`ConversationTranscript.tsx:274`），注释里承诺的 "collapsible Thinking history"（`conversation-presentation.ts:36-40`）并不存在。想核对工具调用/中间结论时无路可走（S3）。
- **停止（S2）**：有停止按钮和 `stoppingRequestId` 双态（`App.tsx:807-823, 1196`）；但停止请求自身没有超时，若 `request.cancelled` 不回，按钮永久"正在停止"。停止后不恢复输入框（`restoreSubmittedPrompt` 未用）。
- **重连/序列（S2）**：渲染进程只按 `event_id` 去重（`App.tsx:379-380`），**没有序列号缺口检测**：`packages/ocean-client/src/backend-sequence.ts` 与 `transport.ts` 仅被测试和遗留 TUI 使用（`useOceanBackend.ts:18`），桌面端丢了帧只能等下一次快照。主进程对 stdout 的异常会包装成 diagnostic 直接显示给用户（`main/main.ts:860, 377` 的 `App.tsx:376` 会把非 backend_log 的诊断当 inlineStatus）。

### A4 长任务：进度 / 专家并行 / 取消 / 失败重试 / 离开页面 — **S1/S2**

- **进度可见性（较好）**：团队画布（`AgentCollaborationCanvas.tsx:380-590`）+ 实时研究日志（`ConversationTranscript.tsx:293-319`）+ 请求计时（`:163-183`）+ 侧栏"运行中"圆环（`ProjectTaskSidebar.tsx:105-122`）。专家节点可 hover/聚焦弹出目标与当前动作（`AgentCollaborationCanvas.tsx:536-555`）。
- **专家并行（较好）**：节点按 `profile_id/agent_run_id` 区分线程（`ConversationTranscript.tsx:53-82` 的别名逻辑；`AgentCollaborationCanvas.tsx:281-330`），可折叠整块团队区（`ConversationTranscript.tsx:280-289`）。
- **取消语义（S2）**：只有会话级取消，没有"取消某个专家/只停止当前分支"；取消后已产出的部分结果仍在，符合预期。但侧栏运行中任务隐藏删除、也不提供"停止"（`styles.css:72`），必须在会话内操作。
- **失败后只重试失败部分（S2，缺失）**：没有重试入口，只能整体重发；`request.failed` 里 `recovery_state=awaiting_user_retry` 的处理是让用户"发送 continue"（`App.tsx:402-403`）——把可按钮化的恢复做成了自然语言约定。
- **离开页面后回来（S1）**：切到别的任务时后端继续跑（正确），但**后端崩溃后不会自动回来**（见上表 S1-2）：`exit` 不清 `activeRequestId`/`streaming`（`App.tsx:377`），自动重启后的 `system.ready` → `connectReady` 也不会重新 `task.open`（`App.tsx:348-373`，只有 `pendingTaskRestore` 才恢复）。用户唯一的自愈动作是再点一次侧栏任务。
- **重复提交防护（OK）**：`task.active_request_id`、`sourceImporting`、`stoppingRequestId` 多守卫（`App.tsx:753, 1196`）；但守卫与按钮 disabled 条件不完全一致（`submit` 看 `task.active_request_id`，按钮不看），存在"点了没反应"的边角（S3）。

### A5 结果与图表：进入/返回/加载/错误/空数据/缩放/导出 — **S2**

- **进入路径（OK）**：答案里的结果按钮（`message-markdown.tsx:227-243`）、"其他结果"折叠区（`ConversationTranscript.tsx:522-534`）、报告内交叉引用（`App.tsx:1116-1123`）都能打开右侧工作台；同结果切换有 `openResultKey` 守卫防止串台（`App.tsx:928-1025`）。
- **返回路径弱（S2）**：关闭按钮只在有 document 时出现（`SpatialWorkbench.tsx:750`），关闭后回到一块空地图而不是收起；Esc 无效；没有"上一个/下一个结果"、没有多标签。报告与图表工作台互斥替换（`App.tsx:1202`）。
- **常驻占屏与空态（S1）**：见上表。`welcome-mode` 只在没有活动任务时隐藏（`styles.css:29-30`），一旦选中任务就永久三列。
- **加载/错误/空数据（较好）**：加载遮罩（`SpatialWorkbench.tsx:755-757`）、地图失败 fallback（`:754`）、渲染失败边界（`InteractiveViewWorkbench.tsx:36-55`）、数据缺失文案（`SpatialWorkbench.tsx:756`）。但错误态没有"重试"按钮，且文案是英文硬编码。
- **缩放交互（S2/S3）**：图表有缩放/重置（`ScientificView.tsx:1108-1111`），但控件默认 `opacity:.28` 仅 hover/focus 才显形（`styles.css:524`），可发现性差；地图依赖 MapLibre 自带控件（`SpatialWorkbench.tsx:547-548`），无键盘平移/缩放。
- **导出（S2，缺失）**：`ScientificView.tsx` 无任何 download/export；只有 fallback 的"下载原始结果"（`SpatialWorkbench.tsx:815`）和报告图片下载（`ReportWorkbench.tsx:30`）。"plot studio"（ADR 0003）在客户端并不存在（见 D 节）。
- **本地优先 vs 底图（S3）**：底图是远程 carto 瓦片（`SpatialWorkbench.tsx:28-31`），离线时 8s 后显示 "Map unavailable"（`:556`），与"本地优先"的产品叙事不一致；无离线底图/重试。

### A6 键盘可达性 / 可访问性 / 中英文与文案 — **S2/S3**

- **键盘（S2）**：只有 Enter 发送（含 IME 组合保护，`App.tsx:1162`）、论文选择 Enter（`InteractionDrawer.tsx:100-107`）、对话框 Esc（`ModalDialog.tsx:20-25`）。没有命令面板、没有全局快捷键、没有 Esc 关闭结果工作台、没有"聚焦输入框"。已实现的 `CommandPalette` 未接线。
- **焦点管理（S2）**：模态只有初始 focus + 关闭恢复（`ModalDialog.tsx:16-26`），Tab 会跑出对话框；`installModalFocusManager`（`packages/ocean-ui/src/modal-focus.ts:36-108`）覆盖了 Tab 循环、Esc、焦点归还，但没有任何产品代码调用它（仅 `index.ts:1` 导出）。
- **语义（S3）**：大部分按钮有 `aria-label`/`aria-pressed`（`App.tsx:1166-1196`），论文选择用了 table/row/cell 角色（`InteractionDrawer.tsx:45-66`）。问题点：
  - 团队画布父级 `role="img"` 包着可聚焦节点（`AgentCollaborationCanvas.tsx:481-484` vs `:536`），子树语义在部分读屏器下会被当装饰；节点 aria-label 是英文模板（`:537`）。
  - 节点焦点有可见反馈（`styles.css:227`，仅描边），但没有全局 `[tabindex]:focus-visible` 规则（`:25` 只覆盖 button/input/textarea/select/summary）。
  - 地图区域无可聚焦入口/键盘操作（`SpatialWorkbench.tsx:750-760`）。
- **对比度（S3）**：`--faint #97a9bb` 在白底 **2.41:1**、在 `--bg` 上 2.22:1，却用于小字（`styles.css:98, 412, 592`）；`--teal #2e8fd4` 白底 **3.5:1**（按钮/链接文本场景不足 4.5:1）；`button:disabled{opacity:.48}`（`:24`）进一步降低。`--muted` 被设成 `var(--ink)`（`:6`），说明作者已经意识到正文对比度，但 faint 小字漏了。
- **动效（S3）**：`prefers-reduced-motion` 只覆盖 CSS 动画/过渡（`styles.css:653`），团队画布的 SMIL `<animateMotion>` 粒子动画不受影响（`AgentCollaborationCanvas.tsx:519-521`），且是无限循环。
- **中文覆盖（S2）**：语言状态见 `i18n.tsx:19-29`，切换入口在设置（`DesktopSettingsDialog.tsx:129`）。用了 `text()` 的只有 App/Welcome/Sidebar/InteractionDrawer/dialogs/ConversationTranscript；**没用**的是右栏三大件 + 画布 + 报告：`ScientificView.tsx:1108-1111`、`SpatialWorkbench.tsx:732,736,754,758,779`、`ReportWorkbench.tsx:27-30`、`InteractiveViewWorkbench.tsx:167-170`、`AgentCollaborationCanvas.tsx:537,572`。`ConversationTranscript.tsx:297,311,314` 的 "Coordinator:/OceanX:" 也是英文。
- **错误文案（S2/S3）**：App 里大量英文硬编码错误（`App.tsx:894, 896, 901-903, 916, 940, 996, 1031, 1037, 1041, 1044`），中文模式下也直接显示英文；协议错误只透传后端 message（`App.tsx:406`），没有"下一步怎么办"（例如"模型密钥无效→去设置"目前只有一条全局 recovery 文案）。

### A7 状态反馈：加载/禁用/乐观更新/重复提交/进度 — **S2/S3**

- **加载态**：项目启动/连接有状态文字（`App.tsx:1126-1128`），任务加载一行文案（`ConversationTranscript.tsx:396`），结果有遮罩。缺骨架屏、缺"预计还要多久"。
- **乐观更新（部分）**：发送时插入乐观 user 项（`App.tsx:73-87, 640`），但**取消/失败时不做回滚标记**，也没有把 `submissionTransportFailureItem` 这类"失败在时间线里可见"的机制接上（`request-recovery.ts:22-34` 未用）。
- **单一状态槽**：`inlineStatus` 一个字符串被 26 处覆盖（`App.tsx:1154`），重要错误很容易被后续"连接中/已就绪"类更新冲掉；没有 toast/通知栈（尽管已实现）。
- **长操作无预估**：研究任务只有计时（`ConversationTranscript.tsx:177-181`），没有阶段/百分比；`AgentActivityPanel` 若接入本可提供逐 agent 活动，但它是死组件（见 B/D）。
- **重复提交/禁用（基本 OK）**：发送、研究模式切换、语音、附件都有 disabled 逻辑（`App.tsx:1166-1196`），研究模式在请求中被禁用（`:1172`）。

---

## B. 代码质量

### B1 App.tsx / main.ts 职责过载 — **S2（维护成本）**

- `renderer/App.tsx` 1208 行单组件：**49 个 `useState`（:113-162）、21 个 `useRef`（:164-184）、18 个 `useEffect`**，其中 6 个 effect 只为把 state 同步进 ref（:185-195）；`handleFrame` 单函数 129 行（:375-503）同时处理 system.ready、request 终态、snapshot、workspace 事件、team、transcript、delta、interaction；三个近乎重复的请求助手 `request` / `taskRequest` / `libraryRequest`（:229-279）；`openTask`（:315-338）、`loadTaskResults`（:339-347）、`importSource`（:713-746）各自带重试/守卫。
- `main/main.ts` 1262 行混合 6 类职责：更新服务（:126-266）、sidecar 生命周期（:396-1018）、artifact 协议与授权（:670-737）、模型 provider helper（:445-511）、窗口（:1033-1086）、项目目录持久化（:70-117）、IPC 注册（:1142-1220）。
- 建议（不动 agent 逻辑）：App 拆 `useBackendTransport`（frame 分发 + 请求表 + 超时）、`useTaskSession`（open/snapshot/transcript）、`useResultSurface`（右栏）；呈现状态收进 `useReducer`，`handleFrame` 变成 reducer 的 event 分支表；main 拆 `backend-sidecar.ts` / `artifact-protocol.ts` / `updates.ts` / `project-catalog.ts`。预期 App.tsx 降到 300 行量级、main.ts 每模块 < 400 行。
- 具体重复/失配（S3）：
  - `tasks` state 只写不读：`renderer/App.tsx:116` `const [, setTasks] = useState(...)`，侧栏实际用 `projects` 目录（`App.tsx:1131-1149`），同一份任务列表在 `tasks`、`projects`、主进程目录文件里存在三份投影。
  - 项目目录双持久化：渲染进程 localStorage（`App.tsx:46,134,199`）+ 主进程 JSON 文件（`main/main.ts:70-117`），两边各写一套合并逻辑（`renderer/project-catalog.ts` vs `main.ts`）。
  - 乐观 transcript 逻辑两套：`App.tsx:73-87` vs `renderer/request-recovery.ts:8-95`（后者除 `revisionFromRequestFailure` 外全未使用）。
  - `pending-requests.ts`（带 180s TTL）与 `backend-sequence.ts`（缺口检测）都没有接进 App，实际用的是裸 `Map`（`App.tsx:164-165`）。

### B2 状态管理与渲染性能 — **S2**

- 流式文本 `setStreaming` 在根组件（`App.tsx:500`），每个 delta 重渲染整个 App（含侧栏、transcript、团队画布、右栏）；全仓 **0 处** `React.memo` / `useDeferredValue` / `startTransition`。
- `ConversationTranscript` 内两个独立 1s `setInterval`（:168-173 与 :268-273）都会重渲染整段 transcript；长任务 + 多段 KaTeX 时滚动会抖。
- 大列表无虚拟化：transcript 分组全量渲染（`ConversationTranscript.tsx:406-537`），侧栏任务全量渲染（`ProjectTaskSidebar.tsx:116-133`）；任务上百后无分页/过滤。

### B3 协议类型：生成代码基本没用起来 — **S2**

- 渲染进程唯一的生成类型使用是 `RequestContext`（`renderer/types.ts:1`）；其余协议全部手写 `Record<string, unknown>`（`types.ts:3` `EventPayload`），事件靠 `as unknown as X` 硬转：`App.tsx:364, 425, 444, 493, 1029`。
- 主进程同样用 `Record<string, unknown>` 传 frame（`src/shared/bridge.ts:72`、`main/main.ts:585-650` 手工校验每个字段）。
- 生成文件本身有 1219 行（`packages/ocean-client/src/generated/protocol-v2.ts`），产品里唯一真正消费它的是**遗留 TUI**（`frontend/ocean_terminal/src/hooks/useOceanBackend.ts:6-18` 用 `OceanEvent`/`TransportSequenceTracker`）。也就是说主客户端反而比废弃客户端类型更弱。
- 建议：以 `generated/protocol-v2.ts` 为源，在 `types.ts` 里做投影/别名（`TranscriptItem`、`TaskResultRecord`、`TaskSnapshotPayload`、`TeamSnapshot`），对事件按 `type` 建判别联合，替换 `as unknown as`；这是纯类型层改动，不动运行时。

### B4 渲染进程与主进程边界 — **做得好的部分**

- `contextIsolation` + `sandbox: true` + `nodeIntegration: false`（`main/main.ts:1044-1057`），preload 只暴露白名单 bridge（`src/shared/bridge.ts:68-90`）。
- IPC 全部校验发送方是主窗口（`main/main.ts:1022-1026`），artifact 资源走短期 token + 路径穿越/realpath 校验（`:670-737`），更新清单有体积/签名约束（`:41, 145-178`）。
- 建议保持；拆文件时不要打破这两处。

### B5 测试覆盖（详见 C）— **S2**

- 40 个 vitest 文件，纯函数覆盖不错（`request-recovery`、`pending-requests`、`backend-sequence`、`message-markdown`、`scientific-figure`、`project-catalog` 等都有测试）。
- **`App.tsx` 零测试**（全仓无 `App.test`），而它承载了全部事件分发/恢复逻辑——上面 S1-2 的崩溃卡死正属于没有测试覆盖的区域。
- `components/workbench-layout.test.tsx` 1379 行，主要给 `AgentActivityPanel` 等**死组件**做快照/静态渲染测试（`:5, :225`），投入与产品价值不匹配。
- `ConversationTranscript.test.ts` 只 73 行、测 presentation 纯函数；`workbench-layout` 里有一些画布/结果布局断言；**没有一条测试覆盖"后端崩溃→恢复"或"请求超时"**。
- **e2e 已失效**：`tests/research-interactions.spec.ts` 与 `tests/result-object-bindings.spec.ts` 在 `d496fcb` 被删除，但 `tests/README.md`（整篇仍描述覆盖范围）、`package.json:15-17` 的 `e2e`/`e2e:research`、`tests/fixtures/*`、10 张 `tests/visual-regression.spec.ts-snapshots/*.png` 都还在；`git log --all -- 'tests/visual-regression.spec.ts'` 为空（该 spec 从未入库），即快照是无主产物。`npm run e2e` 现在会 "no tests found"，`npm run e2e:research` 指向不存在的文件。
- 这也意味着 README 里"Project/Task creation through Enter…Cancellation during generation…"那段承诺目前**没有可执行的回归保障**。

---

## C. 可运行验证（只读，未构建）

| 命令 | 结果 | 说明 |
|---|---|---|
| `./node_modules/.bin/tsc --noEmit -p tsconfig.json`（renderer） | **通过** | 0 错误 |
| `./node_modules/.bin/tsc --noEmit -p tsconfig.main.json`（main） | **通过** | 0 错误 |
| `npm run check`（= 上面两条） | **未能执行** | 本机 npm 缓存目录 root 权限报错（`~/.npm/_cacache` EPERM），与仓库无关；等价命令直接调 tsc 已通过 |
| `npm test` / `./node_modules/.bin/vitest run` | **无法启动** | Node 21.6.1 缺少 `node:util` 的 `styleText`（vite 8/rolldown 要求 `^20.19.0 || >=22.12.0`，`node_modules/vite/package.json:179`）。本机只有 Node 21.6.1，无 22；故 40 个 vitest 用例**未实际执行**（环境限制，非用例失败） |
| `npm run e2e` | **不可用** | `tsconfig.e2e.json` 只含 `tests/**/*.ts`（fixtures），Playwright `testDir: './tests'` 下已无 `*.spec.ts`；按用户要求未执行 build |
| 工作区 | **干净** | 审计开始 `git status --short` 为空；本报告是唯一新增文件 |

环境问题本身是一个可修项（S3）：仓库没有 `engines`/`.nvmrc`，README 只说 "Node.js 24"（`README.md:223`），CI 用 `node-version: "20"`（`.github/workflows/desktop-signed-release.yml:37,110`），开发机落在 21.x 时会得到"测试跑不起来"而不是明确报错。

---

## D. 死代码 / 遗留 / 入库产物

### D1 ocean_terminal：**确认是遗留，建议退役（先迁移类型）**

- 13 个 tracked 文件，含 `src/hooks/useOceanBackend.ts` 1450 行、`src/App.tsx` 708 行（`git ls-files frontend/ocean_terminal`）。
- **产品侧无引用**：桌面端不 import；Python 后端 `src/oceanx` 内 grep 不到 `ocean_terminal`/`ocean-terminal`；CLI 命令只有 `batch/run/configure-models/backend/schema-export/doctor/export/version`（`src/oceanx/cli.py:35-311`），没有任何 TUI 入口。
- 只有发布校验和里出现它的构建产物：`src/oceanx/_ocean_terminal/dist/ocean-terminal.mjs`（tracked 构建产物，本应生成而非入库），被 `release-metadata/**/checksums.json` 引用。
- 唯一价值：它是**唯一正确使用生成协议类型 + 序列追踪 + workspace revision 的客户端**（`useOceanBackend.ts:6-18`），可作为 B3 的类型迁移参考。建议：先迁类型/序列检测，再删 TUI 与 tracked dist（或至少停止入库产物）。

### D2 plot_studio：**空壳**

- `frontend/plot_studio/` 下只有被忽略的 `node_modules/` 和一个 `tsconfig.tsbuildinfo`，无源码、无 package.json、`git ls-files` 为空；ADR 0003 已标 `Superseded by ADR 0019; historical only`（`docs/adr/0003-plot-studio-map-and-linked-plot-libraries.md:3`）。客户端里也没有 "Plot Studio" 入口（结果只有 map + scientific figure）。建议删目录；若产品仍需"图库/联动图"能力，应按 ADR 0019 重新立项目标。

### D3 packages/ocean-ui、ocean-client：**桌面端基本未消费**

- `packages/ocean-ui` 的 `CommandPalette`、`NotificationStack`、`installModalFocusManager`、`DockResizeHandle/SpatialPaneResizeHandle` 均未被产品代码引用，只有测试引用（`renderer/notifications.test.ts:10`、`renderer/command-filter.test.ts:3`）；桌面端各自重写了一份（`ModalDialog.tsx`、`inlineStatus` 字符串、`SpatialWorkbench.tsx:771-795` 内联 split rule）。
- `ocean-client` 的 `transport.ts`（17 行）、`backend-sequence.ts`（28 行）只在测试中被引用（`renderer/backend-sequence.test.ts:3`）。
- 结论：这两包目前是"为遗留 TUI 建的共享层"，对主客户端只提供 1 个类型。要么接入（B1/B3 建议顺带消化），要么承认并合并，避免后续双实现继续漂移。

### D4 死组件 / 死模块 / 死样式

- `renderer/components/AgentActivityPanel.tsx`（222 行）：产品无引用，仅 `workbench-layout.test.tsx:5,225` 使用。
- `renderer/components/InteractiveViewWorkbench.tsx` 的导出组件 `InteractiveViewWorkbench`（:158）无产品引用（`SpatialWorkbench` 只 import 了 helpers），仅测试使用；同文件 `viewLabel` 等仍有用。
- 未接入的模块：`renderer/pending-requests.ts`、`renderer/request-recovery.ts`（除 revision）、`packages/ocean-client/src/transport.ts`、`backend-sequence.ts`、`packages/ocean-ui/src/modal-focus.ts`、`command-palette.tsx`、`notification-stack.tsx`、`resize-handles.tsx`。
- 死样式：`styles.css:106-107` 的重命名输入框；`.agent-activity*` 一组（`:253-311`，仅死组件与一处 class 名巧合复用）；`--faint` 相关对比度问题见 A6。
- 入库产物/目录：`dist/`、`dist-electron/`、`.sidecar-build/`、`sidecar/`、`test-results/` 均已在 `.gitignore`（:5,:50,:61,:62）——干净；**唯一例外**是 `src/oceanx/_ocean_terminal/dist/ocean-terminal.mjs` 被 tracked，应改为构建生成。

---

## 最值得先做的 5 件事（按投入产出）

1. **收起常驻结果工作台**（S1，中）：空态不渲染 `ResultWorkbench`/不初始化 MapLibre，首次打开结果时再展开并记忆宽度。直接释放 42vw。
2. **崩溃/丢终态自愈**（S1，中）：接入 `PendingRequestHandlers` 超时；`exit`/重连统一 reset 并 `task.open` 当前任务（用主进程已有的 `activeTaskId`）。这是"长任务不可用"的核心。
3. **欢迎页三卡做成真按钮**（S1，低）+ 失败气泡内嵌「重试/继续」并回填 prompt（S2，低）。
4. **中文模式补齐右栏三件套 + 画布文案**（S2，中），先做 `SpatialWorkbench`/`ReportWorkbench`/`ScientificView` 的标题、控件、错误态。
5. **接命令面板与模态焦点管理器**（S2，低）：`packages/ocean-ui` 里已写好，接线即可得到 Cmd+K、Tab 循环、Esc 归还焦点。

补充：修 e2e（恢复被删 spec 或删残留快照/README/脚本二选一，S2）与补 `App` 的事件恢复单测，应跟第 2 项一起做，否则同类回归还会出现。

---

*未评审范围：agent 编排/专家调度逻辑、skill/tool 学习与审核逻辑（用户明确排除）。本报告未修改任何产品代码、测试或配置。*
