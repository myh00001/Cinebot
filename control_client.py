#!/usr/bin/env python3
"""
相机控制客户端 - 支持拍照、录像、文件传输
完整画质，非预览流
"""

import socket
import struct
import sys
import os
from enum import IntEnum


class Command(IntEnum):
    CAPTURE = 1
    RECORD_START = 2
    RECORD_STOP = 3
    GET_FILE_LIST = 4
    DOWNLOAD_FILE = 5
    GET_STATUS = 6
    SWITCH_LENS = 7
    PREVIEW_START = 8
    PREVIEW_STOP = 9


class CameraController:
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.sock = None
        self.magic = 0x54534E49  # 'INST'

    def connect(self):
        """连接控制服务器"""
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.connect((self.host, self.port))
        print(f"Connected to {self.host}:{self.port}")
        return True

    def disconnect(self):
        """断开连接"""
        if self.sock:
            self.sock.close()
            self.sock = None

    def send_command(self, cmd, param=b"", binary=False):
        """发送命令并接收响应"""
        if not self.sock:
            raise ConnectionError("Not connected")

        # 发送命令头
        header = struct.pack("<III", self.magic, int(cmd), len(param))
        self.sock.sendall(header)

        # 发送参数
        if param:
            self.sock.sendall(param)

        # 接收响应头
        resp_header = self.recv_all(12)
        magic, status, data_len = struct.unpack("<III", resp_header)

        if magic != self.magic:
            raise ValueError("Invalid response magic")

        # 接收数据
        data = b""
        if data_len > 0:
            data = self.recv_all(data_len)

        if binary:
            return status == 0, data
        else:
            return status == 0, data.decode("utf-8", errors="ignore")

    def recv_all(self, size):
        """接收指定长度数据"""
        data = b""
        while len(data) < size:
            chunk = self.sock.recv(size - len(data))
            if not chunk:
                raise ConnectionError("Connection closed")
            data += chunk
        return data

    def capture(self):
        """拍照 - 返回文件URL"""
        print("Taking photo...")
        success, result = self.send_command(Command.CAPTURE)
        if success:
            print(f"Photo saved: {result}")
            return result.strip()
        else:
            print(f"Failed: {result}")
            return None

    def record_start(self):
        """开始录像"""
        print("Starting recording (8K)...")
        success, result = self.send_command(Command.RECORD_START)
        if success:
            print(f"Recording started")
            return True
        else:
            print(f"Failed: {result}")
            return False

    def record_stop(self):
        """停止录像 - 返回文件URL"""
        print("Stopping recording...")
        success, result = self.send_command(Command.RECORD_STOP)
        if success:
            print(f"Video saved: {result}")
            return result.strip()
        else:
            print(f"Failed: {result}")
            return None

    def get_file_list(self):
        """获取文件列表"""
        print("Getting file list...")
        success, result = self.send_command(Command.GET_FILE_LIST)
        if success:
            files = [f for f in result.strip().split("\n") if f]
            return files
        return []

    def download_file(self, filename, save_path=None):
        """下载文件"""
        print(f"Downloading: {filename}")
        success, data = self.send_command(
            Command.DOWNLOAD_FILE, filename.encode(), binary=True
        )
        if success:
            if save_path is None:
                save_path = filename.split("/")[-1]

            with open(save_path, "wb") as f:
                f.write(data)  # data is already bytes

            print(f"Saved to: {save_path} ({len(data)} bytes)")
            return save_path
        else:
            print(f"Failed: {data}")
            return None

    def switch_lens(self, lens):
        """切换镜头 1=前 2=后 3=全"""
        print(f"Switching to lens {lens}...")
        success, result = self.send_command(Command.SWITCH_LENS, bytes([lens]))
        if success:
            print(f"OK: {result}")
            return True
        else:
            print(f"Failed: {result}")
            return False

    def get_status(self):
        """获取状态"""
        success, result = self.send_command(Command.GET_STATUS)
        return result if success else "Unknown"


def interactive_menu():
    """交互式菜单"""
    if len(sys.argv) < 3:
        print(f"Usage: python {sys.argv[0]} <host> <control_port>")
        print(f"Example: python {sys.argv[0]} 192.168.88.189 8889")
        sys.exit(1)

    host = sys.argv[1]
    port = int(sys.argv[2])

    controller = CameraController(host, port)

    try:
        controller.connect()

        while True:
            print("\n" + "=" * 50)
            print("Camera Control Menu")
            print("=" * 50)
            print("1. Take Photo (Full Quality)")
            print("2. Start Recording (8K)")
            print("3. Stop Recording")
            print("4. List Files")
            print("5. Download File")
            print("6. Switch Lens")
            print("7. Get Status")
            print("0. Exit")
            print("=" * 50)

            choice = input("Select: ").strip()

            if choice == "1":
                url = controller.capture()
                if url:
                    download = input("Download photo? (y/n): ").strip().lower()
                    if download == "y":
                        controller.download_file(url)

            elif choice == "2":
                controller.record_start()

            elif choice == "3":
                url = controller.record_stop()
                if url:
                    download = input("Download video? (y/n): ").strip().lower()
                    if download == "y":
                        controller.download_file(url)

            elif choice == "4":
                files = controller.get_file_list()
                print(f"\n{len(files)} files:")
                for i, f in enumerate(files[:20], 1):  # 只显示前20个
                    print(f"  {i}. {f}")

            elif choice == "5":
                filename = input("Enter file path: ").strip()
                if filename:
                    controller.download_file(filename)

            elif choice == "6":
                print("1. Front lens (screen side)")
                print("2. Rear lens (back side)")
                print("3. All (panorama)")
                lens = input("Select lens: ").strip()
                if lens in ["1", "2", "3"]:
                    controller.switch_lens(int(lens))

            elif choice == "7":
                status = controller.get_status()
                print(f"Status: {status}")

            elif choice == "0":
                break

    except KeyboardInterrupt:
        print("\nExiting...")
    finally:
        controller.disconnect()


if __name__ == "__main__":
    interactive_menu()
