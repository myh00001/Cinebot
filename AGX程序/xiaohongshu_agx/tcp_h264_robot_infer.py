#!/usr/bin/env python3
"""
TCP H264 机器人视觉决策推理客户端
- 连接 TCP H264 服务器接收视频流
- 降低分辨率后进行多模态推理
- 严格限制输出为机器人控制指令
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
from datetime import datetime

# ==================== 配置项 ====================
DEFAULT_HOST = "192.168.88.189"
DEFAULT_PORT = 8888

# 模型配置
LLAMA_BIN = "/home/hhws/llama.cpp/build/bin/llama-mtmd-cli"
MODEL = "/home/hhws/models/MiniCPM-V-4_5-Q4_K_M.gguf"
MMPROJ = "/home/hhws/models/mmproj-model-f16.gguf"

# 分辨率配置
INFER_WIDTH = 640           # 推理时图像宽度（降低分辨率提高速度）
INFER_HEIGHT = 320          # 推理时图像高度
JPEG_QUALITY = 85           # JPEG 压缩质量

# GPU 配置
USE_GPU = True              # 是否使用 GPU 推理
N_GPU_LAYERS = 999          # GPU 层数，999 = 全部放到 GPU

# 推理配置
SAMPLE_INTERVAL = 0.5       # 每 0.5 秒推理一次（响应更快）
MAX_RETRIES = 3

# 显示配置
SHOW_VIDEO = False          # 是否显示视频窗口（默认关闭，避免无GUI环境报错）
SCALE_WIDTH = 640           # 显示缩放宽度

# System Prompt - 严格限制输出格式
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

# 用户提示词（简单的指令）
USER_PROMPT = "控制小车跟随我移动"


def validate_and_clean_output(output: str) -> str:
    """
    验证并清理模型输出，只保留符合格式的指令行
    """
    valid_lines = []
    lines = output.strip().split('\n')
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        # 匹配 V 指令: V <DIR> <STEP>
        # DIR: L R U D H, STEP: 0-400
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
        
        # 匹配 C 指令: C <DIR> <SPEED> <DURATION_MS>
        # DIR: F B L R S, SPEED: 0-3, DURATION_MS: 80-500
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
        
        # 匹配 A 指令: A <ACTION>
        # ACTION: NO RS RE PH TS TE
        a_pattern = r'^A\s+(NO|RS|RE|PH|TS|TE)$'
        a_match = re.match(a_pattern, line)
        if a_match:
            valid_lines.append(line)
            continue
    
    return '\n'.join(valid_lines)


def infer_image(image_path: str) -> str:
    """
    使用多模态大模型推理单帧图像（支持 GPU）
    使用 --system-prompt 传递 system prompt，-p 传递 user prompt
    """
    cmd = [
        LLAMA_BIN,
        "-m", MODEL,
        "--mmproj", MMPROJ,
        "-c", "2048",
        "--image", image_path,
        "--system-prompt", SYSTEM_PROMPT,
        "-p", USER_PROMPT,
        "--temp", "0.1",           # 低温度，更确定性输出
        "--top-p", "0.9",
        "--top-k", "40",
        "-n", "50",                # 限制最大生成 token 数
    ]
    
    # 添加 GPU 支持
    if USE_GPU:
        # 使用 --gpu-layers all 加载所有层到 GPU
        cmd.extend(["--gpu-layers", "all"])
        # 显式启用 mmproj GPU offload
        cmd.append("--mmproj-offload")
    
    # 打印命令用于调试（只打印一次）
    if not hasattr(infer_image, '_printed_cmd'):
        print(f"推理命令: {' '.join(cmd[:10])} ... (省略参数)")
        print(f"GPU 启用: {USE_GPU}")
        infer_image._printed_cmd = True
    
    for attempt in range(MAX_RETRIES):
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if result.returncode == 0:
                raw_output = result.stdout.strip()
                # 验证并清理输出
                cleaned_output = validate_and_clean_output(raw_output)
                return cleaned_output if cleaned_output else "[NO_VALID_CMD]"
            else:
                print(f"  推理错误: {result.stderr[:200]}")
        except subprocess.TimeoutExpired:
            print(f"  推理超时 (尝试 {attempt + 1}/{MAX_RETRIES})")
        except Exception as e:
            print(f"  推理异常: {e}")
        
        time.sleep(0.5)
    
    return "[ERROR]"


def resize_frame_for_inference(frame, target_width=INFER_WIDTH, target_height=INFER_HEIGHT):
    """
    将帧 resize 到目标分辨率用于推理
    保持宽高比，如果必要则裁剪或填充
    """
    h, w = frame.shape[:2]
    
    # 直接 resize 到目标尺寸（不保持宽高比，追求速度）
    resized = cv2.resize(frame, (target_width, target_height), interpolation=cv2.INTER_LINEAR)
    return resized


def simple_tcp_infer(host: str, port: int):
    """
    简化版本：使用命名管道/文件将 H264 数据喂给 OpenCV
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
    print(f"推理分辨率: {INFER_WIDTH}x{INFER_HEIGHT}")
    print(f"采样间隔: {SAMPLE_INTERVAL} 秒")
    print(f"推理设备: {'GPU (CUDA)' if USE_GPU else 'CPU'}")
    if USE_GPU:
        print(f"GPU 层数: {N_GPU_LAYERS}")
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
                    
                    # 使用 ffmpeg 封装（添加时间戳和容错）
                    result = subprocess.run(
                        ["ffmpeg", "-hide_banner", "-loglevel", "error",
                         "-y",
                         "-fflags", "+genpts+igndts",  # 生成时间戳，忽略 DTS
                         "-r", "30",  # 设置输入帧率
                         "-f", "h264",
                         "-i", temp_h264,
                         "-c:v", "libx264",  # 重新编码（裸流可能有问题）
                         "-preset", "ultrafast",
                         "-tune", "zerolatency",
                         "-f", "matroska",
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
                                # 原图用于显示
                                display_frame = last_frame.copy()
                                
                                # 降低分辨率用于推理
                                infer_frame = resize_frame_for_inference(
                                    last_frame, INFER_WIDTH, INFER_HEIGHT
                                )
                                
                                # 显示
                                if SHOW_VIDEO:
                                    try:
                                        # 显示原图（缩放到显示尺寸）
                                        h, w = display_frame.shape[:2]
                                        scale = SCALE_WIDTH / w
                                        display = cv2.resize(
                                            display_frame, 
                                            (SCALE_WIDTH, int(h * scale))
                                        )
                                        # 叠加显示推理分辨率信息
                                        cv2.putText(
                                            display, 
                                            f"Infer: {INFER_WIDTH}x{INFER_HEIGHT}", 
                                            (10, 30), 
                                            cv2.FONT_HERSHEY_SIMPLEX, 
                                            0.7, 
                                            (0, 255, 0), 
                                            2
                                        )
                                        cv2.imshow("TCP H264 Stream", display)
                                        if cv2.waitKey(1) & 0xFF == ord('q'):
                                            break
                                    except cv2.error:
                                        SHOW_VIDEO = False  # 如果显示失败，自动关闭显示
                                
                                # 保存降低分辨率后的图像用于推理
                                fd, img_path = tempfile.mkstemp(suffix=".jpg")
                                os.close(fd)
                                try:
                                    # 使用较高质量保存
                                    encode_params = [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY]
                                    cv2.imwrite(img_path, infer_frame, encode_params)
                                    
                                    timestamp = datetime.now().strftime("%H:%M:%S")
                                    print(f"\n[{timestamp}] 第 {frame_count} 帧 (原图 {last_frame.shape[1]}x{last_frame.shape[0]} -> 推理 {infer_frame.shape[1]}x{infer_frame.shape[0]})")
                                    
                                    answer = infer_image(img_path)
                                    
                                    # 只显示有效的指令
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
                        
                        # 清理 mkv，但保留 h264 继续累积
                        os.remove(temp_mkv)
    
    except KeyboardInterrupt:
        print("\n用户中断")
    except ConnectionError as e:
        print(f"\n连接断开: {e}")
    finally:
        sock.close()
        try:
            if SHOW_VIDEO:
                cv2.destroyAllWindows()
        except cv2.error:
            pass  # 忽略无GUI环境的错误
        for f in [temp_h264, temp_mkv]:
            if os.path.exists(f):
                os.remove(f)
        print(f"\n总计接收 {frame_count} 帧")


def main():
    global SHOW_VIDEO, SAMPLE_INTERVAL, INFER_WIDTH, INFER_HEIGHT
    
    if len(sys.argv) < 2:
        print(f"Usage: python {sys.argv[0]} <server_ip> [port]")
        print(f"Example: python {sys.argv[0]} {DEFAULT_HOST} {DEFAULT_PORT}")
        print(f"\n选项:")
        print(f"  --no-display      不显示视频窗口")
        print(f"  --interval N      设置推理间隔为 N 秒 (默认: {SAMPLE_INTERVAL})")
        print(f"  --res WxH         设置推理分辨率 (默认: {INFER_WIDTH}x{INFER_HEIGHT})")
        print(f"  --cpu             使用 CPU 推理 (默认使用 GPU)")
        print(f"  -ngl N            设置 GPU 层数 (默认: {N_GPU_LAYERS})")
        sys.exit(1)
    
    host = sys.argv[1]
    port = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].isdigit() else DEFAULT_PORT
    
    # 解析额外参数
    if "--no-display" in sys.argv:
        SHOW_VIDEO = False
    for i, arg in enumerate(sys.argv):
        if arg == "--interval" and i + 1 < len(sys.argv):
            SAMPLE_INTERVAL = float(sys.argv[i + 1])
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
    
    # 运行
    simple_tcp_infer(host, port)


if __name__ == "__main__":
    main()
