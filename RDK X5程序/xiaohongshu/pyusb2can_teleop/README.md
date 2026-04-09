# pyusb2can + CyberGear 三轮小车手柄控制

这套代码不再依赖旧的 `car_controller.py`，而是直接围绕：

```python
from pyusb2can import USB2CAN, FrameInfo, EXTENDED
```

从头重写。

## 目录结构

- `main.py`：程序入口
- `teleop/pyusb2can_bus.py`：pyusb2can 适配层
- `teleop/cybergear_protocol.py`：CyberGear 协议打包
- `teleop/cybergear_motor.py`：单电机控制
- `teleop/chassis.py`：三轮底盘
- `teleop/base_controller.py`：控制基类
- `teleop/gamepad_controller.py`：手柄类
- `teleop/kinematics.py`：底盘混控
- `teleop/commands.py`：统一运动命令

## 运行

```bash
pip install pygame
python main.py --device /dev/USB2CAN2 --channel 1 --front-id 1 --left-id 2 --right-id 3
```

## 常用参数

```bash
python main.py \
  --device /dev/USB2CAN2 \
  --channel 1 \
  --bitrate 1000000 \
  --host-id 0 \
  --front-id 1 --left-id 2 --right-id 3 \
  --front-dir 1 --left-dir -1 --right-dir 1 \
  --max-speed 10 \
  --max-rotation 5 \
  --torque-limit 3
```

## 说明

1. 如果你的三轮方向和当前不一致，只改 `--front-dir / --left-dir / --right-dir`。
2. 如果你后面要替换成更准确的官方三轮混控，只改 `teleop/kinematics.py`。
3. 如果你本地 `pyusb2can` 的方法签名和这里的自适配仍然对不上，只需要改 `teleop/pyusb2can_bus.py`，别的文件都不用动。
4. 如果电机协议大小端和这份实现不一致，只改 `teleop/cybergear_protocol.py` 里的 `_pack_param_write()`。
