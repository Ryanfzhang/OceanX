# Data plan (Linux server)

All data live on the server under one data root. Nothing is copied into the repository, and nothing is
downloaded on a laptop.

```text
DATA_ROOT=/import/home4/share/mafzhang          # the existing download root
RUNS_ROOT=$HOME/oceanx-bench/runs               # agent runs, never inside DATA_ROOT
EVAL_ROOT=$HOME/oceanx-bench/eval               # rubrics, references, scores; private
```

```text
$DATA_ROOT/
  CMOMS/<var>/<year>/*.nc                       private, staged by the owner (test suite, South China Sea)
  CMOMS_DIA/<var>/<year>/*.nc                 requested agent-visible production/carbon diagnostics
  CMOMS/grid/*.nc                               private grid, masks, cell areas, depths, bathymetry
  MODIS_Aqua/chlorophyll/<year>/...             public (test suite)
  OISST/<var>/<year>/...                        public, East China Sea crop (test suite)
  CMEMS_Gulf/..., CMEMS_ECS/..., ERA5/...       services (test suite)
  CMEMS_ARABIAN_MONTHLY/<var>/<year>/...        services (test suite)
  CMEMS_ARABIAN_BGC_MONTHLY/<var>/<year>/...    services (test suite)
  CMEMS_CCS_MONTHLY/<var>/<year>/...            services (evolution set A)
  CMEMS_CCS_SURFACE_DAILY/thetao/<year>/...     services (evolution set A)
  CMEMS_CCS_BGC_MONTHLY/<var>/<year>/...        services (evolution set A)
  CMEMS_TASMAN_MONTHLY/<var>/<year>/...         services (evolution set B)
  CMEMS_TASMAN_SURFACE_DAILY/thetao/<year>/...  services (evolution set B)
  CMEMS_TASMAN_BGC_MONTHLY/<var>/<year>/...     services (evolution set B)
  _download_all/                                plans, reports, coverage.json, data_bindings.json
```

The machine-readable source is `download/data_manifest.json`. Every task file lists its groups, and
`download_all.py` refuses to run if the two disagree.

## Groups

| Group | Phase | Product | Variables | Period | Region | Used by | On the server |
|---|---|---|---|---|---|---|---|
| C_CORE | private | CMOMS model output (owner) | temp, salt, u, v, oxygen, chlorophyll + grid | daily, 2011-2020, full depth | CMOMS domain | Q01-Q06, Q11-Q14, Q16, Q17, Q22 | have; stage as below |
| C_PRODUCTION | private, agent-visible | CMOMS primary-production diagnostics (dia file) | P_Production, NO3_uptake | 2011-2020; native interval averages, daily requested; 0-100 m | 116-120 E, 16-20 N, wet cells northwest of Luzon | Q14 | **request; not yet staged** |
| C_CARBON | private, agent-visible | CMOMS surface air-sea carbon diagnostics (dia file) | CO2_airsea, pCO2 | 2011-2020; native interval averages, daily requested; surface | 112-116 E, 20-23 N; Q16 uses wet shelf cells with depth <=200 m | Q16 | **request; not yet staged** |
| P_MODIS | public | MODIS-Aqua monthly chlorophyll (ERDDAP `erdMH1chlamday_R2022SQ`) | chlor_a | 2003-2020 | 104-122 E, 1-25 N | Q22 | 2003-2017 likely present; adds 2018-2020 |
| P_GULF | services | GLORYS12 daily `cmems_mod_glo_phy_my_0.083deg_P1D-m`, version 202311 | thetao, so, zos | 2011-2017, 0-2000 m | 98-80 W, 18-31 N | Q07-Q09, Q23-Q26 | present, unchanged |
| P_OISST | public | NOAA OISST v2.1 daily (NCEI originals, cropped) | sst, ice | 1982-2023 | 120-128 E, 25-34 N | Q10, Q27, Q30 | present, unchanged |
| P_ECS | services | GLORYS12 daily, version 202311 | thetao, uo, vo | May-Nov of 1993-2011 and 2023, full depth | 119-129 E, 24-35 N | Q10, Q28, Q29 | present, unchanged |
| P_ERA5 | services | ERA5 hourly surface fluxes (Google ARCO mirror) | ssr, str, sshf, slhf | May-Nov of 1993-2011 and 2023 | 119-129 E, 24-35 N | Q10 | present, unchanged |
| P_ARAB_PHY | services | GLORYS12 monthly `cmems_mod_glo_phy_my_0.083deg_P1M-m`, version 202311 | thetao, so, uo, vo, zos, mlotst | 2011-2020, 0-1000 m | 47-70 E, 4-26 N | Q15, Q19, Q20, Q21 | new |
| P_ARAB_BGC | services | CMEMS global biogeochemical reanalysis monthly `cmems_mod_glo_bgc_my_0.25deg_P1M-m`, version 202406 | o2, chl, no3 | 2011-2020, 0-1000 m | 47-70 E, 4-26 N | Q18, Q19 | new |
| P_CCS_PHY | services | GLORYS12 monthly `cmems_mod_glo_phy_my_0.083deg_P1M-m`, version 202311 | thetao, so, uo, vo, zos, mlotst | 2011-2020, 0-1000 m | 130-116 W, 30-48 N | E01, E06, E09, E10, E12 | new |
| P_CCS_SURF | services | GLORYS12 daily, top level only (0.5 m), version 202311 | thetao | 1993-2020 | 130-116 W, 30-48 N | E02, E04, E05, E11 | new |
| P_CCS_BGC | services | CMEMS global biogeochemical reanalysis monthly `cmems_mod_glo_bgc_my_0.25deg_P1M-m`, version 202406 | o2, chl, no3 | 1993-2020, 0-1000 m | 130-116 W, 30-48 N | E03, E04, E07, E08, E12 | new |
| P_TAS_PHY | services | GLORYS12 monthly `cmems_mod_glo_phy_my_0.083deg_P1M-m`, version 202311 | thetao, so, uo, vo, zos, mlotst | 2011-2020, 0-1000 m | 147-162 E, 46-26 S | E13-E18, E24 | new |
| P_TAS_SURF | services | GLORYS12 daily, top level only (0.5 m), version 202311 | thetao | 1993-2020 | 147-162 E, 46-26 S | E19, E20, E21 | new |
| P_TAS_BGC | services | CMEMS global biogeochemical reanalysis monthly `cmems_mod_glo_bgc_my_0.25deg_P1M-m`, version 202406 | o2, chl, no3 | 1993-2020, 0-1000 m | 147-162 E, 46-26 S | E20, E22, E23, E24 | new |

All dataset IDs, versions and variable names were checked against the providers' catalogues on
2026-10-01. The three Tasman Sea groups request the same datasets, versions and variables as the
California Current groups, for another box of these global products. The NOAA MODIS server could not be reached from the planning machine, so the first download run
checks the extension to 2020. The downloader stops if any requested month is missing.

The new diagnostic groups are owner-staged requests, not public downloads or data already on the server.
Their boxes are requested analysis footprints; check them against the actual CMOMS wet grid. Preserve
native masks, layer thicknesses and time bounds. The supplied CDL gives variable names and units, but
does not establish the available years or averaging frequency.

The four "present, unchanged" groups have the same definitions as in the 2026-09 catalogue, so their
verified files are reused without any new transfer.

The monthly wind group of earlier catalogues (`NOAA_Blended_Wind/`) is no longer used. Files already on the
server can stay; no question binds them.

New transfer, roughly:
- **MODIS (36 months):** well under 1 GB.
- **P_ARAB_PHY:** about 1.5-2 GB on disk (720 monthly requests).
- **P_ARAB_BGC:** about 0.3 GB (360 small requests).
- **P_CCS_PHY:** about 1-1.5 GB on disk (720 monthly requests).
- **P_CCS_SURF:** about 0.7 GB (336 requests).
- **P_CCS_BGC:** about 0.4 GB (1,008 small requests).
- **P_TAS_PHY:** about 1.2-1.8 GB on disk (720 monthly requests). The box has 1.2 times the cells of the
  California Current box.
- **P_TAS_SURF:** about 0.8 GB (336 requests).
- **P_TAS_BGC:** about 0.5 GB (1,008 small requests).

The Tasman Sea sizes are scaled from the California Current estimates by the number of grid cells. Neither
set has been downloaded yet, so the first transfer checks them.

## Staging CMOMS (owner)

For the owner's existing flat annual archive at `/import/home4/share/PRE_wavyocean`,
see [SERVER_DATA.md](SERVER_DATA.md#original-cmoms-do-not-copy-the-entire-2011-2022-archive).
It describes no-copy hard-link staging, the shared-inode caveat, and missing grid metadata.
Current completion reports are also summarized there; the acquisition notes below describe the plan,
not a live download status. All public groups now report complete (2026-10-02).

1. One folder per variable and year: `$DATA_ROOT/CMOMS/<variable>/<year>/*.nc`. The NetCDF variable must
   have the folder's name (`temp`, `salt`, `u`, `v`, `oxygen`, `chlorophyll`). Years 2011-2020.
2. `$DATA_ROOT/CMOMS/grid/` holds the static files:
   - longitude and latitude;
   - depth levels (positive down);
   - wet masks and cell areas;
   - bathymetry;
   - the grid angle, if the grid is curvilinear.
3. Add `$DATA_ROOT/CMOMS/grid/README.md` with the conventions the agents need. Agents read only what you
   supply:
   - units: temp is potential temperature in C, oxygen in mmol/m3, chlorophyll in mg/m3;
   - the salinity scale;
   - whether u and v are east/north components and how they are collocated;
   - time stamps and sampling (daily means?);
   - fill values;
   - the model domain (which straits are inside it);
   - the atmospheric forcing product, because Q05 and Q06 depend on whether it contains the typhoons.
4. **The queries say "daily".** If the files are not daily means, stop and tell the owner before any run.
5. Restrict permissions to the benchmark user: `chmod -R go-rwx $DATA_ROOT/CMOMS`; apply the same restriction to staged CMOMS_DIA and EVAL_ROOT.

The OceanX sandbox only lets an agent read the folders bound to its question, so it never sees
`_evaluator_only`. Query preparation also refuses any path containing `_evaluator_only`, `evaluator` or
`rubric.json`.

## Requesting extra CMOMS variables

The variable lists in `avg_info.cdl` (32 variables) and `dia_info.cdl` (174 terms) offer much more. The
agent-visible request adds two small regional groups for 2011-2020. Native heat and oxygen budget
archives are not requested; Q05 and Q11-Q13 use independent reference diagnostics from their core inputs:

| Priority | Variables (dia file) | Why | If not granted |
|---|---|---|---|
| Required for Q14 | `P_Production, NO3_uptake` | Winter chlorophyll versus measured primary production and nitrate uptake, northwest of Luzon (116-120 E, 16-20 N), upper 100 m; retain all months to evaluate seasonality | Do not run Q14 until both fields are staged and their sampling is documented. |
| Required for Q16 | `CO2_airsea, pCO2` | Seasonal and annual source/sink exchange on the Pearl River adjacent shelf (112-116 E, 20-23 N); surface fields only | Do not run Q16 until both fields, sign conventions and sampling are documented. |

The requests use the same grid, depth layout and sampling as the core archive. For Q05 and Q11-Q13,
freeze independent event, transport, stratification and association diagnostics before judging. These
references do not establish a closed heat or oxygen budget. A residual is unresolved; oxygen decline
is not measured respiration, and ocean currents alone do not establish wind forcing. Keep the
reference calculations private under EVAL_ROOT even though they use the same core inputs as the agent.

For the two new groups, stage each field as `$DATA_ROOT/CMOMS_DIA/<variable>/<year>/*.nc` for every
year 2011-2020. Include a provider-conventions file with each bound variable folder: units, the meaning
and direction of positive `CO2_airsea`, the definition of `pCO2`, averaging intervals, time bounds,
coordinates, masks and vertical geometry. The supplied CDL labels `P_Production` and `NO3_uptake` in
mmol N m-3 day-1, `CO2_airsea` in mmol C m-2 day-1, and `pCO2` in atm; verify the actual files and
convert explicitly. A volumetric production rate requires depth integration; a surface flux does not.

Daily diagnostic averages are requested. If the provider supplies another frequency, document it before
freezing references and align core fields to those intervals. Do not invent daily values by upsampling,
interpret uptake/production as an observed export fraction, or claim a closed carbon budget from these
four fields. Neither group is evaluator-only; independent reference calculations remain private.

Not requested in this step: nutrient concentrations, complete plankton or carbon budgets, momentum terms
and mixing coefficients. The extra-variable request is limited to these four fields on the two boxes.

## Commands (repository root, `oceanx-bench` environment)

```bash
python benchmarking/download/download_all.py public   --output "$DATA_ROOT"            # preview, no network
python -u benchmarking/download/download_all.py public   --output "$DATA_ROOT" --execute
python -u benchmarking/download/download_all.py services --output "$DATA_ROOT" --execute --workers 2
python benchmarking/download/download_all.py private  --output "$DATA_ROOT"            # checks CMOMS staging
python benchmarking/download/download_all.py verify   --output "$DATA_ROOT"            # re-hash every download
```

To download one part only, name its groups. The two evolution sets:

```bash
python -u benchmarking/download/download_all.py services --output "$DATA_ROOT" --execute --workers 2 \
  --groups P_CCS_PHY P_CCS_SURF P_CCS_BGC                                              # set A, California Current
python -u benchmarking/download/download_all.py services --output "$DATA_ROOT" --execute --workers 2 \
  --groups P_TAS_PHY P_TAS_SURF P_TAS_BGC                                              # set B, Tasman Sea
```

Without `--execute` the same command prints the fixed scope of those groups and touches no network.

- **Accounts:** `services` needs `copernicusmarine login` once. ERA5 uses the anonymous Google mirror.
- **Running together:** `public` and `services` can run at the same time in two terminals. A re-run skips
  verified files.
- **The private phase:** checks that every variable and year folder holds a readable NetCDF file naming that
  variable. C_CORE, C_PRODUCTION and C_CARBON must be staged for the tasks that bind them.
- **The coverage report:** `$DATA_ROOT/_download_all/coverage.json` lists, per task, missing agent inputs
  and missing answer-key data.

Privacy: CMOMS data, and everything computed from them, stay on the server. That covers references,
answer keys, figures and scores. They are never committed and never sent to an outside service.
