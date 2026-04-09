from __future__ import annotations

import time
from dataclasses import dataclass

from .cybergear_protocol import CyberGearProtocol, RunMode
from .pyusb2can_bus import USB2CANBus


@dataclass(slots=True)
class CyberGearMotor:
    name: str
    motor_id: int
    direction: int
    bus: USB2CANBus
    protocol: CyberGearProtocol
    speed_limit: float = 15.0
    current_limit: float = 8.0  # 速度模式电流限制 (A)

    def __post_init__(self) -> None:
        if self.direction not in (-1, 1):
            raise ValueError(f"{self.name}: direction 只能是 1 或 -1")

    def enable_velocity_mode(self) -> None:
        # 先停止电机，防止模式切换时出错
        self.bus.send_extended(*self._frame_tuple(self.protocol.stop(self.motor_id)))
        time.sleep(0.02)
        # 设置速度模式
        self.bus.send_extended(*self._frame_tuple(self.protocol.write_run_mode(self.motor_id, RunMode.VELOCITY)))
        time.sleep(0.02)
        # 使能电机
        self.bus.send_extended(*self._frame_tuple(self.protocol.enable(self.motor_id)))
        time.sleep(0.02)
        # 设置电流限制
        self.bus.send_extended(*self._frame_tuple(self.protocol.write_limit_cur(self.motor_id, self.current_limit)))
        time.sleep(0.01)

    def disable(self, clear_fault: bool = False) -> None:
        self.bus.send_extended(*self._frame_tuple(self.protocol.stop(self.motor_id, clear_fault=clear_fault)))

    def set_speed(self, speed_rad_s: float) -> None:
        speed = max(-self.speed_limit, min(self.speed_limit, speed_rad_s))
        speed *= self.direction
        self.bus.send_extended(*self._frame_tuple(self.protocol.write_speed_ref(self.motor_id, speed)))

    def stop(self) -> None:
        self.set_speed(0.0)

    @staticmethod
    def _frame_tuple(frame) -> tuple[int, bytes]:
        return frame.arbitration_id, frame.data
