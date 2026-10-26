"""Energy-trained apparent-power estimator, inspired by F1ATB's Linky router.

Independent implementation of the method, not a translation of its firmware.
See docs/power-estimator.md for the pinned reference, equations and limitations.
"""
from collections import deque
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class PowerEstimate:
    watts: float | None
    state: str
    factor: float | None = None
    energy_mean_watts: float | None = None
    window_seconds: float = 0.0
    calibration_age_seconds: float | None = None
    window_wh: int = 0
    smoothing_seconds: float = 0.0


class _Direction:
    def __init__(self):
        self.edges = deque(maxlen=4096)
        self.integral_va_seconds = 0.0
        self.last_edge = None
        self.factor = None
        self.mean = None
        self.window = 0.0
        self.delta_wh = 0
        self.smoothing_seconds = 0.0
        self.calibrated_at = None


class PowerEstimator:
    """Separate import/export learning; all elapsed times use a monotonic clock."""

    def __init__(self, config):
        self.config = config
        self.reset()

    def reset(self):
        self.channels = {1: _Direction(), -1: _Direction()}
        self.previous = None
        self.direction = 0

    def _window_complete(self, anchor, now, energy):
        duration, delta_wh = now - anchor[0], energy - anchor[1]
        return (duration >= self.config.power_min_seconds
                and delta_wh >= self.config.power_min_wh
                and (duration >= self.config.power_window_seconds
                     or delta_wh >= self.config.power_window_wh))

    def update(self, now, apparent_import, apparent_export, imported_wh, exported_wh):
        previous = self.previous
        direction = 1 if apparent_import else -1 if apparent_export else 0
        apparent = apparent_import + apparent_export
        if previous is not None:
            old_time, old_apparent, old_import, old_export = previous
            elapsed = now - old_time
            if elapsed <= 0:
                raise ValueError("estimator needs strictly increasing reception timestamps")
            if elapsed >= self.config.stale_after:
                self.reset()
                previous = None
            else:
                # Allow two Wh for quantization and asynchronous group updates.
                # A gross counter jump must not teach an arbitrary power factor.
                allowance = max(apparent, old_apparent) * elapsed / 3600 + 2
                if (imported_wh < old_import or exported_wh < old_export
                        or imported_wh - old_import > allowance
                        or exported_wh - old_export > allowance):
                    raise ValueError("energy increment inconsistent with elapsed time/apparent power")

        if direction != self.direction:
            # Neither a partial Wh nor a former factor may cross a reversal.
            # Re-entering a direction starts a new observation interval.
            self.channels = {1: _Direction(), -1: _Direction()}
            previous = None
        self.direction = direction
        self.previous = (now, apparent, imported_wh, exported_wh)
        if not direction:
            return PowerEstimate(0.0, "zero_apparent")

        channel = self.channels[direction]
        energy = imported_wh if direction == 1 else exported_wh
        if previous is None:
            return PowerEstimate(None, "warming_up")

        old_time, old_apparent, old_import, old_export = previous
        old_energy = old_import if direction == 1 else old_export
        channel.integral_va_seconds += (old_apparent + apparent) * (now - old_time) / 2
        if energy != old_energy:
            channel.last_edge = now
            channel.edges.append((now, energy, channel.integral_va_seconds))
            # Keep the shortest available window that reaches either target,
            # while always retaining BOTH minimum time and minimum energy.
            # An anchor is a real observed Wh edge; never interpolate it.
            while (len(channel.edges) > 2
                   and self._window_complete(channel.edges[1], now, energy)):
                channel.edges.popleft()
            first_time, first_energy, first_integral = channel.edges[0]
            duration = now - first_time
            delta_wh = energy - first_energy
            integral = channel.integral_va_seconds - first_integral
            # Discard the initial partial Wh. Learn only between observed edges,
            # across enough time/energy to reduce integer-Wh timing noise.
            if (duration >= self.config.power_min_seconds
                    and delta_wh >= self.config.power_min_wh and integral > 0):
                if delta_wh > integral / 3600 + 2:
                    raise ValueError("energy window inconsistent with apparent power")
                candidate = min(1.0, max(0.0, delta_wh * 3600 / integral))
                # Shorten the smoothing lag, retaining some averaging of Wh
                # steps: a 15 s window uses tau=7.5 s with the defaults.
                smoothing = self.config.power_smoothing_seconds * math.sqrt(min(
                    1.0, duration / self.config.power_window_seconds))
                if channel.factor is None:
                    channel.factor = candidate
                else:
                    alpha = -math.expm1(-(now - channel.calibrated_at)
                                       / smoothing)
                    channel.factor += alpha * (candidate - channel.factor)
                channel.mean = delta_wh * 3600 / duration
                channel.window = duration
                channel.delta_wh = delta_wh
                channel.smoothing_seconds = smoothing
                channel.calibrated_at = now

        if channel.factor is None:
            return PowerEstimate(None, "warming_up")
        watts = apparent * channel.factor
        state = "tracking"
        # F1ATB's no-new-Wh bound: a fresh, unchanged energy index constrains
        # average active power. The 1.3 Wh margin is heuristic, not metrology.
        since_edge = now - channel.last_edge
        if since_edge > 0:
            bound = 1.3 * 3600 / since_edge
            if bound < watts:
                watts = bound
                state = "energy_limited"
        watts = min(apparent, max(0.0, watts))
        return PowerEstimate(direction * watts, state, watts / apparent,
                             direction * channel.mean, channel.window,
                             now - channel.calibrated_at, channel.delta_wh,
                             channel.smoothing_seconds)
