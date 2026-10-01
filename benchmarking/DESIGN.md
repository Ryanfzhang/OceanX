# OceanX benchmark: design

Catalogue `2026-10-01-v6`. Two suites:

- **Test suite, Q01-Q30.** Scored. 10 paper verifications and 20 open problems. South China Sea questions
  use the private CMOMS model output. The other questions use public data in the Gulf of Mexico, the East
  China Sea and the Arabian Sea. Every scored measurement comes from this suite.
- **Evolution suite, E01-E24.** Never scored. Open problems on public reanalyses, in two sets of twelve:
  set A on the California Current System and set B on the Tasman Sea and East Australian Current. OceanX
  learns lessons from these runs in two rounds (see "Evolution suite").

Everything runs on the Linux server, never on macOS.

[summary.md](summary.md) is the three-column inventory of all 54 queries: question, required data
(type, period, sampling, spatial/depth scope and variables), and brief assessment criteria.

## Goals

1. Measure how well OceanX does two kinds of research work:
   - verifying published findings with data from the paper's own study period;
   - investigating typical open problems in physical and biogeochemical oceanography.
2. Measure whether the research-policy choice and self-improvement (lessons learned from earlier runs) help
   on questions OceanX has never seen, and whether a second round of learning adds to the first.

## Design rules

| Rule | How the catalogue follows it |
|---|---|
| Two question types only | 10 paper verifications and 20 open problems. There are no basic calculation or visualisation tasks. |
| Paper data cover the paper's period | Every paper's study period lies inside the supplied data (see "Papers"). Each `task_info.json` records this under `period_match`, and a test checks it against the data manifest. |
| South China Sea questions use CMOMS | All 13 South China Sea questions use CMOMS (temperature, salinity, velocity, oxygen, chlorophyll; daily, 2011-2020, full depth). |
| CMOMS is a minority of the open problems | 7 of the 20 open problems use CMOMS. The other 13 use public data: 5 in the Arabian Sea, 4 in the Gulf of Mexico and 4 in the East China Sea. |
| Centred on the CMOMS variables | Questions use temperature, salinity, currents, oxygen and chlorophyll. Q14 also uses primary production and nitrate uptake, and Q16 uses air-sea CO2 exchange and surface pCO2. Oxygen: Q05, Q13, Q17 on CMOMS and Q19 on public data. Chlorophyll: Q06, Q14, Q22 on CMOMS and Q18 on public data. |
| Typical problems, several regions | The open problems are standard research problems: marine heatwaves, coastal upwelling, hypoxia, blooms, primary production, air-sea carbon exchange, oxygen minimum zones, deep ventilation, water-mass spreading, boundary currents and eddy shedding, river plumes, ocean heat content, fronts. |
| Few multi-product questions | Only 3 of 30 combine products: Q10 (OISST, GLORYS12 and ERA5), Q19 (biogeochemical and physical reanalyses) and Q22 (CMOMS and MODIS). Q14 and Q16 add diagnostics from the same CMOMS model, not another product. |
| Download as little as possible | The Gulf of Mexico, East China Sea, ERA5, OISST and MODIS groups are already on the server (MODIS is extended to 2020). New downloads are two monthly Arabian Sea groups (about 2 GB) and the evolution suite's California Current and Tasman Sea groups (about 2-3 GB each). The two evolution sets use the same three products, so no new product is added. The monthly winds are no longer needed. |
| Paper verification needs real papers | The 10 papers were checked against Crossref (title, authors, volume, pages, DOI) and their abstracts on 2026-10-01. The findings in each query paraphrase the abstract. Five were also read in full (Q02, Q04, Q05, Q07, Q10); see "Papers". |
| Different rubrics for the two types | Paper verification scores whether each finding of the paper was actually verified. Open problems are scored more broadly and deeply, on seven dimensions, against a hidden answer key (see "Rubrics"). |
| No evaluator material reaches the agent | Rubrics live in `tasks/<task>/evaluator/`. Answer-key data lives under `_evaluator_only/` on the server. Query preparation refuses both. |
| No evolution while benchmarking | Each attempt starts from empty OceanX state. An arm fixes the research policy and an optional frozen lesson set, and every attempt verifies its lessons were unchanged. |
| Evolution uses open problems on separate data | The evolution suite has 24 open problems and no paper verification. It uses two regions outside the test suite (the California Current System and the Tasman Sea) and the same kinds of public products. CMOMS never appears in evolution, so CMOMS questions measure transfer to data OceanX has never seen. |
| Two rounds of learning | Set A runs without lessons and yields lesson set L1. Set B runs with L1 and yields L2. The test suite runs with no lessons, with L1 and with L2, so each round is measured separately. |
| Lessons are judged by the research process too | Lessons are about research-tree decisions, so each run also reports process measures from its tree (see `EVALUATION.md`). One of them is a pre-registered endpoint. |

## Allocation (30 test questions)

| Type | IDs | Count | Regions | What is scored |
|---|---|---|---|---|
| Paper verification | Q01-Q10 | 10 | 6 South China Sea, 3 Gulf of Mexico, 1 East China Sea | Whether each finding listed in the query was verified with the supplied data |
| Open problem, checkable | Q11-Q19, Q21, Q24-Q26, Q28, Q30 | 15 | 6 South China Sea, 4 Arabian Sea, 3 Gulf, 2 East China Sea | The answer against a hidden answer key; depth, robustness, breadth and insight |
| Open problem, disagreement | Q20, Q22, Q23, Q27, Q29 | 5 | 1 South China Sea, 1 Arabian Sea, 1 Gulf, 2 East China Sea | Diagnosing why estimates disagree: between published studies, methods, or two datasets |

Data access:
- **CMOMS only:** 12 questions (6 papers, 6 open problems).
- **CMOMS plus a public product:** 1 question (Q22).
- **Public data only:** 17 questions (4 papers, 13 open problems).

Six pairs put the same kind of problem on private and on public data. Published analyses of the public data
exist, and a model may have memorised them. None exist for this CMOMS archive.

| Problem | Private (CMOMS) | Public |
|---|---|---|
| Salinity change (papers) | Q01 | Q09 |
| Loop current and eddy structure (papers) | Q02 | Q08 |
| Marine heatwaves | Q11 | Q27 |
| Coastal upwelling | Q12 | Q29 |
| Seasonal blooms | Q14 | Q18 |
| Ventilation of low-oxygen water | Q17 | Q19 |

## Test suite

| ID | Region | Kind | Title | Agent data | Paper or answer key |
|---|---|---|---|---|---|
| Q01 | SCS | paper | Salinification of the South China Sea since late 2012 | C_CORE | Zeng et al. (2018) |
| Q02 | SCS | paper | The Kuroshio Loop Current in the winters of 2014-2017 | C_CORE | Sun et al. (2020) |
| Q03 | SCS | paper | The weakest winter western boundary current, 2015-2016 | C_CORE | Zhao and Zhu (2016) |
| Q04 | SCS | paper | The South Vietnam upwelling in summer 2018 | C_CORE | Herrmann et al. (2023) |
| Q05 | SCS | paper | Destruction and return of hypoxia off the Pearl River Estuary, July 2018 | C_CORE | Zhao et al. (2021) |
| Q06 | SCS | paper | Typhoon Merbok and the vertical chlorophyll distribution, June 2017 | C_CORE | Fang et al. (2022) |
| Q07 | GULF | paper | Hydrography of the deep Gulf of Mexico, 2011-2015 | P_GULF | Hamilton et al. (2018) |
| Q08 | GULF | paper | Vertical structure of a Loop Current eddy | P_GULF | Meunier et al. (2018) |
| Q09 | GULF | paper | Erosion of the salinity maximum inside the Loop Current eddy Poseidon | P_GULF | Sosa-Gutierrez et al. (2020) |
| Q10 | ECS | paper | The late-arriving 2023 East China Sea marine heatwave | P_OISST, P_ECS, P_ERA5 | Oh et al. (2024) |
| Q11 | SCS | checkable | Subsurface marine heatwaves | C_CORE | hidden CMOMS budget (X_HEAT) + reference diagnostics |
| Q12 | SCS | checkable | Year-to-year control of the upwelling off eastern Hainan | C_CORE | hidden CMOMS budget (X_HEAT) + reference diagnostics |
| Q13 | SCS | checkable | Year-to-year control of hypoxia off the Pearl River Estuary | C_CORE | hidden CMOMS budget (X_OXY) + reference diagnostics |
| Q14 | SCS | checkable | Winter chlorophyll, primary production and nitrate uptake northwest of Luzon | C_CORE, C_PRODUCTION | reference diagnostics |
| Q15 | ARAB | checkable | Year-to-year strength of the summer upwelling off Somalia and Oman | P_ARAB_PHY | reference diagnostics |
| Q16 | SCS | checkable | Seasonal and interannual air-sea CO2 exchange on the Pearl River adjacent shelf | C_CORE, C_CARBON | reference diagnostics |
| Q17 | SCS | checkable | Ventilation of the deep South China Sea | C_CORE | reference diagnostics |
| Q18 | ARAB | checkable | The winter and summer blooms of the Arabian Sea | P_ARAB_BGC | reference diagnostics |
| Q19 | ARAB | checkable | Structure and ventilation of the Arabian Sea oxygen minimum zone | P_ARAB_BGC, P_ARAB_PHY | reference diagnostics |
| Q20 | ARAB | disagreement | What starts the Great Whirl | P_ARAB_PHY | reference diagnostics; candidate causes with tests |
| Q21 | ARAB | checkable | Spreading and dilution of the Gulf outflow water in the Arabian Sea | P_ARAB_PHY | reference diagnostics |
| Q22 | SCS | disagreement | Why CMOMS and MODIS surface chlorophyll disagree | C_CORE, P_MODIS | reference diagnostics; candidate causes with tests |
| Q23 | GULF | disagreement | How often the Loop Current sheds eddies, and why estimates differ | P_GULF | reference diagnostics; candidate causes with tests |
| Q24 | GULF | checkable | Offshore export of river water from the northern Gulf shelf | P_GULF | reference diagnostics |
| Q25 | GULF | checkable | Ocean heat available to hurricanes and the Loop Current's share | P_GULF | reference diagnostics |
| Q26 | GULF | checkable | What sea surface height reveals about the subsurface | P_GULF | reference diagnostics |
| Q27 | ECS | disagreement | Are East China Sea marine heatwaves increasing, and how the baseline changes the answer | P_OISST | reference diagnostics; candidate causes with tests |
| Q28 | ECS | checkable | Kuroshio intrusion onto the East China Sea shelf | P_ECS | reference diagnostics |
| Q29 | ECS | disagreement | What drives the summer upwelling off Zhejiang and Fujian | P_ECS | reference diagnostics; candidate causes with tests |
| Q30 | ECS | checkable | Changes in East China Sea temperature fronts | P_OISST | reference diagnostics |

- **Where things live:** the query text, paper, period match, region and data groups are in
  `tasks/<task>/task_info.json`. The rubric (criteria, findings, answer key, probes, candidate causes and
  gates) is in `tasks/<task>/evaluator/rubric.json`.
- **X_OXY:** it is optional. Without it, Q05 and Q13 use their reference diagnostics.

### Papers (verified 2026-10-01)

Each paper was chosen so that its study period lies inside the supplied data.

| Task | Paper | Paper's period and data | Supplied data |
|---|---|---|---|
| Q01 | Zeng et al. (2018), Salinification in the South China Sea since late 2012, GRL 45. doi:10.1002/2017GL076574 | late 2012 to about 2017; satellite and Argo salinity | CMOMS, 2011-2020 |
| Q02 | Sun et al. (2020), Three-dimensional structure and interannual variability of the Kuroshio Loop Current, JPO 50. doi:10.1175/JPO-D-20-0058.1 | June 2014-June 2017; ten moorings west of the Luzon Strait | CMOMS, 2011-2020 |
| Q03 | Zhao and Zhu (2016), Weakest winter South China Sea western boundary current caused by the 2015-2016 El Nino event, JGR Oceans 121. doi:10.1002/2016JC012252 | winter 2015-2016; in situ transport monitoring and altimetry | CMOMS, 2011-2020 |
| Q04 | Herrmann et al. (2023), Intraseasonal variability of the South Vietnam upwelling, Ocean Science 19. doi:10.5194/os-19-453-2023 | June-September 2018; 1 km model ensemble | CMOMS, 2011-2020 |
| Q05 | Zhao et al. (2021), Destruction and reinstatement of coastal hypoxia off the Pearl River estuary, Biogeosciences 18. doi:10.5194/bg-18-2755-2021 | 8-29 July 2018; three cruise legs around Typhoon Son-Tinh | CMOMS, 2011-2020 |
| Q06 | Fang et al. (2022), Typhoon effects on the vertical chlorophyll distribution on the northern shelf, JGR Oceans 127. doi:10.1029/2022JC019350 | June 2017; field observations and a coupled model | CMOMS, 2011-2020 |
| Q07 | Hamilton et al. (2018), Hydrography of the Gulf of Mexico using autonomous floats, JPO 48. doi:10.1175/JPO-D-17-0205.1 | July 2011-August 2015; 706 float profiles | GLORYS12, 2011-2017 |
| Q08 | Meunier et al. (2018), The vertical structure of a Loop Current eddy, JGR Oceans 123. doi:10.1029/2018JC013801 | August-November 2016; glider sections | GLORYS12, 2011-2017 |
| Q09 | Sosa-Gutierrez et al. (2020), Erosion of the subsurface salinity maximum of the Loop Current eddies, JGR Oceans 125. doi:10.1029/2019JC015397 | August 2016-July 2017; glider sections and a regional model | GLORYS12, 2011-2017 |
| Q10 | Oh et al. (2024), Late-arriving 2023 summer marine heatwave in the East China Sea, npj Climate and Atmospheric Science 7. doi:10.1038/s41612-024-00846-4 | 2023 event, 1982-2011 baseline, 1993-2011 budget reference; OISST, GLORYS12, ERA5 | the same three products, same periods |

How far each paper was checked:
- **Read in full (five):** Q02, Q04, Q05, Q07 and Q10. For Q07 the full text supplied the paper's own
  definitions, now in its rubric: the water-mass criteria, the mixed-layer criteria, the sea-surface-height
  classes and the potential vorticity. That vorticity is the Coriolis parameter divided by the thickness
  below the 6 C isotherm, which needs the water depth. No bathymetry is supplied, so finding 5 of Q07 is now
  partly testable.
- **Abstract only (five):** Q01, Q03, Q06, Q08 and Q09. The publisher's site refuses automated reading. Open
  repository copies exist for Q01 (Woods Hole), Q08 (Ifremer) and Q09 (HAL); none was found for Q03 and Q06.
  Their regions, windows and definitions must be confirmed from the paper before their rubrics are frozen.

What still differs from the papers:
- **The product.** Nine papers used observations or another model. Here CMOMS or the GLORYS12 reanalysis
  stands in for them. Only Q10 uses the paper's own products.
- **A few findings reach beyond the study period.** Examples are the 1993-2012 freshening in Q01, "the
  strongest event since 1993" in Q02, and the ENSO composites in Q03. The rubric marks these partly
  testable or not testable.

The query lists the paper's findings. The agent tests each one in the supplied data, says whether it was
reproduced, partly reproduced, not reproduced, or cannot be tested, and explains the differences. Agreeing
with the paper does not earn marks. Agreeing with what the supplied data show does.

Four rubrics also cite verified literature for judging the agent's comparison with published work:
- Keerthi et al. (2017) for Q18;
- McCreary et al. (2013) and Lachkar et al. (2019) for Q19;
- Beal and Donohue (2013) for Q20;
- Hamilton et al. (2018) for Q26.

## Rubrics: two designs

Both types score each criterion 0-4. The total is `sum(weight * score / 4)` out of 100. Codex judges both
(`evaluation/CODEX_JUDGE.md`).

### Paper verification: was each finding verified?

| Criterion | Weight | What earns a 4 |
|---|---|---|
| One criterion per finding (`K1`...`K5`) | 70 in total, by importance | The finding is tested appropriately and completely. The result is compared quantitatively with the paper's statement. The verdict agrees with the evaluator's frozen reference within tolerance, and any mismatch with the paper is traced to a stated cause. |
| Method fidelity (`M`) | 10 | The paper's key definitions and methods (listed in the rubric) are reproduced, or each adaptation is justified with parameters. |
| Differences from the paper's setting (`D`) | 10 | Each material difference (product, resolution, model versus observations) is linked to the findings it could affect, and at least one is tested. |
| Verification report (`R`) | 10 | A table per finding (paper statement, reproduced value, verdict, evidence), comparable figures, traceable numbers. |

Each finding in the rubric carries:
- the paper's evidence (a quote from the abstract or full text);
- its **testability**;
- how the evaluator tests it;
- the expected result in the supplied data, computed and frozen before judging;
- the tolerance.

Testability has three levels:
- **Testable.** The finding can be checked with the supplied data.
- **Partly testable.** For example, the wind part of a mechanism cannot be tested without winds. A 4
  requires testing every testable part and saying plainly which part cannot be tested.
- **Not testable.** For example, the 1993-2012 freshening in Q01, or the CMIP6 projections in Q10. A 4
  requires saying so and naming the missing data. Claiming to have verified it scores 0.

### Open problems: broad and deep

| Criterion | Weight | What it judges |
|---|---|---|
| Framing and competing hypotheses (`F`) | 10 | Operational definitions; competing explanations with distinguishing predictions |
| Data fitness and handling (`A`) | 10 | Correct handling; whether the data can answer the question (model realism, record length, resolution) |
| Quantitative answer (`Q`) | 20 | The answer-key items for this criterion, within the frozen tolerances |
| Mechanistic depth (`M`) | 20 | Dominant and secondary processes agree with the hidden answer key, established by process-based tests; competing explanations ruled in or out; the task's depth probes |
| Robustness and uncertainty (`R`) | 15 | Sensitivity to every choice that could change the conclusion; statistics for short, autocorrelated records |
| Breadth and synthesis (`B`) | 15 | Links across scales, processes and variables; agreement and disagreement with published work; the task's breadth probes |
| Insight, limits and next steps (`I`) | 10 | A clear quantified answer, what the data cannot settle, what would settle it, a non-obvious insight |

The hidden answer key differs by question:
- **Q11 and Q12:** the closed CMOMS heat budget (X_HEAT).
- **Q13:** the CMOMS oxygen budget (X_OXY, optional).
- **Every open problem:** reference diagnostics that the evaluator computes on the same inputs.

The answer-key values are filled in and frozen before any test run is judged.

For the five disagreement questions, `Q` becomes "disagreement quantified" and `M` becomes "causes diagnosed
with targeted tests". Each of these questions lists at least three candidate causes, each with the test
that could confirm or reject it.

Gates apply to both types:
- untraceable numbers or citations count as unsupported;
- copying the paper's values as results scores 0 on that finding;
- answering a different question caps the answer and mechanism criteria;
- an answer without executed analysis scores almost nothing.

## Evolution suite (never scored)

Twenty-four open problems in two sets of twelve. There is no paper verification in this suite. Both sets use
the same three public products, each cropped to its own region:
- **GLORYS12 monthly** temperature, salinity, velocity, sea surface height and mixed-layer thickness,
  2011-2020, 0-1000 m (`P_CCS_PHY`, `P_TAS_PHY`);
- **GLORYS12 daily** near-surface temperature, 1993-2020 (`P_CCS_SURF`, `P_TAS_SURF`);
- **CMEMS global biogeochemical reanalysis monthly** oxygen, chlorophyll and nitrate, 1993-2020, 0-1000 m
  (`P_CCS_BGC`, `P_TAS_BGC`).

The variable set mirrors CMOMS, so lessons about temperature, currents, oxygen and chlorophyll can transfer.
The regions do not: neither appears in the test suite.

| Set | Region | Runs with | Yields |
|---|---|---|---|
| A, E01-E12 | California Current System, 30-48 N, 130-116 W: an eastern-boundary upwelling system | no lessons (L0) | lesson set L1 |
| B, E13-E24 | Tasman Sea and East Australian Current, 46-26 S, 147-162 E: a western boundary current and an ocean-warming hotspot | L1 | lesson set L2 |

Set B is on other waters and another kind of circulation, so L2 is not learned where L1 was. It shows two
things the first round cannot: whether tasks run with L1 still make the mistakes L1 addresses, and which
lessons hold in a second region. The meta-agent may propose retiring an L1 lesson that set B contradicts.

### Set A: California Current System

| ID | Kind | Title | Data |
|---|---|---|---|
| E01 | checkable | The equatorward California Current | P_CCS_PHY |
| E02 | checkable | Temperature fronts of the upwelling zone | P_CCS_SURF |
| E03 | checkable | Has subsurface oxygen declined since 1993 | P_CCS_BGC |
| E04 | checkable | Two El Ninos compared: 1997-1998 and 2015-2016 | P_CCS_SURF, P_CCS_BGC |
| E05 | checkable | Timing of the spring transition to upwelling | P_CCS_SURF |
| E06 | checkable | The California Undercurrent | P_CCS_PHY |
| E07 | checkable | Depth of the hypoxic boundary on the slope | P_CCS_BGC |
| E08 | checkable | Timing and size of the upwelling-season chlorophyll maximum | P_CCS_BGC |
| E09 | checkable | Local or advected: subsurface anomalies of 2014-2016 | P_CCS_PHY |
| E10 | disagreement | Product mixed-layer thickness versus mixed layers computed from profiles | P_CCS_PHY |
| E11 | checkable | Coastal versus offshore marine heatwaves | P_CCS_SURF |
| E12 | disagreement | When temperature stops predicting nitrate | P_CCS_PHY, P_CCS_BGC |

### Set B: Tasman Sea and East Australian Current

| ID | Kind | Title | Data |
|---|---|---|---|
| E13 | checkable | The East Australian Current and where it leaves the coast | P_TAS_PHY |
| E14 | checkable | Southward or eastward: the two pathways of the separated current | P_TAS_PHY |
| E15 | checkable | Local or advected: the upper-ocean warm anomaly of 2015-2016 | P_TAS_PHY |
| E16 | checkable | Spreading and dilution of the saline subtropical water | P_TAS_PHY |
| E17 | checkable | Deep winter mixed layers and the water they form | P_TAS_PHY |
| E18 | disagreement | How much water the East Australian Current carries, and why estimates differ | P_TAS_PHY |
| E19 | checkable | How fast the sea surface has warmed since 1993 | P_TAS_SURF |
| E20 | checkable | Two marine heatwaves compared: 2015-2016 and 2017-2018 | P_TAS_SURF, P_TAS_BGC |
| E21 | checkable | Cold water inshore of the East Australian Current | P_TAS_SURF |
| E22 | checkable | Timing and size of the spring bloom | P_TAS_BGC |
| E23 | checkable | Has oxygen in the thermocline changed since 1993 | P_TAS_BGC |
| E24 | disagreement | Do warm-core eddies hold more or less chlorophyll than cold-core eddies | P_TAS_PHY, P_TAS_BGC |

Set B has the same mix as set A: ten checkable problems and two disagreement problems, across physics,
surface temperature and biogeochemistry. Three problems state that surface fluxes or winds are not supplied
(E15, E17, E21), and two combine products from different model systems (E20, E24).

## What changed in v6

- **A second evolution set.** Set B (E13-E24) adds twelve open problems on the Tasman Sea and East
  Australian Current, with three new download groups (`P_TAS_PHY`, `P_TAS_SURF`, `P_TAS_BGC`) of the same
  products as set A. The test suite (Q01-Q30) is unchanged.
- **Two rounds of learning.** L0 to L1 on set A, L1 to L2 on set B. The test suite gains one arm: no
  lessons, L1 and L2 under the same policy.
- **Process measures.** Each run reports how its research tree went, not only its score.
- **Q07 follows the paper's full text.** Its rubric now uses the paper's own definitions, and its fifth
  finding is partly testable because the paper's potential vorticity needs bathymetry.
- **A longer time limit.** The default per-attempt limit is three hours instead of two. Three recorded
  research runs of one question took 79 to 152 minutes, and a timed-out attempt scores 0.

## What changed in v5

- **Paper verification is period-matched.** Six of the eight South China Sea papers of v4 analysed periods
  that CMOMS 2011-2020 does not cover: 1992-2011 for Gan et al., 1982-2020 for Yao and Wang, and records
  ending before 2011 for Chen, Liu, Xie and Qu. The periods of the other two (Li et al., Xu et al.) could
  not be confirmed from open sources. All eight are replaced by six South China Sea papers whose stated
  study periods fall inside 2011-2020. Two Gulf of Mexico papers that match the existing 2011-2017
  reanalysis are added: Hamilton et al. (2018) and Sosa-Gutierrez et al. (2020). Meunier et al. (2018) and
  Oh et al. (2024) already matched and stay.
- **The evolution suite has open problems only.** The four paper questions (E01-E04) became open problems
  on the same data.
- **Fewer open problems use CMOMS:** 7 of 20 instead of 12. Five South China Sea problems were dropped
  (Luzon Strait transport, El Nino heat content, the winter Warm Current, the Beibu Gulf, tropical-water
  erosion). Five Arabian Sea problems on public reanalyses replace them (Q15, Q18-Q21).
- **Q24 is new.** The former Q24 (salinity-maximum erosion) became the paper question Q09.
- **Data groups:** the monthly winds (P_WIND) are no longer needed. Two monthly Arabian Sea groups are
  added (P_ARAB_PHY, P_ARAB_BGC).

## What changed in v4

- Q14 retains the Luzon winter-bloom question and adds measured production and nitrate uptake on the
  116-120 E, 16-20 N box, upper 100 m.
- Q16 replaces the Pearl River plume question with surface air-sea CO2 exchange on the adjacent shelf,
  112-116 E, 20-23 N, bathymetry <=200 m.
- Both groups request 2011-2020, with provider-confirmed averaging intervals. They are required agent
  inputs for their questions, not hidden answer-key data; missing fields prevent those questions running.
- Rubrics for Q14 and Q16 assess the new measurements, unit/sign handling, uncertainty and supported
  interpretations. Full ecosystem or carbon-budget attribution is not required without its inputs.

## What changed in v3

- The six basic calculation tasks were removed, leaving two question types with separate rubric designs.
- The Gulf of Mexico and East China Sea questions moved from the evolution suite into the test suite, with
  their existing data. The evolution suite moved to the California Current.
- Only three questions combine datasets (24 did in the v2 draft).
