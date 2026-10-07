"""Presence counts only; never assigns or changes a 0–4 rubric level.

One-based probe indices follow the rubrics saved in the original evidence snapshot.
Each included item supplies a literal/regex locator into that snapshot. A count
means a probe-specific executed result (or an explicit tested/data-resolution
limit), not that the result is correct. Mentioning a mechanism or proposing a
future computation alone is not a tested cause. Compound breadth probes require
the specified connection, not just a reference list.
"""

def case(depth, breadth, causes=None, note=''):
    return {'depth': depth, 'breadth': breadth, 'causes': causes or {}, 'note': note}


OPEN = {
 'Q15': {
  'OceanX': case({1:r'coastal 0–30 m heat budget',2:r'no wind field',3:r'interior-SSH EOF1',4:r'sub-monthly events'},
                 {2:r'published\s+literature'}, note='No executed IOD/ENSO–productivity connection; the annual heat-content answer item is not being rescored.'),
  'Claude': case({1:r'Great Whirl recirculation',2:r'No winds',4:r'Monthly means miss'}, {},
                 note='Executed coastal/offshore and ocean-proxy contrasts exist despite needs_interaction. Basin EOFs alone do not test preconditioning/waves; Rebert is not a comparison of Somali/Oman upwelling accounts.'),
  'Finch': case({}, {}, note='No executed notebook analysis; expected correlations and listed deliverables are not results.')},
 'Q18': {
  'OceanX': case({1:r'supply geometry is cross-shore',2:r'0-100 m chlorophyll inventory does not increase',3:r'QUID states explicitly'},
                 {1:r'Oxygen shows no consistent relationship',2:r'Testing the published winter mechanism'}),
  'Claude': case({1:r'0–100 m nitrate stock',3:r'How this compares with the literature'},
                 {1:r'Beneath both blooms',2:r'Keerthi et al'}),
  'Finch': case({1:r'shoaling nutricline'}, {}, note='Surface/vertical sections are executed, but no column-integrated chlorophyll or published-realism test; seasonal oxygen mention does not connect bloom controls to the underlying OMZ.')},
 'Q19': {
  'OceanX': case({1:r'fixed-depth −5.80',2:r'Winter convection',3:r'forcing the four-face volume budget'},
                 {1:r'northern-shelf upwelling',2:r'published 300–1000 m range'}),
  'Claude': case({2:r'Isopycnal backward tracking',3:r'Oxygen was therefore computed'}, {},
                 note='Density-surface trajectories do not decompose oxygen changes into heave versus water-property change. No explicit data-derived productivity-offset comparison or measured comparison to published dynamics is retained.'),
  'Finch': case({2:r'Lateral ventilation pathways',3:r'differing native grids'}, {},
                 note='Pathway/vertical-gap proxies count as addressed, not proven ventilation. Fixed-depth oxygen trends are not a density-surface change/heave test; no reference-based dynamics comparison.')},
 'Q20': {
  'OceanX': case({1:r'initiation.{0,100}intensif|intensif.{0,100}initiation|Timing relative to the monsoon onset',2:r'Interannual covariation|interannual covariation'},
                 {1:r'coastal cooling'}, {'Q20-H1':r'Timing relative to the monsoon onset','Q20-H2':r'in phase across longitude',
                  'Q20-H3':r'barotropic conversion','Q20-H4':r'no daily or 5-day output'},
                 note='H4 is a documented resolution limit, counted because that is the listed test; no wind-causality verdict is being accepted.'),
  'Claude': case({1:r'preconditions',2:r'predictor|amplitude|year.to.year'}, {1:r'cooling|upwelling|cold wedge'},
                 {'Q20-H1':r'local southwest-monsoon','Q20-H2':r'phase speed',
                  'Q20-H4':r'Monthly resolution'}, note='Ocean-state timing and current-covariation tests count, not the stronger wind/wave attribution. Current strength is examined, but the listed H3 strength-and-separation-latitude relation is not completed.'),
  'Finch': case({1:r'formation.*peak.*decay'}, {}, note='Only the executed monthly life-cycle table remains; no completed precursor/cause comparison.')},
 'Q21': {
  'OceanX': case({1:r'84-90 % of the cross-path change',2:r'resolved mean flow',3:r'strait-mixing'}, {},
                 note='A tested mean-flow budget and explicit unresolved eddy remainder count. RSOW interpretation exists, but the combined OMZ-ventilation/RSW breadth connection and an executed cross-system erosion comparison are absent.'),
  'Claude': case({1:r'isopycnal-following RK4',2:r'eddy kinetic energy',3:r'Strait of Hormuz'}, {},
                 note='EKE versus dilution and isopycnal susceptibility are examined, without treating association as an identified mixing rate. No executed OMZ/other-salinity-maximum connection.'),
  'Finch': case({}, {}, note='Fixed-depth manual route, scalar-speed travel and asserted isopycnal mixing do not address the listed density/eddy/source-realism probes.')},
 'Q23': {
  'OceanX': case({1:r'criterion|definition',2:r'subsurface warm core'}, {1:r'precursor'},
                 {'Q23-H1':r'definition','Q23-H2':r'Record length / sampling','Q23-H3':r'subsurface warm core','Q23-H4':r'lifetime|size'},
                 note='The targeted definition/sampling/subsurface/size tests are counted irrespective of the reliability of the final event dates.'),
  'Claude': case({1:r'E1/E2 gap',2:r'20 °C isotherm deepens'}, {1:r'precursor'},
                 {'Q23-H1':r'reattachment','Q23-H2':r'bootstrap|seven.year|7.year|record|sampling',
                  'Q23-H3':r'20 °C isotherm deepens','Q23-H4':r'life ≥90'},
                 note='Saved split classifications, subsurface checks and sample-spread experiments are present.'),
  'Finch': case({}, {}, note='SSH threshold exploration and core preprocessing remain, but not a sensitivity of the delivered event count/intervals, subsurface confirmation or precursor comparison.')},
 'Q24': {
  'OceanX': case({1:r'supply|shelf reservoir|freshwater excess',2:r'event|lag|onset',3:r'collapsed shoreline step'}, {},
                 note='The literature lists hurricane/stratification links, but the requested derived connection is not executed.'),
  'Claude': case({1:r'shelf reservoir',2:r'August 2011',3:r'No river discharge|model|reanalysis'}, {},
                 note='Source/entrainment and tracked event products exist. Missing discharge and product limits are stated; no retained hurricane/stratification/heat linkage.'),
  'Finch': case({}, {}, note='No executed analysis; the described freshwater/eddy event products are not saved executed results.')},
 'Q25': {
  'OceanX': case({1:r'non-Loop-Current background',2:r'28 °C reference',3:r'salinity|barrier.layer|stratification'},
                 {1:r'operational definition'}, note='SSH-mask/TCHP products are interpreted in the operational SSH–heat-content setting; this does not assert observed hurricane validation or repair the existing unit error.'),
  'Claude': case({}, {}, note='The saved terminal delivery is a preprocessing note. Kept code has some TCHP output, but no completed listed probe comparison is identified; original zero score is unchanged.'),
  'Finch': case({1:r'Loop Current/eddy field is a spatially concentrating amplifier'}, {},
                 note='A seasonal/eddy thermal decomposition is addressed. A standard formula is not a definition sensitivity experiment; salinity is a descriptor, no barrier-layer/cooling test or specified operational/actual-storm comparison.')},
 'Q26': {
  'OceanX': case({1:r'non-seasonal band carries',2:r'water.mass|heaving of the background stratification',3:r'SSH-assimilating reanalysis'}, {},
                 note='Synthetic-profile papers are listed by the literature consultation, but no retained analysis-backed forecast/synthetic-profile use is demonstrated.'),
  'Claude': case({1:r'seasonal-cycle skill is therefore reported separately',2:r'mode-1 baroclinic structure',3:r'assimilates altimetry and in-situ profiles'}, {},
                 note='No synthetic-profile/forecasting discussion tied to executed reconstruction is retained.'),
  'Finch': case({1:r'deseasonalized',2:r'vertical stratification'}, {},
                 note='Season removal and vertical/water-regime interpretation count. No assimilation/non-independence warning or specified forecasting/synthetic-profile application.')},
 'Q27': {
  'OceanX': case({1:r'mean-shift counterfactual|Shifting only the summer mean',2:r'autocorrelation|AR\(1\)'},
                 {1:r'ECS trend literature|East China Sea.*trend papers|ECS.*trend papers'},
                 {'Q27-H1':r'baseline that moves','Q27-H4':r'event-based.*daily-exceedance|daily-exceedance.*event-based'},
                 note='Counts come from executed partial reports, not a new grade. No specific 1982–2011 versus 1991–2020 computation, no events-on-area-mean-SST versus per-cell-event comparison, and no executed input-homogeneity test. Daily-exceedance versus 5-day-event comparison counts as an event-rule test.'),
  'Claude': case({1:r'variance counterfactual',2:r'block bootstrap|autocorrelation|autocorrel'}, {1:r'Sources:'},
                 {'Q27-H1':r'Moving 15-yr','Q27-H4':r'Pooling window and minimum duration'},
                 note='Its recent fixed baseline is 1993–2022, not the specified 1991–2020 comparison. The satellite-constellation caveat is not an executed homogeneity test.'),
  'Finch': case({}, {}, note='No executed notebook analysis.')},
 'Q28': {
  'OceanX': case({1:r'surface|bottom|depth',2:r'position of the Kuroshio',3:r'2012–2022 withheld|December|winter'},
                 {1:r'2023'}),
  'Claude': case({1:r'not bottom-intensified',2:r'upstream|Kuroshio index|eddy',3:r'winter|December|May–Nov'},
                 {1:r'2023'}, note='Upstream/eddy tests are present, but the axis alternative is incomplete; this count is coverage, not the original mechanism grade.'),
  'Finch': case({1:r'maximum of \+3.0 °C at ~66 m'}, {1:r'2023'},
                 note='The vertical composite addresses surface/subsurface structure. No competing upstream/axis/eddy test or explicit treatment of the missing winter in variability interpretation.')},
 'Q29': {
  'OceanX': case({1:r'two-layer|surface.*bottom|near-bottom'}, {1:r'2023|heat content|Kuroshio'},
                 {'Q29-H1':r'surface|wind','Q29-H2':r'near-bottom cross-shore','Q29-H3':r'Taiwan Warm Current',
                  'Q29-H4':r'tide-free'}, note='H4 is the model/resolution limit listed in the rubric; no resolved tidal mechanism is inferred.'),
  'Claude': case({1:r'two-layer upwelling cell'}, {1:r'2023 summer heatwave|2023|Oh et al'},
                 {'Q29-H1':r'surface cross-isobath divergence','Q29-H2':r'Q100_bot|100 m isobath',
                  'Q29-H3':r'TWC|Taiwanese Warm Current'}, note='No retained explicit daily-mean tidal-mixing-front test/limit.'),
  'Finch': case({1:r'surface-intensified offshore flow'}, {1:r'bottom cold pool|Taiwan Warm Current'},
                 {'Q29-H1':r'JJA coastal cross-shore velocity','Q29-H2':r'bottom|intrusion'}, note='Executed layered velocity/thermal proxies count. H3 is excluded: the northward-flow and topographic-setting description does not execute the specified along-shelf-current/bottom-slope relation. No tidal-front resolution discussion.')},
 'Q30': {
  'OceanX': case({1:r'depending on smoothing scale',2:r'no front displacement',3:r'best step year 2007'}, {},
                 note='No retained marine-heatwave/biology/fisheries connection grounded in this analysis.'),
  'Claude': case({1:r'0.25/0.5/0.75',2:r'Position was tracked two independent ways',3:r'pre/post-2007 step'}, {},
                 note='No retained marine-heatwave/biology/fisheries connection.'),
  'Finch': case({1:r'persists across thresholds',2:r'centroid migrates'}, {},
                 note='Static mask and complete time coverage are QC, not an input-stream homogeneity test; no specified heatwave/biology/fisheries connection.')}
}


# Verdicts are the agent's own labels, not a match to a frozen reference. Mixed
# testable/untestable findings use the agent's verdict on the tested component.
# Evidence_ok asks for traceable executed support of that component or a verified
# missing-data limitation. It is not a new 0–4 score or a numerical oracle check.
PAPER = {
 'Q07': {
  'OceanX': (['partly_reproduced','partly_reproduced','reproduced','partly_reproduced','not_reproduced'], [True]*5,
             ['SUW/AAIW/NADW maps and corrected density diagnostic','SSH-class 6°C retest','10-m-reference MLD retest','literal 0–50 m integral','truncated PV/eddy test and unresolved bathymetry']),
  'Claude': (['partly_reproduced','reproduced','reproduced','partly_reproduced','reproduced'],[True,True,True,True,False],
             ['fixed-depth water-mass products; fidelity flaw retained','isotherm/SSH classes','MLD pair','steric integral','low Ertel-PV uniformity does not execute an eddy-translation mechanism test']),
  'Finch': (['partly_reproduced','reproduced','partly_reproduced','partly_reproduced','partly_reproduced'],[True,True,True,True,False],
             ['fixed-depth maps','isotherm composites (6°C omitted)','10-m-reference density MLD','steric table, partial-year flaw retained','mixed not-testable/partly label; no eddy-translation test'])},
 'Q08': {
  'OceanX': (['partly_reproduced','partly_reproduced','partly_reproduced','partly_reproduced','partly_reproduced'],[True]*5,
             ['thermostad profile','background/radius ensemble','two salinity cores','tracked post-detachment evolution','SSH-referenced thermal wind']),
  'Claude': (['partly_reproduced','reproduced','reproduced','reproduced','partly_reproduced'],[True,True,True,False,True],
             ['core stratification','temperature anomaly','double core','176 days cannot evidence claimed seven-month conservation','executed velocity with corrected signs; wrong expected depth remains in original grade']),
  'Finch': (['missing']*5,[False]*5,['No retained finding-specific verdict']*5)},
 'Q09': {
  'OceanX': (['reproduced','partly_reproduced','not_testable','reproduced','partly_reproduced'],[True,True,True,True,False],
             ['erosion track','season/MLD, missing winds explicit','diffusion fits plus missing heat-flux limitation','upper-layer homogenization','heave/partial geostrophic budget cannot evidence transport shares']),
  'Claude': (['reproduced','partly_reproduced','partly_reproduced','partly_reproduced','partly_reproduced'],[True,True,True,True,False],
             ['density-surface erosion','winter/MLD timing','diffusion fit','gradient homogenization','unclosed inventory does not evidence exclusive advection']),
  'Finch': (['not_testable']*5,[False]*5,['Blocker verdict present but no recorded execution; claimed mount tests are not verified']*5)},
 'Q10': {
  'OceanX': (['partly_reproduced','partly_reproduced','not_reproduced','not_testable'],[True]*4,
             ['event dates/baseline','revised 3-D budget','phase-resolved latent flux','CMIP6 missing verified from supplied inputs']),
  'Claude': (['reproduced','partly_reproduced','partly_reproduced','not_testable'],[True]*4,
             ['event detection','executed budget (residual attribution flaw retained)','latent-flux phase comparisons','CMIP6 absence stated against input inventory']),
  'Finch': (['reproduced','partly_reproduced','partly_reproduced','not_testable'],[True,False,True,True],
             ['event detection','no executed available 3-D advection term-ranking test','executed surface-flux summaries','CMIP6 absence stated against input inventory'])}
}
