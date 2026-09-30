"""Optional structural checks; never infer coordinates, missing data or scientific meaning."""
import numpy as np


def check_dims(array, expected_dims):
    actual = tuple(array.dims)
    if actual != tuple(expected_dims):
        raise ValueError(f"Expected dimensions {tuple(expected_dims)}, got {actual}; transpose explicitly")
    return array


def exact_align(*arrays):
    import xarray as xr
    return xr.align(*arrays, join="exact", copy=False)


def column_take(array, indices, *, axis):
    values, index = np.asarray(array), np.asarray(indices)
    if not -values.ndim <= axis < values.ndim:
        raise ValueError("axis is outside the array dimensions")
    axis %= values.ndim
    expected = values.shape[:axis] + values.shape[axis + 1:]
    if index.shape != expected:
        raise ValueError(f"Index shape {index.shape} must equal remaining column shape {expected}")
    if not np.issubdtype(index.dtype, np.integer):
        raise ValueError("Indices must be integers; handle missing indices explicitly")
    if np.any(index < 0) or np.any(index >= values.shape[axis]):
        raise ValueError("Index outside the selected axis; do not silently clip")
    return np.take_along_axis(values, np.expand_dims(index, axis), axis=axis).squeeze(axis)


def masked_values(array, mask):
    if hasattr(array, "dims") and hasattr(mask, "dims"):
        check_dims(mask, array.dims)
        array, mask = exact_align(array, mask)
    values, selected = np.asarray(array), np.asarray(mask)
    if selected.dtype != np.dtype(bool) or selected.shape != values.shape:
        raise ValueError(f"Boolean mask shape {selected.shape} must match field shape {values.shape}")
    return values[selected]


def small_sample(dataset, n=5):
    if not isinstance(n, int) or isinstance(n, bool) or n < 1:
        raise ValueError("n must be a positive integer")
    return dataset.isel({dim: slice(0, min(n, size)) for dim, size in dataset.sizes.items()})


def weighted_mean(array, weights, *, dims):
    """Named-dimension mean with a validity-matched denominator; no silent alignment."""
    if isinstance(dims, str):
        dims = (dims,)
    if not dims or not set(dims) <= set(array.dims):
        raise ValueError("Reduction dimensions must name existing array axes")
    if not set(weights.dims) <= set(dims):
        raise ValueError("Weight axes must be reduction dimensions, not implicit new axes")
    array, weights = exact_align(array, weights)
    if not np.all(np.isfinite(weights)) or np.any(weights < 0):
        raise ValueError("Weights must be finite and nonnegative")
    valid_weights = weights.broadcast_like(array).where(np.isfinite(array), 0)
    denominator = valid_weights.sum(dims)
    if np.any(denominator <= 0):
        raise ValueError("No valid positive weight in at least one reduction slice")
    result = (array.where(np.isfinite(array), 0) * valid_weights).sum(dims) / denominator
    result.attrs = dict(array.attrs)
    return result


def rate_per_day(rate, *, input_unit):
    """Only convert the declared temporal denominator; do not guess missing units."""
    if input_unit == "per_second":
        return rate * 86400.0
    if input_unit == "per_day":
        return rate
    raise ValueError("input_unit must explicitly be per_second or per_day")


def angular_gradient_per_metre(gradient, *, latitude, angle_unit, direction, radius=6371000.0):
    """Convert a declared angular derivative to a metric derivative on a sphere."""
    if angle_unit not in {"degrees", "radians"} or direction not in {"zonal", "meridional"}:
        raise ValueError("Declare degrees/radians and zonal/meridional explicitly")
    lat = np.asarray(latitude)
    if radius <= 0 or not np.isfinite(radius) or np.any(~np.isfinite(lat)) or np.any(abs(lat) >= 90):
        raise ValueError("Require a positive finite radius and finite nonpolar latitude in degrees")
    metric = radius * (np.cos(np.deg2rad(latitude)) if direction == "zonal" else 1.0)
    if angle_unit == "degrees":
        metric = metric * np.pi / 180.0
    if hasattr(gradient, "dims") and hasattr(metric, "dims"):
        if not set(metric.dims) <= set(gradient.dims):
            raise ValueError("Metric dimensions must already exist in the gradient")
        gradient, metric = exact_align(gradient, metric)
    elif np.ndim(metric) and np.shape(metric) != np.shape(gradient):
        raise ValueError("Use named dimensions or an explicitly shape-matched latitude metric")
    return gradient / metric


def self_test():
    import xarray as xr
    field = np.arange(2 * 3 * 4 * 5).reshape(2, 3, 4, 5)
    index = np.indices((2, 4, 5)).sum(axis=0) % 3
    found = column_take(field, index, axis=1)
    expected = np.empty((2, 4, 5), dtype=field.dtype)
    for t, y, x in np.ndindex(expected.shape):
        expected[t, y, x] = field[t, index[t, y, x], y, x]
    np.testing.assert_array_equal(found, expected)
    mask = np.array([[True, False], [False, True]])
    np.testing.assert_array_equal(masked_values(np.arange(4).reshape(2, 2), mask), [0, 3])
    labeled = xr.DataArray(field, dims=("time", "depth", "lat", "lon"))
    check_dims(labeled, ("time", "depth", "lat", "lon"))
    assert small_sample(labeled, 2).shape == (2, 2, 2, 2)
    return "Array helper self-test passed"


if __name__ == "__main__":
    print(self_test())
