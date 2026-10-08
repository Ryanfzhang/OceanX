"""Six new artifact assessments; preserve all 45 unchanged October 6 grades.

Provisional, identity-known audit. This is not a frozen-reference evaluation.
The prior review source stays unchanged, and selection is by attempt time.
"""
import copy
import importlib.util
from pathlib import Path

OLD = Path('/Users/ryanzhang/.codex/visualizations/2026/08/22/01a02889-8101-7d21-9d67-f7b62e1a6809/benchmark-review')
spec = importlib.util.spec_from_file_location('historical_review', OLD / 'reviewed_cases.py')
historical = importlib.util.module_from_spec(spec)
spec.loader.exec_module(historical)
p, r = historical.p, historical.r
CASES = copy.deepcopy(historical.CASES)

CASES['Q25']['methods']['OceanX'] = r([4,3,3,3,3,3,3],
 p('Integrated TCHP26 over a stated Gulf mask; separated standing heat in SSH-defined structures from transport attribution; tested stratification, threshold/domain choices, pre-season memory and the thickness/temperature variance split.',
   '在明确墨西哥湾掩码下积分TCHP26；区分SSH结构内的现存热量与输送归因；检验层结、阈值/区域、季前记忆及厚度/温度方差分解。'),
 p('The final answer correctly uses 40.2 kJ/cm² over 1.70 million km² = 0.68 ZJ, explicitly correcting the earlier ×1000 slip. It carries forward the independently checked D26 split and retreats from a uniquely advective explanation. Enclosed heat (33%, criterion range 10–44%) is not called measured delivered heat.',
   '最终答案正确使用40.2 kJ/cm²×170万km²=0.68 ZJ，明确修正先前1000倍单位错误；吸收独立复核的D26分解，并撤回唯一平流解释。结构内热量33%（阈值范围10–44%）没有被称为测得的输送热量。'),
 p('The new final integral is corrected, but the old B1.1 report still contains the erroneous value. The 65% storm-accessible interpretation is not established without storm mixing; the stratification reduction under-integrates bottom-limited columns and retains a roughly 6% bias. Seven seasons, screened correlations and unvalidated salinity-source proxies limit causal and water-origin claims. Some saved B1.11 panels are superseded by the corrected depth-axis diagnosis.',
   '新最终积分已改正，但B1.1原报告仍保留错误值。没有风暴混合诊断，不能证明65%的热量实际可被风暴利用；层结汇总漏算底部受限水柱，约6%偏差仍在。七个季节、多次筛选相关及未经独立验证的盐度来源代理限制因果/水源结论；部分B1.11图被修正后的深度轴诊断取代。'),
 [p('Explicit reservoir, structure, transport and competing-driver definitions.', '明确热库、结构、输送及竞争驱动定义。'),
  p('Masks, units and thresholds examined; reanalysis and bottom-limited bias remain.', '检查掩码、单位及阈值；仍有再分析与底部受限偏差。'),
  p('Final 0.68 ZJ passes the dimensional check; seasonal and structural quantities are traceable, but the accessibility partition remains approximate.', '最终0.68 ZJ通过量纲核对；季节及结构量可追溯，可利用性分区仍为近似。'),
  p('Targeted seasonal, heave and conditional tests; missing flux/velocity prevents causal identification.', '有季节、起伏及条件检验；缺少通量/速度，不能识别因果。'),
  p('Threshold/domain ensemble, leave-one-year-out and bootstrap are retained; n=7 and residual reduction errors limit precision.', '保留阈值/区域组合、逐年剔除与bootstrap；n=7及残余汇总错误限制精度。'),
  p('Connects season, stratification, LC geometry and basin memory, with snippet-level literature limits.', '联系季节、层结、环流几何与海盆记忆，文献仍受搜索摘录范围限制。'),
  p('Presence versus delivery and arithmetic versus causation are separated; storm accessibility and source percentages are more weakly supported.', '区分现存/输送及算术/因果；风暴可利用性和来源百分比证据较弱。')])

CASES['Q27']['methods']['OceanX'] = r([4,3,3,3,3,3,3],
 p('Executed cell-wise East China Sea MHW detection, warming-removal counterfactuals and a mean/variance/shape decomposition; swept fixed and rolling baselines, percentiles, event rules, averaging order, coastal masks and intensity estimators.',
   '执行东海逐网格热浪检测、移除增暖反事实及均值/方差/形状分解；扫描固定/滑动基线、百分位、事件规则、平均次序、沿岸掩码及强度估计。'),
 p('Delivers the formerly missing completed answer: +7.78 MHW days/decade under a fixed 1982–2011 baseline, versus near-zero de-warmed residual; mean-shift share 103% with 85–125% interval. Paired same-period baseline comparisons and fixed-count hot-tail tests address real methodological alternatives. The AVHRR-only correction is incorporated.',
   '交付此前缺失的完整答案：固定1982–2011基线下+7.78热浪日/十年，移除增暖后残差接近零；均值移动份额103%，区间85–125%。同时间段配对基线比较及固定数量热尾检验回应真正的方法替代；吸收AVHRR-only修正。'),
 p('One OISST realization, no frozen oracle or independent SST validation. The summary’s “variability contribution is negligible” is stronger than the broad interval that still permits a substantial negative contribution. Several significance claims lack a common spatial/multiplicity adjustment; rolling windows have unequal usable periods. Intensity panel (c) is explicitly invalid, and published-disagreement claims rely on snippets rather than full methods.',
   '仅一个OISST产品，没有冻结真值或独立SST验证。“变率贡献可忽略”的摘要措辞强于仍允许较大负贡献的宽区间。部分显著性缺少统一空间/多重检验处理；滑动窗口可用期不同。强度图(c)明确无效，论文分歧判断依赖摘录而非完整方法。'),
 [p('Precise frequency/intensity and fixed-versus-current-climate questions guide discriminating experiments.', '明确频率/强度及固定/当前气候问题，指导判别实验。'),
  p('Temporal/mask checks and product correction are explicit, but no independent observational calibration.', '时间/掩码检查及产品修正明确，但无独立观测校准。'),
  p('Quantified, traceable trends and decomposition, with definitions kept separate; no independent reference match.', '趋势及分解定量可追溯，区分不同定义；未与独立参考匹配。'),
  p('Several falsifiable arithmetic counterfactuals isolate methodological effects, not physical forcing attribution.', '多项可证伪算术反事实分离方法效应，不等于物理强迫归因。'),
  p('Block bootstrap, baseline sweeps and matched-period checks; invalid panel and heterogeneous significance remain.', '有块bootstrap、基线扫描及匹配时期检查；仍有无效面板和不统一显著性。'),
  p('Connects spatial, seasonal and estimator differences to literature with stated snippet limitations.', '联系空间、季节及估计差异与文献，注明摘录限制。'),
  p('Useful distinction between warming relative to a fixed past and extremes relative to a changing climate; some near-zero claims are too categorical.', '有效区分相对固定过去的增暖与相对变化气候的极端；部分接近零的判断过于绝对。')])

CASES['Q15']['methods']['Claude'] = r([3,3,2,1,2,3,2],
 p('Completed an executed notebook, eight figures, coastal/offshore annual SST and D20 series, connectivity/EOF diagnostics, and an ageostrophic-current-derived Ekman/upwelling proxy for Somalia and Oman.',
   '完成执行notebook、八张图、索马里/阿曼沿岸与外海年度SST和D20序列、联系/EOF诊断及由非地转海流构造的Ekman/上升流代理。'),
 p('The rerun now has a final answer and 13 executed code cells with zero saved notebook errors. It distinguishes monthly covariance from annual upwelling-intensity covariance, reports non-closing budgets, and quantifies the coastal noise-floor effect on the 6.1 versus 4.3 contrast.',
   '重跑有最终答案，保存13个执行代码单元且无notebook错误；区分月协变与年度上升流强度协变，说明收支不闭合，并量化沿岸噪声底对6.1与4.3倍差异的影响。'),
 p('The headline “actual upwelling velocity” and local-wind/Findlater-jet control are not measured: M=(u−ug)×MLD and w=(Moff−Mcoast)/distance, so the strongest M–w correlations are partly built in. Literature magnitude agreement cannot independently validate inferred winds. The nominal 0–100 m budget averages levels without thickness weights. Monthly p-values assume independent samples, and the claim that Oman’s thermocline is shallower contradicts its reported D20 (97.6 versus 84.9 m).',
   '标题中的“实际上升流速度”及局地风/Findlater急流控制并未测得：M=(u−ug)×MLD，w=(M外海−M沿岸)/距离，最强M–w相关部分由构造决定。文献量级相符不能独立验证倒推的风；名义0–100米收支未按层厚加权。月p值假设样本独立；“阿曼温跃层更浅”与D20=97.6米、索马里84.9米矛盾。'),
 [p('Explicit paired-coast operational diagnostics, but forcing tests are not independent.', '成对海岸操作性诊断明确，但强迫检验不独立。'),
  p('Geometry and domain handling improved; coastal residual and reanalysis fitness remain uncertain.', '几何与区域处理改善；沿岸残差及再分析适用性仍不确定。'),
  p('Annual ocean-state indices are traceable; the headline vertical-velocity magnitude is a model-dependent proxy.', '年度海洋状态指标可追溯；标题垂向速度量级为依赖模型假设的代理。'),
  p('Circular proxy correlations do not identify independent wind controls.', '循环代理相关不能识别独立风控制。'),
  p('Noise-floor sensitivity is useful; short/autocorrelated inference and geometry uncertainty are incompletely treated.', '噪声底敏感性有用；短记录/自相关推断及几何不确定性处理不完整。'),
  p('Multiple ocean variables, EOF/lag scales and named literature are integrated.', '综合多海洋变量、EOF/滞后尺度及具名文献。'),
  p('Clear conditional caveats, but causal headlines and actual-velocity wording overreach them.', '条件限制清楚，但因果标题及实际速度措辞超出限制。')])

CASES['Q08']['methods']['Finch'] = r([1,2,2,1,2,2,1,1],
 p('Executed a 2016 SSH-center search, thermohaline core/far-field profiles, source-region salinity snapshots and a corrected surface-geostrophic ring calculation; saved four figures and a finding table.',
   '执行2016年SSH中心搜索、温盐核心/远场剖面、源区盐度快照及修正后的表面地转涡环计算，保存四张图和判定表。'),
 p('A real completed delivery replaces the old failed attempt: temperature anomaly 8.2°C at 222 m, fresh/saline anomalies −0.154/+1.05, and corrected surface-ring peak about 0.70 m/s are traceable to notebook outputs. It does not claim that surface SSH alone proves subsurface intensification.',
   '真实完整交付替代旧失败：222米温度异常8.2°C、淡/咸异常−0.154/+1.05，以及修正表面涡环峰值约0.70 m/s均可追溯到notebook输出；没有把表面SSH当作次表层增强的证明。'),
 p('Cells 12/14 overwrite Tcomp/Scomp inside the time loop rather than accumulate: the advertised Aug–Oct composite is the final sampled day. Homogeneity is judged from a temperature-gradient threshold, not the paper’s density stratification; seven-month evolution and thermal-wind reconstruction are omitted despite supplied T/S history. Cell 17’s saved speed map retains the old degree/radian spacing error after later numeric corrections, and resolution is asserted as the main discrepancy cause without a discriminating test.',
   '单元12/14在时间循环中覆盖Tcomp/Scomp而非累加，宣称的8–10月合成实际为最后采样日。以温度梯度阈值替代论文密度层结；已有温盐历史仍未做七个月演变和热成风重建。单元17速度图保留度/弧度间距错误，后续数值修正没有更新该图；未做判别检验就把分辨率称为主要差异原因。'),
 [p('Temperature-only criterion and last-day profile do not adequately test density homogeneity.', '仅温度判据及最后一天剖面不足以检验密度均匀性。'),
  p('Measured anomaly is traceable, but its composite/background differs from the paper.', '测得异常可追溯，但合成/背景与论文不同。'),
  p('Both cores are quantified; overwritten time aggregation undermines the claimed composite.', '双核心定量，但时间汇总覆盖削弱合成声明。'),
  p('Source snapshots do not test seven-month conservation or pre-detachment winter formation.', '源区快照不检验七个月守恒或脱离前冬季形成。'),
  p('Corrected surface ring is executed; the requested subsurface thermal-wind structure is not tested.', '修正表面涡环已执行；未检验要求的次表层热成风结构。'),
  p('Tracking/reference adaptations are explicit, but aggregation and density diagnostics are incomplete.', '追踪/参考替代明确，但汇总及密度诊断不完整。'),
  p('Resolution/bias explanations remain conjectural and over-weighted.', '分辨率/偏差解释仍是推测且权重过高。'),
  p('Notebook is inspectable, but no real temporal ensemble and an uncorrected speed figure impair consistency.', 'notebook可检查，但缺真实时间组合且未修正速度图影响一致性。')])

CASES['Q20']['methods']['Finch'] = r([3,1,2,1,1,2,2],
 p('Computed ten years of monthly SSH-box maxima, onset/peak positions, longitude-time sections, SST/MLD context, lag correlations and a surface-vorticity diagnostic.',
   '计算十年月SSH区域最大值、起始/峰值位置、经度时间剖面、SST/混合层、滞后相关及表面涡度。'),
 p('Saved executed outputs quantify 22.6–36.0 cm annual peaks, July–October peak months, and pre-monsoon coastal anomalies. Monthly timing and absent winds are acknowledged; eight output figures are retained.',
   '执行输出量化年度峰值22.6–36.0厘米、7–10月峰值月份及季风前沿岸异常；承认月时间精度及缺风，保留八张输出图。'),
 p('Cell 16 divides derivatives per degree by one grid-cell spacing, inflating vorticity by roughly 12×. April onset is enforced by searching only months ≥4; box maxima need not track the same eddy. The stated phase maxima do not establish westward propagation, and the lag maximum is at zero rather than a unique east-leading lag. Without winds the conclusion that local winds are required is too strong. The deseasonalized calendar composite is identically near zero, and the cited ninth summary figure was never saved after a cell error.',
   '单元16把每度导数除以单网格距离，涡度约放大12倍。只搜索≥4月使四月起始部分由规则决定；区域最大值未必追踪同一涡。所列相位峰值未证明西传，滞后最大在零而非唯一东侧领先。没有风，不能断言局地风是必要条件。去季节后的日历合成近乎恒为零；第九张摘要图因单元错误没有保存。'),
 [p('Initiation and intensification are separated, though detector selection biases onset.', '区分启动与增强，但检测选择偏置起始。'),
  p('The vorticity unit error changes a headline diagnostic; masks and eddy identity are weakly checked.', '涡度单位错误改变标题诊断；掩码及涡身份核查较弱。'),
  p('Traceable SSH amplitudes and dates are proxy-based rather than coherent event tracking.', 'SSH幅度及日期可追溯，但基于代理而非相干事件追踪。'),
  p('Seasonal coincidence and non-unique lags do not discriminate wind and Rossby-wave mechanisms.', '季节巧合及非唯一滞后未判别风与Rossby波机制。'),
  p('No threshold/box ensemble or autocorrelation-aware lag uncertainty; only generic limits.', '没有阈值/区域组合或考虑自相关的滞后不确定性；主要是一般限制。'),
  p('Connects SSH, currents, SST and mixed-layer context, without reliable forcing attribution or literature verification.', '联系SSH、海流、SST及混合层，但无可靠强迫归因或文献验证。'),
  p('Two-stage interpretation is plausible, not demonstrated; claimed phase direction and onset need stronger tests.', '两阶段解释合理但未证明；相位方向及起始需要更强检验。')])

CASES['Q23']['methods']['Finch'] = r([3,2,2,2,2,2,2],
 p('Detected SSH northern-extent/retraction cycles, merged peaks within 120 days, inspected western high-SSH components, tested 16 trigger/retraction thresholds and tried a 92-m thermal cross-check.',
   '检测SSH北伸/回缩循环，合并120天内峰值，检查西侧高SSH连通域，扫描16种触发/回缩阈值并尝试92米温度交叉检验。'),
 p('Eight peak-dated cycles and seven intervals (mean 318 days) are reproduced in saved tables and code. A 4–28 event sensitivity range demonstrates substantial definition dependence, and the absence of literature access is stated.',
   '八个按峰值定时的循环及七个间隔（均值318天）对应保存表格与代码；4–28事件敏感性范围揭示定义依赖，明确说明无文献访问。'),
 p('The detector is the northernmost SSH>0.20 m cell, not a Yucatán-connected contour track; its peak dates precede retraction by up to about 100 days and are not verified detachment dates. The headline merges within 120 days while the sensitivity sweep does not, conflating thresholds with counting rules. Ring episodes do not establish one-to-one separation; the thermal proxy saturates and fails to corroborate events. Short-record interval uncertainty and actual published estimates are missing.',
   '检测的是SSH>0.20米最北网格，不是与尤卡坦连接的等值线追踪；峰值可比回缩提前约100天，未验证为脱离日期。标题合并120天内事件，敏感性扫描却不合并，混合阈值和计数规则。涡环片段未建立一一对应脱离；温度代理饱和，无法证实事件。缺短记录间隔不确定性及真正的已发表估计对比。'),
 [p('Operational competing definitions are explicit, but peak-cycle proxies replace physical separation.', '竞争操作性定义明确，但峰值循环代理替代物理脱离。'),
  p('Full daily record is read correctly; absolute SSH and coastal contamination remain uncontrolled.', '完整日记录读取正确；绝对SSH及沿岸污染控制不足。'),
  p('Counts/intervals are traceable for the stated cycles, not validated final separations.', '所述循环的计数/间隔可追溯，非验证后的最终脱离。'),
  p('Threshold sensitivity is a targeted definition test; subsurface and record-length explanations are not demonstrated.', '阈值敏感性是针对性定义检验；次表层及记录长度解释未证明。'),
  p('Several thresholds tested, but inconsistent merge rules and no interval uncertainty limit robustness.', '检验多个阈值，但合并规则不一致且无间隔不确定性限制稳健性。'),
  p('SSH and an attempted thermal check are used; no quantitative eddy heat/size or sourced literature comparison.', '使用SSH及尝试温度核查；无定量涡热量/大小或具来源文献对比。'),
  p('Identifies definition dependence, but overstates cycle dates as separations and comparison as published evidence.', '识别定义依赖，但夸大循环日期为脱离及将比较说成已发表证据。')])
