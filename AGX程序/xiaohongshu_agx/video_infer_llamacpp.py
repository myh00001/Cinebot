#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import cv2
import time
import tempfile
import subprocess

VIDEO_PATH = "/home/hhws/data/test.mp4"  # 也可以改成 RTSP
LLAMA_BIN = "/home/hhws/llama.cpp/build/bin/llama-mtmd-cli"
MODEL = "/home/hhws/models/MiniCPM-V-4_5-Q4_K_M.gguf"
MMPROJ = "/home/hhws/models/mmproj-model-f16.gguf"

PROMPT = "请理解这一帧所属的视频内容，并简洁描述当前场景、主体和动作。"


def infer_image(image_path: str) -> str:
    cmd = [
        LLAMA_BIN,
        "-m",
        MODEL,
        "--mmproj",
        MMPROJ,
        "-c",
        "4096",
        "--image",
        image_path,
        "-p",
        PROMPT,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return f"[ERROR]\n{result.stdout}\n{result.stderr}"
    return result.stdout.strip()


def main():
    cap = cv2.VideoCapture(VIDEO_PATH)
    if not cap.isOpened():
        raise RuntimeError(f"无法打开视频: {VIDEO_PATH}")

    frame_id = 0
    sample_every = 24  # 例如 24fps 视频里每秒取 1 帧

    while True:
        ok, frame = cap.read()
        if not ok:
            break

        frame_id += 1
        if frame_id % sample_every != 0:
            continue

        fd, img_path = tempfile.mkstemp(suffix=".jpg")
        os.close(fd)

        try:
            cv2.imwrite(img_path, frame)
            answer = infer_image(img_path)
            print(f"\n===== frame {frame_id} =====")
            print(answer)
        finally:
            if os.path.exists(img_path):
                os.remove(img_path)

    cap.release()


if __name__ == "__main__":
    main()
