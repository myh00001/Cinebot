from __future__ import annotations

import inspect
from typing import Any, Iterable, Optional

from .pyusb2can import USB2CAN, FrameInfo, EXTENDED


class USB2CANBus:
    """对 pyusb2can 做一层薄封装。

    由于不同版本/私有封装的 pyusb2can 方法名可能略有差异，
    这里做了少量自适配，尽量减少你后面改代码的范围。
    """

    def __init__(self, device: str, channel: int, bitrate: int = 1_000_000, verbose: bool = False):
        self.device = device
        self.channel = channel
        self.bitrate = bitrate
        self.verbose = verbose
        self.dev: Optional[Any] = None
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    def connect(self) -> None:
        if self._connected:
            return

        ctor_candidates = [
            {"device_name": self.device},
            {"device": self.device, "channel": self.channel, "bitrate": self.bitrate},
            {"device_path": self.device, "channel": self.channel, "bitrate": self.bitrate},
            {"path": self.device, "channel": self.channel, "bitrate": self.bitrate},
            {"device": self.device, "channel": self.channel},
            {"device_path": self.device, "channel": self.channel},
            {"path": self.device, "channel": self.channel},
            {"device": self.device},
            {"device_path": self.device},
            {"path": self.device},
            {},
        ]

        last_error: Optional[Exception] = None
        for kwargs in ctor_candidates:
            try:
                self.dev = USB2CAN(**kwargs)
                break
            except TypeError as exc:
                last_error = exc
                continue

        if self.dev is None:
            raise RuntimeError(f"无法实例化 USB2CAN: {last_error}")

        open_candidates = [
            ("open", {"channel": self.channel, "bitrate": self.bitrate}),
            ("open", {"bitrate": self.bitrate}),
            ("open", {"channel": self.channel}),
            ("open", {}),
            ("connect", {"channel": self.channel, "bitrate": self.bitrate}),
            ("connect", {"bitrate": self.bitrate}),
            ("connect", {"channel": self.channel}),
            ("connect", {}),
            ("start", {"channel": self.channel, "bitrate": self.bitrate}),
            ("start", {"bitrate": self.bitrate}),
            ("start", {"channel": self.channel}),
            ("start", {}),
            ("init", {"channel": self.channel, "bitrate": self.bitrate}),
            ("init", {"bitrate": self.bitrate}),
            ("init", {"channel": self.channel}),
            ("init", {}),
        ]

        opened = False
        for name, kwargs in open_candidates:
            fn = getattr(self.dev, name, None)
            if fn is None:
                continue
            try:
                result = fn(**kwargs)
                if result is False:
                    continue
                opened = True
                break
            except TypeError:
                continue

        if not opened and self.verbose:
            print("[USB2CANBus] 未找到显式 open/connect/start/init，默认认为构造后即可使用")

        self._connected = True

    def disconnect(self) -> None:
        if self.dev is None:
            return
        for name in ("close", "disconnect", "stop", "shutdown"):
            fn = getattr(self.dev, name, None)
            if fn is None:
                continue
            try:
                fn()
                break
            except Exception:
                pass
        self._connected = False

    def send_extended(self, arbitration_id: int, data: bytes) -> None:
        if not self._connected or self.dev is None:
            raise RuntimeError("USB2CAN 未连接")
        data = bytes(data[:8]).ljust(8, b"\x00")
        frame_info = self._build_frame_info(arbitration_id)
        self._send_with_fallback(arbitration_id, data, frame_info)
        if self.verbose:
            print(f"[USB2CANBus] TX id=0x{arbitration_id:08X} data={data.hex(' ')}")

    def _build_frame_info(self, can_id: int) -> Any:
        """构建 FrameInfo，必须设置 canID, frameType, dataLength"""
        # FrameInfo 字段: canID (uint32), frameType (uint8), dataLength (uint8)
        try:
            frame = FrameInfo()
            frame.canID = can_id
            frame.frameType = EXTENDED
            frame.dataLength = 8
            return frame
        except Exception:
            pass
        
        # 如果直接赋值失败，尝试构造函数
        candidates = [
            {"canID": can_id, "frameType": EXTENDED, "dataLength": 8},
            {"can_id": can_id, "frame_type": EXTENDED, "data_length": 8},
            {"id": can_id, "type": EXTENDED, "length": 8},
            {"flags": EXTENDED},
            {"frame_type": EXTENDED},
            {"format": EXTENDED},
            {},
        ]
        for kwargs in candidates:
            try:
                sig = inspect.signature(FrameInfo)
                valid = {k: v for k, v in kwargs.items() if k in sig.parameters}
                return FrameInfo(**valid)
            except Exception:
                try:
                    return FrameInfo(*kwargs.values())
                except Exception:
                    continue
        return FrameInfo()

    def _send_with_fallback(self, arbitration_id: int, data: bytes, frame_info: Any) -> None:
        # 首先尝试自定义的 send_usbcan 方法 (channel, frame_info, data)
        send_fn = getattr(self.dev, "send_usbcan", None)
        if send_fn is not None:
            try:
                # send_usbcan(self, channel: int, info: FrameInfo, data: bytearray)
                result = send_fn(self.channel, frame_info, bytearray(data))
                if result is not False:
                    return
            except Exception as exc:
                pass  # 失败则尝试其他方法

        # 尝试其他通用方法名
        send_methods = ["send", "write", "transmit", "send_frame", "Send", "Write"]
        errors: list[str] = []

        payload_candidates: Iterable[tuple] = [
            (arbitration_id, data, frame_info),
            (arbitration_id, frame_info, data),
            (frame_info, arbitration_id, data),
            (data, arbitration_id, frame_info),
            (arbitration_id, data),
            (data, arbitration_id),
        ]

        for method_name in send_methods:
            fn = getattr(self.dev, method_name, None)
            if fn is None:
                continue
            for args in payload_candidates:
                try:
                    result = fn(*args)
                    if result is False:
                        continue
                    return
                except TypeError as exc:
                    errors.append(f"{method_name}{args}: {exc}")
                except Exception as exc:
                    errors.append(f"{method_name}{args}: {exc}")

        msg = " | ".join(errors[:6])
        raise RuntimeError(f"pyusb2can 发送失败，请按你本地库的方法签名微调 _send_with_fallback(): {msg}")
