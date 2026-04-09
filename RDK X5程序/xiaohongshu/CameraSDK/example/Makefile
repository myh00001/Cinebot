# Insta360 CameraSDK Example Makefile

CXX = g++
CXXFLAGS = -std=c++11 -Wall -O2
INCLUDES = -I../include
LDFLAGS = -L../lib -lCameraSDK -lpthread
RPATH = -Wl,-rpath,'$$ORIGIN/../lib'

# 目标程序
TARGETS = CameraSDKTest rtmp_streamer http_mjpeg_server http_hls_server

all: $(TARGETS)

# 原始测试程序
CameraSDKTest: main.cc
	$(CXX) $(CXXFLAGS) $(INCLUDES) $< $(LDFLAGS) $(RPATH) -o $@

# RTMP推流器（需要FFmpeg）
rtmp_streamer: rtmp_streamer.cc
	$(CXX) $(CXXFLAGS) $(INCLUDES) $< $(LDFLAGS) $(RPATH) -o $@

# HTTP MJPEG服务器
http_mjpeg_server: http_mjpeg_server.cc
	$(CXX) $(CXXFLAGS) $(INCLUDES) $< $(LDFLAGS) $(RPATH) -o $@

clean:
	rm -f $(TARGETS)

.PHONY: all clean
