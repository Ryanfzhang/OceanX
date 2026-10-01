# OceanX benchmark: design

Catalogue `2026-10-01-v3`. Two suites:

- **Test suite, Q01-Q30.** Scored. 10 paper reproductions and 20 open problems. South China Sea questions
  use the private CMOMS model output. Open problems also cover the Gulf of Mexico and the East China Sea
  with public data. Every scored measurement comes from this suite.
- **Evolution suite, E01-E12.** Never scored. California Current System, public reanalyses only. OceanX
  learns lessons from these runs.

Everything runs on the Linux server, never on macOS.

## Goals

1. Measure how well OceanX does two kinds of research work:
   - reproducing published findings with new data;
   - investigating typical open problems in physical and biogeochemical oceanography.
2. Measure whether the research-policy choice and self-improvement (lessons learned from earlier runs) help
   on questions OceanX has never seen.

## Design rules

| Rule | How the catalogue follows it |
|---|---|
| Two question types only | 10 paper reproductions and 20 open problems. There are no basic calculation or visualisation tasks. |
| South China Sea questions use CMOMS | All 20 South China Sea questions use CMOMS (temperature, salinity, velocity, oxygen, chlorophyll; daily, 2011-2020, full depth). 18 use nothing else. |
| Centred on the CMOMS variables | Every question is about temperature, salinity, currents, oxygen or chlorophyll. Oxygen: Q07, Q13, Q17. Chlorophyll: Q04, Q08, Q14, Q22, with Q07 and Q13 using it as a proxy. The public questions use the same physical variables (temperature, salinity, currents, sea level). |
| Typical problems, several regions | The open problems are standard research problems: marine heatwaves, coastal upwelling, hypoxia, blooms, plumes, boundary-current intrusion, deep ventilation, water-mass transformation, eddy shedding, ocean heat content, fronts. 12 are in the South China Sea, 4 in the Gulf of Mexico and 4 in the East China Sea. |
| Few multi-dataset questions | Only 3 of 30 combine products: Q04 (CMOMS and winds), Q10 (OISST, GLORYS12 and ERA5) and Q22 (CMOMS and MODIS). |
| Download as little as possible | The test suite uses only data already on the server: the Gulf of Mexico, East China Sea, ERA5, OISST, MODIS and monthly wind groups from the 2026-09 catalogue. MODIS and the winds are extended to 2020. The evolution suite adds one coarse-resolution region (about 2-3 GB on disk). |
| Paper reproduction needs real papers | 10 papers were checked against Crossref (title, authors, volume, pages, DOI) and their abstracts on 2026-10-01. The findings in each query paraphrase the abstract. |
| Different rubrics for the two types | Paper reproduction scores whether each finding of the paper was actually verified. Open problems are scored more broadly and deeply, on seven dimensions, against a hidden answer key (see "Rubrics"). |
| No evaluator material reaches the agent | Rubrics live in `tasks/<task>/evaluator/`. Answer-key data lives under `_evaluator_only/` on the server. Query preparation refuses both. |
| No evolution while benchmarking | Each attempt starts from empty OceanX state. An arm fixes the research policy and an optional frozen lesson set, and every attempt verifies its lessons were unchanged. |
| Evolution data are disjoint from test data | The evolution suite uses another region (the California Current System), the same kinds of questions and the same kinds of public products. CMOMS never appears in evolution. CMOMS questions therefore measure transfer to data OceanX has never seen. |

## Allocation (30 test questions)

| Type | IDs | Count | Regions | What is scored |
|---|---|---|---|---|
| Paper reproduction | Q01-Q10 | 10 | 8 South China Sea, 1 Gulf of Mexico, 1 East China Sea | Whether each finding listed in the query was verified with the supplied data |
| Open problem, checkable | Q11-Q14, Q16-Q18, Q20, Q21, Q24-Q26, Q28, Q30 | 14 | 9 South China Sea, 3 Gulf, 2 East China Sea | The answer against a hidden answer key; depth, robustness, breadth and insight |
| Open problem, disagreement | Q15, Q19, Q22, Q23, Q27, Q29 | 6 | 3 South China Sea, 1 Gulf, 2 East China Sea | Diagnosing why estimates disagree: between published studies, methods, or two datasets |

Data access:
- **CMOMS only:** 18 questions.
- **CMOMS plus a public product:** 2 questions.
- **Public data only:** 10 questions.

Six pairs put the same kind of problem on private and on public data. Published analyses of the public data
exist, and a model may have memorised them. None exist for this CMOMS archive.

| Problem | Private (CMOMS) | Public |
|---|---|---|
| Eddy statistics and structure (papers) | Q05 | Q09 |
| Marine heatwaves (papers) | Q06 | Q10 |
| Marine heatwaves (open) | Q11 | Q27 |
| Coastal upwelling | Q12 | Q29 |
| Kuroshio intrusion | Q15 | Q28 |
| Erosion of a subsurface salinity maximum | Q21 | Q24 |

## Test suite

| ID | Region | Kind | Title | Agent data | Paper or answer key |
|---|---|---|---|---|---|
| Q01 | SCS | paper | Layered rotating circulation and its vorticity hotspots | C_CORE | Gan et al. (2022) |
| Q02 | SCS | paper | The South China Sea throughflow as a heat and freshwater conveyor | C_CORE | Qu et al. (2006) |
| Q03 | SCS | paper | The winter cold tongue and slope current off southern Vietnam | C_CORE | Liu et al. (2004) |
| Q04 | SCS | paper | Summer upwelling, wind jet and cold filament off southern Vietnam | C_CORE, P_WIND | Xie et al. (2003) |
| Q05 | SCS | paper | Mesoscale eddy statistics and their thermohaline imprint | C_CORE | Chen et al. (2011) |
| Q06 | SCS | paper | Summer marine heatwaves in the South China Sea | C_CORE | Yao and Wang (2021) |
| Q07 | SCS | paper | Synoptic wind-driven control of hypoxia off the Pearl River Estuary | C_CORE | Li et al. (2021) |
| Q08 | SCS | paper | Eddy modulation of the subsurface chlorophyll maximum | C_CORE | Xu et al. (2023) |
| Q09 | GULF | paper | Vertical structure of a Loop Current eddy | P_GULF | Meunier et al. (2018) |
| Q10 | ECS | paper | The late-arriving 2023 East China Sea marine heatwave | P_OISST, P_ECS, P_ERA5 | Oh et al. (2024) |
| Q11 | SCS | checkable | Subsurface marine heatwaves | C_CORE | hidden CMOMS budget (X_HEAT) + reference diagnostics |
| Q12 | SCS | checkable | Year-to-year control of the upwelling off eastern Hainan | C_CORE | hidden CMOMS budget (X_HEAT) + reference diagnostics |
| Q13 | SCS | checkable | Year-to-year control of hypoxia off the Pearl River Estuary | C_CORE | hidden CMOMS budget (X_OXY) + reference diagnostics |
| Q14 | SCS | checkable | What controls the winter bloom northwest of Luzon | C_CORE | reference diagnostics |
| Q15 | SCS | disagreement | Why estimates of the Luzon Strait transport and Kuroshio intrusion differ | C_CORE | reference diagnostics; candidate causes with tests |
| Q16 | SCS | checkable | Year-to-year extent and spreading of the Pearl River plume | C_CORE | reference diagnostics |
| Q17 | SCS | checkable | Ventilation of the deep South China Sea | C_CORE | reference diagnostics |
| Q18 | SCS | checkable | Imprint of the 2015-2016 El Nino on South China Sea heat content | C_CORE | hidden CMOMS budget (X_HEAT) + reference diagnostics |
| Q19 | SCS | disagreement | Does the winter South China Sea Warm Current exist, and what drives it | C_CORE | reference diagnostics; candidate causes with tests |
| Q20 | SCS | checkable | Summer circulation and bottom cold water of the Beibu Gulf | C_CORE | reference diagnostics |
| Q21 | SCS | checkable | Erosion of the North Pacific Tropical Water salinity maximum | C_CORE | reference diagnostics |
| Q22 | SCS | disagreement | Why CMOMS and MODIS surface chlorophyll disagree | C_CORE, P_MODIS | reference diagnostics; candidate causes with tests |
| Q23 | GULF | disagreement | How often the Loop Current sheds eddies, and why estimates differ | P_GULF | reference diagnostics; candidate causes with tests |
| Q24 | GULF | checkable | Loss of the salinity maximum in Loop Current eddies | P_GULF | reference diagnostics |
| Q25 | GULF | checkable | Ocean heat available to hurricanes and the Loop Current's share | P_GULF | reference diagnostics |
| Q26 | GULF | checkable | What sea surface height reveals about the subsurface | P_GULF | reference diagnostics |
| Q27 | ECS | disagreement | Are East China Sea marine heatwaves increasing, and how the baseline changes the answer | P_OISST | reference diagnostics; candidate causes with tests |
| Q28 | ECS | checkable | Kuroshio intrusion onto the East China Sea shelf | P_ECS | reference diagnostics |
| Q29 | ECS | disagreement | What drives the summer upwelling off Zhejiang and Fujian | P_ECS | reference diagnostics; candidate causes with tests |
| Q30 | ECS | checkable | Changes in East China Sea temperature fronts | P_OISST | reference diagnostics |

- **Where things live:** the query text, paper, region, period and data groups are in
  `tasks/<task>/task_info.json`. The rubric (criteria, findings, answer key, probes, candidate causes and
  gates) is in `tasks/<task>/evaluator/rubric.json`.
- **X_HEAT for Q03:** it also checks the paper's cold-advection claim.
- **X_OXY:** it is optional. Without it, Q07 and Q13 use their reference diagnostics.

### Papers (verified 2026-10-01)

| Task | Paper | DOI |
|---|---|---|
| Q01 | Gan et al. (2022), Hotspots of the stokes rotating circulation in a large marginal sea, Nature Communications 13, 2223 | 10.1038/s41467-022-29610-z |
| Q02 | Qu et al. (2006), South China Sea throughflow: A heat and freshwater conveyor, Geophysical Research Letters 33 | 10.1029/2006GL028350 |
| Q03 | Liu et al. (2004), A gap in the Indo-Pacific warm pool over the South China Sea in boreal winter, JGR Oceans 109 | 10.1029/2003JC002179 |
| Q04 | Xie et al. (2003), Summer upwelling in the South China Sea and its role in regional climate variations, JGR Oceans 108 | 10.1029/2003JC001867 |
| Q05 | Chen et al. (2011), Mesoscale eddies in the South China Sea: Mean properties, spatiotemporal variability, and impact on thermohaline structure, JGR 116, C06018 | 10.1029/2010JC006716 |
| Q06 | Yao and Wang (2021), Variations in Summer Marine Heatwaves in the South China Sea, JGR Oceans 126 | 10.1029/2021JC017792 |
| Q07 | Li et al. (2021), Spatiotemporal Development and Dissipation of Hypoxia Induced by Variable Wind-Driven Shelf Circulation off the Pearl River Estuary, JGR Oceans 126 | 10.1029/2020JC016700 |
| Q08 | Xu et al. (2023), Mesoscale Eddy Modulation of Subsurface Chlorophyll Maximum Layers in the South China Sea, JGR Biogeosciences 128 | 10.1029/2023JG007648 |
| Q09 | Meunier et al. (2018), The Vertical Structure of a Loop Current Eddy, JGR Oceans 123, 6070-6090 | 10.1029/2018JC013801 |
| Q10 | Oh et al. (2024), Late-arriving 2023 summer marine heatwave in the East China Sea and implications for global warming, npj Climate and Atmospheric Science 7, 294 | 10.1038/s41612-024-00846-4 |

Every paper used different data, a different period, or both. The query lists the paper's findings. The
agent tests each one in the supplied data, says whether it was reproduced, partly reproduced, not
reproduced, or cannot be tested, and explains the differences. Agreeing with the paper does not earn marks.
Agreeing with what the supplied data show does.

Three rubrics also cite verified literature for judging the agent's comparison with published work:
- Nan et al. (2015) for Q15;
- Sosa-Gutiérrez et al. (2020) for Q24;
- Hamilton et al. (2018) for Q26.

## Rubrics: two designs

Both types score each criterion 0-4. The total is `sum(weight * score / 4)` out of 100. Codex judges both
(`evaluation/CODEX_JUDGE.md`).

### Paper reproduction: was each finding verified?

| Criterion | Weight | What earns a 4 |
|---|---|---|
| One criterion per finding (`K1`...`K5`) | 70 in total, by importance | The finding is tested appropriately and completely. The result is compared quantitatively with the paper's statement. The verdict agrees with the evaluator's frozen reference within tolerance, and any mismatch with the paper is traced to a stated cause. |
| Method fidelity (`M`) | 10 | The paper's key definitions and methods (listed in the rubric) are reproduced, or each adaptation is justified with parameters. |
| Differences from the paper's setting (`D`) | 10 | Each material difference (data, period, resolution, model versus observations) is linked to the findings it could affect, and at least one is tested. |
| Verification report (`R`) | 10 | A table per finding (paper statement, reproduced value, verdict, evidence), comparable figures, traceable numbers. |

Each finding in the rubric carries:
- the paper's evidence (an abstract quote);
- its **testability**;
- how the evaluator tests it;
- the expected result in the supplied data, computed and frozen before judging;
- the tolerance.

Testability has three levels:
- **Testable.** The finding can be checked with the supplied data.
- **Partly testable.** For example, the wind part of a mechanism cannot be tested without winds. A 4
  requires testing every testable part and saying plainly which part cannot be tested.
- **Not testable.** For example, Yao and Wang's 1982-2020 trend, or Oh et al.'s CMIP6 projections. A 4
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
- **Q11, Q12 and Q18:** the closed CMOMS heat budget (X_HEAT).
- **Q13:** the CMOMS oxygen budget (X_OXY, optional).
- **Every open problem:** reference diagnostics that the evaluator computes on the same inputs.

The answer-key values are filled in and frozen before any test run is judged.

For the six disagreement questions, `Q` becomes "disagreement quantified" and `M` becomes "causes diagnosed
with targeted tests". Each of these questions lists at least three candidate causes, each with the test
that could confirm or reject it.

Gates apply to both types:
- untraceable numbers or citations count as unsupported;
- copying the paper's values as results scores 0 on that finding;
- answering a different question caps the answer and mechanism criteria;
- an answer without executed analysis scores almost nothing.

## Evolution suite (never scored)

California Current System, 30-48 N, 130-116 W. Public products only:
- **P_CCS_PHY:** GLORYS12 monthly temperature, salinity, velocity, sea surface height and mixed-layer
  thickness, 2011-2020, 0-1000 m;
- **P_CCS_SURF:** GLORYS12 daily near-surface temperature, 1993-2020;
- **P_CCS_BGC:** CMEMS global biogeochemical reanalysis monthly oxygen, chlorophyll and nitrate, 1993-2020,
  0-1000 m.

The variable set mirrors CMOMS, so lessons about temperature, currents, oxygen and chlorophyll can transfer.
The region does not.

| ID | Kind | Title | Data |
|---|---|---|---|
| E01 | Zaba and Rudnick (2016) | The 2014-2015 warming of the Southern California Current System | P_CCS_PHY |
| E02 | Gentemann et al. (2017) | Coastal temperatures during the 2014-2016 northeast Pacific heatwave | P_CCS_SURF |
| E03 | Bograd et al. (2008) | Oxygen decline and the shoaling hypoxic boundary | P_CCS_BGC |
| E04 | Jacox et al. (2016) | Impacts of the 2015-2016 El Nino on the California Current System | P_CCS_SURF, P_CCS_BGC |
| E05 | checkable | Timing of the spring transition to upwelling | P_CCS_SURF |
| E06 | checkable | The California Undercurrent | P_CCS_PHY |
| E07 | checkable | Depth of the hypoxic boundary on the slope | P_CCS_BGC |
| E08 | checkable | Timing and size of the upwelling-season chlorophyll maximum | P_CCS_BGC |
| E09 | checkable | Local or advected: subsurface anomalies of 2014-2016 | P_CCS_PHY |
| E10 | disagreement | Product mixed-layer thickness versus mixed layers computed from profiles | P_CCS_PHY |
| E11 | checkable | Coastal versus offshore marine heatwaves | P_CCS_SURF |
| E12 | disagreement | When temperature stops predicting nitrate | P_CCS_PHY, P_CCS_BGC |

The four evolution papers were checked against Crossref and their abstracts like the test papers. As in
the test suite, each evolution paper question lists findings to verify and needs a verdict on each.

## What changed from the v2 draft

- The six basic calculation tasks are gone, and so are the "basic" types in both suites.
- Ten paper reproductions:
  - eight South China Sea papers, each tested with CMOMS alone except Xie et al. (2003);
  - Meunier et al. (2018) for the Gulf of Mexico;
  - Oh et al. (2024) for the East China Sea.

  Gan et al. (2006) and Palacz et al. (2011) were dropped. Gan (2006) overlapped Gan (2022) and Liu (2004).
  Palacz (2011) needed 1997-2010 satellite data.
- Twenty open problems instead of fourteen, in three regions. Only three questions combine datasets
  (24 did in the v2 draft).
- The Gulf of Mexico and East China Sea questions moved from the evolution suite into the test suite, with
  their existing data. The evolution suite moved to the California Current.
- Five public groups planned for v2 are no longer needed and were never downloaded:
  - South China Sea OISST, altimetry and monthly GLORYS12;
  - daily Pearl River winds;
  - the ENSO index.
- The two question types have separate rubric designs.
