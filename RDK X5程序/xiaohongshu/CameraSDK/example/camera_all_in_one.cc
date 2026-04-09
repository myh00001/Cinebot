#include <iostream>
#include <thread>
#include <chrono>
#include <csignal>
#include <cstring>
#include <atomic>
#include <mutex>
#include <sys/socket.h>
#include <netinet/in.h>
#include <unistd.h>
#include <arpa/inet.h>
#include <cstdio>
#include <sys/stat.h>
#include <sys/select.h>
#include <errno.h>

#include <camera/camera.h>
#include <camera/photography_settings.h>
#include <camera/device_discovery.h>

// 前向声明
extern volatile sig_atomic_t g_stop;
bool shouldStop();

// TCP推流服务器
class TCPStreamer : public ins_camera::StreamDelegate {
public:
    bool Start(int port) {
        server_fd_ = socket(AF_INET, SOCK_STREAM, 0);
        if (server_fd_ < 0) return false;
        
        int opt = 1;
        setsockopt(server_fd_, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));
        
        sockaddr_in addr;
        addr.sin_family = AF_INET;
        addr.sin_addr.s_addr = INADDR_ANY;
        addr.sin_port = htons(port);
        
        if (bind(server_fd_, (sockaddr*)&addr, sizeof(addr)) < 0) return false;
        if (listen(server_fd_, 1) < 0) return false;
        
        std::cout << "[Stream] TCP server on port " << port << std::endl;
        
        is_running_ = true;
        thread_ = std::thread(&TCPStreamer::AcceptLoop, this);
        return true;
    }

    void AcceptLoop() {
        while (is_running_ && !shouldStop()) {
            // 设置accept超时，以便检查g_stop
            fd_set fds;
            FD_ZERO(&fds);
            FD_SET(server_fd_, &fds);
            struct timeval tv;
            tv.tv_sec = 1;
            tv.tv_usec = 0;
            
            int ret = select(server_fd_ + 1, &fds, NULL, NULL, &tv);
            if (ret <= 0) continue;  // 超时或错误，检查g_stop
            
            sockaddr_in client_addr;
            socklen_t len = sizeof(client_addr);
            int client = accept(server_fd_, (sockaddr*)&client_addr, &len);
            if (client < 0) continue;
            
            std::cout << "[Stream] Client connected from " << inet_ntoa(client_addr.sin_addr) << std::endl;
            {
                std::lock_guard<std::mutex> lock(mutex_);
                if (client_fd_ > 0) close(client_fd_);
                client_fd_ = client;
            }
        }
    }

    void OnVideoData(const uint8_t* data, size_t size, int64_t ts, uint8_t type, int idx) override {
        if (idx != 0) return;
        std::lock_guard<std::mutex> lock(mutex_);
        if (client_fd_ > 0) {
            uint32_t len = htonl(size);
            if (send(client_fd_, &len, 4, MSG_NOSIGNAL) < 0 ||
                send(client_fd_, data, size, MSG_NOSIGNAL) < 0) {
                close(client_fd_);
                client_fd_ = -1;
            }
        }
        
        frame_count_++;
        auto now = std::chrono::steady_clock::now();
        auto elapsed = std::chrono::duration_cast<std::chrono::seconds>(now - last_print_).count();
        if (elapsed >= 5) {
            std::cout << "[Stream] " << frame_count_ / elapsed << " fps" << std::endl;
            frame_count_ = 0;
            last_print_ = now;
        }
    }

    void OnAudioData(const uint8_t* data, size_t size, int64_t ts) override {}
    void OnGyroData(const std::vector<ins_camera::GyroData>& data) override {}
    void OnExposureData(const ins_camera::ExposureData& data) override {}

    void Stop() {
        is_running_ = false;
        close(server_fd_);
        close(client_fd_);
        if (thread_.joinable()) thread_.join();
    }

private:
    int server_fd_ = -1, client_fd_ = -1;
    std::mutex mutex_;
    std::thread thread_;
    std::atomic<bool> is_running_{false};
    std::atomic<int> frame_count_{0};
    std::chrono::steady_clock::time_point last_print_ = std::chrono::steady_clock::now();
};

// 控制服务器
class ControlServer {
public:
    struct Command {
        uint32_t magic;      // 'INST' = 0x54534E49
        uint32_t type;       // 1=capture, 2=record_start, 3=record_stop
        uint32_t param_len;
    };

    bool Start(int port, std::shared_ptr<ins_camera::Camera> cam) {
        cam_ = cam;
        server_fd_ = socket(AF_INET, SOCK_STREAM, 0);
        if (server_fd_ < 0) return false;
        
        int opt = 1;
        setsockopt(server_fd_, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));
        
        sockaddr_in addr;
        addr.sin_family = AF_INET;
        addr.sin_addr.s_addr = INADDR_ANY;
        addr.sin_port = htons(port);
        
        if (bind(server_fd_, (sockaddr*)&addr, sizeof(addr)) < 0) return false;
        if (listen(server_fd_, 2) < 0) return false;
        
        std::cout << "[Control] Server on port " << port << std::endl;
        
        is_running_ = true;
        thread_ = std::thread(&ControlServer::AcceptLoop, this);
        return true;
    }

    void AcceptLoop() {
        while (is_running_ && !shouldStop()) {
            fd_set fds;
            FD_ZERO(&fds);
            FD_SET(server_fd_, &fds);
            struct timeval tv;
            tv.tv_sec = 1;
            tv.tv_usec = 0;
            
            int ret = select(server_fd_ + 1, &fds, NULL, NULL, &tv);
            if (ret <= 0) continue;
            
            sockaddr_in client_addr;
            socklen_t len = sizeof(client_addr);
            int client = accept(server_fd_, (sockaddr*)&client_addr, &len);
            if (client < 0) continue;
            
            std::cout << "[Control] Client connected" << std::endl;
            std::thread(&ControlServer::HandleClient, this, client).detach();
        }
    }

    void HandleClient(int fd) {
        // 设置接收超时
        struct timeval tv;
        tv.tv_sec = 1;
        tv.tv_usec = 0;
        setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
        
        while (is_running_ && !shouldStop()) {
            Command cmd;
            int n = recv(fd, &cmd, sizeof(cmd), MSG_WAITALL);
            if (n <= 0) {
                if (errno == EAGAIN || errno == EWOULDBLOCK) continue;  // 超时
                break;
            }
            
            if (cmd.magic != 0x54534E49) break;
            
            // 下载命令特殊处理
            if (cmd.type == 5) {
                std::string result;
                bool ok = HandleDownload(fd, cmd, result);
                // 下载命令已经发送过响应，跳过标准响应
                if (!ok) {
                    uint32_t status = 1;
                    uint32_t len = result.size();
                    send(fd, &status, 4, MSG_NOSIGNAL);
                    send(fd, &len, 4, MSG_NOSIGNAL);
                    if (!result.empty()) {
                        send(fd, result.data(), len, MSG_NOSIGNAL);
                    }
                }
                continue;
            }
            
            std::string result;
            bool ok = false;
            
            switch (cmd.type) {
                case 1: // 拍照
                    std::cout << "[Control] Taking photo..." << std::endl;
                    ok = Capture(result);
                    break;
                case 2: // 开始录像
                    std::cout << "[Control] Starting record..." << std::endl;
                    ok = RecordStart(result);
                    break;
                case 3: // 停止录像
                    std::cout << "[Control] Stopping record..." << std::endl;
                    ok = RecordStop(result);
                    break;
                case 4: // 获取文件列表
                    ok = GetFileList(result);
                    break;
                default:
                    result = "Unknown command";
            }
            
            // 发送响应
            uint32_t status = ok ? 0 : 1;
            uint32_t len = result.size();
            send(fd, &status, 4, MSG_NOSIGNAL);
            send(fd, &len, 4, MSG_NOSIGNAL);
            if (!result.empty()) {
                send(fd, result.data(), len, MSG_NOSIGNAL);
            }
        }
        close(fd);
    }
    
    bool HandleDownload(int fd, const Command& cmd, std::string& result) {
        // 接收文件名
        std::vector<char> name_buf(cmd.param_len + 1);
        if (cmd.param_len > 0) {
            if (recv(fd, name_buf.data(), cmd.param_len, MSG_WAITALL) != cmd.param_len) {
                result = "Failed to receive filename";
                return false;
            }
        }
        name_buf[cmd.param_len] = '\0';
        std::string filename(name_buf.data());
        
        std::cout << "[Control] Downloading: " << filename << std::endl;
        
        std::lock_guard<std::mutex> lock(cam_mutex_);
        if (!cam_) {
            result = "Camera not available";
            return false;
        }
        
        // 下载到临时文件
        std::string local_path = "/tmp/download_" + std::to_string(getpid()) + ".tmp";
        std::cout << "[Control] Downloading to: " << local_path << std::endl;
        
        int64_t total_size = 0;
        bool download_ok = cam_->DownloadCameraFile(filename, local_path,
            [&total_size](int64_t current, int64_t total) {
                total_size = total;
                if (total > 0 && current % (total/10) == 0) {
                    std::cout << "[Control] Download progress: " << (current*100/total) << "%" << std::endl;
                }
            });
        
        if (!download_ok) {
            result = "Download failed";
            return false;
        }
        
        std::cout << "[Control] Downloaded to temp file, size: " << total_size << std::endl;
        
        // 检查文件是否存在及大小
        struct stat st;
        if (stat(local_path.c_str(), &st) != 0) {
            result = "Temp file not found";
            return false;
        }
        std::cout << "[Control] Temp file size: " << st.st_size << " bytes" << std::endl;
        
        // 读取文件
        FILE* f = fopen(local_path.c_str(), "rb");
        if (!f) {
            result = "Failed to open file";
            unlink(local_path.c_str());
            return false;
        }
        
        fseek(f, 0, SEEK_END);
        long file_size = ftell(f);
        fseek(f, 0, SEEK_SET);
        std::cout << "[Control] Sending file: " << file_size << " bytes" << std::endl;
        
        // 发送成功状态 + 文件大小
        uint32_t status = 0;
        uint32_t size = file_size;
        send(fd, &status, 4, MSG_NOSIGNAL);
        send(fd, &size, 4, MSG_NOSIGNAL);
        
        // 发送文件内容
        char buf[65536];
        size_t n;
        size_t total_sent = 0;
        while ((n = fread(buf, 1, sizeof(buf), f)) > 0) {
            ssize_t sent = send(fd, buf, n, MSG_NOSIGNAL);
            if (sent < 0) {
                std::cerr << "[Control] Send failed" << std::endl;
                break;
            }
            total_sent += sent;
        }
        fclose(f);
        unlink(local_path.c_str());
        
        std::cout << "[Control] Download complete: " << total_sent << " bytes" << std::endl;
        result = "OK";
        return true;
    }

    bool Capture(std::string& result) {
        std::lock_guard<std::mutex> lock(cam_mutex_);
        if (!cam_) return false;
        
        cam_->SetPhotoSubMode(ins_camera::SubPhotoMode::PHOTO_SINGLE);
        auto url = cam_->TakePhoto();
        if (url.Empty()) return false;
        
        for (const auto& u : url.OriginUrls()) {
            result += u + "\n";
        }
        std::cout << "[Control] Photo: " << result << std::endl;
        return true;
    }

    bool RecordStart(std::string& result) {
        std::lock_guard<std::mutex> lock(cam_mutex_);
        if (!cam_) return false;
        
        // 先停止预览流（避免冲突）
        cam_->StopLiveStreaming();
        std::this_thread::sleep_for(std::chrono::milliseconds(500));
        
        // 切换到录像模式
        if (!cam_->SetVideoSubMode(ins_camera::SubVideoMode::VIDEO_NORMAL)) {
            result = "Failed to set video mode";
            return false;
        }
        
        ins_camera::RecordParams params;
        params.resolution = ins_camera::VideoResolution::RES_8KP30;
        params.bitrate = 10 * 1024 * 1024;
        
        if (!cam_->SetVideoCaptureParams(params, 
                ins_camera::CameraFunctionMode::FUNCTION_MODE_NORMAL_VIDEO)) {
            result = "Failed to set params";
            return false;
        }
        
        if (!cam_->StartRecording()) {
            result = "Failed to start";
            // 恢复预览流
            RestartPreview();
            return false;
        }
        
        is_recording_ = true;
        result = "Recording started (8K)";
        std::cout << "[Control] Recording started" << std::endl;
        return true;
    }
    
    bool RecordStop(std::string& result) {
        std::lock_guard<std::mutex> lock(cam_mutex_);
        if (!cam_) return false;
        
        if (!is_recording_) {
            result = "Not recording";
            return false;
        }
        
        auto url = cam_->StopRecording();
        is_recording_ = false;
        
        if (url.Empty()) {
            result = "Failed to stop (no url)";
            // 恢复预览流
            RestartPreview();
            return false;
        }
        
        for (const auto& u : url.OriginUrls()) {
            result += u + "\n";
        }
        std::cout << "[Control] Video saved: " << result << std::endl;
        
        // 恢复预览流
        RestartPreview();
        
        return true;
    }
    
    void RestartPreview() {
        if (!cam_) return;
        
        std::this_thread::sleep_for(std::chrono::milliseconds(500));
        
        ins_camera::LiveStreamParam param;
        param.video_resolution = ins_camera::VideoResolution::RES_1440_720P30;
        param.lrv_video_resulution = ins_camera::VideoResolution::RES_1440_720P30;
        param.video_bitrate = 2 * 1024 * 1024;
        param.enable_audio = false;
        param.using_lrv = false;
        
        if (!cam_->StartLiveStreaming(param)) {
            std::cerr << "[Control] Failed to restart preview" << std::endl;
        } else {
            std::cout << "[Control] Preview restarted" << std::endl;
        }
    }

    bool GetFileList(std::string& result) {
        std::lock_guard<std::mutex> lock(cam_mutex_);
        if (!cam_) return false;
        
        auto files = cam_->GetCameraFilesList();
        for (const auto& f : files) {
            result += f + "\n";
        }
        return true;
    }



    void Stop() {
        is_running_ = false;
        close(server_fd_);
        if (thread_.joinable()) thread_.join();
    }

private:
    int server_fd_ = -1;
    std::thread thread_;
    std::atomic<bool> is_running_{false};
    std::shared_ptr<ins_camera::Camera> cam_;
    std::mutex cam_mutex_;
    std::atomic<bool> is_recording_{false};
};

volatile sig_atomic_t g_stop = 0;

void signalHandler(int sig) {
    g_stop = 1;
    std::cout << "\n[Signal] Received signal " << sig << ", shutting down..." << std::endl;
}

// 全局访问函数
bool shouldStop() { return g_stop != 0; }

int main(int argc, char* argv[]) {
    signal(SIGINT, signalHandler);
    signal(SIGTERM, signalHandler);
    
    // 参数: <stream_port> <control_port> <lens>
    int stream_port = (argc >= 2) ? std::atoi(argv[1]) : 8888;
    int control_port = (argc >= 3) ? std::atoi(argv[2]) : 8889;
    int lens = (argc >= 4) ? std::atoi(argv[3]) : 3;
    
    std::cout << "========================================" << std::endl;
    std::cout << "Camera All-in-One Server" << std::endl;
    std::cout << "Stream port: " << stream_port << std::endl;
    std::cout << "Control port: " << control_port << std::endl;
    std::cout << "Lens: " << lens << " (1=front, 2=rear, 3=all)" << std::endl;
    std::cout << "========================================" << std::endl;
    
RESTART:
    // 连接相机
    ins_camera::DeviceDiscovery discovery;
    auto list = discovery.GetAvailableDevices();
    if (list.empty()) {
        std::cerr << "No camera, retrying in 3s..." << std::endl;
        std::this_thread::sleep_for(std::chrono::seconds(3));
        goto RESTART;
    }
    
    std::cout << "Found: " << list[0].camera_name << std::endl;
    
    auto cam = std::make_shared<ins_camera::Camera>(list[0].info);
    if (!cam->Open()) {
        std::cerr << "Failed to open, retrying..." << std::endl;
        std::this_thread::sleep_for(std::chrono::seconds(3));
        goto RESTART;
    }
    
    // 设置镜头
    if (lens >= 1 && lens <= 3) {
        cam->SetActiveSensor(static_cast<ins_camera::SensorDevice>(lens));
    }
    
    // 同步时间
    time_t now = time(nullptr);
    tm tm_local{};
    localtime_r(&now, &tm_local);
    cam->SyncLocalTimeToCamera(now, timegm(&tm_local) - now);
    
    // 启动推流服务器
    TCPStreamer streamer;
    if (!streamer.Start(stream_port)) {
        cam->Close();
        return -1;
    }
    
    // 启动控制服务器
    ControlServer control;
    if (!control.Start(control_port, cam)) {
        cam->Close();
        return -1;
    }
    
    // 设置流回调
    std::shared_ptr<ins_camera::StreamDelegate> stream_delegate(&streamer, 
        [](ins_camera::StreamDelegate*){});
    cam->SetStreamDelegate(stream_delegate);
    
    // 启动预览流（用于推流）
    ins_camera::LiveStreamParam param;
    param.video_resolution = ins_camera::VideoResolution::RES_1440_720P30;
    param.lrv_video_resulution = ins_camera::VideoResolution::RES_1440_720P30;
    param.video_bitrate = 2 * 1024 * 1024;
    param.enable_audio = false;
    param.using_lrv = false;
    
    if (!cam->StartLiveStreaming(param)) {
        std::cerr << "Failed to start streaming!" << std::endl;
        cam->Close();
        return -1;
    }
    
    std::cout << "\n========================================" << std::endl;
    std::cout << "Server ready!" << std::endl;
    std::cout << "Stream: tcp://<ip>:" << stream_port << std::endl;
    std::cout << "Control: tcp://<ip>:" << control_port << std::endl;
    std::cout << "========================================" << std::endl;
    
    // 主循环 - 看门狗
    int fail_count = 0;
    while (!shouldStop()) {
        std::this_thread::sleep_for(std::chrono::seconds(1));
        
        if (!cam->IsConnected()) {
            fail_count++;
            if (fail_count >= 3) {
                std::cerr << "Camera disconnected, restarting..." << std::endl;
                break;
            }
        } else {
            fail_count = 0;
        }
    }
    
    // 清理
    control.Stop();
    streamer.Stop();
    cam->StopLiveStreaming();
    cam->Close();
    
    if (g_stop) return 0;
    
    std::cout << "Restarting in 3s..." << std::endl;
    std::this_thread::sleep_for(std::chrono::seconds(3));
    goto RESTART;
}
