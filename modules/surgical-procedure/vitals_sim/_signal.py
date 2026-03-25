"""Signal model for physiological vital sign simulation.

Each signal has a current value, a target value (set by the scenario profile),
and a convergence rate. The current value moves toward the target over multiple
publication cycles, not in a single step. Per-cycle noise is added after the
trend computation.

See vision/simulation-model.md — Temporal Realism (Section 4).
"""

from __future__ import annotations

import random


class SignalModel:
    """Models a single continuously-varying physiological signal.

    Parameters
    ----------
    name:
        Human-readable signal identifier (e.g., "heart_rate").
    initial:
        Starting value for the signal.
    convergence_rate:
        Fraction of the remaining gap (current → target) closed per tick.
        A value of 0.05 means 5% of the gap is closed each tick.
    noise_amplitude:
        Standard deviation of Gaussian noise added per tick.
    min_val:
        Hard physiological floor (clamp after noise).
    max_val:
        Hard physiological ceiling (clamp after noise).
    rng:
        Seeded random.Random instance for reproducibility.
    """

    def __init__(
        self,
        name: str,
        initial: float,
        convergence_rate: float,
        noise_amplitude: float,
        min_val: float,
        max_val: float,
        rng: random.Random,
    ) -> None:
        self.name = name
        self._value = initial
        self._target = initial
        self._convergence_rate = convergence_rate
        self._noise_amplitude = noise_amplitude
        self._min = min_val
        self._max = max_val
        self._rng = rng

    @property
    def value(self) -> float:
        return self._value

    @property
    def target(self) -> float:
        return self._target

    @target.setter
    def target(self, new_target: float) -> None:
        self._target = max(self._min, min(self._max, new_target))

    def tick(self) -> float:
        """Advance the signal by one time step.

        The value moves toward the target by ``convergence_rate`` fraction of
        the remaining gap and then Gaussian noise is added.

        Returns the new value.
        """
        gap = self._target - self._value
        self._value += gap * self._convergence_rate
        self._value += self._rng.gauss(0, self._noise_amplitude)
        self._value = max(self._min, min(self._max, self._value))
        return self._value

    def set_value(self, v: float) -> None:
        """Force the current value (for test or acute event injection)."""
        self._value = max(self._min, min(self._max, v))
