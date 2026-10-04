"""Reviewer-only numerical reference for the current synthetic objective.

Branch-and-bound uses Taylor upper bounds over the normalized parameter box.
The first three coordinates interact; later coordinates are separable. Values
are floating-point estimates, not formal interval-arithmetic certificates.
"""

import heapq
import math
from functools import lru_cache

from .config import TaskConfig
from .task import SyntheticObjective


def _maximize(value, gradient, dimensions, curvature, tolerance):
    best_point = (0.5,) * dimensions
    best = value(best_point)
    serial = 0

    def upper(lower, higher):
        middle = tuple((a + b) / 2 for a, b in zip(lower, higher))
        radius = tuple((b - a) / 2 for a, b in zip(lower, higher))
        bound = value(middle) + sum(abs(g) * r for g, r in zip(gradient(middle), radius))
        return bound + curvature / 2 * sum(r * r for r in radius), middle

    lower, higher = (0.0,) * dimensions, (1.0,) * dimensions
    heap = [(-upper(lower, higher)[0], serial, lower, higher)]
    visited = 0
    while heap and -heap[0][0] > best + tolerance and visited < 200_000:
        _, _, lower, higher = heapq.heappop(heap)
        axis = max(range(dimensions), key=lambda i: higher[i] - lower[i])
        midpoint = (lower[axis] + higher[axis]) / 2
        for side in (0, 1):
            a, b = list(lower), list(higher)
            if side:
                a[axis] = midpoint
            else:
                b[axis] = midpoint
            bound, point = upper(a, b)
            candidate = value(point)
            if candidate > best:
                best, best_point = candidate, point
            if bound > best:
                serial += 1
                heapq.heappush(heap, (-bound, serial, tuple(a), tuple(b)))
        visited += 1
    return best, max(best, -heap[0][0] if heap else best), best_point, visited


@lru_cache(maxsize=128)
def _normalized_reference(seed, dimensions):
    objective = SyntheticObjective(TaskConfig(objective_seed=seed, dimensions=dimensions))
    centers, phases = objective.center, objective.phase
    frequency = 6 * math.pi
    strong_count = min(3, dimensions - 1)

    def strong(x):
        return (
            sum(
                -(x[i] - centers[i]) ** 2 + 0.15 * math.cos(frequency * x[i] + phases[i])
                for i in range(strong_count)
            )
            + 0.25 * math.sin(math.tau * x[0] * x[1])
            - 0.3 * (x[1] - x[2]) ** 2
        )

    def gradient(x):
        g = [0.0] * 3
        for i in range(strong_count):
            g[i] = -2 * (x[i] - centers[i]) - 0.15 * frequency * math.sin(
                frequency * x[i] + phases[i]
            )
        cosine = math.cos(math.tau * x[0] * x[1])
        g[0] += 0.25 * math.tau * x[1] * cosine
        g[1] += 0.25 * math.tau * x[0] * cosine - 0.6 * (x[1] - x[2])
        g[2] += 0.6 * (x[1] - x[2])
        return g

    # Absolute Hessian row sums are <80 on [0,1]^3. Taylor's remainder
    # is therefore bounded by 80/2 * ||delta||^2 throughout each box.
    best, upper, point, boxes = _maximize(strong, gradient, 3, 80, 1e-5)
    parameters = list(point)
    for i in range(3, dimensions - 1):
        def weak(x):
            return 0.05 * (
                -(x[0] - centers[i]) ** 2 + 0.15 * math.cos(frequency * x[0] + phases[i])
            )

        def weak_gradient(x):
            return (
                0.05 * (-2 * (x[0] - centers[i]) - 0.15 * frequency * math.sin(
                    frequency * x[0] + phases[i]
                )),
            )

        value, bound, location, count = _maximize(weak, weak_gradient, 1, 3, 1e-7)
        best += value
        upper += bound
        boxes += count
        parameters.extend(location)
    if dimensions > 3:
        parameters.append(0.5)
    return dict(estimated_maximum=best, upper_bound=upper, parameters=parameters, boxes=boxes)


def objective_reference(config: TaskConfig) -> dict:
    reference = _normalized_reference(config.objective_seed, config.dimensions)
    objective = SyntheticObjective(config)
    parameters = [
        config.lower + x * (config.upper - config.lower) for x in reference["parameters"]
    ]
    score = objective.evaluate(parameters)
    return dict(
        method="Synthetic objective v1: Taylor branch-and-bound (floating-point estimate)",
        task=config.model_dump(mode="json"),
        estimated_maximum=score,
        upper_bound=reference["upper_bound"],
        bound_gap=max(0, reference["upper_bound"] - score),
        maximizing_parameters=parameters,
        center_score=objective.evaluate([(config.lower + config.upper) / 2] * config.dimensions),
        boxes_evaluated=reference["boxes"],
    )
