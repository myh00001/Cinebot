from __future__ import annotations

import argparse
import sys
import time

from teleop.chassis import TriOmniChassis
from teleop.cybergear_motor import CyberGearMotor
from teleop.cybergear_protocol import CyberGearProtocol
from teleop.gamepad_controller import GamepadTeleopController
from teleop.pyusb2can_bus import USB2CANBus


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="pyusb2can + CyberGear 三轮小车手柄控制")
    parser.add_argument("--device", default="/dev/USB2CAN2", help="USB2CAN 设备路径")
    parser.add_argument("--channel", type=int, default=1, help="CAN 通道")
    parser.add_argument("--bitrate", type=int, default=1_000_000, help="CAN 波特率")
    parser.add_argument("--host-id", type=int, default=0, help="主机 CAN ID")

    parser.add_argument("--front-id", type=int, default=1, help="前轮电机 ID")
    parser.add_argument("--left-id", type=int, default=2, help="左轮电机 ID")
    parser.add_argument("--right-id", type=int, default=3, help="右轮电机 ID")

    parser.add_argument("--front-dir", type=int, default=1, help="前轮方向，1 或 -1")
    parser.add_argument("--left-dir", type=int, default=-1, help="左轮方向，1 或 -1")
    parser.add_argument("--right-dir", type=int, default=1, help="右轮方向，1 或 -1")

    parser.add_argument("--max-speed", type=float, default=10.0, help="最大线速度 rad/s")
    parser.add_argument("--max-rotation", type=float, default=5.0, help="最大旋转速度 rad/s")
    parser.add_argument("--current-limit", type=float, default=8.0, help="速度模式电流限制 (A)")
    parser.add_argument("--deadzone", type=float, default=0.15, help="摇杆死区")
    parser.add_argument("--update-rate", type=int, default=50, help="控制频率 Hz")
    parser.add_argument("--accel-limit", type=float, default=20.0, help="线速度斜坡 rad/s^2")
    parser.add_argument("--rot-accel-limit", type=float, default=12.0, help="角速度斜坡 rad/s^2")
    parser.add_argument("--verbose", action="store_true", help="打印底层 CAN 发送")
    return parser


def main() -> int:
    args = build_parser().parse_args()

    print("=" * 52)
    print("  pyusb2can + CyberGear 三轮小车控制")
    print("=" * 52)

    bus = USB2CANBus(
        device=args.device,
        channel=args.channel,
        bitrate=args.bitrate,
        verbose=args.verbose,
    )
    protocol = CyberGearProtocol(host_id=args.host_id)

    try:
        bus.connect()
        print("[Main] USB2CAN 已连接")

        front = CyberGearMotor(
            name="front",
            motor_id=args.front_id,
            direction=args.front_dir,
            bus=bus,
            protocol=protocol,
            speed_limit=args.max_speed,
            current_limit=args.current_limit,
        )
        left = CyberGearMotor(
            name="left",
            motor_id=args.left_id,
            direction=args.left_dir,
            bus=bus,
            protocol=protocol,
            speed_limit=args.max_speed,
            current_limit=args.current_limit,
        )
        right = CyberGearMotor(
            name="right",
            motor_id=args.right_id,
            direction=args.right_dir,
            bus=bus,
            protocol=protocol,
            speed_limit=args.max_speed,
            current_limit=args.current_limit,
        )

        chassis = TriOmniChassis(front=front, left=left, right=right)
        controller = GamepadTeleopController(
            chassis=chassis,
            max_linear_speed=args.max_speed,
            max_rotation_speed=args.max_rotation,
            update_rate=args.update_rate,
            accel_limit=args.accel_limit,
            rot_accel_limit=args.rot_accel_limit,
            deadzone=args.deadzone,
        )

        chassis.enable()
        time.sleep(0.2)
        controller.run()
        return 0

    except KeyboardInterrupt:
        print("\n[Main] 用户中断")
        return 0
    except Exception as exc:
        print(f"[Main] 错误: {exc}")
        return 1
    finally:
        try:
            print("[Main] 停车并断开...")
            # 这里只停车，不主动 stop(clear_fault)，避免退出时把故障状态一起改掉。
            if 'chassis' in locals():
                chassis.stop()
        except Exception:
            pass
        try:
            bus.disconnect()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
