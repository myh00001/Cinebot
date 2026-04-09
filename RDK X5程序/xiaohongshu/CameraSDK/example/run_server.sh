#!/bin/bash
# Insta360 HLS 流服务器启动脚本
# 自动重连，持久运行

PORT=${1:-8888}
HLS_DIR="/tmp/insta360_hls"
LOG_FILE="/tmp/insta360_server.log"

echo "========================================"
echo "Insta360 HLS Stream Server"
echo "Port: $PORT"
echo "Log: $LOG_FILE"
echo "========================================"

# 清理旧文件
sudo rm -rf "$HLS_DIR"/*

# 循环运行，自动重启
count=0
while true; do
    count=$((count + 1))
    echo "[$(date)] Starting server (attempt #$count)..."
    
    cd "$(dirname "$0")"
    sudo ./http_hls_server "$PORT" 2>&1 | tee -a "$LOG_FILE"
    
    echo "[$(date)] Server stopped, restarting in 3 seconds..."
    sleep 3
done
