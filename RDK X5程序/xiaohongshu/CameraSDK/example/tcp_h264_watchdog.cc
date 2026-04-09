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

#include <camera/camera.h>
#include <camera/photography_settings.h>
#include <camera/device_discovery.h>

// TCP H264服务器 - 简化版，带看门狗重启
class TCPH264Server : public ins_camera::StreamDelegate {
public:
    TCPH264Server() = default;
    ~TCPH264Server() { Stop(); }

    bool Start(int port) {
        server_fd_ = socket(AF_INET, SOCK_STREAM, 0);
        if (server_fd_ < 0) return false;
        
        int opt = 1;
        setsockopt(server_fd_, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));
        
        sockaddr_in addr;
        addr.sin_family = AF_INET;
        addr.sin_addr.s_addr = INADDR_ANY;
        addr.sin_port = htons(port);
        
        if (bind(server_fd_, (sockaddr*)&addr, sizeof(addr)) < 0) {
            std::cerr << "Bind failed" << std::endl;
            return false;
        }
        
        if (listen(server_fd_, 1) < 0) return false;
        
        std::cout << "TCP Server on port " << port << std::endl;
        
        is_running_ = true;
        accept_thread_ = std::thread(&TCPH264Server::AcceptLoop, this);
        return true;
    }

    void AcceptLoop() {
        while (is_running_) {
            sockaddr_in client_addr;
            socklen_t addr_len = sizeof(client_addr);
            int client = accept(server_fd_, (sockaddr*)&client_addr, &addr_len);
            if (client < 0) continue;
            
            std::cout << "Client connected from " << inet_ntoa(client_addr.sin_addr) << std::endl;
            {
                std::lock_guard<std::mutex> lock(mutex_);
                if (client_fd_ > 0) {
                    close(client_fd_);
                }
                client_fd_ = client;
            }
        }
    }

    void OnVideoData(const uint8_t* data, size_t size, int64_t timestamp, 
                     uint8_t streamType, int stream_index) override {
        if (stream_index != 0) return;
        
        std::lock_guard<std::mutex> lock(mutex_);
        if (client_fd_ > 0) {
            uint32_t len = htonl(size);
            if (send(client_fd_, &len, 4, MSG_NOSIGNAL) < 0 ||
                send(client_fd_, data, size, MSG_NOSIGNAL) < 0) {
                close(client_fd_);
                client_fd_ = -1;
                return;
            }
        }
        
        frame_count_++;
        auto now = std::chrono::steady_clock::now();
        auto elapsed = std::chrono::duration_cast<std::chrono::seconds>(now - last_print_time_).count();
        if (elapsed >= 5) {
            std::cout << "Sending... " << frame_count_ / elapsed << " fps" << std::endl;
            frame_count_ = 0;
            last_print_time_ = now;
        }
    }

    void OnAudioData(const uint8_t* data, size_t size, int64_t timestamp) override {}
    void OnGyroData(const std::vector<ins_camera::GyroData>& data) override {}
    void OnExposureData(const ins_camera::ExposureData& data) override {}

    void Stop() {
        is_running_ = false;
        close(server_fd_);
        close(client_fd_);
        if (accept_thread_.joinable()) {
            accept_thread_.join();
        }
    }

private:
    int server_fd_ = -1;
    int client_fd_ = -1;
    std::mutex mutex_;
    std::thread accept_thread_;
    std::atomic<bool> is_running_{false};
    std::atomic<int> frame_count_{0};
    std::chrono::steady_clock::time_point last_print_time_ = std::chrono::steady_clock::now();
};

static std::atomic<bool> g_stop{false};

void signalHandler(int sig) {
    g_stop = true;
}

int runServer(int port, int sensor) {
    ins_camera::SetLogLevel(ins_camera::LogLevel::ERR);
    
    std::cout << "\n========================================" << std::endl;
    std::cout << "Starting server..." << std::endl;
    
    std::cout << "Searching for camera..." << std::endl;
    ins_camera::DeviceDiscovery discovery;
    auto list = discovery.GetAvailableDevices();
    
    if (list.empty()) {
        std::cerr << "No camera!" << std::endl;
        return -1;
    }
    
    std::cout << "Found: " << list[0].camera_name << std::endl;
    
    auto cam = std::make_shared<ins_camera::Camera>(list[0].info);
    
    if (!cam->Open()) {
        std::cerr << "Failed to open!" << std::endl;
        return -1;
    }
    
    // 切换镜头
    if (sensor >= 1 && sensor <= 3) {
        std::cout << "Setting sensor to " << sensor << "..." << std::endl;
        if (!cam->SetActiveSensor(static_cast<ins_camera::SensorDevice>(sensor))) {
            std::cerr << "WARNING: SetActiveSensor failed" << std::endl;
        }
    }
    
    // 同步时间
    time_t now = time(nullptr);
    tm tm_local{};
    localtime_r(&now, &tm_local);
    cam->SyncLocalTimeToCamera(now, timegm(&tm_local) - now);
    
    auto server = std::make_shared<TCPH264Server>();
    
    if (!server->Start(port)) {
        cam->Close();
        return -1;
    }
    
    std::shared_ptr<ins_camera::StreamDelegate> d = server;
    cam->SetStreamDelegate(d);
    
    ins_camera::LiveStreamParam param;
    param.video_resolution = ins_camera::VideoResolution::RES_1440_720P30;
    param.lrv_video_resulution = ins_camera::VideoResolution::RES_1440_720P30;
    param.video_bitrate = 2 * 1024 * 1024;
    param.enable_audio = false;
    param.using_lrv = false;
    
    std::cout << "Starting live stream..." << std::endl;
    
    if (!cam->StartLiveStreaming(param)) {
        std::cerr << "Failed to start stream!" << std::endl;
        server->Stop();
        cam->Close();
        return -1;
    }
    
    std::cout << "========================================" << std::endl;
    std::cout << "Server ready! Port: " << port << std::endl;
    std::cout << "Sensor: " << sensor << std::endl;
    std::cout << "========================================" << std::endl;
    
    // 主循环 - 检查相机状态
    int fail_count = 0;
    while (!g_stop) {
        std::this_thread::sleep_for(std::chrono::seconds(1));
        
        if (!cam->IsConnected()) {
            fail_count++;
            std::cerr << "Connection check failed (" << fail_count << "/3)" << std::endl;
            if (fail_count >= 3) {
                std::cerr << "Camera disconnected!" << std::endl;
                break;
            }
        } else {
            fail_count = 0;
        }
    }
    
    // 清理
    server->Stop();
    cam->StopLiveStreaming();
    cam->Close();
    
    if (g_stop) {
        return 0;  // 正常退出
    }
    return -1;  // 需要重启
}

int main(int argc, char* argv[]) {
    signal(SIGINT, signalHandler);
    signal(SIGTERM, signalHandler);
    
    int port = (argc >= 2) ? std::atoi(argv[1]) : 8888;
    int sensor = (argc >= 3) ? std::atoi(argv[2]) : 3;
    
    int restart_count = 0;
    
    while (!g_stop) {
        int ret = runServer(port, sensor);
        
        if (ret == 0) {
            break;  // 正常退出
        }
        
        restart_count++;
        std::cerr << "Server crashed (" << restart_count << "), restarting in 3s..." << std::endl;
        std::this_thread::sleep_for(std::chrono::seconds(3));
        
        // 清理残留
        system("sudo pkill -9 -f tcp_h264_watchdog 2>/dev/null");
        std::this_thread::sleep_for(std::chrono::seconds(1));
    }
    
    std::cout << "Server stopped." << std::endl;
    return 0;
}
