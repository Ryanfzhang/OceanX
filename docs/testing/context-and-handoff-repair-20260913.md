# 上下文与研究交接修复（2026-09-13）

## 修改范围

本轮没有修改模型身份、研究树、角色名单、执行预算或审核路由。没有新增模型交接字段，也没有编号项/字符数不合格就退回的委派门禁。

1. `native_text.py` / `native_backend.py`：在既有 DeepAgents read_file / grep 接口后处理纯文本。内容搜索跳过常见二进制扩展名及二进制头；跨 Expert 共享文件权限保持不变。文本页以实际字符体量分页，长行另存为可逐页读取、无损 JSON 字符串分片视图，原文件不变。原生图像/PDF读取保持原实现。
2. `deep_runtime.py`：使用 FilesystemMiddleware 的现有落盘机制，将大工具结果保留在文件里，模型可见窗口由原 20,000 降为 4,000 近似 tokens。这是单次上下文返回窗口，不是执行次数或研究预算。
3. `context_summary.py`：摘要仍用原模型和凭据；DeepSeek 摘要单独关闭 thinking，正文空间 8,192 tokens，主模型不变。截断/空白/工具调用不算完整摘要；一次更大正文空间的修复若仍失败，保留上一份有效历史，不提交新的截断点。原始历史归档机制保持不变。
4. `runtime.py` / `team/profiles.py`：替换委派与返回职责段。用户明确要求的计算仍须传递；Coordinator 预想的方法不再定义为交付项。Expert 可以带着足以改变方向的发现或明确阻塞返回，普通方法选择和局部调试仍由 Expert 自主完成。未解决的版本差异不能凭主观可信度选一个当结论。

额外尝试过同步原生 `start_async_task.description` 的参数说明，真实委派探针未验证出改善，因此已撤回该额外适配。最终仍为上述四处修改，不保留新的委派 schema 子类或中间件。

## 已完成验证

### 搜索与分页

本地回归覆盖：嵌套 glob、正常共享文件、伪装二进制、缺失路径错误、长匹配行、结果截断标记、普通分页无遗漏、长行无损续读、沙箱读取权限、原生工具和持久 Python 的文件互通。

对上一轮 `box_transport` 搜索目录运行新文本搜索：**0.221 秒**，返回 26 条匹配、11,794 字符，并明确 `truncated=true`。原运行完整扫描耗时 395.365 秒。二者搜索返回量不同，不能把比值当成等量计算加速；新结果验证的是“不再为首屏匹配扫描所有二进制并返回巨大文本”。

### 一次真实摘要

[计量](/Users/ryanzhang/Code/OceanX-v2/output/context-summary-repair-20260913/measurement.json) · [实际摘要](/Users/ryanzhang/Code/OceanX-v2/output/context-summary-repair-20260913/summary.md)

- 同一已配置 Expert 模型：`deepseek-v4-flash`，没有切换 Pro。
- 人工历史，不含真实数据分析；历史正文 36,350 字符。
- 3.85 秒；输入 10,047、输出 644 tokens；一次调用正常 `stop`，没有修复重试，没有报告 reasoning tokens。
- 摘要保留了样本时间、幅度/相位与原始极值的区别、文件路径、未核实 bootstrap 和缺少热通量的限制。
- 这是小规模摘要路径验证，不是整轮研究的提速或科学质量证明。

### 真实 Campeche 首轮：未通过委派行为验收

[运行终态](/Users/ryanzhang/Code/OceanX-v2/output/campeche-context-repair-20260913/query/attempt-1789292495963094000-ec9e21e8/result.json)

同问题、同数据开启独立测试。Coordinator 先执行 ls、read_file、execute 查看数据，正确识别单年覆盖和缺少通量变量，并派一个物理 Expert。

但是委派仍有五条具体要求：定义研究对象、描述三维结构、逐类机制诊断、区分证据、图及报告；其中还含 EKE、平流项及水平散度等方法指示。因此首轮委派行为不能算通过。测试在 **126.806 秒**由测试人员取消，未新增产品级预算限制。

取消时记录输入 98,875、输出 5,750，总计 **104,625 tokens**；3 次代码执行成功，1 次连接错误后续有继续调用，另有中断调用未闭合计量。没有专家最终报告或审核，本轮不能用于评价 Tree。原始事件和文件保留。

之后仅进行委派探针：模型正常收到问题、数据与工具，在 `start_async_task` 真正执行之前截取请求并停止，**不启动 Expert**。

[实际委派](/Users/ryanzhang/Code/OceanX-v2/output/campeche-dispatch-docs-20260913/dispatch.json) · [探针原始输入目录](/Users/ryanzhang/Code/OceanX-v2/output/campeche-dispatch-docs-20260913)

探针用时 **53.61 秒**，4 次模型调用，输入 38,807、输出 3,702，总计 **42,509 tokens**。仍包含四条 framing constraints，以及要求 MLD、热含量趋势、平流通量散度等诊断的返回清单。不能算职责行为通过。额外工具说明适配未证明有效，已撤回，不继续叠加第三套提示干预。

相关回归原计划版本为 **145 passed**；额外工具说明试验版本为 **146 passed**（多一条参数说明测试），随后撤回额外代码及该测试。测试通过证明接口回归，不证明模型委派行为正确。

当前结论：工具和摘要修复有直接验证；Coordinator 的研究型委派仍未达到目标，Expert 正常返回与 Coordinator 后续决策没有在此次短测试里得到验证。所有真实测试已结束，没有留下付费研究后台进程。

## 实现依据

核对了本地安装的 DeepAgents 与 LangChain 实现，以及 [DeepAgents FilesystemMiddleware 参数](https://reference.langchain.com/python/deepagents/middleware/filesystem/FilesystemMiddleware)、[摘要实现](https://reference.langchain.com/python/deepagents/middleware/summarization) 和 [DeepSeek thinking 参数](https://api-docs.deepseek.com/guides/thinking_mode/)。保留框架原生调用与历史归档，仅修适配和提示说明。
