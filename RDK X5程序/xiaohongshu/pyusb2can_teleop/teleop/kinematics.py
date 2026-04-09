from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple


@dataclass(slots=True)
class TriOmniKinematics:

    rotation_gain: float = 1.0

    def inverse(self, vx: float, vy: float, wz: float) -> Tuple[float, float, float]:

        front = -vy + wz * self.rotation_gain
        left = vx - min(vy, 0) - wz * self.rotation_gain 
        right = vx + max(vy, 0) + wz * self.rotation_gain
        return front, left, right
