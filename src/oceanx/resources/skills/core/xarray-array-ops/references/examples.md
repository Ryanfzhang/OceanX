# Select the example matching the operation

## A column index is not an advanced-index grid

For `T(time, depth, lat, lon)` and `k(time, lat, lon)`, `T[:, k]`
creates extra advanced-index dimensions. Use:

```python
T = T.transpose("time", "depth", "lat", "lon")
k = k.transpose("time", "lat", "lon")
T, k = ao.exact_align(T, k)
at_depth = ao.column_take(T.values, k.values, axis=1)
assert at_depth.shape == (T.sizes["time"], T.sizes["lat"], T.sizes["lon"])
```

All indices must be valid. For columns without a crossing, keep a separate
validity mask and explicitly restore missing values after gathering a safe index;
do not report index zero as the physical answer for missing columns.

## Masks and flattened points

`area(lat, 1)[mask(lat, lon)]` fails; flattening the field alone can fail or pair
different points. Explicitly broadcast latitude weights to the field grid first:

```python
weights = np.broadcast_to(np.cos(np.deg2rad(lat_values))[:, None], field.shape)
valid = wet_mask & np.isfinite(field) & np.isfinite(weights)
values = ao.masked_values(field, valid)
selected_weights = ao.masked_values(weights, valid)
mean = np.average(values, weights=selected_weights) if values.size else np.nan
```

This is only an example for a regular latitude/longitude grid. Use actual cell
areas where required. If using xarray `.stack`, stack field and mask with the same
named dimensions and coordinate order; a Boolean mask with a different point order
must not be reused just because it has the same length.

## Broadcast one named axis, not a guessed shape

For `flux(time, lat, lon)`, latitude spacing `dx(lat)` becomes `dx[None, :, None]`.
After a reduction to `flux(lat, lon)`, it becomes `dx[:, None]`. An extra singleton
axis can silently create an unintended outer product. Named xarray arithmetic
avoids guessing these positions, but check matching coordinates and output dimensions.

## Boundaries and local indices

After slicing a subregion, global grid indices are no longer local indices. Use
coordinate-based selection or recompute indices against the sliced coordinates.
For integrals or tendencies, retain masks and weights from the same selected grid.
