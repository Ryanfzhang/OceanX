# OceanX 界面改进（v2，2026-10-25）

范围：单机版与网页版共用的界面（`frontend/ocean-desktop/src/renderer`，网页版经 `frontend/ocean-web` 换掉侧栏、欢迎页、设置和来源对话框）以及品牌资源。不改协议、后端、agent、提示词和调度。

## 1. 已定的设计

| 项目 | 决定 |
| --- | --- |
| 字体 | 用 Claude Code 的字体设置。它的英文字体 Anthropic Sans 是 Anthropic 专有字体，不能随 OceanX 分发，所以去掉这一项：英文用系统字体，中文用苹方，Windows 用微软雅黑。 |
| 字号 | 照 Claude Code：正文 16/24 px，界面 14 px，标题 15 px，说明 12–13 px，大标题 22 px；加粗 580。 |
| 颜色 | 照 Claude Code，不随图标调整：暖白背景（侧栏 `#f5f4ed`、正文 `#faf9f5`、卡片 `#fff`），文字三级（`#141413`/`#3d3d3a`/`#73726c`），细边框（`#1f1e1d` 的 10% 和 15%）。橙色 `#c6613f` 只用于发送按钮和运行中，蓝色 `#1b67b2` 用于链接，`#2c84db` 用于焦点框。深色模式用 Claude Code 的深色：`#1f1e1d`/`#262624`/`#30302e`，橙色 `#d97757`。 |
| 图标 | "分层的海"：纸色天空下三层蓝色的海，海面一道长涌浪，下面两条界面随深度变平；另有夜空版用于深色模式。源文件和生成脚本在 `docs/desktop/brand/`。 |
| 侧栏 | 单机版不放品牌：顶行只留窗口按钮，下面直接是"项目 +"。网页版没有窗口按钮，顶行放图标和 OceanX，下面是"任务 +"。 |
| 欢迎页 | 不显示地图。图标和"你想用 OceanX 做什么？"一行；保留三张卡片（检索与阅读论文、分析数据、开展 Autoresearch）；起名框里有"+"、项目名和发送按钮。 |
| 地图 | 打开任务后始终显示，作为圆角卡片放在窗口背景上，四周留 12 px；海用蓝灰、陆地用中性色。 |
| 添加来源 | 输入框和起名框的"+"都弹出两项：添加 PDF、添加数据文件夹。单机版分别打开只显示 PDF 的对话框和选文件夹的对话框（也可选单个数据文件）；网页版直接进入"上传 PDF"或"服务器路径"。在欢迎页选的来源，任务建好后逐个导入。 |
| 对话 | 单智能体不再套卡片：过程说明作为正文显示，下面一行"● 步骤 · 目的　详情 ›"，没有"OceanX:"前缀和步骤计数；团队仍是带关系图的卡片。 |

设计稿在 `docs/desktop/design/`（`make_mocks.py` 生成），图标页是 `docs/desktop/brand/icon-sheet.png`。

## 2. 已实施（未提交）

- `styles.css`：令牌换成上面的字体、字号和颜色；原来的青色强调色全部按用途换成橙色、蓝色或中性色；侧栏品牌样式删除；欢迎页、起名框、"+"菜单、单智能体活动行、地图卡片和深色模式的样式。
- 组件：`ProjectTaskSidebar.tsx` 去掉品牌；新增 `SourceMenu.tsx`；`OceanXWelcome.tsx` 加图标、"+"、项目名和待导入来源；`App.tsx` 接上菜单，并在新任务打开后逐个导入欢迎页选的来源；`ConversationTranscript.tsx` 的单智能体活动行。
- 选择来源：`shared/bridge.ts` 的 `chooseWorkspaceSource` 增加 `kind`（`pdf`/`data`），`preload.ts` 与 `main.ts` 按它打开对话框。
- 网页版：`TaskSidebar.tsx` 用图标；`source-picker.ts` 按 `kind` 打开对应模式，并跟随深色模式；`web.css` 改用同一套令牌；`index.html` 加网站图标（`public/favicon.svg`）。
- 地图：`basemap.ts` 的海、陆、海岸线颜色。
- 图标文件：`frontend/ocean-desktop/assets/oceanx-icon.{svg,png,icns,ico}` 和 `oceanx-icon.iconset/` 取代 `ocean-partner-icon.*`，`package.json` 已改引用；界面内用 `src/renderer/assets/brand/oceanx-icon{,-dark}.svg`。

## 3. 验证

- 单机版两组 `tsc` 和网页版 `tsc` 通过；单机版 vitest 210 项通过（新增欢迎页"+"和无品牌侧栏两项断言，更新单智能体活动行两项）；改动文件 eslint 通过；单机版和网页版 `vite build` 通过。
- 用假后端渲染真实界面截图（浅色/深色，中文/英文）：欢迎页和菜单、单智能体运行、团队运行、已完成任务；网页版欢迎页、深色团队、"添加 PDF"和"添加数据文件夹"对话框。

## 4. 未做

- 没有在真实后端上点一遍"+"：单机版的两个系统对话框、欢迎页来源在建任务后的导入。
- 没有打包验证新图标（dmg/exe 的应用图标）。
- 对话里每一步单独成行并带用时（设计稿的样子）需要逐步记录，目前只有当前一步和折叠的最近步骤。
