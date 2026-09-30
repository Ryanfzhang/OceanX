---
name: ocean-physical-consistency-review
description: Select and check ocean-physics methods for heat budgets, transport, stratification and mixing when investigating a physical subquestion or reviewing its evidence.
metadata:
  origin: oceanmind
  roles:
    - ocean_process_expert
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
Read `references/methods/transport.md` for section conventions when needed.

For a scalar `C`, `div_h(u_h C) = u_h dot grad_h(C) + C div_h(u_h)`.
Flux divergence and advective tendency are not interchangeable; the advective contribution
to temperature tendency is `-u_h dot grad_h(T)`. Check continuity and vertical/boundary terms
before attribution. An isolated property transport may depend on the reference zero when
volume transport is unbalanced; examine the complete accounting, not a preferred reference.

## Stratification

Separate density stratification, temperature stratification and mixed-layer depth (MLD).
Salinity compensation can make temperature gradients a misleading density proxy. Use the
thermodynamic variable and pressure/depth conventions required by the chosen equation of state.
For GSW calculations, consult `references/coding/gsw.md` and the
[GSW profile-function documentation](https://teos-10.github.io/GSW-Python/gsw_flat.html).

MLD depends on the threshold, reference depth, vertical resolution and interpolation. State
these when interpreting or comparing MLD; it is not interchangeable with a thermocline depth.
Read `references/methods/mixed-layer-depth.md` when deriving MLD. A stable/shallow layer can be
consistent with heat retention without showing that it caused the observed warming.

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

## relevant_references
`references/review/physical-consistency.md`, `references/data/common-variables-and-units.md`, `references/methods/transport.md`.
