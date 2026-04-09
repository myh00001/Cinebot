#!/usr/bin/env python3
"""
TCP H264 机器人视觉决策推理客户端 (GPU 版本)
- 使用 FFmpeg 实时解码 H264 流
- GPU 推理
- 严格限制输出格式
"""

import socket
import struct
import sys
import os
import cv2
import time
import tempfile
import subprocess
import threading
import queue
import re
import numpy as np
from datetime import datetime

# ==================== 配置项 ====================
DEFAULT_HOST = "192.168.88.189"
DEFAULT_PORT = 8888

# 模型配置
LLAMA_BIN = "/home/hhws/llama.cpp/build/bin/llama-mtmd-cli"
MODEL = "/home/hhws/models/MiniCPM-V-4_5-Q4_K_M.gguf"
MMPROJ = "/home/hhws/models/mmproj-model-f16.gguf"

# 分辨率配置
INFER_WIDTH = 640
INFER_HEIGHT = 320
JPEG_QUALITY = 85

# GPU 配置
USE_GPU = True

# 推理配置
SAMPLE_INTERVAL = 0.5
MAX_RETRIES = 3

# System Prompt
SYSTEM_PROMPT = """你是全景相机移动机器人视觉决策助手。

你只能输出流式原子指令，不允许输出解释，不允许输出 JSON，不允许输出 Markdown。

可输出的行只有三种：

1. V <DIR> <STEP>
DIR 只能是：L R U D H
STEP 是整数，范围 0~400
DIR=H 时 STEP=0

2. C <DIR> <SPEED> <DURATION_MS>
DIR 只能是：F B L R S
SPEED 只能是：0 1 2 3
DURATION_MS 范围 80~500
DIR=S 时 SPEED=0

3. A <ACTION>
ACTION 只能是：NO RS RE PH TS TE

规则：
- 输入是一张来自实时全景视频流的当前帧
- 图中有一个红色矩形框，表示当前取景窗口
- 红框初始默认在画面中心
- V 指令用于移动红框
- C 指令用于控制底盘
- A 指令用于控制动作
- 优先输出最可执行、最紧急的控制
- 如果目标在红框左侧，优先输出 V L
- 如果目标在红框右侧，优先输出 V R
- 如果目标在红框上方，优先输出 V U
- 如果目标在红框下方，优先输出 V D
- 如果目标离机器人较远，优先输出 C F
- 如果目标离机器人较近，优先输出 C B
- 如果需要横向跟拍，可用 C L / C R
- 如果目标稳定处于红框中且画面稳定，优先输出 V H 0 和 C S 0 100
- 如果目标丢失，优先输出 C S 0 100
- 全景图左右边界连通，不能因为拼接边界误判目标丢失
- 输出尽量短，通常 1~2 行
- 不要输出任何额外内容
"""

USER_PROMPT = "分析当前帧，输出机器人控制指令。"


def validate_and_clean_output(output: str) -> str:
    """验证并清理模型输出"""
    valid_lines = []
    lines = output.strip().split('\n')
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        # V 指令
        v_pattern = r'^V\s+([LRUDH])\s+(\d+)$'
        v_match = re.match(v_pattern, line)
        if v_match:
            dir_val = v_match.group(1)
            step_val = int(v_match.group(2))
            if 0 <= step_val <= 400:
                if dir_val == 'H':
                    step_val = 0
                valid_lines.append(f"V {dir_val} {step_val}")
                continue
        
        # C 指令
        c_pattern = r'^C\s+([FBLRS])\s+(\d+)\s+(\d+)$'
        c_match = re.match(c_pattern, line)
        if c_match:
            dir_val = c_match.group(1)
            speed_val = int(c_match.group(2))
            duration_val = int(c_match.group(3))
            if 0 <= speed_val <= 3 and 80 <= duration_val <= 500:
                if dir_val == 'S':
                    speed_val = 0
                valid_lines.append(f"C {dir_val} {speed_val} {duration_val}")
                continue
        
        # A 指令
        a_pattern = r'^A\s+(NO|RS|RE|PH|TS|TE)$'
        a_match = re.match(a_pattern, line)
        if a_match:
            valid_lines.append(line)
            continue
    
    return '\n'.join(valid_lines) if valid_lines else "[NO_VALID_CMD]"


def infer_image(image_path: str, use_gpu: bool) -> str:
    """使用多模态大模型推理（支持 GPU）"""
    cmd = [
        LLAMA_BIN,
        "-m", MODEL,
        "--mmproj", MMPROJ,
        "-c", "2048",
        "--image", image_path,
        "--system-prompt", SYSTEM_PROMPT,
        "-p", USER_PROMPT,
        "--temp", "0.1",
        "--top-p", "0.9",
        "--top-k", "40",
        "-n", "50",
    ]
    
    if use_gpu:
        cmd.extend(["--gpu-layers", "all"])
        cmd.append("--mmproj-offload")
    
    for attempt in range(MAX_RETRIES):
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if result.returncode == 0:
                raw_output = result.stdout.strip()
                return validate_and_clean_output(raw_output)
            else:
                err = result.stderr[:200] if result.stderr else "unknown error"
                print(f"  推理错误: {err}")
        except subprocess.TimeoutExpired:
            print(f"  推理超时 (尝试 {attempt + 1}/{MAX_RETRIES})")
        except Exception as e:
            print(f"  推理异常: {e}")
        time.sleep(0.5)
    
    return "[ERROR]"


def tcp_receiver(sock: socket.socket, packet_queue: queue.Queue):
    """接收线程：从 TCP 接收 H264 数据包"""
    try:
        while True:
            # 接收 4 字节长度头
            length_bytes = b""
            while len(length_bytes) < 4:
                chunk = sock.recv(4 - len(length_bytes))
                if not chunk:
                    return
                length_bytes += chunk
            
            length = struct.unpack("!I", length_bytes)[0]
            
            if length > 10 * 1024 * 1024:
                # 跳过异常大的包
                remaining = length
                while remaining > 0:
                    chunk = sock.recv(min(65536, remaining))
                    if not chunk:
                        return
                    remaining -= len(chunk)
                continue
            
            # 接收完整帧
            frame_data = b""
            while len(frame_data) < length:
                chunk = sock.recv(min(65536, length - len(frame_data)))
                if not chunk:
                    return
                frame_data += chunk
            
            packet_queue.put(frame_data)
    except Exception as e:
        print(f"\n接收线程退出: {e}")


def run_inference(host: str, port: int, use_gpu: bool, sample_interval: float):
    """主推理循环"""
    print(f"Connecting to {host}:{port}...")
    
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(30.0)
    try:
        sock.connect((host, port))
    except socket.error as e:
        print(f"连接失败: {e}")
        return
    
    print("Connected!")
    print(f"推理设备: {'GPU (CUDA)' if use_gpu else 'CPU'}")
    print(f"采样间隔: {sample_interval} 秒")
    print("-" * 50)
    
    # 启动接收线程
    packet_queue = queue.Queue(maxsize=200)
    recv_thread = threading.Thread(target=tcp_receiver, args=(sock, packet_queue))
    recv_thread.daemon = True
    recv_thread.start()
    
    # 启动 FFmpeg 解码进程
    # 从 stdin 读取 H264，输出 raw 帧
    ffmpeg_cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel", "error",
        "-f", "h264",
        "-i", "pipe:0",
        "-f", "rawvideo",
        "-pix_fmt", "bgr24",
        "-s", "1280x720",  # 假设输入分辨率，FFmpeg 会自动处理
        "pipe:1"
    ]
    
    ffmpeg_proc = subprocess.Popen(
        ffmpeg_cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    
    # 线程：将收到的包喂给 FFmpeg
    def feed_ffmpeg():
        try:
            while True:
                try:
                    data = packet_queue.get(timeout=5.0)
                    if ffmpeg_proc.stdin and not ffmpeg_proc.stdin.closed:
                        ffmpeg_proc.stdin.write(data)
                        ffmpeg_proc.stdin.flush()
                except queue.Empty:
                    continue
                except (BrokenPipeError, OSError):
                    break
        except Exception as e:
            print(f"Feed thread error: {e}")
    
    feed_thread = threading.Thread(target=feed_ffmpeg)
    feed_thread.daemon = True
    feed_thread.start()
    
    # 读取 FFmpeg 输出并推理
    frame_width, frame_height = 1280, 720
    frame_size = frame_width * frame_height * 3
    
    last_infer_time = 0
    frame_count = 0
    
    try:
        while True:
            # 读取一帧 raw 数据
            raw_frame = ffmpeg_proc.stdout.read(frame_size)
            if len(raw_frame) != frame_size:
                time.sleep(0.01)
                continue
            
            frame_count += 1
            
            # 转换为 numpy 数组
            frame = np.frombuffer(raw_frame, dtype=np.uint8).reshape((frame_height, frame_width, 3))
            
            # 检查是否需要推理
            current_time = time.time()
            if current_time - last_infer_time >= sample_interval:
                # 降低分辨率用于推理
                infer_frame = cv2.resize(frame, (INFER_WIDTH, INFER_HEIGHT))
                
                # 保存并推理
                fd, img_path = tempfile.mkstemp(suffix=".jpg")
                os.close(fd)
                try:
                    cv2.imwrite(img_path, infer_frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
                    
                    timestamp = datetime.now().strftime("%H:%M:%S")
                    print(f"\n[{timestamp}] 第 {frame_count} 帧 (推理 {INFER_WIDTH}x{INFER_HEIGHT})")
                    
                    answer = infer_image(img_path, use_gpu)
                    
                    if answer == "[NO_VALID_CMD]":
                        print("指令: (无有效指令)")
                    elif answer.startswith("[ERROR]"):
                        print(f"指令: {answer}")
                    else:
                        print(f"指令:\n{answer}")
                    print("-" * 50)
                    
                    last_infer_time = current_time
                finally:
                    os.remove(img_path)
    
    except KeyboardInterrupt:
        print("\n用户中断")
    finally:
        ffmpeg_proc.terminate()
        sock.close()
        print(f"\n总计处理 {frame_count} 帧")


def main():
    if len(sys.argv) < 2:
        print(f"Usage: python {sys.argv[0]} <server_ip> [port]")
        print(f"Example: python {sys.argv[0]} {DEFAULT_HOST} {DEFAULT_PORT}")
        print(f"\n选项:")
        print(f"  --interval N      设置推理间隔为 N 秒 (默认: 0.5)")
        print(f"  --cpu             使用 CPU 推理 (默认使用 GPU)")
        sys.exit(1)
    
    host = sys.argv[1]
    port = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].isdigit() else DEFAULT_PORT
    
    use_gpu = USE_GPU
    sample_interval = SAMPLE_INTERVAL
    
    if "--cpu" in sys.argv:
        use_gpu = False
    for i, arg in enumerate(sys.argv):
        if arg == "--interval" and i + 1 < len(sys.argv):
            sample_interval = float(sys.argv[i + 1])
    
    # 检查依赖
    for path, name in [(LLAMA_BIN, "llama-mtmd-cli"), (MODEL, "模型"), (MMPROJ, "mmproj")]:
        if not os.path.exists(path):
            print(f"错误: 找不到 {name}: {path}")
            sys.exit(1)
    
    run_inference(host, port, use_gpu, sample_interval)


if __name__ == "__main__":
    main()
