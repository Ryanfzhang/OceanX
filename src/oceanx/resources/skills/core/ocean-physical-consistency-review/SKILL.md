---
name: ocean-physical-consistency-review
description: Read before calculating transport, budgets, streamfunctions, density, stratification or mixing diagnostics, or checking their physical assumptions.
metadata:
  origin: oceanmind
  roles:
    - ocean_process_expert
    - statistical_inference_expert
    - literature_reproduction_expert
---

# Ocean Physical Methods

## when_to_use
Use the methods relevant to the physical subquestion, for analysis or a specific evidence review.
These are alternatives and supporting techniques, not a sequence to complete. This skill does
not require an independent reviewer for every result.

## Scale and support

Match the diagnostic's spatial, temporal and vertical scale to the supplied resolution and coverage.
A regional mean cannot silently replace a point, section or water-mass comparison; averaging can
hide local or phase-dependent effects. State when sampling, boundaries or unresolved scales limit
the physical interpretation, without redefining the assigned question.

## Heat budgets

Distinguish temperature tendency, layer-integrated heat storage and boundary heat transport.
Identify the temperature convention, reference temperature, control volume and flux signs.
For a fixed wet layer and constant density and heat capacity,
`E = rho * cp * integral(T - T_ref, dz)` approximates storage in J/m2. A fixed-layer mean
temperature tendency has equivalent flux `rho * cp * H * tendency_K_per_day / 86400` in W/m2.
K/day and W/m2 cannot be compared before conversion to the same layer and time convention.

Changing mixed-layer or free-surface boundaries introduces moving-boundary terms. Multiplying
temperature tendency by instantaneous depth is not the full heat-content derivative.
Net surface heat flux is not shortwave alone; radiation can penetrate below a shallow layer.
Use actual model flux/tendency diagnostics where available, distinguishing them from approximate
reconstructions using sampled velocity and temperature. Averaging, subgrid processes and
assimilation increments can prevent closure. Missing terms are unknown, not zero.

A residual is not a measured forcing: unresolved transport, entrainment, mixing and numerical
errors may contribute. Missing flux observations plus a large residual do not demonstrate
surface-forcing dominance. [MITgcm's tracer documentation](https://mitgcm.readthedocs.io/en/latest/getting_started/getting_started.html#parameters-tracer-equations)
is a model-specific reference, not a variable-name template for other products.

## Transport and advection

Choose the section or boundary and its normal orientation. Volume transport integrates normal
velocity over wet area; heat/property transport also needs the tracer, density and reference
convention. Use actual cell areas, partial layer thicknesses and staggered-grid placement.
Before integration, use `/references/methods/transport.md` to resolve any remaining section,
grid-placement or snapshot-versus-mean convention.

For a scalar `C`, `div_h(u_h C) = u_h dot grad_h(C) + C div_h(u_h)`.
Flux divergence and advective tendency are not interchangeable; the advective contribution
to temperature tendency is `-u_h dot grad_h(T)`. Check continuity and vertical/boundary terms
before attribution. An isolated property transport may depend on the reference zero when
volume transport is unbalanced; examine the complete accounting, not a preferred reference.

## Vorticity budgets and streamfunctions

A layer's circulation is the area integral of its vertically integrated relative vorticity or, by
Stokes' theorem, the line integral of its integrated velocity along the domain boundary, open
straits included; the two must agree. So must the two forms of a flux term, such as the area
integral of `div_h(f V)` and the sum of `f V` normal to the boundary. When they differ, the boundary
does not follow the area that was integrated (coastal cells removed, staggered C-grid points, a
strait left open, a face given the velocity of the wrong cell): fix that rather than keep the form
that looks right. Divide by an area only when the quantity is defined as a domain average, and say
which area.

On depth levels, a level enters a layer with only the part of its cell between the layer's top and
bottom, so where the sea floor lies deeper the layer's level thicknesses add up to the layer's own
thickness; check that sum before integrating. A layer's transport is an integral: zero in a water
column whose sea floor lies above the layer (a mean over the layer is undefined there), unknown and not
zero on land or where data are missing. Unless the paper gives each layer its own domain, every layer's
circulation uses the same domain, boundary and area; summing only where the layer holds water gives the
circulation along the layer's own edge on the slope, another quantity. Keep missing values missing
through the derivatives, so that the cells beside land or missing data drop out, as papers that mask the
points next to land require; filling them with zero first gives those cells the shear against the
zeros, which can change a circulation several times over, and restoring the mask afterwards does not
undo it. On a regular latitude-longitude grid with both components at the same points and NaN on land,
below the sea floor and where data are missing, compute it with `ocean_layers`, tested functions every
agent's Python imports, rather than with code of your own: `layer_circulations` gives every layer's
circulation on one domain and one area, and its steps serve the other terms of a budget:
`level_edges(z)`, `layer_transport(u, edges, top, bottom)` (zero where a column holds no water in the
layer, NaN where it holds no valid data), `vorticity(U, V, lat, lon)` (NaN beside land and missing data)
and `circulation(zeta, lat, lon, used)`. Follow the paper wherever it defines the layer, the domain or the
grid otherwise; its masking of the points next to land is already done, land being the same for every
layer.

```python
from ocean_layers import layer_circulations

# u, v: (..., level, lat, lon), NaN on land, below the sea floor and where data are missing; z: their depths
# (m, positive down); region: the domain (bool, lat x lon), open only at real straits; layers: the paper's
# layers as (top, bottom) in m, np.inf for the sea floor
gammas, area = layer_circulations(u, v, z, lat, lon, region, layers)  # m3 s-1 each, and the one area in m2
```

Archives rarely store every term of a vorticity budget; derive a term before calling it missing:
- pressure from temperature, salinity and sea surface height, through the equation of state and
  the hydrostatic relation `p(z) = rho0 * g * eta + integral(rho * g, z..0)`; from it a layer's
  pressure-gradient torque and the bottom pressure torque `J(p_b, H) / rho0`; without sea surface
  height the density part alone is no estimate of them, since at depth the two parts largely cancel,
  so they stay inside the labelled residual;
- the planetary vorticity flux through a strait, `f` times the layer transport normal to the
  strait section, on the section's own grid points; a boundary cut through open sea to shape the
  domain carries flux too, so the domain's open boundaries are the real straits and nothing else:
  `open_edges(region, ocean, lat, lon, U, V)` from `ocean_layers` lists them with the transport through
  each and every corner where the edge turns in open water, which a domain closed at its straits does not
  have, and a strait's transport is the sum over the open edges that cross it;
- advection and tilting from the velocity fields, and the tendency from successive fields;
- one remaining term as the budget residual, labelled as a residual.
A term is missing only when neither the archive nor the attached sources hold what it needs.

Translate each budget term's full mathematical operator before implementing it. For a horizontal
layer transport `V`, `div_h(f V) = f div_h(V) + V dot grad_h(f)`; using only the first term omits the
spatial variation of `f`. Use the equation's flux sign and include all components of a grouped term,
such as advection and tilting, or label the computed subset. Apply the same domain, layer and
normalisation to every term. A residual also contains omitted components and reconstruction errors;
it is not a separately measured forcing or an independent closure check.

A layer's transport streamfunction integrates the layer's depth-integrated transport from a coast,
`psi(x, y) = integral(V, x0..x)` or of `-U` along y, on the native grid. Inverting vorticity with a
Poisson solve needs boundary values the data do not give, so its pattern is not evidence.

Retain the layer mask when interpreting or plotting the result. Water around an island is one body: no
water crosses the island, so the integral keeps its value across it, neither stopping there nor starting
again from zero beyond it. Only water bodies the domain does not join need their own boundaries and
reference constants.

Check a reconstructed streamfunction against both transport components, with the chosen sign and
grid metrics: `U = -dpsi/dy`, `V = dpsi/dx`. Layer transport can be divergent through exchange across
its top and bottom; if so, state which component or approximation the streamfunction represents.
A single constant changes only the reference zero. Subtracting a different value for every row or
column changes a spatial derivative and therefore the represented transport; derive and check such
a correction as analysis, not as a cosmetic adjustment. Investigate boundary-aligned bands through
the masks, integration path and reference choice before interpreting them or smoothing them away.

## Stratification

Separate density stratification, temperature stratification and mixed-layer depth (MLD).
Salinity compensation can make temperature gradients a misleading density proxy. Use the
thermodynamic variable and pressure/depth conventions required by the chosen equation of state.
Before GSW calculations, distinguish practical from absolute salinity, in-situ or potential from
conservative temperature, and sea pressure from geometric depth. Convert the supplied quantities to
the inputs the selected function requires; do not relabel one convention as another.
For implementation details, consult `/references/coding/gsw.md` and the
[GSW profile-function documentation](https://teos-10.github.io/GSW-Python/gsw_flat.html).

MLD depends on the threshold, reference depth, vertical resolution and interpolation. State
these when interpreting or comparing MLD; it is not interchangeable with a thermocline depth.
Read `/references/methods/mixed-layer-depth.md` when deriving MLD. A stable/shallow layer can be
consistent with heat retention without showing that it caused the observed warming.

For water-mass comparisons, preserve the salinity, temperature and equation-of-state conventions
across datasets. A temperature-salinity curve alone does not identify a water source or pathway;
read `/references/methods/water-mass.md` before interpreting that structure.

## Mixing and entrainment

Distinguish resolved vertical advection, parameterized turbulent mixing and entrainment across
a moving layer boundary. An MLD tendency by itself is not an entrainment heat flux; the
boundary's motion relative to the water and the temperature contrast matter.
Use diagnosed turbulent fluxes or a stated closure only where supported by the data. Shear or
stratification proxies do not directly measure diffusivity or dissipation. Do not name an
unclosed residual "mixing" without evidence separating its other contributions.

## research_objective
Choose physically meaningful diagnostics and assess their evidence without turning possible methods into required outputs.

## questions_to_resolve
- Are units, dimensions, magnitudes, signs, and coordinate directions consistent?
- Could grid-cell area, layer thickness, boundaries, masks, or land contamination explain the signal?
- Does the structure agree with known seasonality, stratification, circulation, or conservation constraints at the stated scale?

## evidence_requirements
Return checks with exact artifact refs and state whether each concern is a warning, failed check, or unresolved interpretation.

## process_checkpoints
Review code assumptions and data conventions separately from the physical conclusion.

A numerical check can validate a diagnostic without distinguishing the mechanism claimed from it.
Explain which competing interpretation is weakened by a result and which remains possible. Reusing
the same signal with another method or reviewer is not automatically independent evidence; examine
shared assumptions and errors. A passed numerical check does not by itself establish a mechanism.

Inspect the saved code, arrays and rendered figures relevant to a specific suspected discrepancy.
Describe the method actually executed, not merely the intended formula. Before comparing supposedly
equivalent computations, align their physical domain, valid support, boundary conditions, weights,
time samples and normalisation. If several of these change together, the comparison does not isolate
one cause; identify which step differs before attributing the discrepancy.
A small known-answer example can resolve a numerical uncertainty without repeating a whole study.
Report the evidence location, discrepancy, impact on the claim and any unexamined scope.

Use only checks relevant to the claim under review:

- Inspect shapes and coordinate alignment before reductions. Verify column interpolation and
  layer weights on a small known case; a plausible regional mean can hide accidental broadcasting
  or integration outside the stated depth range.
  Consult [array operations](/skills/xarray-array-ops/SKILL.md) for these operations when needed.
- Do not discard a mean because daily variability exceeds it or monthly values change sign.
  Mean divided by daily standard deviation is not a significance test; uncertainty of the mean
  requires the sampling dependence and effective sample size to be considered. Seek statistical
  review when needed, or leave significance unresolved.
- An unexpected sign or magnitude is a reason to check definitions and computations, not permission
  to replace the value with a physically preferred story. Assess net flux using its relevant
  components, not shortwave radiation alone; distinguish variability from estimator failure.
  Leave an untested cause unresolved rather than attributing it to data noise. Call a result an upper
  or lower bound only when the direction of the error has been established.
- A statistical decomposition is not a mechanism detector. Fluctuations relative to a temporal
  mean need not isolate coherent eddies or any other named process; persistent structures can
  contribute to the mean. A small covariance or domain-mean contribution cannot exclude that
  process without a discriminating diagnostic at the relevant spatial and temporal scales.

## expected_artifacts
Return evidence-linked findings through the existing result/report path. No separate review form,
decision artifact, or mandatory set of sections is needed. Empty limitations are valid when the
evidence gives no material reason to name one.

## quality_gates
Do not label a result physically plausible merely because a color map looks familiar.

## stop_or_escalation_conditions
Report sign, unit, conservation, or boundary inconsistencies that could change the answer, with a
focused correction or the evidence needed to settle them. Explain a no-effect judgment at the
claim's actual precision and level. Preserve unresolved interpretation limits; partial findings support only the checks actually performed.
The existence of additional possible checks alone is not a reason to withhold supported findings.

<!-- oceanx:lessons max=6 for="expert" about="physical method assumptions (budgets, transport, stratification, mixing) that did not hold, and checks that caught a physically wrong result" -->
<!-- /oceanx:lessons -->

## relevant_references
`/references/review/physical-consistency.md`, `/references/data/common-variables-and-units.md`, `/references/methods/transport.md`.
