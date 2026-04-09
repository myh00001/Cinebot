#!/usr/bin/env python3
"""
简单的控制客户端 - 用于控制录像服务器
"""

import socket
import sys


def send_command(host, port, cmd):
    """发送单个命令并获取响应"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(10)
        sock.connect((host, port))
        sock.sendall(cmd.encode('utf-8'))
        response = sock.recv(1024).decode('utf-8').strip()
        sock.close()
        return response
    except Exception as e:
        return f"错误: {e}"


def main():
    if len(sys.argv) < 3:
        print(f"用法: python {sys.argv[0]} <server_ip> <command> [args...]")
        print(f"")
        print(f"命令:")
        print(f"  start [文件名]   开始录制")
        print(f"  stop             停止录制")
        print(f"  snapshot         拍照")
        print(f"  status           查看状态")
        print(f"")
        print(f"示例:")
        print(f"  python {sys.argv[0]} 127.0.0.1 start")
        print(f"  python {sys.argv[0]} 127.0.0.1 start myvideo")
        print(f"  python {sys.argv[0]} 127.0.0.1 snapshot")
        print(f"  python {sys.argv[0]} 127.0.0.1 stop")
        sys.exit(1)
    
    host = sys.argv[1]
    cmd = ' '.join(sys.argv[2:])
    port = 9999  # 默认控制端口
    
    # 支持IP:PORT格式
    if ':' in host:
        host, port_str = host.rsplit(':', 1)
        port = int(port_str)
    
    print(f"发送命令到 {host}:{port}: {cmd}")
    response = send_command(host, port, cmd)
    print(response)


if __name__ == "__main__":
    main()
