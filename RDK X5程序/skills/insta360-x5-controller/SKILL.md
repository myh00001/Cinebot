---
name: "insta360-x5-controller"
description: "Control Insta360 X5 360° camera to take photos, process with multimodal AI. Invoke when user wants to take photos with Insta360 X5 camera and extract specific views from 360° panoramic images."
---

# Insta360 X5 Camera Controller

This skill controls Insta360 X5 360° camera via RDK X5, takes photos, and uses multimodal AI (Qwen3-VL) to crop and style panoramic images based on user requirements.

## Usage

Invoke this skill when user wants to:
- Take photos with Insta360 X5 360° camera
- Record videos
- Process 360° panoramic photos to extract specific views and apply styles

## Workflow

1. **Capture**: Call photo_record_control.py to control camera and download original photo
2. **Process**: Use Qwen3-VL (via SiliconFlow API) to analyze the 360° photo and determine:
   - Crop center position (x_ratio, y_ratio: 0.0-1.0)
   - Crop size (width_ratio, height_ratio: 0.0-1.0)
   - Style recommendation (赛博朋克/清新/复古/电影/黑白/鲜艳/暖色/冷色/原图)
3. **Convert**: Convert ratio coordinates to pixel coordinates
4. **Execute**: Crop and apply style using Pillow
5. **Return**: Provide original photo + processed photo

## Configuration

### Environment Variables
```bash
# SiliconFlow API Key (required for AI processing)
set SILICON_API_KEY=your_api_key
```

### Default Settings
- Camera IP: 192.168.88.189
- Control Port: 8889

## Image Processing Features

### Supported Styles
- 赛博朋克/Cyberpunk - Cyberpunk style (high contrast, neon, cool)
- 清新/日系 - Japanese style (bright, soft)
- 复古/Vintage - Vintage style (desaturated, warm)
- 电影/Cinematic - Cinematic style (high contrast, cool)
- 黑白/BW - Black and white
- 暖色/Warm - Warm tones
- 冷色/Cool - Cool tones
- 鲜艳/Vivid - Vivid colors
- 原图 - No style processing

### AI Output Format
The AI returns JSON with ratio coordinates (0.0-1.0):
```json
{
    "scene_analysis": "会场中有多个参会者坐在电脑前",
    "main_subject": "穿蓝色上衣的男性",
    "crop_center_ratio": {
        "x_ratio": 0.65,
        "y_ratio": 0.55
    },
    "suggested_size": {
        "width_ratio": 0.3,
        "height_ratio": 0.35
    },
    "style": "赛博朋克"
}
```

### Coordinate System
- x_ratio: 0.0 = left edge, 0.5 = center, 1.0 = right edge
- y_ratio: 0.0 = top edge, 0.5 = center, 1.0 = bottom edge
- width_ratio: crop width as percentage of image width
- height_ratio: crop height as percentage of image height

## Examples

User: "帮我拍一张人像，赛博朋克风格"

1. Take photo using camera
2. Send to Qwen3-VL with prompt
3. AI returns crop ratios for person + "赛博朋克" style
4. Convert ratios to pixel coordinates
5. Crop panorama to specified region
6. Apply cyberpunk style
7. Return: original.jpg + styled.jpg
