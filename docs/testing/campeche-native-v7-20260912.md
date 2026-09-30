# Native v7: autonomous completion without research quotas

## Scope

User authorized the existing DeepSeek configuration and `/Users/ryanzhang/Code/CMEMS_oceanmind` for an isolated live test. Model assignments were not changed. The original Campeche question is used without scripted roles, ordering, or intermediate answers. Existing tasks are untouched.

Research runtime no longer installs cumulative-token wind-down, team-token dispatch rejection, per-assignment token tiers, turn/tool-count cutoffs, duplicate-result execution rejection, or an overall execution deadline. LangGraph uses an infinite recursion limit, not a larger finite allowance. Expert execution defaults disable wall/CPU/memory/file/output quotas. Usage and execution logs remain recorded. Explicit cancellation and read-only/path/network permissions remain; provider/API constraints are not removed. CLI/batch execution has no default timeout (an explicitly supplied caller timeout still applies).

Automatic review is still limited to the two analysis profiles, but does not stop solely because it has run two rounds. It ends when the reviewer returns PASS or UNRESOLVED, or an execution/transport error occurs. Repairs retain the original analysis session.

The Coordinator prompt contains short examples of simple execution, research subquestions and evidence-led follow-up. The Expert chooses methods; only user-specified methods are mandatory. No all-Pro model change was made.

## Diagnostic attempt A

Directory: `output/campeche-native-v7-unlimited-20260912`.

The Coordinator dispatched Data and Literature concurrently. Both initial messages remained long, enumerated assignments; removing quotas did not itself change delegation style. The run was manually cancelled for a diagnosed defect, not by a resource threshold: the model repeatedly submitted the historical-code placeholder as a new executable Python script. This was confirmed in the original LangGraph checkpoint, not only in projected request snapshots. Comment-only scripts exited successfully without doing the requested work.

The custom `ExpertContextMiddleware` projection was removed from the production runtime. It had replaced executed code with valid Python comments referring to saved files. Framework summarization and on-disk evidence remain. A wire-level test assertion checks that this synthetic placeholder is absent from outgoing tool-call history in the clean run.

Recorded at cancellation: 149 model-call records; 4,314,902 input tokens and 149,559 output tokens from available usage records. Data: 85 model calls, 69 code calls, cancelled. Literature: 63 model calls, 30 code calls, cancelled. One Coordinator call. These are diagnostic costs, not a successful research result.

## Clean attempt B

Directory: `output/campeche-native-v7-clean-20260912`.

Status: manually stopped at the user's request. The harness exited with code 130; its process and backend are no longer running. No further real API run was started after the stop request. Same original question, supplied dataset and configured models; new task and clean model history. No research quota and no test timeout. This is **not a successful end-to-end research result**.

Observed interval: 2026-09-12 15:54:24–16:09:02 UTC (about 14 minutes 38 seconds). Per-call records include the cancelled final Coordinator call; usage totals below include only usage actually returned by the provider.

| Role | Model calls | Input tokens | Cached input (subset) | Output tokens | Python calls / failures | Summed model-call elapsed | Summed Python elapsed |
| --- | ---: | ---: | ---: | ---: | --- | ---: | ---: |
| Data | 45 | 1,320,015 | 1,160,448 | 66,473 | 31 / 7 | 341 s | 104 s |
| Literature | 41 | 1,615,732 | 929,664 | 107,959 | 6 / 2 | 495 s | 46 s |
| Coordinator | 9 (8 completed, 1 interrupted) | 180,490 | 156,544 | 11,837 | — | 196 s | — |

Total recorded usage: **3,116,237 input + 186,269 output tokens**. Cache reads are already included in input, not an additional quantity. These counts are not a bill; token pricing depends on cache and provider tariffs. Model-call elapsed includes client/provider waiting, not a pure generation measurement. Concurrent role times must not be added to derive wall time.

Framework context summarization was active: Data 2 summary calls (about 51 s), Literature 6 (about 140 s). It is incorrect to describe this run as having no memory compression. Across the eight summary calls, recorded usage was 381,871 input and 44,803 output tokens. Their benefit cannot be estimated without a controlled comparison.

### 实际发现及边界

1. **初始路线对了，委派内容仍然清单化。** Coordinator 自主并行派出 Data 和 Literature；但 Data 的消息仍有六项编号要求，Literature 列了四组主题和逐篇字段。不是后台偷偷扩写这两条消息，也不是预算退出触发的清单。提示词示例没有在本次运行中消除这种行为。由于尚未进入下一轮物理研究委派，不能据此断言所有研究子问题仍会被写成方法清单。
2. **Data 自己扩大了工作范围。** 前 11 次代码调用已做文件、变量、坐标、时间、缺测和区域覆盖检查；之后主动做 SST 年谐波、残差持续性、MLD 多种判据、温度剖面、26°C 等温线及图件修正。并非 Coordinator 首轮明确要求逐项计算这些诊断。部分工作有科学价值，但把准备阶段扩成了小型分析，也会与后续分析角色重叠。Data 总轮次约 586 s，其中 Python 约 104 s，计算本身不是全部耗时的主因。
3. **文件复用仍有真实摩擦。** 每次代码执行的 outputs 目录不同。Data 的第 17、19 次调用在当前输出目录找先前结果而失败，之后改用绝对路径或重算；Literature 也在生成报告时找不到上一执行的 JSON，再尝试目录搜索，最后在一次执行里重写三个交付物。这是本次记录中直接可见的文件定位成本，不应再靠责怪模型“不记得路径”掩盖。
4. **文献范围和交付体量膨胀。** 最终候选清单有 28 条，落盘 Markdown 为 70,906 字符。其记录显示搜索服务遇到 429，改用其他检索通道，增加了检索/核对工作。这里未独立核查 28 条文献的真实性或科学内容。不能把六次摘要调用简单归因于“模型不够强”。
5. **两份结果都在交接阶段被旧限制损坏。** Literature 已完成 ocean_deliver，但 ExpertResult.text 的 8,000 字符上限拒收，外层误报为 Participant could not start；工单汇总甚至显示零用量，和 41 次调用记录矛盾。Data 第一次交付含不存在的路径，之后请求执行列目录代码来纠正路径；旧中间件只允许 ocean_deliver，随即计为第二次失败并终止。Data 不曾耗尽研究预算。
6. **Coordinator 在读文件救场，而非推进研究。** 收到两个失败返回后，它确实使用 report_path 读取证据，说明文件交接不是完全失效；但随后多轮分页读取文献报告和清单，直到用户停止测试仍无第二次研究委派。不能把这段运行用来评价 research tree 是否改善科学结论：物理/统计分析、同类型审核、最终综合都未走完。

### 本次交接修复（停测后，仅离线验证）

- 移除 ExpertResult 正文、方法、局限文字等对应的正文长度上限，以及最终答案正文的 64,000 字符上限；不截掉报告来绕过校验。
- 移除格式修复阶段的工具剥离和两次失败计数器。路径错误仍返回事实错误，但 Expert 可以查文件再交付；不存在的文件不会假装验证成功。
- 删除模型返回包中已经无意义的 remaining_team_tokens 字段。
- 保留取消和文件访问权限；未改模型配置，未加入新的委派规则，未改动旧测试记录。

First dispatch, post-return Coordinator context, exact file reads and per-call measurements are in `output/campeche-native-v7-clean-20260912/handoff-excerpts/`. In particular: `first_dispatch.json`, `after_first_delivery_context.json`, `observations.json`, `expert-metrics.json`, `model-call-metrics.json`. Per-work-order Literature usage is invalid after the receipt exception; the table deliberately uses per-call measurements instead.

**结论：** 本次验证了移除预算后专家能够持续执行并主动进入交付，但交付仍被旧协议限制拦截；没有验证到完整研究闭环。剩余观察到的问题是准备阶段工作量扩张、跨执行文件复用成本、文献报告体量和 Coordinator 阅读成本，不能继续统称为“预算太小”或“Tree 太重”。

## 后续修复：固定 Expert 输出目录

针对用户随后要求修复的目录问题，Python 的当前目录和 `OCEAN_OUTPUT_DIR` 现统一固定为 `<expert-session>/outputs/`，同一逻辑 Expert 的多次执行及续派复用该目录。原有 `<expert-session>/workspace/` 中间文件目录仍保留。模型收到的输出文件路径也指向固定位置，不再以新的执行 ID 改变。

代码、日志和结果的审计快照仍按执行分别存档。活跃文件和快照不共享可变字节，原地覆盖活跃文件不会修改旧结果；未变化的快照通过已有快照硬链接复用，避免重复复制大数组。报告归档将固定位置的引用绑定到最新执行快照。不同 Expert 仍使用不同目录，旧真实测试文件未移动。

验证不调用真实 API：实际沙箱连续执行写 JSON、用相对路径和 `OCEAN_OUTPUT_DIR` 读取 JSON、续派修改文件、核对旧快照未变、核对另一个 Expert 的目录独立；同时检查模型工具返回固定路径。回归文件：`tests/test_oceanx/test_fixed_expert_outputs.py`、`tests/test_oceanx/test_expert_file_handoff.py`。

最终全量回归：**654 passed, 3 skipped, 4 warnings**（60.66 秒），日志 `/tmp/oceanx-fixed-outputs-verified.log`；静态检查与 `git diff --check` 通过。无需迁移旧测试结果；本轮未进行真实 API 重测，也未迁移到 DeepAgents 原生 subagent。

## Verification

- Before removing the placeholder projection: 651 tests passed, 3 skipped, 4 warnings across backend and sandbox suites.
- Real graph regression exercises 49 tool calls and multi-million cumulative input usage without a step/token stop, then returns an ordinary final answer.
- Zero-quota sandbox execution completes; explicit cancellation still terminates its process group.
- Native broker portable tests: 15 passed. Windows-specific execution is not validated on this macOS host.
- Final full regression after removal of the placeholder projection: 652 passed, 3 skipped, 4 warnings (63.96 seconds). Log: `/tmp/oceanx-v7-clean-verified.log`.
- After the live-test handoff fixes: **653 passed, 3 skipped, 4 warnings** (68.67 seconds). Log: `/tmp/oceanx-v7-handoff-verified.log`. Handoff-specific tests separately: **33 passed** (6.62 seconds), including file lookup after an invalid reference, delivery after multiple invalid attempts, and a report longer than 100,000 characters. No paid model calls were used in these regressions.
- An initial regression invocation inside the restricted host sandbox produced 25 failures from unavailable nested sandbox/process/loopback operations; rerunning with the required local test permissions produced the full passing result above. This did not restart the research test.
