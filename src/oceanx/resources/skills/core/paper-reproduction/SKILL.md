---
name: paper-reproduction
description: Reproduce, test or apply a published analysis with the supplied data, the paper's own or other data; find the analyses and their definitions in the paper, do those the data support, derive what the data do not store, check each quantity by the method's own identities, adapt the method to the record and redraw the paper's figures.
metadata:
  origin: oceanmind
  roles:
    - coordinator
    - ocean_process_expert
    - statistical_inference_expert
    - literature_reproduction_expert
    - scientific_discussion_partner
---

# Reproducing or applying a paper's analysis

## when_to_use
Use when a request asks to reproduce, test, extend or apply the analysis of a paper the researcher attached
or named, with the paper's data or with other data. The request need not say which analyses: they are in
the paper. Both compute the paper's quantities as the paper defines them, from the supplied data; a
similar-looking analysis is neither a reproduction nor the paper's method.

## Definitions before code
Before computing anything, read each equation that defines a quantity you will compute on the enlarged
part of its page that shows it whole, named above the page in the extracted text: the text garbles
equations, symbols and subscripts, and on the whole page image a cross, a minus or a subscript is easily
missed. Take every quantity from the methods, not from the abstract or the captions: its formula,
integration domain and boundary, vertical limits, whether it is integrated or averaged (divided by an
area, volume or thickness), units, sign convention, grid placement, masking, smoothing or filtering, and
the periods compared. Check each definition by its units against the paper's stated values and figure
axes: a circulation integrated along a boundary over a layer is in m3 s-1, so a figure in m s-1 shows it
divided by an area.

## Writing down what the paper requires
Before computing anything, write repro_spec.md in your working directory. First list every figure of the
paper, one for each figure image its extracted text names, whether it shows results, a mean state or a
schematic, with its panels; then list the paper's analyses. For each panel and analysis give the variables,
depths, region, period and time sampling it needs and whether the supplied data hold them (look in the
files, not at their names). Do every analysis and draw every panel whose inputs exist, and name the others
with what they need. Decide panel by panel, curve by curve and term by term, never for a figure as a whole:
a figure is left out only when none of its panels can be computed, and a doubt, such as a definition the
paper leaves open or an original drawn by hand, is said in the answer, not a reason to leave it out. For
each figure give the path of its image, the name of the file you will save yours as, and what the image and
its caption show: its panels and their arrangement, each axis with its variable, units, range and multiplier,
twin axes included, colour encoding,
line styles, markers, fills, overlays, arrows, reference lines, legends and annotations. For each quantity,
copy the paper's equation as printed, in its order of operations, write below it the discrete form you will
compute, and give the paper's values, each with the dataset and period it comes from. Write only what the
paper shows or states, mark what you could not read, and correct the file from the paper, never to fit your
results. Read it again whenever earlier messages have been replaced by a summary.

## One computation per quantity
Fix one computation of each quantity and check it, as under Checking the computation, on a part of the
record such as one year, before computing the whole record or drawing any figure. From then on use only
that computation: rename or remove the outputs of the versions it replaced, and compute every series you
compare or correlate from the same samples.
For time derivatives, convert timestamp differences explicitly to the time unit of the reported quantity.
For detrending, evaluate and subtract the fitted trend on the same time coordinate and in the same units
used for fitting. Reading every n-th time step is allowed when the timescale studied is much longer than the
step; say in the answer which steps you read.

## Deriving what the data do not store
Before writing code for a vorticity budget or a streamfunction, read
/skills/ocean-physical-consistency-review/SKILL.md, under Vorticity budgets and streamfunctions. Derive a
term from the stored variables before calling it missing. A term is missing only when neither the archive
nor the attached sources hold what it needs. Name that variable, for example the surface wind stress, and
the conclusions it leaves untested. When several terms cannot be told apart, give their sum as the residual
of the terms you computed, labelled with the terms it holds, rather than marking each one missing: where
the paper finds one of them small, the residual tests the others. Do not substitute another dataset unless
the researcher allows it.

## Checking the computation
Check each quantity by the method itself: its units, its discrete form against the equation copied in
repro_spec.md, and the identities it must satisfy, such as the area and boundary forms of a circulation
agreeing and a budget closing up to its labelled residual. Where your data and period are the paper's own,
also compare means, magnitudes, signs and trends with the paper's values, read from its text, tables and
figure axes; a difference of more than about a factor of two, or of sign, comes from a definition,
normalisation, unit, domain, mask or sign convention until shown otherwise. With other data the paper's
values are context, not a target, and a difference may be real: explain it by the data only after the
checks above pass. Find the cause of a failed check before drawing or interpreting that quantity.

## Adapting the method to the record
A method built for a long record can fail on a short one. Keep the paper's smoothing window when it is at
most about a quarter of your record. When it is longer, use a window of about a quarter of your record, and
say that the curve then shows a shorter timescale than the paper's. Where the paper's smoothed curves reach
the ends of its record, compute yours to the ends of yours, shortening the window near them. Justify any
other change to smoothing or filtering by the available record, the timescale studied and the samples
retained, respect explicit user requirements, and record each change from the paper's method. Before
reporting a trend or correlation of a smoothed series, read /skills/ocean-analysis-design/SKILL.md, under
Autocorrelation and dependence, and judge each trend and correlation by the independent values behind it.
Account for serial dependence when estimating uncertainty from averaged or smoothed series; overlapping
windows do not provide independent samples. Name each departure from the paper's method and why.

## Figures
Before drawing the first figure, read /references/coding/matplotlib.md, under Publication figures, and
before drawing a map, read /references/coding/matplotlib.md, under Maps. Redraw each figure listed in
repro_spec.md from your quantities as the original draws it, with the paper's data or other data: the same
panels and arrangement, axes with any twin axes, variables, symbols, units, colour encoding, line styles,
markers, fills, overlays, arrows, reference lines, legends and annotations, and how each field is drawn:
colour bands at the original's levels with contourf where the original shows bands, its contour lines with
their levels and labels, and continuous shading with pcolormesh only where the original shows shading.
Simplify nothing and add nothing: draw every element the original has, the trend line of each period included; one the record is too short to support is
drawn and marked not significant, never left out. Put no text panel, table or note in a figure that the
original lacks: numbers belong in the answer. Text on the original that states a result, such as a
rotation sense, a transport or a correlation, is written from your values, never copied. Smoothed curves and
their fills cover your record as the original's cover its record; a fill about a mean is drawn around the
quantity itself, and a series drawn minus its mean is labelled as an anomaly. With other data the axis
ranges are set from your values as the quoted matplotlib section says; with the paper's own data its scales
are kept too. Every figure that shows a smoothed series draws the one the computation saved, with the window
chosen under Adapting the method to the record. Before drawing each figure, read repro_spec.md again and,
when you can read images, open the original again, since what you read at the start lies far back in the
conversation. After saving, open yours: the original repro_spec.md names for it comes after it. Compare them
item by item (panel layout, axes, line styles, markers, colours, colour bands or shading, contour lines,
fills, axis multipliers, panel letters, legends and annotations, text that crosses a line, text the
original lacks) and fix every difference the data allow. Draw each panel,
curve and term the data allow, and name each doubt and each missing one in the answer, with what it needs.
Draw a partial budget as partial and not closed rather than withholding it; never draw a missing term as
zero, or a mechanism these data did not test as established, and never fill a gap with another quantity, a
table or another kind of figure.

## Reviewing the results
Before answering, read repro_spec.md again and review your results against it: every figure it lists,
drawn or not, beside the image of its original, item by item as under Figures, drawing any panel left out
that the data allow, and each quantity by its checks under Checking the computation. Check that every
figure and number you report comes from the saved output of the one computation of its quantity. Fix what
the data allow, and report what remains with its reason.

## Reporting
For each of the paper's conclusions give the paper's value, your value from the supplied data, whether the
conclusion holds in these data and the reason for a difference. Name the analyses you did not do and what
they need. Keep apart what was reproduced, what differs and what the data cannot test.
