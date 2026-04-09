#!/usr/bin/env python3
"""
手柄测试程序 - 实时显示所有轴和按钮的状态
"""

import sys
import time


def test_gamepad():
    try:
        import pygame
    except ImportError:
        print("请先安装 pygame: pip install pygame")
        sys.exit(1)

    pygame.init()
    pygame.joystick.init()

    if pygame.joystick.get_count() == 0:
        print("未检测到游戏手柄！")
        pygame.quit()
        sys.exit(1)

    joystick = pygame.joystick.Joystick(0)
    joystick.init()

    print("\n" + "=" * 60)
    print("  手柄测试程序")
    print("=" * 60)
    print(f"手柄名称: {joystick.get_name()}")
    print(f"轴数量: {joystick.get_numaxes()}")
    print(f"按钮数量: {joystick.get_numbuttons()}")
    print(f"帽子(方向键)数量: {joystick.get_numhats()}")
    print("=" * 60)
    print("操作提示:")
    print("  - 移动左摇杆 (查看轴 0, 1)")
    print("  - 移动右摇杆 (查看轴变化)")
    print("  - 按下手柄按钮")
    print("  - 按 Ctrl+C 退出")
    print("=" * 60 + "\n")

    # 记录初始值
    print("请保持摇杆中立，2秒后记录初始值...")
    time.sleep(2)
    initial_values = [joystick.get_axis(i) for i in range(joystick.get_numaxes())]
    print(f"初始值: {[f'{v:.3f}' for v in initial_values]}\n")

    print("开始实时监控 (按 Ctrl+C 退出)...\n")
    
    try:
        while True:
            pygame.event.pump()
            
            # 获取所有轴的值
            axes = [joystick.get_axis(i) for i in range(joystick.get_numaxes())]
            
            # 获取所有按钮状态
            buttons = [joystick.get_button(i) for i in range(joystick.get_numbuttons())]
            pressed_buttons = [i for i, v in enumerate(buttons) if v]
            
            # 构建显示字符串
            lines = []
            lines.append("-" * 50)
            
            # 显示轴值，高亮变化的轴
            axes_str = "轴值: ["
            for i, (v, init) in enumerate(zip(axes, initial_values)):
                changed = abs(v - init) > 0.01
                if changed:
                    axes_str += f"\033[91m{i}:{v:+.3f}\033[0m, "  # 红色高亮变化的轴
                else:
                    axes_str += f"{i}:{v:+.3f}, "
            axes_str = axes_str.rstrip(", ") + "]"
            lines.append(axes_str)
            
            # 显示按钮
            if pressed_buttons:
                lines.append(f"按下按钮: {pressed_buttons}")
            else:
                lines.append("按下按钮: 无")
            
            # 显示帽子(方向键)
            if joystick.get_numhats() > 0:
                hats = [joystick.get_hat(i) for i in range(joystick.get_numhats())]
                lines.append(f"方向键: {hats}")
            
            lines.append("-" * 50)
            
            # 清屏并打印
            print("\033[H\033[J", end="")  # 清屏
            print("\n".join(lines))
            
            time.sleep(0.05)  # 20Hz刷新
            
    except KeyboardInterrupt:
        print("\n\n退出测试程序")
    finally:
        pygame.quit()


if __name__ == "__main__":
    test_gamepad()
