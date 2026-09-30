# Mechanisms of Seasonal Warm Anomalies in the Bay of Campeche — Final Report

**Dataset:** GLORYS12 (CMEMS) daily reanalysis, 2025-04-01 to 2026-03-31, 0.25° grid, 50 z-levels (T, S, u, v, chlorophyll, oxygen). All results below are computed from this one year; the full runnable analysis is in `analysis.ipynb`, with reusable code in `code/`, derived data in `outputs/`, and 9 final figures in `figures/`.

## 1. The anomaly: what the data show

The BoC SST cycle spans 24.1 °C (Feb) to 30.7 °C (Sep). Relative to the annual mean (27.7 °C), the warm anomaly reaches **+2.7 to +3.0 °C in Aug–Sep** over the whole bay (not a coastal fringe), while winter is only −2.4 to −3.6 °C (`fig03_sst_anomaly_maps.png`). The 0–100 m heat content anomaly tracks it (max +96 K·m in Sep). The anomaly peaks exactly when the mixed layer is shallowest (~22 m) and mesoscale energy is at its annual minimum (EKE 3.6–3.9×10⁻³ m²/s²).

## 2. Closed heat budget (0–100 m box, 18.5–22.5°N, 97.5–90.5°W)

TEND = HADV + VADV + RES, with VADV = −w(100)·T(100), RES = surface flux + vertical mixing + diffusion + sub-monthly covariance + errors (`fig04_heat_budget.png`):

- **Jan:** TEND −120 W/m², HADV −110, RES +13 → winter cooling is **advective export**, not local heat loss — direct support for the "BoC has the weakest winter surface heat loss in the Gulf" mechanism.
- **May–Aug:** TEND +24…+77 W/m² while HADV is *negative* (−45…−83, export); the warming is entirely **residual-driven (+87…+191 W/m²)**. The residual's magnitude and sign are consistent with the Gulf's strong spring–summer net surface heat flux (storage peaks May–Jun in [Zavala-Hidalgo et al. 2002](https://www.scielo.org.mx/scielo.php?script=sci_abstract&pid=S0187-62362002000200002)) → **surface heating, trapped in a thin mixed layer, is the formation mechanism**; the gyre opposes it.
- **Oct:** HADV flips to +170 W/m² (heat import), yet TEND is −25 because RES = −201 (autumn cooling + entrainment). Eddy heat arrives in autumn but does not sustain the anomaly.
- VADV is negligible (±5 W/m²). Caveat: RES for 0–200 m differs strongly from 0–100 m, so vertical exchange across 100 m is substantial — the surface-flux attribution is qualitative, not quantitative (no flux product was provided).

## 3. Circulation, Loop Current, eddies

- The circulation is a **gyre-like through-flow**: warm inflow through the east face all year (+58…+177 W/m²) and strong north-face export Jan–Jul (−204…−297 W/m²). Monthly surface vorticity is patchy at 0.25° — a coherent single gyre is not resolved, but a cyclonic band persists along the western/northern shelves (`fig05_circulation.png`).
- **Yucatan Channel transport** (my Loop Current index): 17.5–25.5 Sv, monthly means; consistent with the observed 23.8 ± 1 Sv of [Sheinbaum et al. 2002](https://agupubs.onlinelibrary.wiley.com/doi/full/10.1029/2001GL013990). Correlation with BoC tendency ≈ −0.1 — LC strength does not pace the anomaly monthly.
- **Sub-monthly eddy heat flux through the box faces is −4…+8 W/m²** — two orders of magnitude below mean advection. Eddies do not flux heat in directly; they reorganize the flow. Mesoscale activity anticorrelates with warming (corr(EKE, TEND) = −0.55).
- **The Oct 2025 eddy event:** a +0.5 °C SST anomaly propagates westward along 21.5°N from ~94.5°W (Oct 26–28) to ~91.5°W (Nov 8–9), ≈ 0.3 m/s (`fig06_eddies.png`, Hovmöller), coincident with the +170 W/m² advective import and a **reversal of the north-face flux to import (+67 W/m²)**. This matches the LCE "weakening/reversal" mechanism of the Campeche Gyre described by [Olvera-Prado et al. 2023](https://link.springer.com/article/10.1007/s10236-023-01569-5): LCE southward penetration reverses the gyre flow. In this year the event occurred during the decay season and coincided with net upper-layer cooling.

## 4. Tracers, mixing, upwelling

- Winter chlorophyll bloom (0.32–0.36 mg/m³ Dec–Feb vs 0.12–0.15 Apr–Jun) tracks deep mixing: **corr(chl, MLD) = +0.87**, corr(chl, SST) = −0.66; oxygen mirrors SST (corr −0.99) — winter entrainment (MLD 350–450 m) is confirmed as the ventilation/nutrient-supply pathway.
- **Summer coastal upwelling is not resolved** in the monthly-mean w(100 m) field: the southern band shows weak downwelling Apr–Jun (+0.1…+1.2 m/d); upwelling (−0.5…−1.0 m/d) appears **Oct–Nov and Jan**, coinciding with the post-minimum chl rise (`fig07_upwelling.png`). The literature's upcoast/upwelling season on the Tamaulipas-Veracruz shelf is May–Aug ([Zavala-Hidalgo et al. 2003](https://agupubs.onlinelibrary.wiley.com/doi/full/10.1029/2003JC001879)); at 0.25° from monthly-mean continuity it is not detectable here — an honest resolution limitation, so upwelling's summer role is *inconclusive* rather than refuted.
- A barrier layer (BLT up to ~80 m) forms Oct–Jan under a fresh cap (`fig08_mld_blt.png`) — plausibly insulating the remnant anomaly from early entrainment, but its causal role is not testable with these data.

## 5. Assessment

| Mechanism | Verdict (1-yr data) |
|---|---|
| Surface heating forms the anomaly | **Supported** (May–Aug RES +87…+191 W/m² vs advective export; peak at minimum MLD/EKE) |
| Weak winter local heat loss | **Supported** (Jan cooling is advective, RES ≈ +13 W/m²) |
| Gyre retention | **Partial** (through-flow exists and exports heat in warm season; coherent closed gyre not resolved; Oct reversal = LCE mechanism) |
| Summer coastal upwelling | **Not resolved / inconclusive** (no summer upwelling in w100; autumn upwelling instead) |
| LCE heat delivery | **Supported as an autumn event**, not as the formation mechanism (Oct import +170 W/m² but net cooling; covariance flux negligible) |
| Winter entrainment | **Supported** (MLD 350–450 m; drives bloom, corr +0.87) |
| Barrier-layer insulation | **Suggestive** (BLT 65–85 m Oct–Jan) |

**Bottom line:** In 2025–26, the BoC warm anomaly forms because strong spring–summer surface heat input is trapped in a thin, quiet mixed layer while the mesoscale circulation is at its annual minimum; it decays when advective export and deep winter entrainment resume. LCE arrivals deliver heat in autumn — visibly, as a westward-propagating anomaly — but arrive during the decay season and are offset by entrainment and surface cooling, so they sustain rather than create the anomaly in this year.

**Blockers, stated honestly:** (1) single year — "anomaly" is relative to the same-year annual mean, not a climatology; (2) the residual conflates surface flux, vertical mixing, diffusion, and discretization error, and no surface-flux or wind product was provided, so Ekman forcing could not be tested directly and the surface-heating attribution is qualitative; (3) 0.25° resolution under-resolves the coastal shelf, the Yucatan Channel, and small eddies (absolute strait transports carry regridding uncertainty; the Florida Straits section was too poorly resolved to use as a calibration, so it is saved but not used).

**Deliverables:** `analysis.ipynb` (20-cell reproducible notebook: runs stages, prints tables, displays all figures, narrative); `code/` — `load_data.py`, `helpers.py`, `plotting.py` (validated palette), `stage1_seasonal.py`, `stage2_budget.py`, `stage3_eddies.py`, `stage4_tracers.py`, `make_figures.py`, `build_notebook.py`; `outputs/` — 7 derived netCDF files; `figures/` — 9 figures.

**Sources:**
- [Zavala-Hidalgo, Parés-Sierra & Ochoa (2002), Atmósfera 15(2), 81–104 — seasonal heat fluxes in the Gulf of Mexico](https://www.scielo.org.mx/scielo.php?script=sci_abstract&pid=S0187-62362002000200002)
- [Zavala-Hidalgo, Morey & O'Brien (2003), JGR 108(C12), 3389 — seasonal circulation on the western shelf](https://agupubs.onlinelibrary.wiley.com/doi/full/10.1029/2003JC001879)
- [Sheinbaum, Candela, Badan & Ochoa (2002), GRL 29(3) — Yucatan Channel flow structure and transport](https://agupubs.onlinelibrary.wiley.com/doi/full/10.1029/2001GL013990)
- [Olvera-Prado et al. (2023), Ocean Dynamics 73, 597–618 — wind, LCE and topography contributions to the Campeche Gyre](https://link.springer.com/article/10.1007/s10236-023-01569-5)

