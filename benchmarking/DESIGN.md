# OceanX benchmark: design

Catalogue `2026-10-02-v7`. Two suites:

- **Test suite, Q01-Q30.** Scored. 10 paper verifications and 20 open problems. South China Sea questions
  use the private CMOMS model output. The other questions use public data in the Gulf of Mexico, the East
  China Sea and the Arabian Sea. Every scored measurement comes from this suite.
- **Evolution suite, E01-E24.** Never scored. Open problems on public reanalyses, in two sets of twelve:
  set A on the California Current System and set B on the Tasman Sea and East Australian Current. OceanX
  learns lessons and tools from these runs in two rounds (see "Evolution suite").

Everything runs on the Linux server, never on macOS.

[summary.md](summary.md) is the three-column inventory of all 54 queries: question, required data
(type, period, sampling, spatial/depth scope and variables), and brief assessment criteria.

## Goals

1. Measure how well OceanX does two kinds of research work:
   - verifying published findings with data from the paper's own study period;
   - investigating typical open problems in physical and biogeochemical oceanography.
2. Measure whether self-improvement (the lessons and tools learned from earlier runs) helps on questions
   OceanX has never seen, and whether a second round of learning adds to the first.

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
| Paper verification needs real papers | The 10 papers were checked against Crossref (title, authors, volume, pages, DOI) and their abstracts on 2026-10-01. The findings in each query paraphrase the abstract. Six were also read in full (Q02, Q04, Q05, Q07, Q08, Q10); see "Papers". |
| Different rubrics for the two types | Paper verification scores whether each finding of the paper was actually verified. Open problems are scored more broadly and deeply, on seven dimensions, against a hidden answer key (see "Rubrics"). |
| No evaluator material reaches the agent | Rubrics live in `tasks/<task>/evaluator/`. Answer-key data lives under `_evaluator_only/` on the server. Query preparation refuses both. |
| No learning while benchmarking | Each attempt starts from empty OceanX state and its library is frozen. Every arm runs the default policy (`v2-nested`); an arm fixes an optional frozen library (lessons and tools), and every attempt verifies that library was unchanged. |
| Evolution uses open problems on separate data | The evolution suite has 24 open problems and no paper verification. It uses two regions outside the test suite (the California Current System and the Tasman Sea) and the same kinds of public products. CMOMS never appears in evolution, so CMOMS questions measure transfer to data OceanX has never seen. |
| Evolution asks other kinds of problems | No evolution question is about a kind of problem that a test question is about, and no kind of problem appears in more than two evolution questions. A lesson or a tool needs support from three different questions, so whatever is learned has to hold across kinds of problems, and the test suite measures transfer to problems OceanX did not practise. |
| Two rounds of learning | Set A runs with nothing learned and yields the library L1. Set B runs with L1 and yields L2. The test suite runs with nothing learned, with L1 and with L2, so each round is measured separately. |
| Learning is the meta-agent's, after each set | After a set has run, the meta-agent reviews its records once: it keeps, revises, retires and adds lessons inside the regions the skills reserve, and adds helper functions that pass a static check, their own test and an independent review. Call counts decide which tools stay listed. The owner can mark any item right or wrong; no approval is needed. |
| The library is judged by the research process too | Lessons are about research-tree and analysis decisions and tools about code, so each run also reports process measures: tokens spent on questions that did not change the answer, failed code runs, helper calls and lessons named (see `EVALUATION.md`). One of them is a pre-registered endpoint. |

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
| Q11 | SCS | checkable | Subsurface marine heatwaves | C_CORE | independent core-field reference diagnostics |
| Q12 | SCS | checkable | Year-to-year control of the upwelling off eastern Hainan | C_CORE | independent core-field reference diagnostics |
| Q13 | SCS | checkable | Year-to-year control of hypoxia off the Pearl River Estuary | C_CORE | independent core-field reference diagnostics |
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
- **Core-field references:** Q05 and Q11-Q13 require no native heat or oxygen budget archive. Freeze independent diagnostics and their uncertainty before judging; retain the distinction between net tendencies, proxies and measured processes.

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
- **Read in full (six):** Q02, Q04, Q05, Q07, Q08 and Q10. The full text supplied each paper's own
  definitions, now in its rubric.
  - Q07: the water-mass criteria, the mixed-layer criteria, the sea-surface-height classes and the
    potential vorticity. That vorticity is the Coriolis parameter divided by the thickness below the 6 C
    isotherm, which needs the water depth. No bathymetry is supplied, so finding 5 of Q07 is partly testable.
  - Q08: the eddy detached on 15 April 2016; anomalies are taken against a mean profile of Gulf water
    outside Loop Current eddies in April-November 2016; the geostrophic velocity is referenced to the
    glider's depth-averaged velocity, which the agents do not have.
- **Abstract only (four):** Q01, Q03, Q06 and Q09. The publisher's site refuses automated reading. Open
  repository copies exist for Q01 (Woods Hole) and Q09 (HAL), but both repositories also answer automated
  requests with a bot check; none was found for Q03 and Q06. Their regions, windows and definitions must be
  confirmed from the paper before their rubrics are frozen.

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
| Mechanistic depth (`M`) | 20 | Quantitative tests of competing explanations agree with independent references; identifiability limits and uncertainty are stated; the task's depth probes. For Q11-Q13, justified unresolved attribution can receive full credit. |
| Robustness and uncertainty (`R`) | 15 | Sensitivity to every choice that could change the conclusion; statistics for short, autocorrelated records |
| Breadth and synthesis (`B`) | 15 | Links across scales, processes and variables; agreement and disagreement with published work; the task's breadth probes |
| Insight, limits and next steps (`I`) | 10 | A clear quantified answer, what the data cannot settle, what would settle it, a non-obvious insight |

The hidden answer key differs by question:
- **Q11 and Q12:** independent event, stratification, displacement and resolved-horizontal-advection diagnostics from core fields; missing forcing and vertical/mixing terms limit attribution.
- **Q13:** independent hypoxia and candidate-association diagnostics from core fields, with collinearity and short-record uncertainty. No measured respiration or closed oxygen budget is assumed.
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

The data resemble the test suite's: the same kinds of products and the CMOMS variables. The problems do not.
No evolution question is about what a test question is about (the transport or path of a boundary current, a
marine heatwave, upwelling, a temperature front, hypoxia or an oxygen minimum, a bloom, the spreading of a
water mass, an eddy, carbon exchange, heat content). The evolution questions ask about dynamical balance and
instability, planetary waves, double diffusion, sound propagation, the sunlit layer, statistical prediction,
sampling in time and space, the homogeneity of a record, observing-system design, gap filling, objective
provinces, the habitat of a species and ship routing. The regions differ as well: neither appears in the
test suite.

Why the problems differ: a lesson or a tool is admitted only with support from three different questions.
An earlier version of this suite asked the test suite's own kinds of problems in other regions (six
questions on heatwaves and warm anomalies, five on boundary currents, three on oxygen). A recipe for one
kind of problem could then be learned and used again on the test questions of that kind, and a gain would
not have shown that OceanX had learned anything general. Now no kind of problem appears in more than two
evolution questions, so whatever passes the three-question rule holds across different kinds of problems.
Each `task_info.json` names its kind of problem under `topic`, and a test checks both properties.

| Set | Region | Runs with | Yields |
|---|---|---|---|
| A, E01-E12 | California Current System, 30-48 N, 130-116 W: an eastern-boundary upwelling system | nothing learned (L0) | library L1 |
| B, E13-E24 | Tasman Sea and East Australian Current, 46-26 S, 147-162 E: a western boundary current and an ocean-warming hotspot | L1 | library L2 |

Set B is on other waters and another kind of circulation, so L2 is not learned where L1 was. It shows
three things the first round cannot: whether tasks run with L1 still make the mistakes L1 addresses, which
lessons hold on other problems and in a second region, and which tools are called when they are offered.
The meta-agent retires an L1 lesson that set B contradicts, and a tool that no set B run called leaves the
list.

### Set A: California Current System

| ID | Kind | Kind of problem | Title | Data |
|---|---|---|---|---|
| E01 | checkable | geostrophic balance | How closely the currents follow geostrophic balance | P_CCS_PHY |
| E02 | checkable | statistical prediction | How far ahead sea surface temperature anomalies can be predicted | P_CCS_SURF |
| E03 | checkable | ocean provinces | Biogeochemical provinces and how stable they are | P_CCS_BGC |
| E04 | checkable | habitat envelope | Where and when the water suits a fish with temperature and food limits | P_CCS_SURF, P_CCS_BGC |
| E05 | checkable | temporal sampling | What monthly means hide | P_CCS_SURF |
| E06 | checkable | ocean acoustics | Sound speed and the conditions for sound propagation | P_CCS_PHY |
| E07 | checkable | observing-system design | How many profiling floats it takes to map subsurface oxygen and nitrate | P_CCS_BGC |
| E08 | disagreement | euphotic depth | How deep light reaches, and why estimates from chlorophyll differ | P_CCS_BGC |
| E09 | checkable | baroclinic instability | Where and when the flow is prone to baroclinic instability | P_CCS_PHY |
| E10 | disagreement | mixed layer | Product mixed-layer thickness versus mixed layers computed from profiles | P_CCS_PHY |
| E11 | checkable | record homogeneity | Is the 1993-2020 temperature record homogeneous in time | P_CCS_SURF |
| E12 | checkable | space and time scales | Do biogeochemical anomalies have the same scales as physical ones | P_CCS_PHY, P_CCS_BGC |

### Set B: Tasman Sea and East Australian Current

| ID | Kind | Kind of problem | Title | Data |
|---|---|---|---|---|
| E13 | disagreement | planetary waves | Westward-moving sea-level signals: waves, eddies or something else | P_TAS_PHY |
| E14 | checkable | double diffusion | Where the water column favours salt fingers | P_TAS_PHY |
| E15 | checkable | modes of variability | Leading patterns of sea-level variability and what they mean | P_TAS_PHY |
| E16 | checkable | observing-system design | Where to put a few moorings to monitor the upper ocean | P_TAS_PHY |
| E17 | checkable | mixed layer | Deep winter mixed layers and the water they form | P_TAS_PHY |
| E18 | checkable | ship routing | Routing a ship with and against the currents | P_TAS_PHY |
| E19 | checkable | gap filling | Filling the gaps a satellite would leave | P_TAS_SURF |
| E20 | checkable | habitat envelope | Where a cool-water seaweed that needs nutrients could grow | P_TAS_SURF, P_TAS_BGC |
| E21 | checkable | space and time scales | The smallest scales the temperature field resolves | P_TAS_SURF |
| E22 | checkable | seasonal cycle | How deep the seasons reach | P_TAS_BGC |
| E23 | checkable | record homogeneity | Drift or ocean change in the biogeochemical record | P_TAS_BGC |
| E24 | disagreement | ocean provinces | Do physical and biogeochemical provinces coincide | P_TAS_PHY, P_TAS_BGC |

Each set has ten checkable problems and two disagreement problems, across the physical, surface-temperature
and biogeochemical products. Six kinds of problem appear once in each set, on different waters: ocean
provinces (E03, E24), the habitat of a species (E04, E20), observing-system design (E07, E16), the mixed
layer (E10, E17), the homogeneity of a record (E11, E23) and scales of variability (E12, E21). Round 2 can
therefore show whether L1 helps on a kind of problem it was learned from. The other twelve questions are
each the only one of their kind. Four questions combine two products from different model systems (E04,
E12, E20, E24). E13 touches one hypothesis named in Q20 (planetary waves); its subject is not the Great
Whirl. E10 and E17 are unchanged from the earlier suite.

## What changed in v7

- **The library is lessons and tools.** A snapshot (L1, L2) now freezes the lessons written into the skills
  and the helper functions that analysis code can call. The arms compare the two together.
- **The meta-agent decides.** Lessons and tools take effect when they pass the rules; the owner can mark any
  of them right or wrong, but no approval step is needed. One review runs after each evolution set.
- **The policy is fixed to `v2-nested`.** Arm A (`v0-coordinator-bfs`) is no longer run; the test suite
  runs in three arms: nothing learned, L1 and L2.
- **Three process measures were added:** failed code runs, helper calls and lessons named.
- Native heat and oxygen budget archives are no longer benchmark dependencies. Q05 and Q11-Q13 use
  independent reference calculations on their core fields; missing terms remain unresolved.
- Q11-Q13 mechanism scoring accepts justified unresolved attribution with quantitative tests of
  competing explanations, rather than requiring an exact dominant native-budget term.
- Test queries and all input groups are unchanged. The catalogue version changes to separate evaluations
  under the revised rubric from earlier results.
- **The evolution questions were replaced on 2026-10-02.** Twenty-two of the 24 now ask about kinds of
  problems the test suite does not have; E10 and E17 are unchanged. Every question keeps the data groups it
  had, so the data manifest, the downloads and the coverage report are the same as before.

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
