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

#include <camera/camera.h>
#include <camera/photography_settings.h>
#include <camera/device_discovery.h>

// TCP H264服务器 - 支持镜头切换
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
            
            std::cout << "Client connected" << std::endl;
            {
                std::lock_guard<std::mutex> lock(mutex_);
                if (client_fd_ > 0) close(client_fd_);  // 关闭旧连接
                client_fd_ = client;
            }
        }
    }

    void OnVideoData(const uint8_t* data, size_t size, int64_t timestamp, 
                     uint8_t streamType, int stream_index) override {
        // 发送所有流（如果要只发一个镜头，在这里过滤）
        std::lock_guard<std::mutex> lock(mutex_);
        if (client_fd_ > 0) {
            uint32_t len = htonl(size);
            if (send(client_fd_, &len, 4, MSG_NOSIGNAL) < 0) {
                close(client_fd_);
                client_fd_ = -1;
                return;
            }
            if (send(client_fd_, data, size, MSG_NOSIGNAL) < 0) {
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
        if (accept_thread_.joinable()) accept_thread_.join();
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

std::shared_ptr<ins_camera::Camera> g_cam = nullptr;
std::shared_ptr<TCPH264Server> g_server = nullptr;

void signalHandler(int sig) {
    if (g_server) g_server->Stop();
    if (g_cam) {
        g_cam->StopLiveStreaming();
        g_cam->Close();
    }
    exit(0);
}

int main(int argc, char* argv[]) {
    signal(SIGINT, signalHandler);
    
    int port = (argc >= 2) ? std::atoi(argv[1]) : 8888;
    
    // 默认镜头：1=前(屏幕侧), 2=后(背侧), 3=全景
    int sensor = (argc >= 3) ? std::atoi(argv[2]) : 3;
    
    ins_camera::SetLogLevel(ins_camera::LogLevel::ERR);
    
    std::cout << "Searching for camera..." << std::endl;
    ins_camera::DeviceDiscovery discovery;
    auto list = discovery.GetAvailableDevices();
    
    if (list.empty()) {
        std::cerr << "No camera!" << std::endl;
        return -1;
    }
    
    std::cout << "Found: " << list[0].camera_name << std::endl;
    
    auto cam = std::make_shared<ins_camera::Camera>(list[0].info);
    g_cam = cam;
    
    if (!cam->Open()) {
        std::cerr << "Failed to open!" << std::endl;
        return -1;
    }
    
    // ===== 尝试切换镜头 =====
    std::cout << "Setting sensor mode to " << sensor << "..." << std::endl;
    if (sensor >= 1 && sensor <= 3) {
        if (!cam->SetActiveSensor(static_cast<ins_camera::SensorDevice>(sensor))) {
            std::cerr << "WARNING: SetActiveSensor failed, using default" << std::endl;
        } else {
            std::cout << "Sensor set to " << sensor << std::endl;
        }
    }
    
    time_t now = time(nullptr);
    tm tm{};
    localtime_r(&now, &tm);
    cam->SyncLocalTimeToCamera(now, timegm(&tm) - now);
    
    auto server = std::make_shared<TCPH264Server>();
    g_server = server;
    
    if (!server->Start(port)) {
        cam->Close();
        return -1;
    }
    
    std::shared_ptr<ins_camera::StreamDelegate> d = server;
    cam->SetStreamDelegate(d);
    
    // 根据镜头选择分辨率
    ins_camera::VideoResolution resolution;
    if (sensor == 3) {
        // 全景模式用低分辨率
        resolution = ins_camera::VideoResolution::RES_1440_720P30;
    } else {
        // 单镜头可以用高分辨率
        resolution = ins_camera::VideoResolution::RES_1920_960P30;
    }
    
    ins_camera::LiveStreamParam param;
    param.video_resolution = resolution;
    param.lrv_video_resulution = ins_camera::VideoResolution::RES_1440_720P30;
    param.video_bitrate = 2 * 1024 * 1024;
    param.enable_audio = false;
    param.using_lrv = false;
    
    std::cout << "Starting live stream..." << std::endl;
    
    if (!cam->StartLiveStreaming(param)) {
        std::cerr << "Failed to start stream!" << std::endl;
        cam->Close();
        return -1;
    }
    
    std::cout << "\n========================================" << std::endl;
    std::cout << "TCP H264 Server Ready!" << std::endl;
    std::cout << "Port: " << port << std::endl;
    std::cout << "Sensor: " << sensor << " (1=front, 2=rear, 3=all)" << std::endl;
    std::cout << "Usage: python3 tcp_client.py <ip> " << port << std::endl;
    std::cout << "========================================" << std::endl;
    
    while (cam->IsConnected()) {
        std::this_thread::sleep_for(std::chrono::seconds(1));
    }
    
    server->Stop();
    cam->StopLiveStreaming();
    cam->Close();
    
    return 0;
}
