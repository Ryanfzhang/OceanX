# Coordinator 按需查看数据：实现与一次真实首轮测试

## 实现

- 撤回 Coordinator graph build 中的自动元数据探测；数据添加时也不调用 Data Expert。
- 新增只读 `ocean_inspect_dataset(source="source_1")`。输入只能选择当前任务附加的数据，不能传任意本地路径。
- 复用现有科学环境、沙箱和 metadata probe，只查看 NetCDF/Zarr 的元数据及有限坐标向量。
  不计算温度等科学变量的统计量，不向 Coordinator 提供 Python 执行工具。
- 多文件摘要保留不同年份/坐标范围及采样间隔。目录检查只覆盖支持的顶层成员，并明确选择方式与遗漏数。
- 确认的元数据使用原有 source-version 缓存，Expert 可复用。检查不可用是事实，不终止研究。
- Coordinator 提示词删去 `usable result you need back`；说明按未知数据事实决定是否查看。
  单个 Expert 可以完整定义并研究现象，不强制拆成统计前置和物理后续。
- Expert 可以调整 Coordinator 的方法建议；用户或复现目标的明确要求不适用时，应报告冲突，不能偷偷替换。

## 验证

全量 Python 回归：548 passed、3 skipped，129.17 秒。现存 NumPy/netCDF4 与 Zarr 警告仍在。
专用测试检查：导入数据/注册工具不会扫描；显式检查才生成缓存；后续复用；任意路径被拒绝；
检查未完成不变成任务失败；科学变量 `.values` 读取被测试禁止；多年份与时间步长正确保留。

真实首轮测试使用当前 `deepseek-v4-pro` 和原 Campeche 问题、原数据目录。
启动于激活的 oceanx Conda 环境。没有更换模型，也没有把预先写好的摘要或预期委派塞给模型。
测试专用 hook 在第一批 start_async_task 执行前停止：Expert 启动数为 0。
只跑了一次，不是五次稳定性评估，也不是完整研究质量验证。

记录目录：`output/coordinator-dispatch-on-demand-20260913/`。
其中 `dispatch.json` 是原文，`model-input-*.json` 是真实输入和工具返回，`result.json` 是停止结果。

## 实际观察

1. Coordinator 主动读取两个 Skill，并调用 ocean_inspect_dataset。
2. 工具报告六个变量 temp、salt、u、v、chlorophyll、oxygen；网格间距 0.25°；
   2025-04-01 至 2025-12-31 和 2026-01-01 至 2026-03-31 两段每日记录。
3. 委派引用实际路径、上述时间/分辨率，并指出没有表面热通量、风应力和河流流量。
4. 首轮选择物理专家完整研究、文献专家提供相关证据，未再让统计与物理同时建立事件序列。
5. 物理委派仍列五项具体诊断产出。按需查看有效，但不能认定清单式委派已经解决。

从提交到保存停止状态 54.43 秒；两次模型调用 4.95 秒与 46.42 秒。
累计输入 14,754 tokens，输出 5,099（其中 reasoning 3,505）；cache_read 6,912 已计入输入。
本次没有连接失败；前一次基线包含一次失败及重试等待，因此不能把 107→54 秒归因于新工具。

## 边界

这一运行证明模型可以主动查看且在委派里使用数据事实。是否减少实际重复计算、是否改善科学结论、
是否能稳定减少方法清单，仍未验证。没有继续放行 Expert，也没有启动定期监控。
