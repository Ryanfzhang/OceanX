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
  CMOMS/grid/*.nc                               private grid, masks, cell areas, depths, bathymetry
  _evaluator_only/CMOMS_DIA/<var>/<year>/*.nc   private answer-key data; never an agent input
  MODIS_Aqua/chlorophyll/<year>/...             public (test suite)
  NOAA_Blended_Wind/<var>/<year>/...            public (test suite)
  OISST/<var>/<year>/...                        public, East China Sea crop (test suite)
  CMEMS_Gulf/..., CMEMS_ECS/..., ERA5/...       services (test suite)
  CMEMS_CCS_MONTHLY/<var>/<year>/...            services (evolution suite)
  CMEMS_CCS_SURFACE_DAILY/thetao/<year>/...     services (evolution suite)
  CMEMS_CCS_BGC_MONTHLY/<var>/<year>/...        services (evolution suite)
  _download_all/                                plans, reports, coverage.json, data_bindings.json
```

The machine-readable source is `download/data_manifest.json`. Every task file lists its groups, and
`download_all.py` refuses to run if the two disagree.

## Groups

| Group | Phase | Product | Variables | Period | Region | Used by | On the server |
|---|---|---|---|---|---|---|---|
| C_CORE | private | CMOMS model output (owner) | temp, salt, u, v, oxygen, chlorophyll + grid | daily, 2011-2020, full depth | CMOMS domain | Q01-Q08, Q11-Q22 | have; stage as below |
| X_HEAT | private, evaluator-only | CMOMS heat budget (dia file) | temp_rate, temp_hadv, temp_vadv, temp_hdiff, temp_vdiff | 2011-2020, upper 300 m is enough | CMOMS domain | answer keys Q03, Q11, Q12, Q18 | **request** |
| X_OXY | private, evaluator-only, optional | CMOMS oxygen budget (dia file) | oxygen_rate, oxygen_hadv, oxygen_vadv, oxygen_hdiff, oxygen_vdiff | May-Sep 2011-2020 | Pearl River shelf is enough | answer keys Q07, Q13 | optional request |
| P_WIND | public | NOAA blended monthly winds (`noaacwBlendedWindsMonthly`) | windspeed, u_wind, v_wind, mask | 2003-2020 | 104-122 E, 1-25 N | Q04 | 2003-2012 likely present; adds 2013-2020 |
| P_MODIS | public | MODIS-Aqua monthly chlorophyll (ERDDAP `erdMH1chlamday_R2022SQ`) | chlor_a | 2003-2020 | 104-122 E, 1-25 N | Q22 | 2003-2017 likely present; adds 2018-2020 |
| P_GULF | services | GLORYS12 daily `cmems_mod_glo_phy_my_0.083deg_P1D-m`, version 202311 | thetao, so, zos | 2011-2017, 0-2000 m | 98-80 W, 18-31 N | Q09, Q23-Q26 | present, unchanged |
| P_OISST | public | NOAA OISST v2.1 daily (NCEI originals, cropped) | sst, ice | 1982-2023 | 120-128 E, 25-34 N | Q10, Q27, Q30 | present, unchanged |
| P_ECS | services | GLORYS12 daily, version 202311 | thetao, uo, vo | May-Nov of 1993-2011 and 2023, full depth | 119-129 E, 24-35 N | Q10, Q28, Q29 | present, unchanged |
| P_ERA5 | services | ERA5 hourly surface fluxes (Google ARCO mirror) | ssr, str, sshf, slhf | May-Nov of 1993-2011 and 2023 | 119-129 E, 24-35 N | Q10 | present, unchanged |
| P_CCS_PHY | services | GLORYS12 monthly `cmems_mod_glo_phy_my_0.083deg_P1M-m`, version 202311 | thetao, so, uo, vo, zos, mlotst | 2011-2020, 0-1000 m | 130-116 W, 30-48 N | E01, E06, E09, E10, E12 | new |
| P_CCS_SURF | services | GLORYS12 daily, top level only (0.5 m), version 202311 | thetao | 1993-2020 | 130-116 W, 30-48 N | E02, E04, E05, E11 | new |
| P_CCS_BGC | services | CMEMS global biogeochemical reanalysis monthly `cmems_mod_glo_bgc_my_0.25deg_P1M-m`, version 202406 | o2, chl, no3 | 1993-2020, 0-1000 m | 130-116 W, 30-48 N | E03, E04, E07, E08, E12 | new |

All dataset IDs, versions and variable names were checked against the providers' catalogues on
2026-10-01. The NOAA MODIS server could not be reached from the planning machine, so the first download run
checks the extension to 2020. The downloader stops if any requested month is missing.

The four "present, unchanged" groups have the same definitions as in the 2026-09 catalogue, so their
verified files are reused without any new transfer.

New transfer, roughly:
- **MODIS (36 months) and winds (96 months):** well under 1 GB.
- **P_CCS_PHY:** about 1-1.5 GB on disk (720 monthly requests).
- **P_CCS_SURF:** about 0.7 GB (336 requests).
- **P_CCS_BGC:** about 0.4 GB (1,008 small requests).

## Staging CMOMS (owner)

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
   - the model domain (which straits are inside it).
4. **The queries say "daily".** If the files are not daily means, stop and tell the owner before any run.
5. Restrict permissions to the benchmark user: `chmod -R go-rwx $DATA_ROOT/CMOMS $DATA_ROOT/_evaluator_only`.

The OceanX sandbox only lets an agent read the folders bound to its question, so it never sees
`_evaluator_only`. Query preparation also refuses any path containing `_evaluator_only`, `evaluator` or
`rubric.json`.

## Requesting extra CMOMS variables

The variable lists in `avg_info.cdl` (32 variables) and `dia_info.cdl` (174 terms) offer much more. The
request is kept to one budget, plus one optional:

| Priority | Variables (dia file) | Why | If not granted |
|---|---|---|---|
| Required | `temp_rate, temp_hadv, temp_vadv, temp_hdiff, temp_vdiff` | The closed heat budget is the hidden answer key for the mechanism parts of Q11 (subsurface heatwaves), Q12 (Hainan upwelling) and Q18 (2015-2016 El Nino). It also checks the cold-advection finding of Q03. The agent never sees it: it gets temperature and velocity and must infer the mechanism. | The evaluator computes the advective terms from velocity and temperature and takes the rest as a residual. The answer key is weaker, but the questions stay. |
| Optional | `oxygen_rate, oxygen_hadv, oxygen_vadv, oxygen_hdiff, oxygen_vdiff`, May-September, Pearl River shelf only | Answer key for Q13 (biological versus physical control of hypoxia; the biological term is the residual) and a check of the mixing finding in Q07 | Q07 and Q13 use their reference diagnostics (already in the rubrics). |

The request uses the same grid, depth layout and sampling as the core archive. If size is a concern, the
heat budget can be limited to the upper 300 m, because every answer key uses the upper ocean (0-50 m to
0-300 m).

Not requested: nutrients, plankton, carbon, momentum terms and mixing coefficients. No test question needs
them.

## Commands (repository root, `oceanx-bench` environment)

```bash
python benchmarking/download/download_all.py public   --output "$DATA_ROOT"            # preview, no network
python -u benchmarking/download/download_all.py public   --output "$DATA_ROOT" --execute
python -u benchmarking/download/download_all.py services --output "$DATA_ROOT" --execute --workers 2
python benchmarking/download/download_all.py private  --output "$DATA_ROOT"            # checks CMOMS staging
python benchmarking/download/download_all.py verify   --output "$DATA_ROOT"            # re-hash every download
```

- **Accounts:** `services` needs `copernicusmarine login` once. ERA5 uses the anonymous Google mirror.
- **Running together:** `public` and `services` can run at the same time in two terminals. A re-run skips
  verified files.
- **The private phase:** checks that every variable and year folder holds a readable NetCDF file naming that
  variable. X_OXY may be missing (it is optional); C_CORE and X_HEAT may not.
- **The coverage report:** `$DATA_ROOT/_download_all/coverage.json` lists, per task, missing agent inputs
  and missing answer-key data.

Privacy: CMOMS data, and everything computed from them, stay on the server. That covers references,
answer keys, figures and scores. They are never committed and never sent to an outside service.
