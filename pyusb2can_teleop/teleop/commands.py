from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class MotionCommand:
    """底盘速度命令。

    vx: 前进为正
    vy: 右移为正
    wz: 顺时针为正
    """

    vx: float = 0.0
    vy: float = 0.0
    wz: float = 0.0

    def is_zero(self, eps: float = 1e-3) -> bool:
        return abs(self.vx) < eps and abs(self.vy) < eps and abs(self.wz) < eps
