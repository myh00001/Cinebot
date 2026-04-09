---
name: photos_and_recording
description: Control OpenClaw camera for photo capture and video recording. Use when user needs to capture photos, record videos, or manage files on the OpenClaw camera. Supports auto-download to local directories.
---

# OpenClaw Camera Control

Control OpenClaw camera via TCP socket connection for remote photo capture and video recording.

## Commands

### Capture Photo
```bash
python photo_record_control.py <host> <port> capture [save_dir]
```
- Takes a photo and optionally downloads to `save_dir` (default: current directory)
- Returns saved file paths

### Start Recording
```bash
python photo_record_control.py <host> <port> record_start
```
- Starts 8K video recording
- Returns success/failure status

### Stop Recording
```bash
python photo_record_control.py <host> <port> record_stop [save_dir]
```
- Stops recording and optionally downloads to `save_dir`
- Returns saved file paths

### List Files
```bash
python photo_record_control.py <host> <port> list
```
- Lists all files stored on camera

## Common Usage

```bash
# Take photo and save to ./photos
python photo_record_control.py 192.168.88.189 8889 capture ./photos

# Start recording
python photo_record_control.py 192.168.88.189 8889 record_start

# Stop recording and save to ./videos
python photo_record_control.py 192.168.88.189 8889 record_stop ./videos
```

## Python API

Import and use directly in Python:

```python
from photo_record_control import capture, record_start, record_stop

# Capture photo
capture("192.168.88.189", 8889, auto_download=True, save_dir="./photos")

# Recording
record_start("192.168.88.189", 8889)
record_stop("192.168.88.189", 8889, auto_download=True, save_dir="./videos")
```
