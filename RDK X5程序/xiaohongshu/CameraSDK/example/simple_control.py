#!/usr/bin/env python3
"""
简化版相机控制客户端
"""

import socket
import struct
import sys

# 命令定义
CMD_CAPTURE = 1
CMD_RECORD_START = 2
CMD_RECORD_STOP = 3
CMD_LIST_FILES = 4
CMD_DOWNLOAD = 5

MAGIC = 0x54534E49  # 'INST'


def send_command(host, port, cmd, param=b''):
    """发送命令到相机"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((host, port))
    
    # 发送命令头
    header = struct.pack('<III', MAGIC, cmd, len(param))
    sock.sendall(header)
    if param:
        sock.sendall(param)
    
    # 接收响应
    status = struct.unpack('<I', sock.recv(4))[0]
    data_len = struct.unpack('<I', sock.recv(4))[0]
    
    data = b''
    if data_len > 0:
        while len(data) < data_len:
            chunk = sock.recv(data_len - len(data))
            if not chunk:
                break
            data += chunk
    
    sock.close()
    return status == 0, data.decode('utf-8', errors='ignore')


def download_file(host, port, filename, save_path=None):
    """下载文件"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((host, port))
    
    # 发送下载命令
    header = struct.pack('<III', MAGIC, CMD_DOWNLOAD, len(filename))
    sock.sendall(header)
    sock.sendall(filename.encode())
    
    # 发送文件名长度和文件名（控制服务器的特殊处理）
    name_bytes = filename.encode()
    sock.sendall(struct.pack('<I', len(name_bytes)))
    sock.sendall(name_bytes)
    
    # 接收文件大小
    file_size = struct.unpack('<I', sock.recv(4))[0]
    
    # 接收文件数据
    if save_path is None:
        save_path = filename.split('/')[-1]
    
    with open(save_path, 'wb') as f:
        received = 0
        while received < file_size:
            chunk = sock.recv(min(65536, file_size - received))
            if not chunk:
                break
            f.write(chunk)
            received += len(chunk)
    
    sock.close()
    print(f"Downloaded: {save_path} ({received} bytes)")
    return save_path


def main():
    if len(sys.argv) < 4:
        print("Usage: python simple_control.py <host> <port> <command>")
        print("")
        print("Commands:")
        print("  capture                 - 拍照")
        print("  record_start           - 开始录像(8K)")
        print("  record_stop            - 停止录像")
        print("  list                   - 列出文件")
        print("  download <file>        - 下载文件")
        print("")
        print("Examples:")
        print("  python simple_control.py 192.168.88.189 8889 capture")
        print("  python simple_control.py 192.168.88.189 8889 record_start")
        print("  python simple_control.py 192.168.88.189 8889 list")
        sys.exit(1)
    
    host = sys.argv[1]
    port = int(sys.argv[2])
    cmd_str = sys.argv[3].lower()
    
    # 命令映射
    cmd_map = {
        'capture': CMD_CAPTURE,
        'record_start': CMD_RECORD_START,
        'record_stop': CMD_RECORD_STOP,
        'list': CMD_LIST_FILES,
        'download': CMD_DOWNLOAD,
    }
    
    if cmd_str not in cmd_map:
        print(f"Unknown command: {cmd_str}")
        sys.exit(1)
    
    cmd = cmd_map[cmd_str]
    
    if cmd_str == 'download':
        if len(sys.argv) < 5:
            print("Usage: download <filename>")
            sys.exit(1)
        download_file(host, port, sys.argv[4])
    else:
        ok, result = send_command(host, port, cmd)
        if ok:
            print(f"Success:\n{result}")
        else:
            print(f"Failed: {result}")


if __name__ == "__main__":
    main()
