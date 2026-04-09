from __future__ import annotations

from dataclasses import dataclass


def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def apply_deadzone(value: float, deadzone: float) -> float:
    if abs(value) < deadzone:
        return 0.0
    sign = 1.0 if value >= 0.0 else -1.0
    return sign * (abs(value) - deadzone) / (1.0 - deadzone)


@dataclass
class SlewRateLimiter:
    """限制目标量变化速度，避免电机速度突变。"""

    rate_per_sec: float
    value: float = 0.0

    def reset(self, value: float = 0.0) -> None:
        self.value = value

    def update(self, target: float, dt: float) -> float:
        if dt <= 0.0:
            self.value = target
            return self.value
        max_step = self.rate_per_sec * dt
        delta = target - self.value
        if delta > max_step:
            delta = max_step
        elif delta < -max_step:
            delta = -max_step
        self.value += delta
        return self.value
