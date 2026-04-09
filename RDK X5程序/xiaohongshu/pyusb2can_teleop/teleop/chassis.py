from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Tuple

from .cybergear_motor import CyberGearMotor
from .kinematics import TriOmniKinematics


@dataclass(slots=True)
class TriOmniChassis:
    front: CyberGearMotor
    left: CyberGearMotor
    right: CyberGearMotor
    kinematics: TriOmniKinematics = field(default_factory=TriOmniKinematics)
    _last_sent: Tuple[float, float, float] = (999.0, 999.0, 999.0)

    def enable(self) -> None:
        self.front.enable_velocity_mode()
        time.sleep(0.02)
        self.left.enable_velocity_mode()
        time.sleep(0.02)
        self.right.enable_velocity_mode()
        time.sleep(0.02)

    def disable(self) -> None:
        self.front.disable()
        time.sleep(0.01)
        self.left.disable()
        time.sleep(0.01)
        self.right.disable()

    def stop(self) -> None:
        self.drive(0.0, 0.0, 0.0, force=True)

    def drive(self, vx: float, vy: float, wz: float, force: bool = False) -> None:
        front, left, right = self.kinematics.inverse(vx, vy, wz)
        target = (front, left, right)
        if not force and self._is_same(target, self._last_sent):
            return
        self.front.set_speed(front)
        time.sleep(0.002)
        self.left.set_speed(left)
        time.sleep(0.002)
        self.right.set_speed(right)
        time.sleep(0.002)
        self._last_sent = target

    @staticmethod
    def _is_same(a: Tuple[float, float, float], b: Tuple[float, float, float], eps: float = 1e-4) -> bool:
        return all(abs(x - y) < eps for x, y in zip(a, b))
