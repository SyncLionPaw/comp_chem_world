"""Average a sharp single-interface double-layer profile over Eq. 19.

For the half-space profile in Figures 5--6, Eq. 19's truncated Gaussian is
normalized on l >= 0 (the distant upper cutoff is taken to infinity). The
mean location and half-width are the Figure 6 caption values. Potential,
polarization, and ion densities are averaged separately over shifted sharp
solutions. In particular, the averaged ion density is not recomputed from the
averaged potential, since the lattice-gas closure is nonlinear.

This is an explicit convolution reconstruction of interface smearing. It is
not a newly solved nonlinear BVP with a spatially varying boundary condition;
the scientific contract should preserve that distinction.
"""
from __future__ import annotations

import numpy as np
from scipy.interpolate import PchipInterpolator
from scipy.signal import oaconvolve
from scipy.special import erf


def halfspace_eq19_density(l_A, mean_A=2.5, delta_A=1.5):
    """Eq. 19 probability density on the half-space, in inverse Angstrom."""
    if not np.isfinite(mean_A) or not np.isfinite(delta_A) or mean_A < 0 or delta_A <= 0:
        raise ValueError("mean must be nonnegative and delta positive")
    l = np.asarray(l_A, dtype=float)
    norm = 0.5 * delta_A * np.sqrt(np.pi) * (1.0 + erf(mean_A / delta_A))
    density = np.exp(-((l - mean_A) / delta_A) ** 2) / norm
    return np.where(l >= 0.0, density, 0.0)


def eq19_cdf(z_A, mean_A=2.5, delta_A=1.5):
    """Probability that the actual wall location lies at or before z."""
    z = np.asarray(z_A, dtype=float)
    if np.any(z < 0):
        raise ValueError("z must lie in the electrolyte half-space")
    den = 1.0 + erf(mean_A / delta_A)
    val = (erf((z - mean_A) / delta_A) + erf(mean_A / delta_A)) / den
    return np.clip(val, 0.0, 1.0)


def average_shifted_profile(z_A, sharp_z_A, fields, mean_A=2.5, delta_A=1.5,
                            quadrature_order=96):
    """Convolve independent sharp fields with Eq. 19 on a half-space.

    A sharp solution field f(x) contributes only for x=z-l >= 0. Therefore
    each average is integral_0^z rho(l) f(z-l) dl. Ion fields use the same
    liquid-fraction factor, so their far-field limits recover the bulk values.
    """
    z = np.asarray(z_A, dtype=float)
    grid = np.asarray(sharp_z_A, dtype=float)
    if (z.ndim != 1 or grid.ndim != 1 or grid.size < 2
            or np.any(~np.isfinite(z)) or np.any(~np.isfinite(grid))
            or np.any(np.diff(grid) <= 0)):
        raise ValueError("profile coordinates must be increasing 1-D arrays")
    if not np.isclose(grid[0], 0.0, rtol=0.0, atol=1e-12):
        raise ValueError("sharp_z_A must start at the physical wall z=0")
    if np.any(z < 0) or np.any(z > grid[-1]):
        raise ValueError("smeared profile points must lie within the sharp profile domain")
    if int(quadrature_order) != quadrature_order or quadrature_order < 8:
        raise ValueError("quadrature_order must be an integer >= 8")
    if not fields:
        raise ValueError("at least one field is required")
    arrays = {key: np.asarray(value, dtype=float) for key, value in fields.items()}
    if any(value.shape != grid.shape or np.any(~np.isfinite(value)) for value in arrays.values()):
        raise ValueError("every input field must be finite and match sharp_z_A")
    spacing = np.diff(grid)
    if np.allclose(spacing, spacing[0], rtol=1e-9, atol=1e-12):
        dx = float(spacing[0])
        output_indices = np.rint(z / dx).astype(int)
        if (np.allclose(output_indices * dx, z, rtol=0.0, atol=1e-9)
                and np.all(output_indices < len(grid))):
            # On uniform grids, Eq. 19 is a one-sided convolution. Sampling
            # the continuous BVP densely and using a composite trapezoid rule
            # resolves narrow ionic saturation layers without a global
            # quadrature panel spanning the whole Gaussian support. The FFT
            # keeps the work O(N log N), independent of the number of output
            # rows times source samples.
            cutoff = mean_A + 8.0 * delta_A
            last_kernel_index = int(np.floor(cutoff / dx))
            ell = np.arange(last_kernel_index + 1, dtype=float) * dx
            kernel = halfspace_eq19_density(ell, mean_A, delta_A)
            full_indices = np.arange(len(grid), dtype=int)
            upper_indices = np.minimum(full_indices, last_kernel_index)
            upper_density = kernel[upper_indices]
            averaged = {}
            for key, values in arrays.items():
                convolution = oaconvolve(values, kernel, mode="full")[:len(grid)]
                # Trapezoid endpoint weights for ell=0 and ell=min(z,cutoff).
                convolution -= 0.5 * values * kernel[0]
                convolution -= 0.5 * values[full_indices - upper_indices] * upper_density
                output_values = dx * convolution[output_indices]
                if np.any(z == 0.0):
                    output_values[z == 0.0] = 0.0
                if key in {"n_plus_m3", "n_minus_m3", "site_occupancy"}:
                    roundoff = (128.0 * np.finfo(float).eps
                                * max(float(np.max(np.abs(values))), 1.0)
                                * max(1.0, np.log2(len(values))))
                    if np.min(output_values) < -roundoff:
                        raise ValueError(f"convolution produced materially negative {key}")
                    output_values = np.maximum(output_values, 0.0)
                averaged[key] = output_values
            averaged["liquid_fraction"] = eq19_cdf(z, mean_A, delta_A)
            return averaged
    interp = {key: PchipInterpolator(grid, value, extrapolate=False)
              for key, value in arrays.items()}
    gx, gw = np.polynomial.legendre.leggauss(int(quadrature_order))
    avg = {key: np.zeros_like(z) for key in arrays}
    # Vectorized bounded chunks avoid one Python interpolation call per
    # output point while keeping memory bounded for long Debye tails.
    for start in range(0, len(z), 1024):
        stop = min(start + 1024, len(z))
        zz = z[start:stop]
        upper = np.minimum(zz, mean_A + 8.0 * delta_A)
        ell = 0.5 * upper[:, None] * (gx + 1.0)
        weights = (0.5 * upper[:, None] * gw[None, :]
                   * halfspace_eq19_density(ell, mean_A, delta_A))
        points = zz[:, None] - ell
        for key, fn in interp.items():
            avg[key][start:stop] = np.einsum("ij,ij->i", weights, fn(points))
    avg["liquid_fraction"] = eq19_cdf(z, mean_A, delta_A)
    return avg


def average_continuous_profile(z_A, field_evaluator, mean_A=2.5, delta_A=1.5,
                               panel_A=0.05, quadrature_order=8):
    """Directly convolve an evaluator on a continuous sharp BVP solution.

    Composite Gauss panels resolve sharp nonlinear ion layers without first
    interpolating a sparsely sampled density table. This is intended for the
    near-wall slice where site saturation makes that distinction measurable.
    ``field_evaluator(x_A)`` must return finite vector fields at the supplied
    electrolyte coordinates and recompute n± from the local sharp potential.
    """
    z = np.asarray(z_A, dtype=float)
    if (z.ndim != 1 or z.size == 0 or np.any(~np.isfinite(z))
            or np.any(z < 0)):
        raise ValueError("continuous roughness coordinates must be finite and nonnegative")
    if not np.isfinite(mean_A) or not np.isfinite(delta_A) or mean_A < 0 or delta_A <= 0:
        raise ValueError("mean must be nonnegative and delta positive")
    if not np.isfinite(panel_A) or panel_A <= 0:
        raise ValueError("quadrature panel spacing must be finite and positive")
    if int(quadrature_order) != quadrature_order or quadrature_order < 2:
        raise ValueError("continuous quadrature order must be an integer >= 2")
    gx, gw = np.polynomial.legendre.leggauss(int(quadrature_order))
    result: dict[str, np.ndarray] = {}
    cutoff = mean_A + 8.0 * delta_A
    for row, zi in enumerate(z):
        upper = min(float(zi), cutoff)
        if upper <= 0:
            continue
        panel_count = max(1, int(np.ceil(upper / panel_A)))
        edges = np.linspace(0.0, upper, panel_count + 1)
        left, right = edges[:-1], edges[1:]
        ell = 0.5 * (right - left)[:, None] * (gx[None, :] + 1.0) + left[:, None]
        weights = (0.5 * (right - left)[:, None] * gw[None, :]
                   * halfspace_eq19_density(ell, mean_A, delta_A))
        x = (float(zi) - ell).ravel()
        order = np.argsort(x)
        sampled_sorted = field_evaluator(x[order])
        inverse_order = np.argsort(order)
        sampled = {key: np.asarray(values)[inverse_order]
                   for key, values in sampled_sorted.items()}
        if not sampled:
            raise ValueError("continuous field evaluator returned no fields")
        if not result:
            result = {key: np.zeros(z.shape, dtype=float) for key in sampled}
        if set(sampled) != set(result):
            raise ValueError("continuous evaluator returned inconsistent field keys")
        for key, values in sampled.items():
            values = np.asarray(values, dtype=float)
            if values.shape != x.shape or np.any(~np.isfinite(values)):
                raise ValueError(f"continuous field {key} has invalid shape or values")
            result[key][row] = float(np.sum(weights.ravel() * values))
    result["liquid_fraction"] = eq19_cdf(z, mean_A, delta_A)
    return result
