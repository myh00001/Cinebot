#!/usr/bin/env python3
import socket
import struct
import sys
import os

MAGIC = 0x54534E49

def send_cmd(host, port, cmd_type):
    """发送命令并返回结果"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((host, port))
    
    # 发送命令头
    header = struct.pack('<III', MAGIC, cmd_type, 0)
    sock.sendall(header)
    
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
    
    if status == 0:
        return data.decode('utf-8', errors='ignore').strip()
    else:
        return None

def download_file(host, port, filename, save_dir="."):
    """下载文件"""
    print(f"  📥 Downloading: {filename}")
    
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((host, port))
    
    # 发送下载命令 (CMD_DOWNLOAD = 5)
    name_bytes = filename.encode()
    header = struct.pack('<III', MAGIC, 5, len(name_bytes))
    sock.sendall(header)
    sock.sendall(name_bytes)
    
    # 接收状态
    status_data = b''
    while len(status_data) < 4:
        chunk = sock.recv(4 - len(status_data))
        if not chunk:
            print("  ❌ Connection closed before status")
            sock.close()
            return None
        status_data += chunk
    status = struct.unpack('<I', status_data)[0]
    
    # 接收文件大小
    size_data = b''
    while len(size_data) < 4:
        chunk = sock.recv(4 - len(size_data))
        if not chunk:
            print("  ❌ Connection closed before file size")
            sock.close()
            return None
        size_data += chunk
    file_size = struct.unpack('<I', size_data)[0]
    
    if status != 0 or file_size == 0:
        print(f"  ❌ Download failed (status={status}, size={file_size})")
        sock.close()
        return None
    
    print(f"  ⏳ Receiving {file_size} bytes...")
    
    # 生成保存路径
    basename = os.path.basename(filename)
    save_path = os.path.join(save_dir, basename)
    
    # 接收文件内容
    with open(save_path, 'wb') as f:
        received = 0
        last_percent = -1
        while received < file_size:
            chunk = sock.recv(min(65536, file_size - received))
            if not chunk:
                print(f"  ⚠️  Connection closed at {received}/{file_size} bytes")
                break
            f.write(chunk)
            received += len(chunk)
            
            # 显示进度
            percent = int(received * 100 / file_size)
            if percent != last_percent and percent % 10 == 0:
                print(f"  📊 {percent}%")
                last_percent = percent
    
    sock.close()
    
    if received == file_size:
        print(f"  ✅ Saved: {save_path} ({received} bytes)")
    else:
        print(f"  ⚠️  Incomplete: {save_path} ({received}/{file_size} bytes)")
    
    return save_path

def capture(host, port, auto_download=True, save_dir="."):
    """拍照"""
    print("📸 Taking photo...")
    result = send_cmd(host, port, 1)  # CMD_CAPTURE
    
    if not result:
        print("❌ Capture failed")
        return None
    
    print(f"  Camera saved: {result}")
    
    if auto_download:
        files = result.strip().split('\n')
        downloaded = []
        for f in files:
            if f:
                path = download_file(host, port, f, save_dir)
                downloaded.append(path)
        return downloaded
    
    return result

def record_start(host, port):
    """开始录像"""
    print("🎬 Starting recording (8K)...")
    result = send_cmd(host, port, 2)  # CMD_RECORD_START
    
    if result is not None:
        print("✅ Recording started")
        return True
    else:
        print("❌ Failed to start recording")
        return False

def record_stop(host, port, auto_download=True, save_dir="."):
    """停止录像"""
    print("🛑 Stopping recording...")
    result = send_cmd(host, port, 3)  # CMD_RECORD_STOP
    
    if not result:
        print("❌ Failed to stop recording")
        return None
    
    print(f"  Camera saved: {result}")
    
    if auto_download:
        files = result.strip().split('\n')
        downloaded = []
        for f in files:
            if f:
                path = download_file(host, port, f, save_dir)
                downloaded.append(path)
        return downloaded
    
    return result

def list_files(host, port):
    """列出文件"""
    print("📁 File list:")
    result = send_cmd(host, port, 4)  # CMD_LIST_FILES
    
    if result:
        files = result.strip().split('\n')
        for i, f in enumerate(files[:50], 1):  # 最多显示50个
            print(f"  {i}. {f}")
        print(f"\nTotal: {len(files)} files")
    else:
        print("  No files or failed")

def main():
    # 参数解析
    if len(sys.argv) < 4:
        print("Usage: python client.py <host> <port> <command> [options]")
        print("")
        print("Commands:")
        print("  capture [save_dir]       - Take photo and auto-download")
        print("  record_start             - Start 8K recording")
        print("  record_stop [save_dir]   - Stop recording and auto-download")
        print("  list                     - List all files on camera")
        print("")
        print("Options:")
        print("  save_dir    - Directory to save files (default: current dir)")
        print("  --no-download  - Don't auto-download (capture/record_stop only)")
        print("")
        print("Examples:")
        print("  python client.py 192.168.88.189 8889 capture")
        print("  python client.py 192.168.88.189 8889 capture ./photos")
        print("  python client.py 192.168.88.189 8889 capture --no-download")
        print("  python client.py 192.168.88.189 8889 record_stop ./videos")
        sys.exit(1)
    
    host = sys.argv[1]
    port = int(sys.argv[2])
    cmd = sys.argv[3]
    
    # 解析额外参数
    save_dir = "."
    auto_download = True
    
    for arg in sys.argv[4:]:
        if arg == "--no-download":
            auto_download = False
        elif not arg.startswith("-"):
            save_dir = arg
            # 确保目录存在
            os.makedirs(save_dir, exist_ok=True)
    
    # 执行命令
    if cmd == "capture":
        result = capture(host, port, auto_download, save_dir)
        if result:
            print(f"\n✅ Capture complete: {len(result)} file(s)")
        else:
            sys.exit(1)
    
    elif cmd == "record_start":
        if not record_start(host, port):
            sys.exit(1)
    
    elif cmd == "record_stop":
        result = record_stop(host, port, auto_download, save_dir)
        if result:
            print(f"\n✅ Recording saved: {len(result)} file(s)")
        else:
            sys.exit(1)
    
    elif cmd == "list":
        list_files(host, port)
    
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)

if __name__ == '__main__':
    main()
