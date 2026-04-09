#!/usr/bin/env python3
"""
TCP H264 多模态大模型推理客户端
- 连接 TCP H264 服务器接收视频流
- 解码后定期抽帧进行多模态推理
"""

import socket
import struct
import sys
import os
import cv2
import time
import tempfile
import subprocess
import numpy as np
from collections import deque

# ==================== 配置项 ====================
# TCP 连接配置
DEFAULT_HOST = "192.168.88.189"
DEFAULT_PORT = 8888

# 模型配置
LLAMA_BIN = "/home/hhws/llama.cpp/build/bin/llama-mtmd-cli"
MODEL = "/home/hhws/models/MiniCPM-V-4_5-Q4_K_M.gguf"
MMPROJ = "/home/hhws/models/mmproj-model-f16.gguf"

# 推理配置
PROMPT = "请理解这一帧所属的视频内容，并简洁描述当前场景、主体和动作。"
SAMPLE_INTERVAL = 2.0  # 每 2 秒推理一次
MAX_RETRIES = 3  # 推理失败重试次数

# H264 解码配置
H264_BUFFER_SIZE = 10 * 1024 * 1024  # 最大帧大小 10MB


def infer_image(image_path: str) -> str:
    """使用多模态大模型推理单帧图像"""
    cmd = [
        LLAMA_BIN,
        "-m", MODEL,
        "--mmproj", MMPROJ,
        "-c", "4096",
        "--image", image_path,
        "-p", PROMPT,
    ]
    
    for attempt in range(MAX_RETRIES):
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            return result.stdout.strip()
        print(f"  推理失败 (尝试 {attempt + 1}/{MAX_RETRIES}): {result.stderr[:200]}")
        time.sleep(0.5)
    
    return f"[ERROR] 推理失败\n{result.stderr[:500]}"


class H264Decoder:
    """H264 解码器 - 累积数据并解码为帧"""
    
    def __init__(self):
        self.codec = cv2.VideoWriter_fourcc(*'H264')
        # 使用 OpenCV 的 VideoCapture 配合内存缓冲区
        self.buffer = b""
        self.temp_file = None
        self.cap = None
        self.frame_buffer = deque(maxlen=5)  # 缓存最近几帧
        self._init_decoder()
    
    def _init_decoder(self):
        """初始化解码器"""
        # 创建临时文件用于存储 H264 数据流
        self.temp_fd, self.temp_file = tempfile.mkstemp(suffix=".h264")
        os.close(self.temp_fd)
        
    def feed_data(self, data: bytes) -> list:
        """
        喂入 H264 数据，尝试解码出帧
        返回解码出的帧列表
        """
        frames = []
        self.buffer += data
        
        # 当缓冲区足够大时尝试解码
        if len(self.buffer) > 1024:
            # 写入临时文件
            with open(self.temp_file, 'wb') as f:
                f.write(self.buffer)
            
            # 尝试用 OpenCV 读取
            if self.cap is None:
                self.cap = cv2.VideoCapture(self.temp_file)
                self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'H264'))
            else:
                self.cap.release()
                self.cap = cv2.VideoCapture(self.temp_file)
            
            # 读取所有可用帧
            while True:
                ok, frame = self.cap.read()
                if not ok:
                    break
                frames.append(frame)
                self.frame_buffer.append(frame)
        
        # 限制缓冲区大小，防止内存无限增长
        if len(self.buffer) > H264_BUFFER_SIZE:
            # 保留后半部分，可能包含不完整的帧
            self.buffer = self.buffer[-H264_BUFFER_SIZE // 2:]
        
        return frames
    
    def get_latest_frame(self):
        """获取最新的一帧"""
        if self.frame_buffer:
            return self.frame_buffer[-1]
        return None
    
    def release(self):
        """释放资源"""
        if self.cap:
            self.cap.release()
        if self.temp_file and os.path.exists(self.temp_file):
            os.remove(self.temp_file)


def receive_and_infer(host: str, port: int):
    """接收 TCP H264 流并进行多模态推理"""
    
    print(f"Connecting to {host}:{port}...")
    
    # 创建 TCP 连接
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(10.0)
    try:
        sock.connect((host, port))
    except socket.error as e:
        print(f"连接失败: {e}")
        return
    
    print("Connected! Starting inference loop...")
    print(f"模型: {MODEL}")
    print(f"采样间隔: {SAMPLE_INTERVAL} 秒")
    print("-" * 50)
    
    decoder = H264Decoder()
    last_infer_time = 0
    frame_count = 0
    
    try:
        while True:
            # 接收 4 字节长度头（网络字节序）
            length_bytes = b""
            while len(length_bytes) < 4:
                try:
                    chunk = sock.recv(4 - len(length_bytes))
                    if not chunk:
                        raise ConnectionError("Server disconnected")
                    length_bytes += chunk
                except socket.timeout:
                    continue
            
            length = struct.unpack("!I", length_bytes)[0]
            
            # 限制单帧大小防止异常
            if length > H264_BUFFER_SIZE:
                print(f"Warning: Large frame {length} bytes, skipping")
                # 跳过这帧数据
                remaining = length
                while remaining > 0:
                    skip = min(65536, remaining)
                    chunk = sock.recv(skip)
                    if not chunk:
                        raise ConnectionError("Server disconnected")
                    remaining -= len(chunk)
                continue
            
            # 接收完整 H264 帧
            frame_data = b""
            while len(frame_data) < length:
                chunk = sock.recv(min(65536, length - len(frame_data)))
                if not chunk:
                    raise ConnectionError("Server disconnected")
                frame_data += chunk
            
            # 解码 H264 数据
            decoded_frames = decoder.feed_data(frame_data)
            frame_count += len(decoded_frames)
            
            # 检查是否需要进行推理
            current_time = time.time()
            if current_time - last_infer_time >= SAMPLE_INTERVAL:
                latest_frame = decoder.get_latest_frame()
                if latest_frame is not None:
                    # 保存帧为临时图像
                    fd, img_path = tempfile.mkstemp(suffix=".jpg")
                    os.close(fd)
                    
                    try:
                        cv2.imwrite(img_path, latest_frame)
                        print(f"\n[{time.strftime('%H:%M:%S')}] Frame #{frame_count} 推理中...")
                        
                        answer = infer_image(img_path)
                        print(f"描述: {answer}")
                        print("-" * 50)
                        
                        last_infer_time = current_time
                    finally:
                        if os.path.exists(img_path):
                            os.remove(img_path)
    
    except KeyboardInterrupt:
        print("\n\n用户中断，停止推理...")
    except ConnectionError as e:
        print(f"\n连接错误: {e}")
    except Exception as e:
        print(f"\n错误: {e}")
        import traceback
        traceback.print_exc()
    finally:
        sock.close()
        decoder.release()
        print(f"\n总计接收 {frame_count} 帧，已断开连接")


def main():
    if len(sys.argv) < 2:
        print(f"Usage: python {sys.argv[0]} <server_ip> [port]")
        print(f"Example: python {sys.argv[0]} {DEFAULT_HOST} {DEFAULT_PORT}")
        print(f"\n要求:")
        print(f"  - OpenCV (cv2) 已安装")
        print(f"  - llama-mtmd-cli 在: {LLAMA_BIN}")
        print(f"  - 模型文件: {MODEL}")
        print(f"  - mmproj 文件: {MMPROJ}")
        sys.exit(1)
    
    host = sys.argv[1]
    port = int(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_PORT
    
    # 检查模型文件是否存在
    for path, name in [(LLAMA_BIN, "llama-mtmd-cli"), (MODEL, "模型"), (MMPROJ, "mmproj")]:
        if not os.path.exists(path):
            print(f"错误: 找不到 {name}: {path}")
            sys.exit(1)
    
    receive_and_infer(host, port)


if __name__ == "__main__":
    main()
