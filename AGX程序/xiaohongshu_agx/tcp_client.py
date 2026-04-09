#!/usr/bin/env python3
"""
TCP H264 Client - 连接板子上的TCP H264服务器
"""

import socket
import struct
import sys
import subprocess


def receive_and_play(host, port):
    """接收TCP H264流并用FFmpeg播放"""

    print(f"Connecting to {host}:{port}...")

    # 创建TCP连接
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((host, port))
    print("Connected! Starting FFmpeg...")

    # 启动FFmpeg解码H264并播放
    # 从stdin接收H264，输出到SDL窗口
    ffmpeg_cmd = [
        "ffplay",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "h264",  # 输入格式H264
        "-i",
        "pipe:0",  # 从stdin读取
        "-fflags",
        "nobuffer",  # 无缓冲
        "-flags",
        "low_delay",  # 低延迟
        "-vf",
        "scale=1280:640",  # 缩放降低显示压力（可选）
        "-window_title",
        "Insta360 X5",
    ]

    ffmpeg = subprocess.Popen(ffmpeg_cmd, stdin=subprocess.PIPE)

    try:
        frame_count = 0
        while True:
            # 接收4字节长度头（网络字节序）
            length_bytes = b""
            while len(length_bytes) < 4:
                chunk = sock.recv(4 - len(length_bytes))
                if not chunk:
                    raise ConnectionError("Server disconnected")
                length_bytes += chunk

            length = struct.unpack("!I", length_bytes)[0]

            # 限制单帧大小防止异常
            if length > 10 * 1024 * 1024:  # 最大10MB
                print(f"Warning: Large frame {length} bytes, skipping")
                continue

            # 接收完整H264帧
            data = b""
            while len(data) < length:
                chunk = sock.recv(min(65536, length - len(data)))
                if not chunk:
                    raise ConnectionError("Server disconnected")
                data += chunk

            # 送入FFmpeg
            ffmpeg.stdin.write(data)
            ffmpeg.stdin.flush()

            frame_count += 1
            if frame_count % 30 == 0:
                print(f"Received {frame_count} frames")

    except KeyboardInterrupt:
        print("\nStopping...")
    except ConnectionError as e:
        print(f"\nConnection error: {e}")
    finally:
        sock.close()
        ffmpeg.terminate()
        try:
            ffmpeg.wait(timeout=2)
        except:
            ffmpeg.kill()
        print("Disconnected")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: python {sys.argv[0]} <server_ip> [port]")
        print(f"Example: python {sys.argv[0]} 192.168.88.189 8888")
        print(f"\nRequirements: ffmpeg must be in PATH")
        sys.exit(1)

    host = sys.argv[1]
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 8888

    receive_and_play(host, port)
