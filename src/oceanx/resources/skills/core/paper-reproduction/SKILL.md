---
name: paper-reproduction
description: Reproduce or test a published analysis with the supplied data; take each quantity's definition from the paper's methods, derive what the data do not store, match the paper's values before interpreting, adapt the method to the record and redraw the paper's figures.
metadata:
  origin: oceanmind
  roles:
    - coordinator
    - ocean_process_expert
    - statistical_inference_expert
    - literature_reproduction_expert
    - scientific_discussion_partner
---

# Reproducing a paper's analysis

## when_to_use
Use when a request asks to reproduce, test or extend the analysis of a paper the researcher attached or
named. A reproduction computes the paper's quantities as the paper defines them and compares them with
the paper's own values; a similar-looking analysis of the same data is not a reproduction.

## Preserve specifications and compare before publishing
After first reading each original figure, call record_reproduction_spec before analysis. Supply
source.pdf, one-based page, normalized figure_box and panel boxes [left, top, right, bottom] with
coordinates between 0 and 1 on the rendered page. The framework saves the whole page, a region-box
audit, original figure and individual panels, and extracts each region's PDF text. Inspect the
saved crops: confirm the figure label/caption and that labels and panels are not cut off. If the
region is uncertain, include the whole page and mark the extraction as uncertain. For an image-only
source, supply reference_image instead. Caption is source text; panel descriptions are extractions,
not new requirements. Only put literal labels in verified_labels after checking them against the image.

The framework generates .runtime/reproduction/repro_spec.md from the versioned records, with
embedded source images and extracted specifications. Do not edit this derived file or write your
own comparison verdict into it. A Markdown image link is only a path; open its image to see pixels.
Source specifications survive compaction. Summaries reference them instead of paraphrasing them.
Correct an extraction with a source-backed revision, never rewrite the original to fit your output.

Record adjustments separately. Parameter changes (smoothing window, period, resolution) need a
reason and must respect explicit user constraints. Changes to physical quantities, variables or
plot types require a specific user authorization: supply its exact quotation and message ID in
adjustments. Your own permitted_adaptations prose cannot authorize them. In particular, mean
transport cannot replace transport trend without the user's agreement.

Use record_reproduction_term for pending, computed (code/data evidence), and not_computable terms
(checked files, missing inputs and why derivation is impossible). A residual cannot resolve a
pending term. Do not claim that metadata or an image check validates a physical calculation.

Before drawing, reopen the original. Save from the actual matplotlib figure using:

```python
from oceanx.reproduction_images import save_reproduction_figure
metadata_file = save_reproduction_figure(
    fig, "outputs/figure.pdf",
    panels={"a": [ax_a], "b": [ax_b, ax_b_twin]},
    source_code=__file__, data_files=["scratch/computed-results.nc"],
)
```

Include every panel; group its twin axes together. This saves the actual figure, panel previews,
artist types, axis labels, legends and source/output hashes. The data paths are provenance pointers,
not proof of numerical correctness. Use a saved plotting script so the source can be checked.
If plotting without matplotlib, report that this export is unsupported instead of inventing metadata.

Open the original and generated figure and correct visible errors. Then call
review_reproduction_figure(figure_id, output_file, metadata_file). A fresh visual context compares
one figure's original pixels, generated pixels, PDF text, metadata and user-authorized adjustments.
It reports missing content, structural differences, scientific differences, uncertainty and concrete
suggestions. It does not accept or reject figures and does not control whether they are displayed.
Use the advice to correct clear errors where feasible, explain remaining gaps, and deliver the
useful results the available data allow. A missing dataset should be documented with evidence;
it does not require hiding the whole figure. Unverified missing-data claims remain tentative.
Do not repeat checks to obtain approval, and do not change scientific results to resemble the paper.
Report each figure's completed parts and limitations rather than calling it accepted or rejected.

## Definitions before code
Before computing anything, read the page image of each page whose equations define the quantities you
will compute: the extracted text names that image above the page and garbles its equations, symbols and
subscripts. Take every quantity from the methods, not from the abstract or the captions: its formula,
integration domain and boundary, vertical limits, whether it is integrated or averaged (divided by an
area, volume or thickness), units, sign convention, grid placement, masking, smoothing or filtering, and
the periods compared. Check each definition by its units against the paper's stated values and figure
axes: a circulation integrated along a boundary over a layer is in m3 s-1, so a figure in m s-1 shows it
divided by an area.

## One computation per quantity
Fix one computation of each quantity before drawing any figure, and check it: its units, the paper's
magnitudes for the overlapping period, and any identity it must satisfy, such as the area and boundary
forms of Stokes' theorem giving the same circulation. From then on use only that computation: rename or
remove the outputs of the versions it replaced, and compute every series you compare or correlate from
the same samples.
For time derivatives, convert timestamp differences explicitly to the time unit of the reported quantity.
For detrending, evaluate and subtract the fitted trend on the same time coordinate and in the same units
used for fitting. If subsampling replaces a full-period average, compare both on a common subset before
using the approximation, and disclose the sampling.

## Deriving what the data do not store
Before writing code for a vorticity budget or a streamfunction, read
/skills/ocean-physical-consistency-review/SKILL.md, under Vorticity budgets and streamfunctions. Derive a
term from the stored variables before calling it missing. A term is missing only when neither the archive
nor the attached sources hold what it needs. Name that variable, for example the surface wind stress, and
the conclusions it leaves untested. When several terms cannot be told apart, give their sum as the residual
of the terms you computed, labelled with the terms it holds, rather than marking each one missing: where
the paper finds one of them small, the residual tests the others. Do not substitute another dataset unless
the researcher allows it.

## Matching the paper before interpreting
For the overlapping period, or the same dataset, compare means, magnitudes, signs and trends with the
paper's values, read from its text, tables and figure axes. A difference of more than about a factor of
two, or of sign, comes from a definition, normalisation, unit, domain, mask or sign convention until
shown otherwise: find it before drawing any conclusion.

## Adapting the method to the record
A method built for a long record can fail on a short one. Justify any change to smoothing or filtering
using the available record, the timescale being studied and the samples retained. Respect explicit user
requirements, preserve the quantity being estimated, and record the change from the paper's method.
Do not assume that scaling a window in proportion to record length is always appropriate.
Before reporting a trend or correlation of a smoothed series, read /skills/ocean-analysis-design/SKILL.md,
under Autocorrelation and dependence, and judge each trend and correlation by the independent values behind
it. Account for serial dependence when estimating uncertainty from averaged or smoothed series;
overlapping windows do not provide independent samples. Name each departure from the paper's method and why.

## Figures
Before drawing the first figure, read /references/coding/matplotlib.md, under Publication figures.
Reproduce each of the paper's figures as one figure with the same panels, from the reproduced quantities:
the same variables, symbols, units, scales, colour encoding, fills, overlays, reference lines, annotations
and layout. Draw every element the original has, the trend line of each period included; one the record
is too short to support is drawn and marked not significant, never left out. Smoothed curves and their
fills run through the whole record as the original's do, over the raw series drawn faintly behind them at
the paper's time resolution. When you can read images, open the
original again right before drawing it, since the image read at the start lies far back in the
conversation. After saving, open the original and yours together, compare them item by item (panel layout,
fills, line styles, axis ranges and their multipliers, panel letters, legends and annotations, text that
crosses a line, lines that run off the axes) and fix every difference the data allow. Deliver every panel you
computed, with any doubt written on it rather than withholding it. Leave out only a panel whose data are
missing, say why, and never fill it with another quantity.

## Reporting
For each of the paper's conclusions give the paper's value, the reproduced value, whether they agree and
the reason for a difference. Keep what was reproduced, what differs and what the data cannot test apart.
