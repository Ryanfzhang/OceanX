"""Review five reruns; retain the previous 46 provisional assessments."""
import copy
import importlib.util
from pathlib import Path

PREVIOUS = Path(__file__).resolve().parent.parent / '2026-10-08-three-methods'
spec = importlib.util.spec_from_file_location('previous_review', PREVIOUS / 'reviewed_cases.py')
previous = importlib.util.module_from_spec(spec)
spec.loader.exec_module(previous)
p, r = previous.p, previous.r
CASES = copy.deepcopy(previous.CASES)

CASES['Q25']['methods']['Claude'] = r([3,3,3,2,2,3,2],
 p('Calculated daily 2011–2017 JJASON TCHP, D26, stratification and mixed-layer indices over a deep-Gulf mask, detected SSH-defined Loop Current/eddy structures, and compared seasonal/interannual inventories and component variability.',
   '在深水墨西哥湾掩码下计算2011–2017年JJASON逐日TCHP、D26、层结与混合层指标，识别SSH定义的环流/涡结构，比较季节/年际库存与分量变率。'),
 p('Executed notebook: 9 code cells, no saved errors, with code, tables and figures. The reported 50.2 kJ/cm² over 984,840 km² correctly converts to 494 EJ (0.494 ZJ). A profile-integration check, SSH-reference and eddy-size sensitivity support the descriptive inventory. Standing heat is explicitly distinguished from storm-track exposure.',
   '执行notebook含9个代码单元，无保存错误，并有代码、表与图。50.2 kJ/cm²乘984,840 km²正确换算为494 EJ（0.494 ZJ）。剖面积分核对、SSH参考与涡面积敏感性支持描述性库存；明确区分现存热量与风暴路径暴露。'),
 p('The 71/20/8% variability shares normalize separate component variances by their sum, omitting covariance and interaction residuals: they are not a partition of total observed variance. Hot-area share uses all detected structures, whereas LC/large-eddy area and heat shares use categories 1/2 only. Seven annual samples and uncorrected daily correlations cannot identify exclusive background control. The shelf-area label includes land. Missing storm/flux/forcing observations prevent independent driver attribution.',
   '71/20/8%变率占比以各分量方差之和归一化，遗漏协方差与交互残差，并非总观测方差分解。高热区域占比用全部结构，而LC/大涡面积与热量占比仅用类别1/2。七个年度样本及未处理自相关的逐日相关不能识别背景唯一控制；陆架面积标签含陆地。缺风暴、通量或强迫观测的独立归因。'),
 [p('Explicit inventory, structure and variability questions; conclusions are conditional on deep-water coverage.', '库存、结构与变率问题明确，结论限于深水覆盖。'),
  p('Depth, units and wet deep-water masks are coherent; reference-depth and shelf-label inconsistencies remain.', '深度、单位与湿深水掩码合理，仍有参考深度与陆架标签不一致。'),
  p('Heat conversion and structural inventories are traceable; hot-area masks and variance shares limit quantitative interpretation.', '热量换算与结构库存可追溯，但高热掩码与方差占比限制定量解释。'),
  p('Descriptive decomposition is useful; missing covariance and structurally related predictors do not identify causation.', '描述性分解有用，但遗漏协方差及结构相关预测量不能识别因果。'),
  p('Profile/reference/size checks exist, but no autocorrelation-aware uncertainty and weak n=7 inference.', '有剖面/参考/面积检查，但缺自相关不确定性，n=7推断较弱。'),
  p('Connects depth, T/S, SSH structures and seasonal/annual scales with stated literature limits.', '联系深度、温盐、SSH结构及季节/年度尺度，注明文献限制。'),
  p('Standing heat versus storm exposure is distinguished; the 71% control headline exceeds the tested arithmetic.', '区分现存热量与风暴暴露，但71%控制标题超出算术检验。')])

CASES['Q09']['methods']['Finch'] = r([2,2,1,1,2,2,2,2],
 p('Tracked monthly western-Gulf SSH peaks, sampled core/background T/S and density surfaces, and compared salinity, mixed-layer depth, vertical contrasts and relaxation/curvature diagnostics; saved six figures and a verdict table.',
   '追踪西部墨西哥湾月SSH峰值，采样核心/背景温盐与等密度面，比较盐度、混合层、垂向差异及松弛/曲率诊断；保存六图与判定表。'),
 p('All 33 code cells executed without saved errors. Salinity decreases and winter mixed-layer deepening are traceable. The report separates above/below density 26 and acknowledges missing winds, diffusivity and a full advective budget.',
   '33个代码单元全部执行且无保存错误。盐度下降与冬季混合层加深可追溯；区分密度26上下，承认缺风、扩散率及完整平流收支。'),
 p('The seeded western-Gulf peak is not independently identified as Poseidon, and August detachment is not checked against Loop Current connectivity. Density bands shift between 24.5–26.2 and 25–26.2; a later maximum includes a surface value. Weak curvature correlation is not a vertical-diffusion budget. A salinity contrast between moving isopycnals is not dS/dz. Wind timing, diffusion dominance and advective control are therefore not reproduced by these proxies.',
   '西部峰值未独立识别为Poseidon，八月脱离未核对环流连通性。密度区间在24.5–26.2与25–26.2间变化，后期最大值含表层值。弱曲率相关不是垂向扩散收支，移动等密度面盐度差不是dS/dz。因此代理未复现风时序、扩散主导或平流控制。'),
 [p('Salinity evolution is partly quantified; eddy identity and density-band consistency are unverified.', '部分量化盐度演变，涡身份与密度区间一致性未验证。'),
  p('Winter deepening coincides with changes, but wind-event evidence is absent.', '冬季加深与变化同时出现，但缺风事件证据。'),
  p('Curvature correlation without diffusivity or flux closure cannot establish vertical-diffusion dominance.', '缺扩散率或通量闭合的曲率相关不能证明垂向扩散主导。'),
  p('Isopycnal salinity contrast does not test disappearance of dS/dz; separation changes are uncontrolled.', '等密度面盐度差不检验dS/dz消失，面间距变化未控制。'),
  p('Below-26 evolution is sampled, but correlation does not discriminate advective control.', '采样密度26以下演变，但相关未判别平流控制。'),
  p('Executed T/S/density diagnostics are useful; event tracking and budget tests remain incomplete.', '执行温盐/密度诊断有用，但事件追踪与收支不完整。'),
  p('Missing forcing and resolution are disclosed; mechanism verdicts still overstate the proxies.', '披露缺强迫与分辨率限制，机制判定仍夸大代理。'),
  p('Inspectable notebook/output, without independent identity/reference matching or temporal/threshold uncertainty.', 'notebook/输出可检查，但缺独立身份/参考匹配或时间/阈值不确定性。')])

CASES['Q15']['methods']['Finch'] = r([3,2,3,1,2,2,2],
 p('Compared ten JJAS seasons of Somalia/Oman coastal/offshore SST, SSH, mixed-layer depth and surface currents using boxes; saved five figures and an annual index table.',
   '用矩形比较索马里/阿曼十个JJAS季节的沿岸/外海SST、SSH、混合层与表层流，保存五图及年度指标表。'),
 p('All 22 code cells executed without saved errors. Shared coastal-SST covariance (r=0.617) is distinguished from coastal-minus-offshore covariance (r=−0.027), with explicit n=10 and missing-wind limits. Annual examples and ocean-state indices are traceable.',
   '22个代码单元全部执行且无保存错误。区分共同沿岸SST协变（r=0.617）与沿岸减外海协变（r=−0.027），注明n=10与缺风限制；年度案例与海洋状态指标可追溯。'),
 p('Broad unweighted boxes are not coast-aligned; Oman’s offshore reference spans a different latitude range. Mean zonal velocity is neither projected alongshore nor integrated cross-equatorial transport. Oman’s r(SST, MLD)=−0.86 implies deeper mixed layers accompany colder SST, contrary to the shallower-layer cooling interpretation. Ocean-state correlations do not identify Findlater-jet/local-wind control. No mask ensemble, leave-one-year-out or autocorrelation-aware confidence intervals are supplied.',
   '宽矩形未沿海岸布置且未加权，阿曼外海参考纬度不同。平均纬向速度既非投影沿岸输送，也非积分跨赤道输送。阿曼r(SST, MLD)=−0.86表示更深混合层伴随更冷SST，与“更浅层冷却更强”相反。海洋状态相关不能识别Findlater急流/局地风控制。缺掩码组合、逐年剔除及自相关置信区间。'),
 [p('Explicit paired-coast covariance and mechanism questions.', '成对海岸协变与机制问题明确。'),
  p('Coverage is appropriate, but unequal boxes and unprojected current proxies limit fitness.', '覆盖适当，但区域不匹配及未投影海流代理限制适用性。'),
  p('Annual SST contrasts and correlations are traceable, conditional on boxes and a short record.', '年度SST差异与相关可追溯，但受区域及短记录约束。'),
  p('Correlations do not discriminate independent winds; the Oman MLD interpretation has the wrong sign.', '相关未判别独立风，阿曼混合层解释符号错误。'),
  p('Seasonal comparisons and sample-size caveats exist; robust inference is missing.', '有季节比较与样本量限制，但缺稳健推断。'),
  p('Multiple ocean-state fields, without direct forcing, transport or verified literature tests.', '多海洋状态场，但缺直接强迫、输送或核实文献检验。'),
  p('Proxy caveats are explicit, but transport and wind-control headlines overreach.', '代理限制明确，但输送与风控制标题超出证据。')])

CASES['Q24']['methods']['Finch'] = r([3,1,1,1,2,2,2],
 p('Detected daily low-salinity footprints over shallow/deep masks, constructed a uniform-5 m freshwater inventory proxy, compared seasonal SSH/current variability and swept four salinity thresholds; saved three figures and two tables.',
   '检测浅/深水掩码下逐日低盐覆盖，构造均匀5米淡水库存代理，比较季节SSH/海流变率并扫描四盐度阈值；保存三图两表。'),
 p('All 17 code cells executed without saved errors. Daily footprints, an August seasonal maximum and threshold dependence are genuinely computed outputs replacing the earlier empty delivery.',
   '17个代码单元全部执行且无保存错误。逐日覆盖、八月季节峰值与阈值依赖是真实计算输出，替代此前空交付。'),
 p('Cell area omits longitude spacing: (111 cos(lat)) × (111 Δlat), with Δlon≈1/12°, inflates area and volume by about 12×. Mean 365,713 km² and 128 km³ are invalid magnitudes. Standing deep/(deep+shelf) footprint ratio is not cross-shelf export flux or a fraction of river discharge. The box lacks a Gulf-only polygon, thickness is assumed, and squared SSH departure is not EKE. Threshold comparisons switch between mean ratios and ratios of means; daily Pearson significance ignores autocorrelation and seasonality.',
   '单格面积遗漏经度间距：(111 cos(lat))×(111 Δlat)，Δlon约1/12°，使面积/体积约放大12倍。平均365,713 km²与128 km³量级无效。现存深水/(深水+陆架)覆盖比不是跨陆架输出通量或径流比例。矩形缺墨西哥湾专用边界，厚度为假设，SSH偏差平方不是EKE。阈值比较混用比值均值与均值比，逐日Pearson显著性忽略自相关与季节。'),
 [p('Footprint/export questions operationalized, mainly as inventory proxies.', '将覆盖/输出问题操作化，但主要是库存代理。'),
  p('Missing longitude spacing invalidates area/volume; regional/source masks are weakly verified.', '遗漏经度间距使面积/体积无效，区域/来源掩码核查弱。'),
  p('Seasonal ratios remain descriptive; headline absolute area and volume are wrong.', '季节比值仍有描述价值，但标题绝对面积与体积错误。'),
  p('Inventory and covariance neither measure export nor identify eddy-driven river-water transport.', '库存与协变既不测输出，也不识别涡驱动河水输送。'),
  p('Threshold sensitivity exists, but estimands differ and serial/mask uncertainty is untreated.', '有阈值敏感性，但估计量不同，序列/掩码不确定性未处理。'),
  p('Salinity/SSH/currents/depth combined, without independent source or flux constraints.', '综合盐度/SSH/海流/深度，但缺独立来源或通量约束。'),
  p('Missing forcing/source is acknowledged, but export and causal labels exceed evidence.', '承认缺强迫/来源，但输出与因果标签超出证据。')])

CASES['Q27']['methods']['Finch'] = r([3,2,2,2,2,2,2],
 p('Analysed 1982–2023 regional-mean East China Sea JJAS OISST using full-period, early fixed and preceding-decade baselines; compared heatwave frequency/intensity, percentile/duration sensitivity and mean/variability summaries.',
   '用全时期、早期固定与前十年基线分析1982–2023年东海区域平均JJAS OISST，比较热浪频率/强度、百分位/时长敏感性及均值/变率摘要。'),
 p('All 17 code cells executed without saved errors; one four-panel figure and four tables are delivered. +0.262°C/decade warming and contrasting day trends under early (+16.47), full-period (+1.94) and rolling (+1.79, not significant) baselines are traceable to the simplified detector.',
   '17个代码单元全部执行且无保存错误，交付一张四面板图四表。增暖+0.262°C/十年及早期（+16.47）、全时期（+1.94）、滑动（+1.79，不显著）基线日数趋势可追溯至简化检测器。'),
 p('The circular threshold window wraps inside truncated JJAS, joining September to June rather than using a full annual calendar; leap days, event gaps and season boundaries are not handled by a standard detector. Spatial-mean events are not cell-wise exposure. Subtracting one constant per year leaves daily SD unchanged, so the raw/detrended SD panel is algebraically redundant. Absolute/relative hot-day comparisons change baseline and remove annual means; they do not quantify a unique warming contribution to five-day events. Mann–Kendall fallback lacks tie correction and serial-dependence intervals; zero Sen slopes for sparse strict-threshold counts do not prove no trends.',
   '阈值循环窗口仅在截断JJAS内循环，将九月与六月连接而非完整年度日历；闰日、间隔与季节边界未按标准检测器处理。空间平均事件非逐网格暴露。每年减一个常数不改变逐日SD，原始/去趋势SD面板算术冗余。绝对/相对热日同时改基线并移除年度均值，不能量化五日事件中唯一增暖贡献。Mann–Kendall替代实现缺并列修正与序列依赖区间；稀疏严格阈值的零Sen斜率不证明无趋势。'),
 [p('Baseline dependence and competing mean/variability explanations are explicit.', '基线依赖及竞争均值/变率解释明确。'),
  p('Long OISST coverage is appropriate; spatial averaging and truncated calendars restrict the target.', '长期OISST覆盖适当，但空间平均与截断日历限制目标。'),
  p('Simplified counts are traceable, not validated standard cell-wise MHW exposure.', '简化日数可追溯，但非经验证的标准逐网格热浪暴露。'),
  p('Baseline contrasts inform, but decomposition changes estimands and repeats an identical SD test.', '基线对比有用，但分解改变估计量并重复相同SD检验。'),
  p('Threshold/duration sweeps exist; ties, serial dependence and confidence intervals remain unresolved.', '有阈值/时长扫描，但并列、序列依赖与置信区间未解决。'),
  p('Temporal definitions compared, without spatial heterogeneity or verified published-method comparisons.', '比较时间定义，但缺空间异质性或核实论文方法比较。'),
  p('Simplifications disclosed; stationary-variability and solely-warming claims still overreach.', '披露简化，但变率稳定与仅增暖声明仍超出证据。')])
