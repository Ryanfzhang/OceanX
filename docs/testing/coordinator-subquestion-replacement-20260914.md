# Coordinator 职责整体替换

## 已停止旧测试

用户要求停止的运行是 `output/campeche-round60-20260913-1425/query/attempt-1789309539547649000-c950fc18`。
向确认的 CLI PID 51071 发送 SIGINT；`result.json` 记录 `cancelled / Runner interrupted`，5798.334 秒。
进程复查确认 CLI 51071、backend 51072、research server 51084 均退出，没有匹配该运行的残留进程。原报告、日志和结果保留；`campeche` 监控已暂停，未重启测试。

## 替换内容

- `runtime.py` 的 Coordinator Research lead / Handoff 段整体替换，删去“一个 Expert 可负责完整研究”及整题转包的示例。
- 开放研究选择首个有价值的子问题；可并行的是独立子问题，不是预先穷尽所有方法。
- 新例子展示原问题、首个子问题、Expert 发现、研究树更新、深化/新方向/不可检验时结束的关系；没有规定某个案例必须采用这些科学方法。
- Research notes 改为模型维护的简洁 Markdown research tree：原问题为根，科学子问题为分支，依据报告更新发现、证据路径和剩余疑点。后端沿用已存在的进度保存，不增加树状态机或节点表格。
- `graphs.py` 删除一处重复的委派粒度说明，保留通知、等待、结束等工具生命周期说明。
- `ocean-question-and-scale-framing` 移除 coordinator 角色，仍供物理 Expert 与 discussion partner 使用。方法内容没有搬到 Coordinator 的另一份 Skill。
- 保留数据权限、原始用户产出要求和图件发布协议；各自负责防止越权、遗漏交付和引用不存在的发布结果。明确 pending 作者报告不等于审核链结束，避免提示词诱导立即打断同一个 Expert。

## 验证与边界

检查生产角色目录的构建结果：Coordinator 的原生 Skills 目录不再包含 framing，物理/讨论角色仍包含。既有任务的 Skill 快照不会被偷偷改写；本次已停止旧测试，新任务使用新目录。

运行 Coordinator 提示词边界、方法 Skill、原生 Skill 加载与交付协议回归。同步修复两处测试替身缺少上一轮新增 `changed_output_files` 的问题，没有为测试修改生产交付逻辑。

结果：76 项通过（11.04 秒），另有 1 条既有 xarray/NumPy 弃用警告；Skill 校验通过，`git diff --check` 通过。

这些检查验证职责文本和工具上下文，不证明 DeepSeek 实际会稳定选择好子问题。这次没有新增真实 API 测试，也没有宣称 research tree 质量已经改善。

上轮发现的错误签名误合并及旧审核取消传播问题不在本次提示词替换中修复；等待终态的职责说明不能代替后台生命周期修复。

## 首次委派实测后的进一步删减

首次委派探针表明有问题拆分但仍指定方法（见 `coordinator-first-dispatch-20260914.md`）。按用户最新要求，现已将职责主体缩为研究委派、结果后决策、非研究请求三段，删除长示例和“preferred methods are suggestions”的许可。研究委派及续问都禁止自行指定或建议指标、算法、诊断步骤、图件清单，用户明确要求除外；非研究请求直接回答或委派操作，不建研究流程。此后未再调用真实 API。
