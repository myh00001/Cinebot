import spidev
import time
import math

# WS2812B 编码表（每个 WS2812 bit -> 3 个 SPI bit）
WS2812B_BIT_PATTERNS = {
    0: [1, 0, 0],  # "0"
    1: [1, 1, 0],  # "1"
}

def encode_ws2812_byte(byte):
    """把一个 8bit 数据转为 SPI 比特流"""
    bits = []
    for i in range(8):
        bit_val = (byte >> (7 - i)) & 1
        bits.extend(WS2812B_BIT_PATTERNS[bit_val])
    return bits

def encode_ws2812_data(rgb_data):
    """rgb_data = [(R,G,B), ...]"""
    spi_bits = []
    for (r, g, b) in rgb_data:
        # WS2812B 使用 GRB 顺序
        for val in (g, r, b):
            spi_bits.extend(encode_ws2812_byte(val))
    # 转成字节数组
    spi_bytes = []
    for i in range(0, len(spi_bits), 8):
        byte = 0
        for j in range(8):
            if i + j < len(spi_bits):
                byte = (byte << 1) | spi_bits[i+j]
        spi_bytes.append(byte)
    return spi_bytes

def hsv_to_rgb(h, s, v):
    """HSV转RGB，h范围0-1，s/v范围0-1，返回(R,G,B) 0-255"""
    if s == 0.0:
        return (int(v*255), int(v*255), int(v*255))

    i = int(h * 6)
    f = (h * 6) - i
    p = v * (1 - s)
    q = v * (1 - s * f)
    t = v * (1 - s * (1 - f))

    i = i % 6
    if i == 0:
        r, g, b = v, t, p
    elif i == 1:
        r, g, b = q, v, p
    elif i == 2:
        r, g, b = p, v, t
    elif i == 3:
        r, g, b = p, q, v
    elif i == 4:
        r, g, b = t, p, v
    else:
        r, g, b = v, p, q

    return (int(r*255), int(g*255), int(b*255))

class WS2812B:
    def __init__(self, num_leds, spi_bus=0, spi_dev=0, spi_speed=2400000):
        self.num_leds = num_leds
        self.leds = [(0,0,0)] * num_leds
        self.spi = spidev.SpiDev()
        self.spi.open(1, 0)
        self.spi.max_speed_hz = spi_speed
        self.spi.mode = 0

    def set_pixel(self, index, r, g, b, show_now=False):
        """设置指定灯珠颜色"""
        if 0 <= index < self.num_leds:
            self.leds[index] = (r, g, b)
        if show_now:
            self.show()

    def clear(self, show_now=True):
        """全部清零"""
        self.leds = [(0,0,0)] * self.num_leds
        if show_now:
            self.show()

    def show(self):
        """更新到灯带"""
        spi_data = encode_ws2812_data(self.leds)
        self.spi.xfer2(spi_data)
        time.sleep(0.001)

    def close(self):
        self.spi.close()

    def rainbow_cycle(self, speed=0.02):
        """彩虹循环效果 - 无限循环"""
        offset = 0
        while True:
            for i in range(self.num_leds):
                # 计算每个灯珠的色相（基于位置和循环进度）
                hue = ((i * 256 // self.num_leds) + offset) % 256 / 255.0
                r, g, b = hsv_to_rgb(hue, 1.0, 1.0)
                self.set_pixel(i, r, g, b, show_now=False)
            self.show()
            offset = (offset + 1) % 256
            time.sleep(speed)


# 使用示例：彩虹循环（无限循环）
if __name__ == "__main__":
    strip = WS2812B(num_leds=100)  # 100颗灯珠

    try:
        print(" 彩虹循环启动（无限循环）")
        print("按 Ctrl+C 停止")
        strip.rainbow_cycle(speed=0.02)

    except KeyboardInterrupt:
        print("\n程序被中断，清空调灯带")
        strip.clear()
    finally:
        strip.close()