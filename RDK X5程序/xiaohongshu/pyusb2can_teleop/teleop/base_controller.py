from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from .chassis import TriOmniChassis
from .commands import MotionCommand
from .utils import SlewRateLimiter, clamp


@dataclass
class BaseTeleopController(ABC):
    chassis: TriOmniChassis
    max_linear_speed: float = 12.0
    max_rotation_speed: float = 5.0
    update_rate: int = 50
    accel_limit: float = 20.0
    rot_accel_limit: float = 12.0
    zero_epsilon: float = 0.01
    running: bool = False
    enabled: bool = True
    _last_loop_time: float = field(default_factory=time.monotonic)
    _last_zero_sent: bool = False

    def __post_init__(self) -> None:
        self.update_interval = 1.0 / float(self.update_rate)
        self._vx_limiter = SlewRateLimiter(self.accel_limit)
        self._vy_limiter = SlewRateLimiter(self.accel_limit)
        self._wz_limiter = SlewRateLimiter(self.rot_accel_limit)

    @abstractmethod
    def read_command(self) -> MotionCommand:
        raise NotImplementedError

    @abstractmethod
    def handle_input_events(self) -> bool:
        raise NotImplementedError

    def enable(self) -> None:
        self.chassis.enable()
        self.enabled = True
        self._last_zero_sent = False

    def disable(self) -> None:
        self.chassis.stop()
        self.chassis.disable()
        self.enabled = False
        self._vx_limiter.reset(0.0)
        self._vy_limiter.reset(0.0)
        self._wz_limiter.reset(0.0)
        self._last_zero_sent = True

    def run(self) -> None:
        self.running = True
        self._last_loop_time = time.monotonic()
        try:
            while self.running:
                self.running = self.handle_input_events()
                if not self.running:
                    break

                now = time.monotonic()
                dt = now - self._last_loop_time
                self._last_loop_time = now

                if not self.enabled:
                    time.sleep(self.update_interval)
                    continue

                raw = self.read_command()
                cmd = self._shape_command(raw, dt)

                if cmd.is_zero(self.zero_epsilon):
                    if not self._last_zero_sent:
                        self.chassis.stop()
                        self._last_zero_sent = True
                else:
                    self.chassis.drive(cmd.vx, cmd.vy, cmd.wz)
                    self._last_zero_sent = False

                time.sleep(self.update_interval)
        finally:
            self.stop()

    def stop(self) -> None:
        self.running = False
        try:
            self.chassis.stop()
        except Exception:
            pass

    def _shape_command(self, cmd: MotionCommand, dt: float) -> MotionCommand:
        vx = clamp(cmd.vx, -self.max_linear_speed, self.max_linear_speed)
        vy = clamp(cmd.vy, -self.max_linear_speed, self.max_linear_speed)
        wz = clamp(cmd.wz, -self.max_rotation_speed, self.max_rotation_speed)

        vx = self._vx_limiter.update(vx, dt)
        vy = self._vy_limiter.update(vy, dt)
        wz = self._wz_limiter.update(wz, dt)
        return MotionCommand(vx=vx, vy=vy, wz=wz)
