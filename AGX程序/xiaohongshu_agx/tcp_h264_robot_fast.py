#!/usr/bin/env python3
"""
TCP H264 机器人视觉决策推理客户端 (高速版本)
- 异步推理：视频流和推理并行，不互相等待
- 更低分辨率：默认 384x192
- 连续模式：尽可能快地推理
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

# 分辨率配置 - 更低分辨率 = 更快
INFER_WIDTH = 384
INFER_HEIGHT = 192
JPEG_QUALITY = 80  # 稍微降低质量提高速度

# GPU 配置
USE_GPU = True

# 推理配置
MIN_INTERVAL = 0.2  # 最小推理间隔 0.2秒 (5fps)
MAX_RETRIES = 2

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

# 全局统计
stats = {
    'frames_received': 0,
    'frames_inferred': 0,
    'inference_time': 0,
    'last_cmd': None,
    'last_cmd_time': 0
}


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


def infer_worker(frame_queue: queue.Queue, result_queue: queue.Queue, use_gpu: bool):
    """
    推理工作线程：持续从队列取帧进行推理
    单线程串行推理，避免 GPU 内存竞争
    """
    while True:
        try:
            # 获取最新帧（如果队列有积压，只取最新的一帧）
            frame_data = None
            while not frame_queue.empty():
                try:
                    frame_data = frame_queue.get_nowait()
                except queue.Empty:
                    break
            
            if frame_data is None:
                try:
                    frame_data = frame_queue.get(timeout=0.1)
                except queue.Empty:
                    continue
            
            frame, frame_id, timestamp = frame_data
            
            # 保存临时图片
            fd, img_path = tempfile.mkstemp(suffix=".jpg")
            os.close(fd)
            cv2.imwrite(img_path, frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
            
            # 构建命令 - 更激进的快速参数
            cmd = [
                LLAMA_BIN,
                "-m", MODEL,
                "--mmproj", MMPROJ,
                "-c", "1024",           # 减少上下文
                "--image", img_path,
                "--system-prompt", SYSTEM_PROMPT,
                "-p", USER_PROMPT,
                "--temp", "0.05",       # 更低温度，更确定性
                "--top-p", "0.5",       # 更小的采样范围
                "--top-k", "10",        # 更小的top-k
                "-n", "30",             # 更少的输出token
                "--no-display-prompt",  # 不显示prompt
            ]
            
            if use_gpu:
                cmd.extend(["--gpu-layers", "all"])
                cmd.append("--mmproj-offload")
            
            # 执行推理
            start_time = time.time()
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            infer_time = time.time() - start_time
            
            os.remove(img_path)
            
            if result.returncode == 0:
                raw_output = result.stdout.strip()
                # 如果 stdout 为空但 stderr 有内容（如 CUDA 日志），尝试从 stderr 获取
                if not raw_output and result.stderr:
                    # 过滤掉 CUDA 初始化日志，保留可能的错误
                    stderr_lines = result.stderr.strip().split('\n')
                    non_cuda_lines = [l for l in stderr_lines if 'cuda' not in l.lower() and 'ggml' not in l.lower()]
                    if non_cuda_lines:
                        raw_output = '\n'.join(non_cuda_lines)
                cleaned = validate_and_clean_output(raw_output)
                result_queue.put({
                    'frame_id': frame_id,
                    'timestamp': timestamp,
                    'result': cleaned,
                    'infer_time': infer_time
                })
            else:
                # 真正的错误
                # 过滤掉 CUDA 初始化日志
                err_lines = result.stderr.strip().split('\n') if result.stderr else []
                real_errors = [l for l in err_lines if 'cuda' not in l.lower() and 'ggml' not in l.lower() and 'vram' not in l.lower()]
                err_msg = real_errors[0][:100] if real_errors else "model error"
                result_queue.put({
                    'frame_id': frame_id,
                    'timestamp': timestamp,
                    'result': f"[ERROR] {err_msg}",
                    'infer_time': infer_time
                })
                
        except Exception as e:
            print(f"推理线程错误: {e}")
            time.sleep(0.1)


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
            stats['frames_received'] += 1
    except Exception as e:
        print(f"\n接收线程退出: {e}")


def run_inference(host: str, port: int, use_gpu: bool, min_interval: float):
    """主推理循环 - 异步版本"""
    print(f"Connecting to {host}:{port}...")
    
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(30.0)
    try:
        sock.connect((host, port))
    except socket.error as e:
        print(f"连接失败: {e}")
        return
    
    print("Connected!")
    print(f"推理分辨率: {INFER_WIDTH}x{INFER_HEIGHT}")
    print(f"推理设备: {'GPU (CUDA)' if use_gpu else 'CPU'}")
    print(f"最小间隔: {min_interval} 秒")
    print("=" * 50)
    
    # 启动接收线程
    packet_queue = queue.Queue(maxsize=100)
    recv_thread = threading.Thread(target=tcp_receiver, args=(sock, packet_queue))
    recv_thread.daemon = True
    recv_thread.start()
    
    # 启动 FFmpeg 解码进程
    ffmpeg_cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel", "error",
        "-f", "h264",
        "-i", "pipe:0",
        "-f", "rawvideo",
        "-pix_fmt", "bgr24",
        "-s", "1280x720",
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
    
    # 创建推理队列和结果队列
    infer_queue = queue.Queue(maxsize=2)  # 只保留最新2帧
    result_queue = queue.Queue()
    
    # 启动推理线程
    infer_thread = threading.Thread(target=infer_worker, args=(infer_queue, result_queue, use_gpu))
    infer_thread.daemon = True
    infer_thread.start()
    
    # 读取 FFmpeg 输出
    frame_width, frame_height = 1280, 720
    frame_size = frame_width * frame_height * 3
    
    last_infer_time = 0
    frame_count = 0
    last_print_time = 0
    
    try:
        while True:
            # 读取一帧 raw 数据
            raw_frame = ffmpeg_proc.stdout.read(frame_size)
            if len(raw_frame) != frame_size:
                time.sleep(0.001)
                continue
            
            frame_count += 1
            
            # 转换为 numpy 数组
            frame = np.frombuffer(raw_frame, dtype=np.uint8).reshape((frame_height, frame_width, 3))
            
            # 检查是否需要推理（控制最小间隔）
            current_time = time.time()
            if current_time - last_infer_time >= min_interval:
                # 降低分辨率
                infer_frame = cv2.resize(frame, (INFER_WIDTH, INFER_HEIGHT))
                
                # 将帧放入推理队列（如果队列满，丢弃旧的）
                try:
                    infer_queue.put_nowait((infer_frame, frame_count, current_time))
                except queue.Full:
                    # 队列满，移除最旧的，放入最新的
                    try:
                        infer_queue.get_nowait()
                        infer_queue.put_nowait((infer_frame, frame_count, current_time))
                    except queue.Empty:
                        pass
                
                last_infer_time = current_time
            
            # 检查结果队列（非阻塞）
            try:
                while not result_queue.empty():
                    result = result_queue.get_nowait()
                    stats['frames_inferred'] += 1
                    stats['inference_time'] = result['infer_time']
                    
                    ts = datetime.fromtimestamp(result['timestamp']).strftime("%H:%M:%S.%f")[:-3]
                    print(f"\n[{ts}] 帧#{result['frame_id']} 推理耗时:{result['infer_time']:.2f}s")
                    
                    if result['result'] == "[NO_VALID_CMD]":
                        print("指令: (无)")
                    elif result['result'].startswith("[ERROR]"):
                        print(f"指令: {result['result']}")
                    else:
                        print(f"指令:\n{result['result']}")
                        stats['last_cmd'] = result['result']
                        stats['last_cmd_time'] = time.time()
                    
                    # 打印统计
                    fps_recv = stats['frames_received'] / (current_time - last_print_time) if last_print_time > 0 else 0
                    print(f"[统计] 接收:{stats['frames_received']} 推理:{stats['frames_inferred']} 耗时:{result['infer_time']:.2f}s")
                    
            except queue.Empty:
                pass
            
            # 每秒打印一次状态
            if current_time - last_print_time >= 1.0:
                last_print_time = current_time
                
    except KeyboardInterrupt:
        print("\n用户中断")
    finally:
        ffmpeg_proc.terminate()
        sock.close()
        print(f"\n总计: 接收 {stats['frames_received']} 帧, 推理 {stats['frames_inferred']} 次")


def main():
    global INFER_WIDTH, INFER_HEIGHT
    
    if len(sys.argv) < 2:
        print(f"Usage: python {sys.argv[0]} <server_ip> [port]")
        print(f"Example: python {sys.argv[0]} {DEFAULT_HOST} {DEFAULT_PORT}")
        print(f"\n选项:")
        print(f"  --interval N      最小推理间隔秒数 (默认: {MIN_INTERVAL})")
        print(f"  --cpu             使用 CPU 推理")
        print(f"  --res WxH         推理分辨率 (默认: {INFER_WIDTH}x{INFER_HEIGHT})")
        sys.exit(1)
    
    host = sys.argv[1]
    port = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].isdigit() else DEFAULT_PORT
    
    use_gpu = USE_GPU
    min_interval = MIN_INTERVAL
    
    if "--cpu" in sys.argv:
        use_gpu = False
    for i, arg in enumerate(sys.argv):
        if arg == "--interval" and i + 1 < len(sys.argv):
            min_interval = float(sys.argv[i + 1])
        if arg == "--res" and i + 1 < len(sys.argv):
            res_str = sys.argv[i + 1]
            if 'x' in res_str:
                w, h = res_str.split('x')
                INFER_WIDTH = int(w)
                INFER_HEIGHT = int(h)
    
    # 检查依赖
    for path, name in [(LLAMA_BIN, "llama-mtmd-cli"), (MODEL, "模型"), (MMPROJ, "mmproj")]:
        if not os.path.exists(path):
            print(f"错误: 找不到 {name}: {path}")
            sys.exit(1)
    
    run_inference(host, port, use_gpu, min_interval)


if __name__ == "__main__":
    main()
