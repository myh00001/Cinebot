# Insta360 实时推流 Demo

这个目录包含两个实时流媒体程序：

1. **rtmp_streamer** - RTMP推流（推送到B站/YouTube等直播平台）
2. **http_mjpeg_server** - HTTP H264流服务器（本地浏览器/VLC播放）

## 编译

```bash
cd CameraSDK/example
make
```

或者单独编译：

```bash
g++ -std=c++11 -I../include -L../lib -lCameraSDK -lpthread \
    -Wl,-rpath,'$ORIGIN/../lib' rtmp_streamer.cc -o rtmp_streamer

g++ -std=c++11 -I../include -L../lib -lCameraSDK -lpthread \
    -Wl,-rpath,'$ORIGIN/../lib' http_mjpeg_server.cc -o http_mjpeg_server
```

## 1. RTMP推流器

将相机画面推送到RTMP服务器（B站、YouTube、抖音等直播平台）。

### 前置要求
- 安装 FFmpeg：`sudo apt install ffmpeg`

### 使用方法

```bash
# 基础用法
./rtmp_streamer <RTMP推流地址>

# 示例：推送到B站
./rtmp_streamer rtmp://live-push.bilivideo.com/live-bvc/?streamname=xxxxxxxx

# 示例：推送到本地RTMP服务器（如SRS、nginx-rtmp）
./rtmp_streamer rtmp://localhost/live/stream

# 选择分辨率（0=3840x1920, 1=2560x1280, 2=1920x960）
./rtmp_streamer rtmp://xxx 1
```

### 获取B站推流地址
1. 登录B站直播中心
2. 开启直播，选择"直播码"方式
3. 复制服务器地址和串流密钥
4. 合并为：`rtmp://tx-direct-live-push.bilivideo.com/live-bvc/?streamname=live_xxxxxxx_xxxxxxxx`

### 获取YouTube推流地址
1. YouTube Studio -> 直播
2. 复制串流网址

## 2. HTTP MJPEG 服务器

在本地启动HTTP服务器，通过浏览器或播放器查看实时画面。

### 使用方法

```bash
# 默认使用8080端口
./http_mjpeg_server

# 指定端口
./http_mjpeg_server 8888
```

### 查看画面

**方式1：浏览器**
打开 http://localhost:8080

**方式2：VLC播放器**
1. 打开 VLC
2. 媒体 -> 打开网络串流
3. 输入：`http://localhost:8080/h264`

**方式3：FFplay**
```bash
ffplay http://localhost:8080/h264
```

**方式4：Python OpenCV**
```python
import cv2
cap = cv2.VideoCapture('http://localhost:8080/h264')
while True:
    ret, frame = cap.read()
    if ret:
        cv2.imshow('Insta360', frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break
cap.release()
cv2.destroyAllWindows()
```

## 网络流播放测试

### 使用VLC播放RTMP流
```bash
vlc rtmp://localhost/live/stream
```

### 使用ffplay播放
```bash
ffplay rtmp://localhost/live/stream
ffplay http://localhost:8080/h264
```

## 常见问题

### 1. FFmpeg未找到
```
Failed to start FFmpeg
```
**解决**：`sudo apt install ffmpeg`

### 2. 推流失败
- 检查网络连接
- 确认推流地址正确
- 检查防火墙设置

### 3. 画面卡顿
- 降低分辨率：`./rtmp_streamer <url> 2` （使用1920x960）
- 检查网络带宽
- 降低码率（修改源码中的`video_bitrate`）

### 4. 端口被占用
```bash
# 查看8080端口占用
sudo lsof -i :8080
# 杀死进程
kill -9 <PID>
```

## 技术说明

- 相机输出H264编码视频流
- RTMP推流器通过管道将H264数据传给FFmpeg，FFmpeg负责封装为FLV格式并推流
- HTTP服务器直接传输H264裸流，需要播放器支持H264解码

## 自定义开发

### 修改分辨率
编辑代码中的 `ins_camera::VideoResolution`：
- `RES_3840_1920P30` - 4K 30fps
- `RES_2560_1280P30` - 2.5K 30fps  
- `RES_1920_960P30` - 1080p 30fps
- `RES_1440_720P30` - 720p 30fps

### 修改码率
```cpp
param.video_bitrate = 1024 * 1024;  // 1Mbps，根据需要调整
```

### 添加音频
```cpp
param.enable_audio = true;
```
