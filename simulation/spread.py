"""Grid fire-growth solver: minimum travel time on a 16-neighbour stencil.

Fire arrival time T(x) is computed with a time-dependent Dijkstra search, the
discrete analogue of the anisotropic eikonal equation
    R(x, n) |grad T| = 1,
where R(x, n) is the Rothermel/Anderson elliptical rate of spread in the
direction n of travel (Finney 2002, "Fire growth using minimum travel time
methods", Can. J. For. Res. 32: 1420-1424, uses the same principle).

Edge travel time between neighbouring cells a -> b at distance d along
azimuth psi:   t = d/2 * (1/R_a(psi) + 1/R_b(psi)).
The weather (and therefore R) is piecewise constant per hour; the edge cost is
evaluated with the weather valid when the fire leaves cell a. Because pop
times are non-decreasing, the hourly field only ever advances.
"""

from __future__ import annotations

import heapq
import math
import time
from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from simulation.rothermel import SpreadField

# 16-neighbour stencil (row, col). Knight moves reduce the angular bias of 8-neighbour grids.
STENCIL = [(-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1),
           (-1, -2), (-1, 2), (1, -2), (1, 2), (-2, -1), (-2, 1), (2, -1), (2, 1)]
AZIMUTH = [math.atan2(dc, -dr) % (2 * math.pi) for dr, dc in STENCIL]
DIST_CELLS = [math.hypot(dr, dc) for dr, dc in STENCIL]


@dataclass
class SpreadResult:
    arrival_min: np.ndarray            # minutes since simulation start; inf = not burned
    max_time_min: float
    runtime_s: float
    hours_used: int
    meta: dict = field(default_factory=dict)

    def burned_at(self, t_min: float) -> np.ndarray:
        return self.arrival_min <= t_min


def _directional_rates(sf: SpreadField) -> list[list[float]]:
    out = []
    for az in AZIMUTH:
        out.append(sf.ros(az).astype(np.float64).ravel().tolist())
    return out


def simulate(initial_arrival_min: np.ndarray, field_for_hour: Callable[[int], SpreadField],
             cell_size_m: float, max_time_min: float) -> SpreadResult:
    """Run fire growth.

    initial_arrival_min: array with finite arrival times (minutes) for initially
        burning cells and +inf elsewhere (ignition = 0 min).
    field_for_hour: callable returning the SpreadField valid during hour k
        (k = floor(t / 60)).
    """
    t_start = time.perf_counter()
    h, w = initial_arrival_min.shape
    n = h * w
    arrival = initial_arrival_min.astype(np.float64).ravel().tolist()
    done = [False] * n
    heap = [(t, i) for i, t in enumerate(arrival) if math.isfinite(t)]
    heapq.heapify(heap)

    cur_hour = -1
    rates: list[list[float]] = []
    offsets = [(dr, dc, k) for k, (dr, dc) in enumerate(STENCIL)]
    dists = [d * cell_size_m for d in DIST_CELLS]
    hours_used = 0
    inf = math.inf

    while heap:
        t, i = heapq.heappop(heap)
        if done[i] or t > arrival[i]:
            continue
        done[i] = True
        if t > max_time_min:
            break
        hour = int(t // 60.0)
        if hour != cur_hour:
            cur_hour = hour
            rates = _directional_rates(field_for_hour(hour))
            hours_used += 1
        r, c = divmod(i, w)
        for dr, dc, k in offsets:
            rr, cc = r + dr, c + dc
            if rr < 0 or rr >= h or cc < 0 or cc >= w:
                continue
            j = rr * w + cc
            if done[j]:
                continue
            ra = rates[k][i]
            rb = rates[k][j]
            if ra <= 0.0 or rb <= 0.0:
                continue
            nt = t + 0.5 * dists[k] * (1.0 / ra + 1.0 / rb)
            if nt < arrival[j] and nt <= max_time_min:
                arrival[j] = nt
                heapq.heappush(heap, (nt, j))

    arr = np.asarray(arrival, dtype=np.float32).reshape(h, w)
    arr[arr > max_time_min] = np.inf
    return SpreadResult(arr, max_time_min, time.perf_counter() - t_start, hours_used)
