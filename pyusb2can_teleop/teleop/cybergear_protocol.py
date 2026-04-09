from __future__ import annotations

import struct
from dataclasses import dataclass
from enum import IntEnum
from typing import Tuple


class CommType(IntEnum):
    FEEDBACK = 2
    ENABLE = 3
    STOP = 4
    SET_MECH_ZERO = 6
    READ_PARAM = 17
    WRITE_PARAM = 18


class RunMode(IntEnum):
    OPERATION = 0
    POSITION = 1
    VELOCITY = 2
    CURRENT = 3


@dataclass(frozen=True, slots=True)
class CyberGearFrame:
    arbitration_id: int
    data: bytes


class CyberGearProtocol:
    """CyberGear 常用协议打包。

    这里采用的是公开资料中常见的 29 位扩展帧布局：
    arbitration_id = (comm_type << 24) | (host_id << 8) | motor_id

    单参数写入：
    Byte0~1: 参数索引
    Byte2~3: 0
    Byte4~7: 参数值

    当前三轮小车只用到了速度模式最常见的几项：
    - run_mode: 0x7005
    - spd_ref: 0x700A
    - limit_torque: 0x700B

    如果你这批电机固件的大小端约定不同，只需要改 _pack_param_write() 这一处。
    """

    RUN_MODE_INDEX = 0x7005
    SPD_REF_INDEX = 0x700A
    LIMIT_CUR_INDEX = 0x7018  # 速度模式使用电流限制，不是扭矩限制

    def __init__(self, host_id: int = 0):
        self.host_id = host_id & 0xFF

    def enable(self, motor_id: int) -> CyberGearFrame:
        return CyberGearFrame(self._make_can_id(CommType.ENABLE, motor_id), b"\x00" * 8)

    def stop(self, motor_id: int, clear_fault: bool = False) -> CyberGearFrame:
        data = bytearray(8)
        data[0] = 1 if clear_fault else 0
        return CyberGearFrame(self._make_can_id(CommType.STOP, motor_id), bytes(data))

    def set_mech_zero(self, motor_id: int) -> CyberGearFrame:
        data = bytearray(8)
        data[0] = 1
        return CyberGearFrame(self._make_can_id(CommType.SET_MECH_ZERO, motor_id), bytes(data))

    def write_run_mode(self, motor_id: int, mode: RunMode) -> CyberGearFrame:
        return CyberGearFrame(
            self._make_can_id(CommType.WRITE_PARAM, motor_id),
            self._pack_param_write(self.RUN_MODE_INDEX, bytes([int(mode), 0, 0, 0])),
        )

    def write_speed_ref(self, motor_id: int, speed_rad_s: float) -> CyberGearFrame:
        return CyberGearFrame(
            self._make_can_id(CommType.WRITE_PARAM, motor_id),
            self._pack_param_write(self.SPD_REF_INDEX, struct.pack("<f", float(speed_rad_s))),
        )

    def write_limit_cur(self, motor_id: int, current_a: float) -> CyberGearFrame:
        """设置电流限制 (速度模式使用)"""
        return CyberGearFrame(
            self._make_can_id(CommType.WRITE_PARAM, motor_id),
            self._pack_param_write(self.LIMIT_CUR_INDEX, struct.pack("<f", float(current_a))),
        )

    def _make_can_id(self, comm_type: int, motor_id: int) -> int:
        return ((int(comm_type) & 0x1F) << 24) | (self.host_id << 8) | (motor_id & 0xFF)

    @staticmethod
    def _pack_param_write(index: int, value4: bytes) -> bytes:
        if len(value4) != 4:
            raise ValueError("参数写入值必须恰好 4 字节")
        # 常见资料里参数索引/float 参数通常按小端打包。
        return struct.pack("<H2x", index) + value4
