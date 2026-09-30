# SeaWiFS ocean colour

Use for an explicit request for download instructions or a user-run script. Research Experts use
supplied data, not autonomous downloads to fill gaps.

SeaWiFS operated in 1997–2010. Check that the requested comparison falls within its coverage.
If comparing climatologies across periods, label the mismatch and its interpretive limits.

Find the collection through NASA Ocean Color / Earthdata CMR, verify its dates,
L2/L3 level, variable, temporal aggregation and processing version, then inspect
the actual granule links in the user-run Python script.
For example, the public CMR collections JSON search accepts a keyword and bounded
page_size; use the returned collection concept ID to search granules with an
explicit temporal interval. Page through results deliberately rather than assuming
the first page is the entire time series.

Use a Python HTTP client or installed `earthaccess` to download verified data links.
Store reusable files in the user's chosen destination, with timeouts, bounded retries
and checks for partial transfers. Report missing authentication setup; do not assume
a backend login is inherited. A spatial search does not imply cropped bytes. Never invent
granule filenames or replace an unavailable SeaWiFS period with another year.

After transfer, check file format and readable variables. Older HDF and newer
NetCDF products may require different local readers; report a missing dependency
instead of claiming support merely because the suffix is familiar.

Sources:
- https://oceandata.sci.gsfc.nasa.gov/l3/
- https://cmr.earthdata.nasa.gov/search/site/docs/search/api.html
- https://earth.gsfc.nasa.gov/ocean/missions/seawifs-sea-viewing-wide-field-view-sensor
