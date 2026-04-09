#!/usr/bin/env python3
"""
Recorder 客户端 - 简化版控制客户端
"""

import socket
import json
import base64
import sys
import os


class RecorderClient:
    """录像器控制客户端"""
    
    def __init__(self, host, control_port=9999, file_port=9998):
        self.host = host
        self.control_port = control_port
        self.file_port = file_port
    
    def cmd(self, command, timeout=30):
        """发送控制命令"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            sock.connect((self.host, self.control_port))
            sock.sendall(command.encode('utf-8'))
            
            # 接收响应
            response_data = b""
            while True:
                try:
                    chunk = sock.recv(8192)
                    if not chunk:
                        break
                    response_data += chunk
                    # 尝试解析JSON
                    try:
                        json.loads(response_data.decode('utf-8'))
                        break
                    except:
                        continue
                except socket.timeout:
                    break
            
            sock.close()
            return json.loads(response_data.decode('utf-8'))
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def start_record(self, filename=None):
        """开始录制"""
        cmd = f"start {filename}" if filename else "start"
        return self.cmd(cmd)
    
    def stop_record(self):
        """停止录制"""
        return self.cmd("stop")
    
    def snapshot(self):
        """拍照"""
        return self.cmd("snapshot")
    
    def get_last_photo(self, save_path=None):
        """获取最后拍摄的照片"""
        resp = self.cmd("get_last_photo")
        if resp.get('success') and save_path:
            self._save_base64_image(resp['data'], save_path)
        return resp
    
    def get_photo(self, filename, save_path=None):
        """获取指定照片"""
        resp = self.cmd(f"get_photo {filename}")
        if resp.get('success') and save_path:
            self._save_base64_image(resp['data'], save_path)
        return resp
    
    def list_videos(self):
        """获取视频列表"""
        return self.cmd("list_videos")
    
    def list_photos(self):
        """获取照片列表"""
        return self.cmd("list_photos")
    
    def get_status(self):
        """获取状态"""
        return self.cmd("status")
    
    def download_video(self, filename, save_path=None, progress_callback=None):
        """下载视频文件"""
        if save_path is None:
            save_path = filename
        
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(60)
            sock.connect((self.host, self.file_port))
            
            # 发送请求
            sock.sendall(f"GET {filename}".encode())
            
            # 接收文件头
            header_data = b""
            while b"\n" not in header_data:
                chunk = sock.recv(1024)
                if not chunk:
                    break
                header_data += chunk
            
            header = json.loads(header_data.decode().split("\n")[0])
            file_size = header['size']
            
            # 发送确认
            sock.sendall(b"READY")
            
            # 接收文件
            received = 0
            with open(save_path, 'wb') as f:
                while received < file_size:
                    chunk = sock.recv(min(65536, file_size - received))
                    if not chunk:
                        break
                    f.write(chunk)
                    received += len(chunk)
                    
                    if progress_callback:
                        progress = (received / file_size) * 100
                        progress_callback(progress)
            
            sock.close()
            return {"success": True, "file": save_path, "size": file_size}
            
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def _save_base64_image(self, data, save_path):
        """保存Base64图片"""
        img_data = base64.b64decode(data['base64'])
        with open(save_path, 'wb') as f:
            f.write(img_data)
        return True


def main():
    if len(sys.argv) < 3:
        print(f"用法: python {sys.argv[0]} <server_ip> <command> [args...]")
        print(f"")
        print(f"命令:")
        print(f"  start [文件名]           开始录制")
        print(f"  stop                     停止录制")
        print(f"  snapshot                 拍照")
        print(f"  get_last_photo [保存路径] 获取最后拍摄的照片")
        print(f"  get_photo <文件名> [路径] 获取指定照片")
        print(f"  list_videos              视频列表")
        print(f"  list_photos              照片列表")
        print(f"  download <文件名> [路径] 下载视频")
        print(f"  status                   查看状态")
        print(f"")
        print(f"示例:")
        print(f"  python {sys.argv[0]} 127.0.0.1 start")
        print(f"  python {sys.argv[0]} 127.0.0.1 snapshot")
        print(f"  python {sys.argv[0]} 127.0.0.1 get_last_photo ./photo.jpg")
        print(f"  python {sys.argv[0]} 127.0.0.1 download video_20250409_120000.mp4 ./myvideo.mp4")
        sys.exit(1)
    
    host = sys.argv[1]
    command = sys.argv[2]
    args = sys.argv[3:]
    
    # 解析端口
    control_port = 9999
    file_port = 9998
    if ':' in host:
        parts = host.split(':')
        host = parts[0]
        if len(parts) > 1:
            control_port = int(parts[1])
        if len(parts) > 2:
            file_port = int(parts[2])
    
    client = RecorderClient(host, control_port, file_port)
    
    if command == "start":
        filename = args[0] if args else None
        resp = client.start_record(filename)
        print(json.dumps(resp, indent=2, ensure_ascii=False))
    
    elif command == "stop":
        resp = client.stop_record()
        print(json.dumps(resp, indent=2, ensure_ascii=False))
    
    elif command == "snapshot":
        resp = client.snapshot()
        print(json.dumps(resp, indent=2, ensure_ascii=False))
    
    elif command == "get_last_photo":
        save_path = args[0] if args else None
        resp = client.get_last_photo(save_path)
        if not save_path:
            print(json.dumps(resp, indent=2, ensure_ascii=False))
        else:
            print(f"照片已保存: {save_path}")
    
    elif command == "get_photo":
        if not args:
            print("错误: 需要指定文件名")
            sys.exit(1)
        filename = args[0]
        save_path = args[1] if len(args) > 1 else None
        resp = client.get_photo(filename, save_path)
        if not save_path:
            print(json.dumps(resp, indent=2, ensure_ascii=False))
        else:
            print(f"照片已保存: {save_path}")
    
    elif command == "list_videos":
        resp = client.list_videos()
        print(json.dumps(resp, indent=2, ensure_ascii=False))
    
    elif command == "list_photos":
        resp = client.list_photos()
        print(json.dumps(resp, indent=2, ensure_ascii=False))
    
    elif command == "download":
        if not args:
            print("错误: 需要指定文件名")
            sys.exit(1)
        filename = args[0]
        save_path = args[1] if len(args) > 1 else filename
        
        def show_progress(p):
            print(f"\r下载进度: {p:.1f}%", end='', flush=True)
        
        print(f"下载 {filename} 到 {save_path}")
        resp = client.download_video(filename, save_path, show_progress)
        print()  # 换行
        print(json.dumps(resp, indent=2, ensure_ascii=False))
    
    elif command == "status":
        resp = client.get_status()
        print(json.dumps(resp, indent=2, ensure_ascii=False))
    
    else:
        print(f"未知命令: {command}")
        print("使用 help 查看可用命令")


if __name__ == "__main__":
    main()
