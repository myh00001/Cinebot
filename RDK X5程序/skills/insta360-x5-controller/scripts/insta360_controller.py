#!/usr/bin/env python3
import os
import sys
import argparse
import json
import re
import subprocess
import shutil
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path("/home/sunrise/xiaohongshu")
PHOTO_SCRIPT = PROJECT_ROOT / "photo_record_control.py"

DEFAULT_CAMERA_HOST = "192.168.88.189"
DEFAULT_CONTROL_PORT = 8889
DEFAULT_SAVE_DIR = PROJECT_ROOT / "captures"

SILICON_FLOW_API_KEY = "sk-geucxoybionmhpkuknffqegmjqogipihmlwuhqaufysuhbub"
SILICON_FLOW_BASE_URL = "https://api.siliconflow.cn/v1"


class ImageProcessor:
    def __init__(self):
        try:
            from PIL import Image, ImageEnhance, ImageFilter

            self.PIL_AVAILABLE = True
        except ImportError:
            print("[Warning] Pillow not installed. Install with: pip install pillow")
            self.PIL_AVAILABLE = False

    def crop_panorama(self, image_path: str, crop_info: dict, output_path: str) -> str:
        if not self.PIL_AVAILABLE:
            return None

        from PIL import Image

        img = Image.open(image_path)
        width, height = img.size

        x = int(crop_info.get("x", 0))
        y = int(crop_info.get("y", 0))
        w = int(crop_info.get("width", width))
        h = int(crop_info.get("height", height))

        x = min(max(x, 0), width - 1)
        y = min(max(y, 0), height - 1)
        w = min(w, width - x)
        h = min(h, height - y)

        cropped = img.crop((x, y, x + w, y + h))
        cropped.save(output_path, quality=95)
        print(f"[Cropped] {w}x{h} -> {output_path}")
        return output_path

    def apply_style(self, image_path: str, style: str, output_path: str) -> str:
        if not self.PIL_AVAILABLE:
            return None

        from PIL import Image, ImageEnhance, ImageFilter

        img = Image.open(image_path)

        style_lower = style.lower()

        if "清新" in style_lower or "日系" in style_lower:
            img = self._apply_japanese_style(img)
        elif "复古" in style_lower or "vintage" in style_lower:
            img = self._apply_vintage_style(img)
        elif "电影" in style_lower or "cinematic" in style_lower:
            img = self._apply_cinematic_style(img)
        elif "黑白" in style_lower or "bw" in style_lower:
            img = img.convert("L").convert("RGB")
        elif "暖色" in style_lower or "warm" in style_lower:
            img = self._apply_warm_style(img)
        elif "冷色" in style_lower or "cool" in style_lower:
            img = self._apply_cool_style(img)
        elif "鲜艳" in style_lower or "vivid" in style_lower:
            img = self._apply_vivid_style(img)
        elif "赛博朋克" in style_lower or "cyberpunk" in style_lower:
            img = self._apply_cyberpunk_style(img)

        img.save(output_path, quality=95)
        print(f"[Style] Applied: {style} -> {output_path}")
        return output_path

    def _apply_japanese_style(self, img):
        from PIL import ImageEnhance

        enhancer = ImageEnhance.Brightness(img)
        img = enhancer.enhance(1.1)
        enhancer = ImageEnhance.Color(img)
        img = enhancer.enhance(0.9)
        enhancer = ImageEnhance.Contrast(img)
        img = enhancer.enhance(0.95)
        return img

    def _apply_vintage_style(self, img):
        from PIL import ImageEnhance, ImageFilter

        img = img.filter(ImageFilter.GaussianBlur(radius=0.5))
        enhancer = ImageEnhance.Color(img)
        img = enhancer.enhance(0.7)
        enhancer = ImageEnhance.Brightness(img)
        img = enhancer.enhance(0.9)
        enhancer = ImageEnhance.Contrast(img)
        img = enhancer.enhance(0.85)
        return img

    def _apply_cinematic_style(self, img):
        from PIL import ImageEnhance

        enhancer = ImageEnhance.Contrast(img)
        img = enhancer.enhance(1.2)
        enhancer = ImageEnhance.Color(img)
        img = enhancer.enhance(0.85)
        enhancer = ImageEnhance.Brightness(img)
        img = enhancer.enhance(0.95)
        return img

    def _apply_warm_style(self, img):
        from PIL import ImageEnhance

        enhancer = ImageEnhance.Color(img)
        img = enhancer.enhance(1.1)
        return img

    def _apply_cool_style(self, img):
        from PIL import ImageEnhance

        enhancer = ImageEnhance.Color(img)
        img = enhancer.enhance(0.9)
        return img

    def _apply_vivid_style(self, img):
        from PIL import ImageEnhance

        enhancer = ImageEnhance.Color(img)
        img = enhancer.enhance(1.4)
        enhancer = ImageEnhance.Contrast(img)
        img = enhancer.enhance(1.1)
        return img

    def _apply_cyberpunk_style(self, img):
        from PIL import ImageEnhance

        enhancer = ImageEnhance.Contrast(img)
        img = enhancer.enhance(1.3)
        enhancer = ImageEnhance.Color(img)
        img = enhancer.enhance(0.8)
        enhancer = ImageEnhance.Brightness(img)
        img = enhancer.enhance(0.9)
        return img


class Insta360Controller:
    def __init__(self, host=DEFAULT_CAMERA_HOST, control_port=DEFAULT_CONTROL_PORT):
        self.host = host
        self.control_port = control_port
        self.save_dir = DEFAULT_SAVE_DIR
        self.save_dir.mkdir(exist_ok=True)
        self.image_processor = ImageProcessor()

    def run_script(self, *args):
        cmd = [
            sys.executable,
            str(PHOTO_SCRIPT),
            self.host,
            str(self.control_port),
        ] + list(args)
        result = subprocess.run(cmd, capture_output=True, text=True)
        return result

    def capture_photo(self, scene_description: str = None, auto_download: bool = True):
        print(f"[Capturing photo] on Insta360 X5...")
        print(f"   Host: {self.host}:{self.control_port}")

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        capture_dir = self.save_dir / f"capture_{timestamp}"
        capture_dir.mkdir(exist_ok=True)

        result = self.run_script("capture", str(capture_dir))

        if result.returncode != 0:
            print(result.stdout)
            print(result.stderr, file=sys.stderr)
            return {"success": False, "error": result.stdout + result.stderr}

        print(result.stdout)

        files = list(capture_dir.glob("*.jpg")) + list(capture_dir.glob("*.insv"))
        if not files:
            return {"success": False, "error": "No file downloaded"}

        original_photo = str(files[0])
        print(f"   Saved: {original_photo}")

        processed = None
        if scene_description and original_photo and original_photo.endswith(".jpg"):
            print(f"\n[AI] Processing with multimodal AI...")
            print(f"   Scene requirement: {scene_description}")
            processed = self.process_with_multimodal(
                original_photo, scene_description, capture_dir
            )

        return {
            "success": True,
            "original_photo": original_photo,
            "processed_photo": processed,
            "capture_dir": str(capture_dir),
        }

    def process_with_multimodal(
        self, image_path: str, scene_requirement: str, output_dir: Path
    ) -> str:
        if not SILICON_FLOW_API_KEY:
            print("[Warning] SILICON_API_KEY not set")
            return None

        from PIL import Image

        img = Image.open(image_path)
        img_width, img_height = img.size
        print(f"   Image size: {img_width}x{img_height}")

        base_name = Path(image_path).stem
        crop_output = str(output_dir / f"{base_name}_cropped.jpg")
        style_output = str(output_dir / f"{base_name}_styled.jpg")

        prompt = f"""你是一个专业的图像裁剪专家。请分析这张360°全景照片，根据用户需求确定最佳的裁剪区域。

【用户需求】
{scene_requirement}

【图片基本信息】
- 图片尺寸：{img_width} x {img_height} 像素
- 图片格式：360°全景等距柱状投影图（Equirectangular Projection）

【坐标系统说明 - 非常重要】
这张图片使用标准像素坐标系（和计算机屏幕坐标一致）：
- 左上角坐标是 (0, 0)
- 右下角坐标是 ({img_width}, {img_height})
- X轴：从左到右，0 → {img_width}
- Y轴：从上到下，0 → {img_height}（Y值越大，位置越靠下）

【关键理解】
- 图片顶部（天空/天花板）：Y = 0 到 ~800
- 图片中部（水平视线，人物站立处）：Y = ~1500 到 ~2800
- 图片底部（地面）：Y = ~3200 到 {img_height}

【重要提醒】
如果主体在"画面下方"或"右下角"，Y坐标应该大于2000！
如果主体在"画面上方"或"左上角"，Y坐标应该小于1000！

【分析任务】
请仔细观察图片，完成以下分析：

1. 画面内容描述：
   - 图片中有什么？（人物、物体、场景等）
   - 人物在哪里？（描述大致位置，如"图片右侧中间偏下"）

2. 主体定位：
   - 根据用户需求，确定要聚焦的主体
   - 估算主体的像素坐标范围
   - 主体中心大约在哪个坐标？(x, y)

3. 裁剪计算：
   - 基于主体位置，计算裁剪框的相对位置和大小
   - 使用比例值（0.0到1.0）而非绝对像素
   - 确保主体完整显示在裁剪框内

【输出格式】
请严格返回以下JSON格式：
{{
    "scene_analysis": "对画面内容的详细描述",
    "main_subject": "识别出的主体是什么",
    "crop_center_ratio": {{
        "x_ratio": "主体中心点在X轴的相对位置 (0.0到1.0的浮点数。0.1在极左侧，0.5在正中间，0.9在极右侧)",
        "y_ratio": "主体中心点在Y轴的相对位置 (0.0到1.0的浮点数。0.2在偏上方，0.5在正中间，0.8在偏下方)"
    }},
    "suggested_size": {{
        "width_ratio": "裁剪宽度占原图的比例 (建议 0.2 到 0.4 之间)",
        "height_ratio": "裁剪高度占原图的比例 (建议 0.2 到 0.4 之间)"
    }},
    "style": "风格类型"
}}

【重要提示】
- 使用相对比例（0.0到1.0）而非绝对像素值
- x_ratio: 0.0=最左, 0.5=中央, 1.0=最右
- y_ratio: 0.0=最上, 0.5=中央, 1.0=最下
- 如果人物在画面右侧，x_ratio应该大于0.5
- 如果人物在画面下方，y_ratio应该大于0.5
- 只返回JSON，不要其他内容"""

        try:
            import base64
            import requests

            with open(image_path, "rb") as f:
                img_b64 = base64.b64encode(f.read()).decode("utf-8")

            response = requests.post(
                f"{SILICON_FLOW_BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {SILICON_FLOW_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "Qwen/Qwen3-VL-8B-Instruct",
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": prompt},
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:image/jpeg;base64,{img_b64}"
                                    },
                                },
                            ],
                        }
                    ],
                    "max_tokens": 1024,
                    "temperature": 0.1,
                },
                timeout=120,
            )

            result = response.json()

            if "choices" not in result:
                print(f"[Error] API response error: {result}")
                return None

            ai_response = result["choices"][0]["message"]["content"]
            print(f"[AI] Response:\n{ai_response}\n")

            json_match = re.search(r"\{[\s\S]*\}", ai_response)
            if not json_match:
                print("[Warning] Failed to parse JSON from AI response")
                return None

            crop_info = json.loads(json_match.group())

            print(f"[Debug] AI Analysis:")
            print(f"   Scene: {crop_info.get('scene_analysis', 'N/A')}")
            print(f"   Main subject: {crop_info.get('main_subject', 'N/A')}")

            # 解析 AI 返回的比例数据
            center = crop_info.get(
                "crop_center_ratio", {"x_ratio": 0.5, "y_ratio": 0.5}
            )
            size = crop_info.get(
                "suggested_size", {"width_ratio": 0.3, "height_ratio": 0.3}
            )

            x_ratio = float(center.get("x_ratio", 0.5))
            y_ratio = float(center.get("y_ratio", 0.5))
            width_ratio = float(size.get("width_ratio", 0.3))
            height_ratio = float(size.get("height_ratio", 0.3))

            print(f"[Debug] AI returned ratios:")
            print(f"   Center: x_ratio={x_ratio}, y_ratio={y_ratio}")
            print(f"   Size: width_ratio={width_ratio}, height_ratio={height_ratio}")

            # 计算实际像素宽高
            w = int(width_ratio * img_width)
            h = int(height_ratio * img_height)

            # 计算中心点像素坐标
            center_x_pixel = int(x_ratio * img_width)
            center_y_pixel = int(y_ratio * img_height)

            # 计算左上角起点 (x, y) = 中心点 - 宽高的一半
            x = center_x_pixel - (w // 2)
            y = center_y_pixel - (h // 2)

            # 确保不越界
            x = max(0, min(x, img_width - w))
            y = max(0, min(y, img_height - h))

            # 组装给原裁剪函数的字典
            crop_data = {"x": x, "y": y, "width": w, "height": h}

            print(f"[Debug] Converted to pixel coordinates:")
            print(f"   Center: ({center_x_pixel}, {center_y_pixel})")
            print(f"   Crop box: x={x}, y={y}, width={w}, height={h}")

            crop_result = self.image_processor.crop_panorama(
                image_path, crop_data, crop_output
            )

            style = crop_info.get("style", "原图")
            if style != "原图" and crop_result:
                final_output = self.image_processor.apply_style(
                    crop_result, style, style_output
                )
            else:
                final_output = crop_result

            result_text = f"裁剪描述: {crop_info.get('description', 'N/A')}\n"
            result_text += f"风格: {style}\n"
            result_text += f"输出文件: {final_output or '处理失败'}"

            return result_text

        except ImportError:
            print(
                "[Warning] Requests library not installed. Install with: pip install requests"
            )
            return None
        except Exception as e:
            print(f"[Error] Multimodal AI: {e}")
            import traceback

            traceback.print_exc()
            return f"Error: {e}"

    def record_start(self):
        print(f"[Starting recording] on Insta360 X5...")
        result = self.run_script("record_start")
        print(result.stdout)
        return result.returncode == 0

    def record_stop(self, auto_download: bool = True):
        print(f"[Stopping recording] on Insta360 X5...")

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        capture_dir = self.save_dir / f"video_{timestamp}"
        capture_dir.mkdir(exist_ok=True)

        result = self.run_script("record_stop", str(capture_dir))
        print(result.stdout)

        if result.returncode == 0:
            files = list(capture_dir.glob("*.insv")) + list(capture_dir.glob("*.mp4"))
            if files:
                video_file = str(files[0])
                print(f"   Saved: {video_file}")
                return {"success": True, "video_file": video_file}

        return {"success": False, "error": result.stdout}

    def list_files(self):
        print(f"[Listing files] on camera...")
        result = self.run_script("list")
        print(result.stdout)
        return result.stdout


def interactive_mode():
    parser = argparse.ArgumentParser(description="Insta360 X5 Controller")
    parser.add_argument("--host", default=DEFAULT_CAMERA_HOST, help="Camera IP")
    parser.add_argument(
        "--control-port", type=int, default=DEFAULT_CONTROL_PORT, help="Control port"
    )
    parser.add_argument("--save-dir", type=str, default=None, help="Save directory")

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    capture_parser = subparsers.add_parser("capture", help="Take photo")
    capture_parser.add_argument(
        "--scene", type=str, help="Scene description for AI processing"
    )
    capture_parser.add_argument(
        "--no-download", action="store_true", help="Skip auto download"
    )

    subparsers.add_parser("record-start", help="Start recording")

    subparsers.add_parser("record-stop", help="Stop recording")
    subparsers.add_parser("list", help="List files")

    subparsers.add_parser("status", help="Get camera status")

    args = parser.parse_args()

    controller = Insta360Controller(host=args.host, control_port=args.control_port)

    if args.save_dir:
        controller.save_dir = Path(args.save_dir)
        controller.save_dir.mkdir(exist_ok=True)

    if args.command == "capture":
        auto_download = not args.no_download
        result = controller.capture_photo(
            scene_description=args.scene, auto_download=auto_download
        )
        if result.get("processed_photo"):
            print("\n" + "=" * 50)
            print("AI处理结果:")
            print(result["processed_photo"])
        elif args.scene and not result.get("processed_photo"):
            print("[Warning] AI processing failed, but original photo was captured")

    elif args.command == "record-start":
        controller.record_start()

    elif args.command == "record-stop":
        controller.record_stop()

    elif args.command == "list":
        controller.list_files()

    elif args.command == "status":
        print("Use 'list' command to see files")

    else:
        parser.print_help()


if __name__ == "__main__":
    interactive_mode()
