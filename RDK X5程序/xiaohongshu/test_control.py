#!/usr/bin/env python3
"""
测试脚本 - 用于测试录像控制功能
"""

import socket
import time
import sys


def send_command(host, port, cmd, timeout=10):
    """发送命令并获取响应"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((host, port))
        sock.sendall(cmd.encode('utf-8'))
        response = sock.recv(1024).decode('utf-8').strip()
        sock.close()
        return response
    except Exception as e:
        return f"ERROR: {e}"


def test_basic_control(host, port):
    """测试基本控制功能"""
    print("=" * 50)
    print("测试基本控制功能")
    print("=" * 50)
    
    # 测试状态查询
    print("\n1. 查询状态...")
    response = send_command(host, port, "status")
    print(f"   响应: {response}")
    
    # 测试开始录制
    print("\n2. 开始录制...")
    response = send_command(host, port, "start test_video")
    print(f"   响应: {response}")
    
    # 等待3秒
    print("\n3. 录制中，等待3秒...")
    time.sleep(3)
    
    # 查询状态
    print("\n4. 查询录制状态...")
    response = send_command(host, port, "status")
    print(f"   响应: {response}")
    
    # 测试拍照
    print("\n5. 拍照...")
    response = send_command(host, port, "snapshot")
    print(f"   响应: {response}")
    time.sleep(1)
    
    # 停止录制
    print("\n6. 停止录制...")
    response = send_command(host, port, "stop")
    print(f"   响应: {response}")
    
    print("\n测试完成!")


def test_http_api(host, http_port):
    """测试HTTP API"""
    print("=" * 50)
    print("测试HTTP API")
    print("=" * 50)
    
    try:
        import urllib.request
        import json
        
        base_url = f"http://{host}:{http_port}"
        
        # 测试状态查询
        print("\n1. GET /status")
        with urllib.request.urlopen(f"{base_url}/status", timeout=5) as resp:
            data = json.loads(resp.read().decode())
            print(f"   响应: {json.dumps(data, indent=2, ensure_ascii=False)}")
        
        # 测试开始录制
        print("\n2. POST /start")
        req = urllib.request.Request(f"{base_url}/start?filename=apitest", method='POST')
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            print(f"   响应: {json.dumps(data, indent=2, ensure_ascii=False)}")
        
        # 等待3秒
        print("\n3. 录制中，等待3秒...")
        time.sleep(3)
        
        # 测试拍照
        print("\n4. POST /snapshot")
        req = urllib.request.Request(f"{base_url}/snapshot", method='POST')
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            print(f"   响应: {json.dumps(data, indent=2, ensure_ascii=False)}")
        time.sleep(1)
        
        # 测试停止录制
        print("\n5. POST /stop")
        req = urllib.request.Request(f"{base_url}/stop", method='POST')
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            print(f"   响应: {json.dumps(data, indent=2, ensure_ascii=False)}")
        
        # 查询视频列表
        print("\n6. GET /videos")
        with urllib.request.urlopen(f"{base_url}/videos", timeout=5) as resp:
            data = json.loads(resp.read().decode())
            print(f"   响应: {json.dumps(data, indent=2, ensure_ascii=False)}")
        
        print("\nHTTP API测试完成!")
        
    except ImportError:
        print("需要 urllib 模块来测试HTTP API")
    except Exception as e:
        print(f"HTTP API测试失败: {e}")


def main():
    if len(sys.argv) < 2:
        print(f"用法: python {sys.argv[0]} <server_ip> [control_port] [http_port]")
        print(f"示例:")
        print(f"  python {sys.argv[0]} 127.0.0.1 9999 8080")
        sys.exit(1)
    
    host = sys.argv[1]
    control_port = int(sys.argv[2]) if len(sys.argv) > 2 else 9999
    http_port = int(sys.argv[3]) if len(sys.argv) > 3 else 8080
    
    # 测试TCP控制
    test_basic_control(host, control_port)
    
    print()
    
    # 测试HTTP API
    test_http_api(host, http_port)


if __name__ == "__main__":
    main()
