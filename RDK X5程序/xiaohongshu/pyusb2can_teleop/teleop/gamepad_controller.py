from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .base_controller import BaseTeleopController
from .commands import MotionCommand
from .utils import apply_deadzone


@dataclass
class GamepadTeleopController(BaseTeleopController):
    deadzone: float = 0.25
    joystick: Optional[object] = field(default=None, init=False)
    pygame: Optional[object] = field(default=None, init=False)

    def init_input(self) -> None:
        try:
            import pygame  # type: ignore
        except ImportError as exc:
            raise RuntimeError("请先安装 pygame: pip install pygame") from exc

        pygame.init()
        pygame.joystick.init()
        if pygame.joystick.get_count() == 0:
            pygame.quit()
            raise RuntimeError("未检测到游戏手柄")

        self.pygame = pygame
        self.joystick = pygame.joystick.Joystick(0)
        self.joystick.init()

        print(f"[Gamepad] 已连接手柄: {self.joystick.get_name()}")

    def close_input(self) -> None:
        if self.pygame is not None:
            try:
                self.pygame.quit()
            except Exception:
                pass

    def handle_input_events(self) -> bool:
        if self.pygame is None:
            return False

        for event in self.pygame.event.get():
            if event.type == self.pygame.QUIT:
                return False

            if event.type == self.pygame.JOYBUTTONDOWN:
                if event.button == 0:
                    print("[Gamepad] A键: 失能电机")
                    self.disable()
                elif event.button == 1:
                    print("[Gamepad] B键: 使能电机")
                    self.enable()
                elif event.button in (6, 8):
                    print("[Gamepad] BACK/SELECT: 退出")
                    return False

        return True

    def read_command(self) -> MotionCommand:
        if self.joystick is None:
            return MotionCommand()

        left_x = self.joystick.get_axis(0)
        left_y = self.joystick.get_axis(1)

        right_x = self.joystick.get_axis(2)

        left_x = apply_deadzone(left_x, self.deadzone)
        left_y = apply_deadzone(left_y, self.deadzone)
        right_x = apply_deadzone(right_x, self.deadzone)

        return MotionCommand(
            vx=-left_y * self.max_linear_speed,
            vy=left_x * self.max_linear_speed,
            wz=-right_x * self.max_rotation_speed,
        )

    def run(self) -> None:
        self.init_input()
        print("\n" + "=" * 52)
        print("  pyusb2can + CyberGear 三轮小车手柄控制")
        print("=" * 52)
        print("左摇杆 : 前后 / 左右")
        print("右摇杆 : 旋转")
        print("A 键   : 失能电机")
        print("B 键   : 使能电机")
        print("BACK   : 退出")
        print("=" * 52 + "\n")
        try:
            super().run()
        finally:
            self.close_input()
