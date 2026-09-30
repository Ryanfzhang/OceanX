# Copernicus Marine acquisition

Use for an explicit request for download instructions or a user-run script. Research Experts use
supplied data, not autonomous downloads to fill gaps.

Choose the dataset from the current Marine Data Store / official documentation,
not from a guessed product ID. Distinguish observations, reanalysis and forecasts;
confirm variable names, native grid, depth, time coverage, frequency and version.

For the user-run Python script, prefer the official
`copernicusmarine` client for supported products. Documented HTTPS original-file or
subset URLs can also be downloaded with a Python HTTP client. Retain product
identity/version and citation in the research result.
Reading a STAC catalog or finding an ARCO Zarr URL is not the same as downloading
a local NetCDF dataset. Never treat a Zarr metadata file as the complete array.

The official Toolbox supports `describe`, `subset` and `get`. A subset can limit
variables, region, time and depth; dry-run can report proposed selection/volume.
Use an explicit user-chosen download directory, not the original source directory. If the client or
authentication is missing, report the needed setup. Do not invent a `subset`
REST endpoint or silently fetch a full global product instead of a subset.

Official references (check current interfaces before recommending commands):
- https://help.marine.copernicus.eu/en/articles/9235249-how-to-download-a-subset-of-data
- https://toolbox-docs.marine.copernicus.eu/en/stable/python-interface.html

A typical user-run Python workflow is
`copernicusmarine.describe(contains=[...])` followed by
`copernicusmarine.subset(dataset_id=..., variables=[...], minimum_longitude=...,
maximum_longitude=..., minimum_latitude=..., maximum_latitude=...,
start_datetime=..., end_datetime=..., dry_run=True)`, then the same verified
selection with `dry_run=False` and an explicit `output_directory` chosen by the user.
Verify current parameters for the installed version.
Do not embed credentials or assume backend environment/login files are inherited.

Validate the acquired file before use, especially staggered velocities, depth
selection and time averaging. For transports, multiplying daily mean velocity by
daily mean concentration does not recover unresolved subdaily covariance.
