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
#include <fstream>
#include <vector>

#include <camera/camera.h>
#include <camera/photography_settings.h>
#include <camera/device_discovery.h>

// 命令协议
enum class Command : uint32_t {
    CAPTURE = 1,           // 拍照
    RECORD_START = 2,      // 开始录像
    RECORD_STOP = 3,       // 停止录像
    GET_FILE_LIST = 4,     // 获取文件列表
    DOWNLOAD_FILE = 5,     // 下载文件
    GET_STATUS = 6,        // 获取状态
    SWITCH_LENS = 7,       // 切换镜头 1=前 2=后 3=全
    PREVIEW_START = 8,     // 开始预览流
    PREVIEW_STOP = 9,      // 停止预览流
};

struct CommandHeader {
    uint32_t magic;        // 'INST' = 0x54534E49
    uint32_t cmd;          // 命令类型
    uint32_t param_len;    // 参数长度
    // 随后是参数数据
};

struct ResponseHeader {
    uint32_t magic;        // 'INST'
    uint32_t status;       // 0=成功, 1=失败
    uint32_t data_len;     // 数据长度
    // 随后是数据
};

// 相机控制服务器
class CameraControlServer {
public:
    CameraControlServer() = default;
    ~CameraControlServer() { Stop(); }

    bool Init(int port, std::shared_ptr<ins_camera::Camera> camera) {
        cam_ = camera;
        
        server_fd_ = socket(AF_INET, SOCK_STREAM, 0);
        if (server_fd_ < 0) return false;
        
        int opt = 1;
        setsockopt(server_fd_, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));
        
        sockaddr_in addr;
        addr.sin_family = AF_INET;
        addr.sin_addr.s_addr = INADDR_ANY;
        addr.sin_port = htons(port);
        
        if (bind(server_fd_, (sockaddr*)&addr, sizeof(addr)) < 0) {
            std::cerr << "Control server bind failed" << std::endl;
            return false;
        }
        
        if (listen(server_fd_, 2) < 0) return false;
        
        std::cout << "Control server on port " << port << std::endl;
        
        is_running_ = true;
        thread_ = std::thread(&CameraControlServer::AcceptLoop, this);
        return true;
    }

    void AcceptLoop() {
        while (is_running_) {
            sockaddr_in client_addr;
            socklen_t addr_len = sizeof(client_addr);
            int client = accept(server_fd_, (sockaddr*)&client_addr, &addr_len);
            if (client < 0) continue;
            
            std::cout << "Control client connected from " << inet_ntoa(client_addr.sin_addr) << std::endl;
            HandleClient(client);
        }
    }

    void HandleClient(int client_fd) {
        while (is_running_) {
            // 读取命令头
            CommandHeader hdr;
            if (recv_all(client_fd, &hdr, sizeof(hdr)) != sizeof(hdr)) {
                break;
            }
            
            if (hdr.magic != 0x54534E49) {  // 'INST'
                std::cerr << "Invalid magic" << std::endl;
                break;
            }
            
            // 读取参数
            std::vector<uint8_t> param(hdr.param_len);
            if (hdr.param_len > 0) {
                if (recv_all(client_fd, param.data(), hdr.param_len) != hdr.param_len) {
                    break;
                }
            }
            
            // 执行命令
            std::string result;
            bool success = ExecuteCommand(static_cast<Command>(hdr.cmd), param, result);
            
            // 发送响应
            ResponseHeader resp;
            resp.magic = 0x54534E49;
            resp.status = success ? 0 : 1;
            resp.data_len = result.size();
            
            send(client_fd, &resp, sizeof(resp), MSG_NOSIGNAL);
            if (!result.empty()) {
                send(client_fd, result.data(), result.size(), MSG_NOSIGNAL);
            }
        }
        
        close(client_fd);
        std::cout << "Control client disconnected" << std::endl;
    }

    bool ExecuteCommand(Command cmd, const std::vector<uint8_t>& param, std::string& result) {
        std::lock_guard<std::mutex> lock(cam_mutex_);
        
        if (!cam_ || !cam_->IsConnected()) {
            result = "Camera not connected";
            return false;
        }
        
        switch (cmd) {
            case Command::CAPTURE: {
                std::cout << "[CMD] Taking photo..." << std::endl;
                
                // 设置单拍模式
                cam_->SetPhotoSubMode(ins_camera::SubPhotoMode::PHOTO_SINGLE);
                
                // 拍照
                auto url = cam_->TakePhoto();
                if (url.Empty()) {
                    result = "Capture failed";
                    return false;
                }
                
                // 返回文件URL
                auto urls = url.OriginUrls();
                for (const auto& u : urls) {
                    result += u + "\n";
                }
                std::cout << "[CMD] Photo saved: " << result << std::endl;
                return true;
            }
            
            case Command::RECORD_START: {
                std::cout << "[CMD] Starting recording..." << std::endl;
                
                // 设置录像参数（最高画质）
                ins_camera::RecordParams record_params;
                record_params.resolution = ins_camera::VideoResolution::RES_8KP30;  // 8K
                record_params.bitrate = 10 * 1024 * 1024;  // 10Mbps
                
                if (!cam_->SetVideoCaptureParams(record_params, 
                        ins_camera::CameraFunctionMode::FUNCTION_MODE_NORMAL_VIDEO)) {
                    result = "Failed to set video params";
                    return false;
                }
                
                if (!cam_->StartRecording()) {
                    result = "Failed to start recording";
                    return false;
                }
                
                result = "Recording started";
                std::cout << "[CMD] Recording started (8K)" << std::endl;
                return true;
            }
            
            case Command::RECORD_STOP: {
                std::cout << "[CMD] Stopping recording..." << std::endl;
                
                auto url = cam_->StopRecording();
                if (url.Empty()) {
                    result = "Failed to stop recording";
                    return false;
                }
                
                auto urls = url.OriginUrls();
                for (const auto& u : urls) {
                    result += u + "\n";
                }
                std::cout << "[CMD] Recording saved: " << result << std::endl;
                return true;
            }
            
            case Command::GET_FILE_LIST: {
                std::cout << "[CMD] Getting file list..." << std::endl;
                
                auto files = cam_->GetCameraFilesList();
                for (const auto& f : files) {
                    result += f + "\n";
                }
                return true;
            }
            
            case Command::DOWNLOAD_FILE: {
                std::string filename(param.begin(), param.end());
                std::cout << "[CMD] Downloading: " << filename << std::endl;
                
                // 下载到临时文件
                std::string local_path = "/tmp/" + filename.substr(filename.find_last_of("/") + 1);
                
                int64_t total = 0, current = 0;
                bool ret = cam_->DownloadCameraFile(filename, local_path, 
                    [&current, &total](int64_t cur, int64_t tot) {
                        current = cur;
                        total = tot;
                        if (total > 0 && current % (total/10) == 0) {
                            std::cout << "Download: " << (current*100/total) << "%" << std::endl;
                        }
                    });
                
                if (!ret) {
                    result = "Download failed";
                    return false;
                }
                
                // 读取文件并发送
                std::ifstream file(local_path, std::ios::binary);
                if (!file) {
                    result = "Failed to read file";
                    return false;
                }
                
                result = std::string((std::istreambuf_iterator<char>(file)),
                                     std::istreambuf_iterator<char>());
                
                file.close();
                unlink(local_path.c_str());  // 删除临时文件
                
                std::cout << "[CMD] Download complete: " << result.size() << " bytes" << std::endl;
                return true;
            }
            
            case Command::GET_STATUS: {
                result = "Camera: " + std::string(cam_->IsConnected() ? "OK" : "Disconnected");
                return true;
            }
            
            case Command::SWITCH_LENS: {
                if (param.empty()) {
                    result = "Missing lens parameter";
                    return false;
                }
                int lens = param[0];
                std::cout << "[CMD] Switching to lens " << (int)lens << std::endl;
                
                if (!cam_->SetActiveSensor(static_cast<ins_camera::SensorDevice>(lens))) {
                    result = "Failed to switch lens";
                    return false;
                }
                result = "Lens switched to " + std::to_string(lens);
                return true;
            }
            
            default:
                result = "Unknown command";
                return false;
        }
    }

    ssize_t recv_all(int fd, void* buf, size_t len) {
        size_t received = 0;
        while (received < len) {
            ssize_t n = recv(fd, (char*)buf + received, len - received, 0);
            if (n <= 0) return n;
            received += n;
        }
        return received;
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
};

// 预览流服务器（同之前）
class PreviewServer : public ins_camera::StreamDelegate {
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
        
        std::cout << "Preview server on port " << port << std::endl;
        
        is_running_ = true;
        thread_ = std::thread(&PreviewServer::AcceptLoop, this);
        return true;
    }

    void AcceptLoop() {
        while (is_running_) {
            sockaddr_in client_addr;
            socklen_t len = sizeof(client_addr);
            int client = accept(server_fd_, (sockaddr*)&client_addr, &len);
            if (client < 0) continue;
            
            std::cout << "Preview client connected" << std::endl;
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
    int server_fd_ = -1;
    int client_fd_ = -1;
    std::mutex mutex_;
    std::thread thread_;
    std::atomic<bool> is_running_{false};
};

static std::atomic<bool> g_stop{false};

void signalHandler(int sig) {
    g_stop = true;
}

int main(int argc, char* argv[]) {
    signal(SIGINT, signalHandler);
    signal(SIGTERM, signalHandler);
    
    int preview_port = (argc >= 2) ? std::atoi(argv[1]) : 8888;
    int control_port = (argc >= 3) ? std::atoi(argv[2]) : 8889;
    int sensor = (argc >= 4) ? std::atoi(argv[3]) : 3;
    
    std::cout << "========================================" << std::endl;
    std::cout << "Camera Control Server" << std::endl;
    std::cout << "Preview port: " << preview_port << std::endl;
    std::cout << "Control port: " << control_port << std::endl;
    std::cout << "========================================" << std::endl;
    
    // 连接相机
    ins_camera::DeviceDiscovery discovery;
    auto list = discovery.GetAvailableDevices();
    if (list.empty()) {
        std::cerr << "No camera!" << std::endl;
        return -1;
    }
    
    std::cout << "Found: " << list[0].camera_name << std::endl;
    
    auto cam = std::make_shared<ins_camera::Camera>(list[0].info);
    if (!cam->Open()) {
        std::cerr << "Failed to open camera!" << std::endl;
        return -1;
    }
    
    // 同步时间
    time_t now = time(nullptr);
    tm tm_local{};
    localtime_r(&now, &tm_local);
    cam->SyncLocalTimeToCamera(now, timegm(&tm_local) - now);
    
    // 设置镜头
    if (sensor >= 1 && sensor <= 3) {
        cam->SetActiveSensor(static_cast<ins_camera::SensorDevice>(sensor));
    }
    
    // 启动控制服务器
    CameraControlServer control_server;
    if (!control_server.Init(control_port, cam)) {
        cam->Close();
        return -1;
    }
    
    // 启动预览服务器
    PreviewServer preview_server;
    if (!preview_server.Start(preview_port)) {
        cam->Close();
        return -1;
    }
    
    // 设置流回调（使用裸指针方式）
    std::shared_ptr<ins_camera::StreamDelegate> d(&preview_server, 
        [](ins_camera::StreamDelegate*){});
    cam->SetStreamDelegate(d);
    
    // 启动预览流
    ins_camera::LiveStreamParam param;
    param.video_resolution = ins_camera::VideoResolution::RES_1440_720P30;
    param.lrv_video_resulution = ins_camera::VideoResolution::RES_1440_720P30;
    param.video_bitrate = 2 * 1024 * 1024;
    param.enable_audio = false;
    param.using_lrv = false;
    
    if (!cam->StartLiveStreaming(param)) {
        std::cerr << "Failed to start preview!" << std::endl;
        cam->Close();
        return -1;
    }
    
    std::cout << "\n========================================" << std::endl;
    std::cout << "Server ready!" << std::endl;
    std::cout << "Preview: tcp://<ip>:" << preview_port << std::endl;
    std::cout << "Control: tcp://<ip>:" << control_port << std::endl;
    std::cout << "========================================" << std::endl;
    
    // 主循环
    while (!g_stop && cam->IsConnected()) {
        std::this_thread::sleep_for(std::chrono::seconds(1));
    }
    
    preview_server.Stop();
    control_server.Stop();
    cam->StopLiveStreaming();
    cam->Close();
    
    return 0;
}
