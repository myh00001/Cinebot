#!/usr/bin/env python3
"""
TCP H264 视频流测试脚本
- 测试 TCP 连接
- 测试 H264 数据接收
- 测试视频帧解码
"""

import socket
import struct
import sys
import os
import tempfile
import subprocess
import time
from datetime import datetime

DEFAULT_HOST = "192.168.88.189"
DEFAULT_PORT = 8888


def test_tcp_connection(host, port):
    """测试 TCP 连接"""
    print(f"\n[1/4] 测试 TCP 连接到 {host}:{port}...")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(10.0)
    try:
        sock.connect((host, port))
        print(f"✓ TCP 连接成功!")
        return sock
    except socket.error as e:
        print(f"✗ TCP 连接失败: {e}")
        return None


def test_h264_receive(sock, duration=5):
    """测试 H264 数据接收"""
    print(f"\n[2/4] 测试 H264 数据接收 ({duration}秒)...")
    
    sock.settimeout(5.0)
    frame_count = 0
    total_bytes = 0
    start_time = time.time()
    
    try:
        while time.time() - start_time < duration:
            # 接收 4 字节长度头
            length_bytes = b""
            while len(length_bytes) < 4:
                chunk = sock.recv(4 - len(length_bytes))
                if not chunk:
                    raise ConnectionError("Server disconnected")
                length_bytes += chunk
            
            length = struct.unpack("!I", length_bytes)[0]
            
            if length > 10 * 1024 * 1024:
                print(f"  警告: 收到异常大的帧: {length} bytes, 跳过")
                remaining = length
                while remaining > 0:
                    chunk = sock.recv(min(65536, remaining))
                    remaining -= len(chunk)
                continue
            
            # 接收帧数据
            frame_data = b""
            while len(frame_data) < length:
                chunk = sock.recv(min(65536, length - len(frame_data)))
                if not chunk:
                    raise ConnectionError("Server disconnected")
                frame_data += chunk
            
            frame_count += 1
            total_bytes += length + 4
            
            if frame_count == 1:
                print(f"  第1帧大小: {length} bytes")
            elif frame_count % 30 == 0:
                print(f"  已接收 {frame_count} 帧, 平均 {(frame_count/(time.time()-start_time)):.1f} fps")
        
        elapsed = time.time() - start_time
        print(f"✓ 接收完成: {frame_count} 帧, {total_bytes/1024/1024:.2f} MB, 平均 {(frame_count/elapsed):.1f} fps")
        return frame_count, total_bytes
        
    except socket.timeout:
        print(f"✗ 接收超时")
        return frame_count, total_bytes
    except ConnectionError as e:
        print(f"✗ 连接断开: {e}")
        return frame_count, total_bytes


def test_video_decode(frame_data_list):
    """测试视频解码"""
    print(f"\n[3/4] 测试视频解码...")
    
    if len(frame_data_list) == 0:
        print("✗ 没有帧数据可以解码")
        return False
    
    # 保存为临时 H264 文件
    temp_h264 = tempfile.mktemp(suffix=".h264")
    temp_mkv = tempfile.mktemp(suffix=".mkv")
    
    try:
        # 写入 H264 数据
        with open(temp_h264, 'wb') as f:
            for data in frame_data_list[:100]:  # 最多取前100帧
                f.write(data)
        
        print(f"  已保存 {min(len(frame_data_list), 100)} 帧到临时文件")
        
        # 使用 ffmpeg 封装为 mkv
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error",
             "-y",
             "-f", "h264",
             "-i", temp_h264,
             "-c", "copy",
             temp_mkv],
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            print(f"✗ FFmpeg 封装失败: {result.stderr}")
            return False
        
        # 使用 ffprobe 获取视频信息
        probe_result = subprocess.run(
            ["ffprobe", "-v", "error",
             "-show_entries", "stream=width,height,r_frame_rate,codec_name",
             "-of", "default=noprint_wrappers=1",
             temp_mkv],
            capture_output=True,
            text=True
        )
        
        if probe_result.returncode == 0:
            print(f"  视频信息:")
            for line in probe_result.stdout.strip().split('\n'):
                print(f"    {line}")
            print(f"✓ 视频解码成功!")
            return True
        else:
            print(f"✗ 视频探测失败")
            return False
            
    finally:
        for f in [temp_h264, temp_mkv]:
            if os.path.exists(f):
                os.remove(f)


def test_save_frame(frame_data, output_path="/tmp/test_frame.h264"):
    """保存一帧用于调试"""
    with open(output_path, 'wb') as f:
        f.write(frame_data)
    print(f"  已保存一帧到 {output_path}")


def main():
    host = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_HOST
    port = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].isdigit() else DEFAULT_PORT
    
    print("=" * 50)
    print("TCP H264 视频流测试")
    print("=" * 50)
    
    # 1. 测试 TCP 连接
    sock = test_tcp_connection(host, port)
    if not sock:
        sys.exit(1)
    
    # 2. 测试 H264 接收
    frame_count, total_bytes = test_h264_receive(sock, duration=5)
    
    # 3. 保存一些帧用于解码测试
    print(f"\n[3/4] 重新接收视频用于解码测试...")
    sock.close()
    
    # 重新连接接收一些帧
    sock = test_tcp_connection(host, port)
    if not sock:
        sys.exit(1)
    
    frame_data_list = []
    sock.settimeout(5.0)
    start = time.time()
    
    try:
        while time.time() - start < 3 and len(frame_data_list) < 100:
            # 接收长度头
            length_bytes = b""
            while len(length_bytes) < 4:
                chunk = sock.recv(4 - len(length_bytes))
                if not chunk:
                    break
                length_bytes += chunk
            
            if len(length_bytes) < 4:
                break
                
            length = struct.unpack("!I", length_bytes)[0]
            
            if length > 10 * 1024 * 1024:
                # 跳过异常帧
                remaining = length
                while remaining > 0:
                    chunk = sock.recv(min(65536, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                continue
            
            # 接收帧数据
            frame_data = b""
            while len(frame_data) < length:
                chunk = sock.recv(min(65536, length - len(frame_data)))
                if not chunk:
                    break
                frame_data += chunk
            
            if len(frame_data) == length:
                frame_data_list.append(frame_data)
                
    except Exception as e:
        print(f"  接收异常: {e}")
    
    print(f"  接收到 {len(frame_data_list)} 帧用于解码测试")
    
    # 保存第一帧用于调试
    if frame_data_list:
        test_save_frame(frame_data_list[0])
    
    # 4. 测试解码
    test_video_decode(frame_data_list)
    
    # 5. 测试 OpenCV 读取
    print(f"\n[4/4] 测试 OpenCV 读取...")
    try:
        import cv2
        
        # 重新封装并尝试用 OpenCV 读取
        temp_h264 = "/tmp/test_cv.h264"
        with open(temp_h264, 'wb') as f:
            for data in frame_data_list:
                f.write(data)
        
        temp_mkv = "/tmp/test_cv.mkv"
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error",
             "-y",
             "-f", "h264",
             "-i", temp_h264,
             "-c", "copy",
             temp_mkv],
            capture_output=True
        )
        
        cap = cv2.VideoCapture(temp_mkv)
        if cap.isOpened():
            ret, frame = cap.read()
            if ret:
                print(f"✓ OpenCV 成功读取帧: {frame.shape}")
                # 保存一张截图
                cv2.imwrite("/tmp/test_frame.jpg", frame)
                print(f"  已保存截图到 /tmp/test_frame.jpg")
            else:
                print(f"✗ OpenCV 无法读取帧")
        else:
            print(f"✗ OpenCV 无法打开视频")
        cap.release()
        
        os.remove(temp_h264)
        os.remove(temp_mkv)
        
    except ImportError:
        print(f"✗ OpenCV 未安装")
    except Exception as e:
        print(f"✗ OpenCV 测试失败: {e}")
    
    sock.close()
    
    print("\n" + "=" * 50)
    print("测试完成")
    print("=" * 50)


if __name__ == "__main__":
    main()
