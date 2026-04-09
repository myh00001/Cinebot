#!/usr/bin/env python3
"""
TCP H264 多模态大模型推理客户端 (最终版)
- 接收 TCP H264 流，定期抽帧保存为图片
- 使用多模态大模型进行推理
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
import signal
from datetime import datetime

# ==================== 配置 ====================
DEFAULT_HOST = "192.168.88.189"
DEFAULT_PORT = 8888

LLAMA_BIN = "/home/hhws/llama.cpp/build/bin/llama-mtmd-cli"
MODEL = "/home/hhws/models/MiniCPM-V-4_5-Q4_K_M.gguf"
MMPROJ = "/home/hhws/models/mmproj-model-f16.gguf"

PROMPT = "请理解这一帧所属的视频内容，并简洁描述当前场景、主体和动作。"
SAMPLE_INTERVAL = 2.0  # 推理间隔（秒）
SHOW_VIDEO = True      # 是否显示视频
SCALE_WIDTH = 640      # 显示宽度

running = True


def check_dependencies():
    """检查必要文件是否存在"""
    deps = [
        (LLAMA_BIN, "llama-mtmd-cli"),
        (MODEL, "模型文件"),
        (MMPROJ, "mmproj 文件"),
    ]
    for path, name in deps:
        if not os.path.exists(path):
            print(f"错误: 找不到 {name}: {path}")
            return False
    return True


def infer_image(image_path: str, frame_info: str = "") -> str:
    """多模态推理"""
    cmd = [
        LLAMA_BIN,
        "-m", MODEL,
        "--mmproj", MMPROJ,
        "-c", "4096",
        "--image", image_path,
        "-p", PROMPT,
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode == 0:
        return result.stdout.strip()
    return f"[ERROR] {result.stderr[:200]}"


def h264_to_frame(h264_file: str, output_jpg: str) -> bool:
    """将 H264 文件转换为 JPG 帧（取最后一帧）"""
    # 先用 ffmpeg 封装为 mp4，然后用 OpenCV 读取
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
        tmp_mp4 = tmp.name
    
    try:
        # H264 -> MP4
        r = subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-f", "h264", "-i", h264_file,
             "-c", "copy", tmp_mp4],
            capture_output=True
        )
        
        if r.returncode != 0:
            return False
        
        # 读取最后一帧
        cap = cv2.VideoCapture(tmp_mp4)
        if not cap.isOpened():
            return False
        
        last_frame = None
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            last_frame = frame
        cap.release()
        
        if last_frame is not None:
            cv2.imwrite(output_jpg, last_frame)
            return True
        return False
    
    finally:
        if os.path.exists(tmp_mp4):
            os.remove(tmp_mp4)


def receive_and_infer(host: str, port: int):
    """主循环：接收 H264 流并推理"""
    global running
    
    print(f"Connecting to {host}:{port}...")
    
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(30.0)
    try:
        sock.connect((host, port))
    except socket.error as e:
        print(f"连接失败: {e}")
        return
    
    print("Connected! 开始接收视频流...")
    print(f"推理间隔: {SAMPLE_INTERVAL} 秒")
    print("按 Ctrl+C 停止\n")
    
    # 临时文件
    temp_h264 = tempfile.mktemp(suffix=".h264")
    temp_jpg = tempfile.mktemp(suffix=".jpg")
    
    frame_count = 0
    packet_count = 0
    last_infer_time = time.time()
    
    try:
        with open(temp_h264, 'wb') as h264_f:
            while running:
                # 设置接收超时，以便定期检查 running 状态
                sock.settimeout(1.0)
                
                try:
                    # 接收 4 字节长度头
                    header = b""
                    while len(header) < 4:
                        chunk = sock.recv(4 - len(header))
                        if not chunk:
                            raise ConnectionError("Server disconnected")
                        header += chunk
                    
                    length = struct.unpack("!I", header)[0]
                    
                    # 安全检查
                    if length > 10 * 1024 * 1024 or length == 0:
                        print(f"Warning: 异常帧大小 {length}, 跳过")
                        continue
                    
                    # 接收帧数据
                    data = b""
                    while len(data) < length:
                        remaining = length - len(data)
                        chunk = sock.recv(min(65536, remaining))
                        if not chunk:
                            raise ConnectionError("Server disconnected")
                        data += chunk
                    
                    # 写入 H264 文件
                    h264_f.write(data)
                    h264_f.flush()
                    packet_count += 1
                    
                    # 定期推理
                    current_time = time.time()
                    if current_time - last_infer_time >= SAMPLE_INTERVAL:
                        # 转换为图片
                        if h264_to_frame(temp_h264, temp_jpg):
                            # 显示
                            if SHOW_VIDEO:
                                frame = cv2.imread(temp_jpg)
                                if frame is not None:
                                    h, w = frame.shape[:2]
                                    scale = SCALE_WIDTH / w
                                    display = cv2.resize(frame, (SCALE_WIDTH, int(h * scale)))
                                    cv2.imshow("TCP H264 Stream", display)
                                    cv2.waitKey(1)
                            
                            # 推理
                            frame_count += 1
                            timestamp = datetime.now().strftime("%H:%M:%S")
                            print(f"[{timestamp}] 第 {frame_count} 次推理...")
                            answer = infer_image(temp_jpg, f"frame_{frame_count}")
                            print(f"  → {answer}\n")
                            
                            last_infer_time = current_time
                            
                            # 清空 H264 文件，避免无限增长
                            h264_f.close()
                            h264_f = open(temp_h264, 'wb')
                
                except socket.timeout:
                    continue
    
    except ConnectionError as e:
        print(f"\n连接断开: {e}")
    except KeyboardInterrupt:
        print("\n用户中断")
    finally:
        running = False
        sock.close()
        try:
            cv2.destroyAllWindows()
        except:
            pass
        for f in [temp_h264, temp_jpg]:
            if os.path.exists(f):
                os.remove(f)
        print(f"\n总计: {packet_count} 个包, {frame_count} 次推理")


def signal_handler(sig, frame):
    """处理 Ctrl+C"""
    global running
    print("\n正在停止...")
    running = False


def main():
    global SAMPLE_INTERVAL, SHOW_VIDEO
    
    if len(sys.argv) < 2:
        print(f"Usage: python {sys.argv[0]} <server_ip> [port]")
        print(f"Example: python {sys.argv[0]} {DEFAULT_HOST} {DEFAULT_PORT}")
        print(f"\n选项:")
        print(f"  --no-display      不显示视频窗口")
        print(f"  --interval N      推理间隔 N 秒 (默认: {SAMPLE_INTERVAL})")
        sys.exit(1)
    
    host = sys.argv[1]
    port = DEFAULT_PORT
    
    # 解析参数
    for i, arg in enumerate(sys.argv[2:], 2):
        if arg.isdigit():
            port = int(arg)
        elif arg == "--no-display":
            SHOW_VIDEO = False
        elif arg == "--interval" and i + 1 < len(sys.argv):
            SAMPLE_INTERVAL = float(sys.argv[i + 1])
    
    # 检查依赖
    if not check_dependencies():
        sys.exit(1)
    
    # 注册信号处理
    signal.signal(signal.SIGINT, signal_handler)
    
    # 启动
    receive_and_infer(host, port)


if __name__ == "__main__":
    main()
