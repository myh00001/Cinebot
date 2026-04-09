#!/usr/bin/env python3
"""
TCP H264 多模态大模型推理客户端 (v2 - 使用 FFmpeg 解码)
- 连接 TCP H264 服务器接收视频流
- 使用 FFmpeg 解码后定期抽帧进行多模态推理
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
from datetime import datetime

# ==================== 配置项 ====================
DEFAULT_HOST = "192.168.88.189"
DEFAULT_PORT = 8888

# 模型配置
LLAMA_BIN = "/home/hhws/llama.cpp/build/bin/llama-mtmd-cli"
MODEL = "/home/hhws/models/MiniCPM-V-4_5-Q4_K_M.gguf"
MMPROJ = "/home/hhws/models/mmproj-model-f16.gguf"

# 推理配置
PROMPT = "请理解这一帧所属的视频内容，并简洁描述当前场景、主体和动作。"
SAMPLE_INTERVAL = 2.0  # 每 2 秒推理一次
MAX_RETRIES = 3

# 显示配置
SHOW_VIDEO = True  # 是否显示视频窗口
SCALE_WIDTH = 640  # 显示缩放宽度


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
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode == 0:
            return result.stdout.strip()
        print(f"  推理失败 (尝试 {attempt + 1}/{MAX_RETRIES})")
        time.sleep(0.5)
    
    return f"[ERROR] {result.stderr[:300]}"


def frame_receiver(sock: socket.socket, frame_queue: queue.Queue):
    """接收线程: 从 TCP 接收 H264 数据并推入队列"""
    buffer = b""
    
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
            
            if length > 10 * 1024 * 1024:  # 最大 10MB
                # 跳过异常大帧
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
            
            # 推入队列
            frame_queue.put(frame_data)
    except Exception as e:
        print(f"\n接收线程退出: {e}")


def decode_and_infer(host: str, port: int):
    """接收 TCP H264 流并进行多模态推理"""
    
    print(f"Connecting to {host}:{port}...")
    
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(30.0)
    try:
        sock.connect((host, port))
    except socket.error as e:
        print(f"连接失败: {e}")
        return
    
    print("Connected!")
    print(f"模型: {os.path.basename(MODEL)}")
    print(f"采样间隔: {SAMPLE_INTERVAL} 秒")
    print("-" * 50)
    
    # 启动接收线程
    frame_queue = queue.Queue(maxsize=100)
    recv_thread = threading.Thread(target=frame_receiver, args=(sock, frame_queue))
    recv_thread.daemon = True
    recv_thread.start()
    
    # 启动 FFmpeg 解码进程
    # 从 stdin 读取 H264，输出 raw YUV 或直接用 ffplay 显示
    ffmpeg_decode_cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel", "warning",
        "-f", "h264",
        "-i", "pipe:0",
        "-f", "rawvideo",
        "-pix_fmt", "bgr24",
        "-s", "1280x640",  # 假设输入分辨率，实际情况可能需要调整
        "pipe:1"
    ]
    
    # 先尝试探测分辨率
    probe_cmd = [
        "ffprobe",
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "csv=p=0",
        "-f", "h264",
        "pipe:0"
    ]
    
    # 使用更简单的方式：直接保存为临时文件然后用 OpenCV 读取
    # 或者使用 ffmpeg 转储为图片序列
    
    # 这里改用 ffmpeg 将 H264 流转为视频流给 OpenCV
    ffmpeg_process = subprocess.Popen(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel", "warning",
            "-f", "h264",
            "-i", "pipe:0",
            "-c:v", "copy",  # 直接复制，不重新编码
            "-f", "matroska",  # 使用 mkv 格式（支持 H264 封装）
            "pipe:1"
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    
    # 启动另一个线程将队列数据喂给 FFmpeg
    def feed_ffmpeg():
        while True:
            try:
                data = frame_queue.get(timeout=5.0)
                if ffmpeg_process.stdin and not ffmpeg_process.stdin.closed:
                    # 添加长度头（某些封装需要）
                    # 对于 annex-b 格式的 H264，直接写入数据
                    ffmpeg_process.stdin.write(data)
                    ffmpeg_process.stdin.flush()
            except queue.Empty:
                continue
            except (BrokenPipeError, OSError):
                break
    
    feed_thread = threading.Thread(target=feed_ffmpeg)
    feed_thread.daemon = True
    feed_thread.start()
    
    # 用 OpenCV 读取 FFmpeg 的输出
    # 注意：这里需要知道视频分辨率，我们先假设一个常见值
    # 更好的做法是先接收几帧探测分辨率
    
    cap = None
    last_infer_time = 0
    frame_count = 0
    
    try:
        # 创建一个临时的 mkv 文件来存储流，然后用 OpenCV 读取
        # 这是最简单可靠的方法
        temp_mkv = tempfile.mktemp(suffix=".mkv")
        
        with open(temp_mkv, 'wb') as f:
            while True:
                try:
                    data = frame_queue.get(timeout=10.0)
                    f.write(data)
                    f.flush()
                    
                    # 定期尝试打开视频文件
                    frame_count += 1
                    if frame_count % 30 == 0:  # 每 30 帧尝试一次
                        if cap is None:
                            cap = cv2.VideoCapture(temp_mkv)
                        else:
                            cap.release()
                            cap = cv2.VideoCapture(temp_mkv)
                        
                        if cap.isOpened():
                            ret, frame = cap.read()
                            while ret:
                                current_time = time.time()
                                
                                # 显示视频
                                if SHOW_VIDEO:
                                    h, w = frame.shape[:2]
                                    scale = SCALE_WIDTH / w
                                    display = cv2.resize(frame, (SCALE_WIDTH, int(h * scale)))
                                    cv2.imshow("TCP H264 Stream", display)
                                    if cv2.waitKey(1) & 0xFF == ord('q'):
                                        raise KeyboardInterrupt()
                                
                                # 推理
                                if current_time - last_infer_time >= SAMPLE_INTERVAL:
                                    fd, img_path = tempfile.mkstemp(suffix=".jpg")
                                    os.close(fd)
                                    try:
                                        cv2.imwrite(img_path, frame)
                                        timestamp = datetime.now().strftime("%H:%M:%S")
                                        print(f"\n[{timestamp}] 第 {frame_count} 帧推理中...")
                                        answer = infer_image(img_path)
                                        print(f"描述: {answer}")
                                        print("-" * 50)
                                        last_infer_time = current_time
                                    finally:
                                        os.remove(img_path)
                                
                                ret, frame = cap.read()
                
                except queue.Empty:
                    continue
    
    except KeyboardInterrupt:
        print("\n用户中断")
    finally:
        if cap:
            cap.release()
        if ffmpeg_process:
            ffmpeg_process.terminate()
        sock.close()
        cv2.destroyAllWindows()
        if os.path.exists(temp_mkv):
            os.remove(temp_mkv)
        print(f"\n总计处理 {frame_count} 帧")


# ============ 更简洁的实现：直接用 OpenCV 打开 TCP 流 ============

def simple_tcp_infer(host: str, port: int):
    """
    简化版本：使用命名管道/文件将 H264 数据喂给 OpenCV
    这是最直接可靠的方法
    """
    print(f"Connecting to {host}:{port}...")
    
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(30.0)
    try:
        sock.connect((host, port))
    except socket.error as e:
        print(f"连接失败: {e}")
        return
    
    print("Connected!")
    print("-" * 50)
    
    # 创建临时文件
    temp_h264 = tempfile.mktemp(suffix=".h264")
    temp_mkv = tempfile.mktemp(suffix=".mkv")
    
    last_infer_time = 0
    frame_count = 0
    h264_size = 0
    
    try:
        with open(temp_h264, 'wb') as f:
            while True:
                # 接收长度头
                length_bytes = b""
                while len(length_bytes) < 4:
                    chunk = sock.recv(4 - len(length_bytes))
                    if not chunk:
                        raise ConnectionError("Server disconnected")
                    length_bytes += chunk
                
                length = struct.unpack("!I", length_bytes)[0]
                
                if length > 10 * 1024 * 1024:
                    # 跳过异常帧
                    remaining = length
                    while remaining > 0:
                        chunk = sock.recv(min(65536, remaining))
                        remaining -= len(chunk)
                    continue
                
                # 接收帧数据
                data = b""
                while len(data) < length:
                    chunk = sock.recv(min(65536, length - len(data)))
                    if not chunk:
                        raise ConnectionError("Server disconnected")
                    data += chunk
                
                # 写入文件
                f.write(data)
                f.flush()
                h264_size += len(data)
                frame_count += 1
                
                # 每 N 帧进行一次推理
                current_time = time.time()
                if current_time - last_infer_time >= SAMPLE_INTERVAL:
                    # 先封装为 mkv 以便 OpenCV 读取
                    f.flush()
                    
                    # 使用 ffmpeg 封装
                    result = subprocess.run(
                        ["ffmpeg", "-hide_banner", "-loglevel", "error",
                         "-y",  # 覆盖输出
                         "-f", "h264",
                         "-i", temp_h264,
                         "-c", "copy",
                         temp_mkv],
                        capture_output=True
                    )
                    
                    if result.returncode == 0 and os.path.exists(temp_mkv):
                        cap = cv2.VideoCapture(temp_mkv)
                        if cap.isOpened():
                            # 读取最后一帧
                            last_frame = None
                            while True:
                                ret, frame = cap.read()
                                if not ret:
                                    break
                                last_frame = frame
                            cap.release()
                            
                            if last_frame is not None:
                                # 显示
                                if SHOW_VIDEO:
                                    h, w = last_frame.shape[:2]
                                    scale = SCALE_WIDTH / w
                                    display = cv2.resize(last_frame, (SCALE_WIDTH, int(h * scale)))
                                    cv2.imshow("Stream", display)
                                    if cv2.waitKey(1) & 0xFF == ord('q'):
                                        break
                                
                                # 推理
                                fd, img_path = tempfile.mkstemp(suffix=".jpg")
                                os.close(fd)
                                try:
                                    cv2.imwrite(img_path, last_frame)
                                    timestamp = datetime.now().strftime("%H:%M:%S")
                                    print(f"\n[{timestamp}] 第 {frame_count} 帧 (累计 {h264_size/1024/1024:.1f} MB)")
                                    answer = infer_image(img_path)
                                    print(f"描述: {answer}")
                                    print("-" * 50)
                                    last_infer_time = current_time
                                finally:
                                    os.remove(img_path)
                        
                        # 清理 mkv，但保留 h264 继续累积
                        os.remove(temp_mkv)
    
    except KeyboardInterrupt:
        print("\n用户中断")
    except ConnectionError as e:
        print(f"\n连接断开: {e}")
    finally:
        sock.close()
        cv2.destroyAllWindows()
        for f in [temp_h264, temp_mkv]:
            if os.path.exists(f):
                os.remove(f)
        print(f"\n总计接收 {frame_count} 帧")


def main():
    if len(sys.argv) < 2:
        print(f"Usage: python {sys.argv[0]} <server_ip> [port]")
        print(f"Example: python {sys.argv[0]} {DEFAULT_HOST} {DEFAULT_PORT}")
        print(f"\n选项:")
        print(f"  --no-display    不显示视频窗口")
        print(f"  --interval N    设置推理间隔为 N 秒 (默认: {SAMPLE_INTERVAL})")
        sys.exit(1)
    
    host = sys.argv[1]
    port = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].isdigit() else DEFAULT_PORT
    
    # 解析额外参数
    global SHOW_VIDEO, SAMPLE_INTERVAL
    if "--no-display" in sys.argv:
        SHOW_VIDEO = False
    for i, arg in enumerate(sys.argv):
        if arg == "--interval" and i + 1 < len(sys.argv):
            SAMPLE_INTERVAL = float(sys.argv[i + 1])
    
    # 检查依赖
    for path, name in [(LLAMA_BIN, "llama-mtmd-cli"), (MODEL, "模型"), (MMPROJ, "mmproj")]:
        if not os.path.exists(path):
            print(f"错误: 找不到 {name}: {path}")
            sys.exit(1)
    
    # 使用简化版本
    simple_tcp_infer(host, port)


if __name__ == "__main__":
    main()
