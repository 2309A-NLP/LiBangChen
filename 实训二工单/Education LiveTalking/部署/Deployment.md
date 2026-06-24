# LiveTalking Deployment Guide

> Complete deployment guide for the LiveTalking real-time digital human engine.  
> Covers local, Docker, and cloud deployment on Windows and Linux.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Quick Start (Local)](#2-quick-start-local)
3. [Detailed Installation](#3-detailed-installation)
4. [Configuration](#4-configuration)
5. [RAG Backend Deployment](#5-rag-backend-deployment)
6. [Docker Deployment](#6-docker-deployment)
7. [Cloud Deployment](#7-cloud-deployment)
8. [Production Checklist](#8-production-checklist)
9. [Troubleshooting](#9-troubleshooting)

---

## 1. Prerequisites

### 1.1 Hardware Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| **GPU** | NVIDIA RTX 3060 (12GB VRAM) | NVIDIA RTX 4090 (24GB VRAM) |
| **CPU** | 8 Cores | 16+ Cores |
| **RAM** | 16 GB | 32+ GB |
| **Disk** | 50 GB SSD | 100+ GB NVMe SSD |
| **Network** | 10 Mbps Upload | 50+ Mbps Upload |

### 1.2 GPU Performance Reference

| Model | GPU | Inference FPS |
|-------|-----|---------------|
| Wav2Lip (256) | RTX 3060 | 60 FPS |
| Wav2Lip (256) | RTX 3080Ti | 120 FPS |
| MuseTalk | RTX 3080Ti | 42 FPS |
| MuseTalk | RTX 4090 | 72 FPS |

> ⚠️ **Real-time requirement**: Both `inferfps` (GPU) and `finalfps` (streaming) must be ≥ 25 FPS.

### 1.3 Software Requirements

| Software | Version | Notes |
|----------|---------|-------|
| **OS** | Windows 10+ / Ubuntu 20.04+ | |
| **Python** | 3.10 | Use Conda for environment management |
| **CUDA** | 11.6+ | Match with PyTorch CUDA version |
| **cuDNN** | 8.x | Required for GPU inference |
| **FFmpeg** | 4.x+ | Required for recording feature |
| **Git** | 2.x+ | For cloning the repository |

---

## 2. Quick Start (Local)

### 2.1 Windows

```powershell
# 1. Clone repository
git clone https://github.com/lipku/LiveTalking.git
cd LiveTalking

# 2. Create Conda environment
conda create -n livetalking python=3.10 -y
conda activate livetalking

# 3. Install PyTorch (CUDA 11.8)
pip install torch==2.0.1 torchvision==0.15.2 --index-url https://download.pytorch.org/whl/cu118

# 4. Install dependencies
pip install -r requirements.txt

# 5. Configure environment
cp .env.example .env
# Edit .env → set DASHSCOPE_API_KEY=sk-your-key

# 6. (Optional) Configure YAML
cp config.yaml.example config.yaml
# Edit config.yaml if needed

# 7. Start the server
python app.py --transport webrtc --model wav2lip --avatar_id wav2lip256_avatar1 --listenport 8010
```

Or use the batch script:

```bat
start_livetalking.bat
```

> Edit `start_livetalking.bat` to match your local paths and parameters.

### 2.2 Linux (Ubuntu 20.04/22.04)

```bash
# 1. Install system dependencies
sudo apt update
sudo apt install -y ffmpeg libsndfile1 git wget curl

# 2. Clone repository
git clone https://github.com/lipku/LiveTalking.git
cd LiveTalking

# 3. Install Miniconda (if not installed)
wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh
bash Miniconda3-latest-Linux-x86_64.sh -b -u -p ~/miniconda3
~/miniconda3/bin/conda init

# 4. Create environment
conda create -n livetalking python=3.10 -y
conda activate livetalking

# 5. Install PyTorch (CUDA 11.8)
pip install torch==2.0.1 torchvision==0.15.2 --index-url https://download.pytorch.org/whl/cu118

# 6. Install dependencies
pip install -r requirements.txt

# 7. Configure and start
cp .env.example .env
# Edit .env with your API keys
python app.py --transport webrtc --model wav2lip --avatar_id wav2lip256_avatar1
```

---

## 3. Detailed Installation

### 3.1 Step-by-Step Environment Setup

#### Create Isolated Conda Environment

```bash
conda create -n livetalking python=3.10 -y
conda activate livetalking
```

#### Install PyTorch with CUDA

Choose the version matching your CUDA driver:

| CUDA Version | Install Command |
|-------------|----------------|
| CUDA 11.8 | `pip install torch==2.0.1 torchvision==0.15.2 --index-url https://download.pytorch.org/whl/cu118` |
| CUDA 12.1 | `pip install torch==2.1.0 torchvision==0.16.0 --index-url https://download.pytorch.org/whl/cu121` |

> Verify: `python -c "import torch; print(torch.cuda.is_available())"` → should print `True`

#### Install Python Dependencies

```bash
pip install -r requirements.txt
```

> 💡 Use Aliyun mirror in China: `pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/`

#### Verify Installation

```bash
python -c "
import torch
import cv2
import numpy
import aiohttp
import aiortc
import transformers
import edge_tts
print('All dependencies OK')
print(f'CUDA Available: {torch.cuda.is_available()}')
if torch.cuda.is_available():
    print(f'GPU: {torch.cuda.get_device_name(0)}')
    print(f'VRAM: {torch.cuda.get_device_properties(0).total_mem / 1024**3:.1f} GB')
"
```

### 3.2 Model Weights

| Model | Path | Download |
|-------|------|----------|
| Wav2Lip | `models/wav2lip.pth` | [Google Drive](https://drive.google.com/) / [Baidu Pan](https://pan.baidu.com/) |
| MuseTalk | `models/musetalk/` | See [MuseTalk repo](https://github.com/TMElyralab/MuseTalk) |
| Ultralight | Auto-download | Handled by code |

> Check the project README for the latest model download links.

### 3.3 Avatar Data

Avatar videos are stored in `data/avatars/`. Each avatar needs:
- `avatar.mp4` — Source video (25 FPS, face visible, no occlusion)
- `avatar.json` — Metadata (bbox coordinates, etc.)

---

## 4. Configuration

### 4.1 Configuration Methods (Priority Order)

```
CLI Arguments > YAML Config File > Code Defaults
```

### 4.2 CLI Arguments

```bash
python app.py \
  --transport webrtc \           # Output: rtcpush / webrtc / rtmp / virtualcam
  --model wav2lip \              # Avatar model: musetalk / wav2lip / ultralight
  --avatar_id wav2lip256_avatar1 \  # Avatar ID in data/avatars/
  --tts edgetts \                # TTS engine: edgetts / gpt-sovits / cosyvoice / ...
  --listenport 8010 \            # HTTP server port
  --max_session 5 \              # Max concurrent sessions
  --batch_size 16 \              # Inference batch size
  --REF_FILE "zh-CN-YunxiaNeural" \  # TTS voice name or reference audio path
  --TTS_SERVER "http://127.0.0.1:9880" \  # Remote TTS server URL
  --push_url "rtmp://your-server/live/stream"  # Push URL for RTMP/RTC
```

### 4.3 YAML Configuration (`config.yaml`)

```yaml
# Audio
l: 10
m: 8
r: 10

# Avatar Model
model: wav2lip
avatar_id: wav2lip256_avatar1
batch_size: 16

# Custom Actions
customvideo_config: ''

# TTS
tts: edgetts
REF_FILE: 'zh-CN-YunxiaNeural'
REF_TEXT: ''
TTS_SERVER: 'http://127.0.0.1:9880'

# Transport
transport: webrtc
push_url: ''
max_session: 5
listenport: 8010
```

> Use with: `python app.py --config config.yaml`

### 4.4 Environment Variables (`.env`)

```ini
# ─── LLM API Keys ───────────────────────────
DASHSCOPE_API_KEY=sk-your-dashscope-key      # Alibaba DashScope (Qwen)

# ─── Tencent Cloud TTS ──────────────────────
TENCENT_APPID=your-app-id
TENCENT_SECRET_KEY=your-secret-key
TENCENT_SECRET_ID=your-secret-id

# ─── ByteDance TTS ──────────────────────────
DOUBAO_APPID=your-app-id
DOUBAO_TOKEN=your-token

# ─── RAG Backend Connection ─────────────────
RAG_API_URL=http://127.0.0.1:8000
RAG_USERNAME=123456
RAG_PASSWORD=123456
RAG_ROLE_TYPE=teacher
RAG_TIMEOUT=30
```

### 4.5 Transport Mode Details

#### WebRTC (Default — Browser Access)

```bash
python app.py --transport webrtc --listenport 8010
# Access: http://<server-ip>:8010/
# Recommended: http://<server-ip>:8010/dashboard.html
```

**Network Requirements:**
- TCP Port 8010 (HTTP/WebSocket signaling)
- UDP Ports 1-65535 (WebRTC media — STUN/TURN assisted)
- STUN Server: `stun:stun.freeswitch.org:3478`
- For production: deploy your own TURN server (coturn)

#### RTMP Push

```bash
python app.py --transport rtmp --push_url rtmp://your-rtmp-server/live/stream
# Access: http://<server-ip>:8010/rtmpapi.html
```

#### RTC Push (WHIP Protocol)

```bash
python app.py --transport rtcpush --push_url http://srs-server:1985/rtc/v1/whip/?app=live&stream=livestream
# Access: http://<server-ip>:8010/rtcpushapi.html
```

#### Virtual Camera

```bash
python app.py --transport virtualcam
# Outputs to system virtual camera device (OBS Virtual Camera required)
```

---

## 5. RAG Backend Deployment

The RAG (Retrieval-Augmented Generation) backend is an optional component that provides knowledge-enhanced conversations for education/role-playing scenarios.

### 5.1 Architecture

```
LiveTalking (port 8010)
    │
    └── HTTP/SSE ──► RAG Backend (port 8000)
                        │
                        ├── SQLite / MySQL (conversation storage)
                        ├── Redis (short-term memory)
                        ├── Milvus (vector database, optional)
                        └── SiliconFlow API (LLM inference)
```

### 5.2 Deploy RAG Backend

```bash
# 1. Navigate to RAG backend
cd "Role_playing system/data-main"

# 2. Create Conda environment
conda env create -f environment.yml
conda activate roleplay

# 3. Configure environment variables
cp .env.example .env
# Edit .env:
#   OPENAI_API_KEY=sk-your-siliconflow-key
#   OPENAI_BASE_URL=https://api.siliconflow.cn/v1
#   MULTIMODAL_API_KEY=your-doubao-key
#   DATABASE_URL=sqlite:///roleplay_system.db

# 4. (Optional) Start Milvus vector database
docker compose -f docker-compose.milvus.yml up -d

# 5. Start RAG server
python run.py serve
# Server starts at http://0.0.0.0:8000
# API docs at http://localhost:8000/docs
```

### 5.3 Connect LiveTalking to RAG

In LiveTalking's `.env`:

```ini
RAG_API_URL=http://127.0.0.1:8000
RAG_USERNAME=123456
RAG_PASSWORD=123456
RAG_ROLE_TYPE=teacher
RAG_TIMEOUT=30
```

LiveTalking will auto-detect RAG availability and fall back to direct DashScope LLM if the RAG backend is unreachable.

### 5.4 Milvus Vector Database (Optional)

```bash
cd "Role_playing system/data-main"
docker compose -f docker-compose.milvus.yml up -d
```

Services started:
- Milvus Standalone (port 19530)
- etcd (port 2379)
- MinIO (ports 9000, 9001)
- Attu GUI (port 3000) — Milvus admin dashboard

---

## 6. Docker Deployment

### 6.1 Build Image

```bash
# From the LiveTalking root directory
docker build -t livetalking:latest .
```

### 6.2 Run Container

```bash
docker run -d \
  --name livetalking \
  --gpus all \
  -p 8010:8010 \
  -p 8000:8000 \
  -v $(pwd)/data:/nerfstream/data \
  -v $(pwd)/models:/nerfstream/models \
  -v $(pwd)/.env:/nerfstream/.env \
  -v $(pwd)/config.yaml:/nerfstream/config.yaml \
  livetalking:latest
```

### 6.3 Docker Compose (Full Stack)

Create `docker-compose.yml`:

```yaml
version: '3.8'

services:
  # ─── LiveTalking Core ─────────────────────
  livetalking:
    build: .
    container_name: livetalking
    runtime: nvidia
    environment:
      - NVIDIA_VISIBLE_DEVICES=all
      - NVIDIA_DRIVER_CAPABILITIES=compute,utility,graphics
    ports:
      - "8010:8010"
      - "8000:8000"
    volumes:
      - ./data:/nerfstream/data
      - ./models:/nerfstream/models
      - ./.env:/nerfstream/.env
      - ./config.yaml:/nerfstream/config.yaml
    command: python app.py --transport webrtc --model wav2lip --listenport 8010
    restart: unless-stopped
    networks:
      - livetalking-net

  # ─── RAG Backend ──────────────────────────
  rag-backend:
    build: ./Role_playing system/data-main
    container_name: rag-backend
    ports:
      - "8001:8000"
    volumes:
      - ./Role_playing system/data-main:/app
      - ./Role_playing system/data-main/.env:/app/.env
    command: python run.py serve
    restart: unless-stopped
    networks:
      - livetalking-net
    depends_on:
      - redis

  # ─── Redis (RAG Memory) ───────────────────
  redis:
    image: redis:7-alpine
    container_name: rag-redis
    ports:
      - "6379:6379"
    restart: unless-stopped
    networks:
      - livetalking-net

  # ─── Milvus Vector Database (Optional) ─────
  # etcd:
  #   image: quay.io/coreos/etcd:v3.5.5
  #   ...
  # milvus:
  #   image: milvusdb/milvus:v2.3.0
  #   ...

networks:
  livetalking-net:
    driver: bridge
```

```bash
# Start full stack
docker compose up -d

# View logs
docker compose logs -f livetalking
docker compose logs -f rag-backend

# Stop
docker compose down
```

---

## 7. Cloud Deployment

### 7.1 AutoDL (codewithgpu.com)

1. Select GPU instance: RTX 3090 / 4090
2. Choose community image: `LiveTalking`
3. Start instance
4. SSH in or use JupyterLab terminal
5. Configure `.env` with your API keys
6. Start: `python app.py --transport webrtc --model wav2lip`

### 7.2 UCloud (compshare)

1. Select GPU instance
2. Choose community image
3. Start and configure as above

### 7.3 Self-Hosted Linux Server

```bash
# 1. Install NVIDIA drivers
sudo apt install nvidia-driver-535

# 2. Install CUDA toolkit
wget https://developer.download.nvidia.com/compute/cuda/11.8.0/local_installers/cuda_11.8.0_520.61.05_linux.run
sudo sh cuda_11.8.0_520.61.05_linux.run

# 3. Verify GPU
nvidia-smi

# 4. Follow Quick Start (Section 2.2)
```

### 7.4 Reverse Proxy (Nginx)

For production deployments, put Nginx in front:

```nginx
server {
    listen 443 ssl http2;
    server_name your-domain.com;

    ssl_certificate     /etc/ssl/certs/your-cert.pem;
    ssl_certificate_key /etc/ssl/private/your-key.pem;

    # LiveTalking main server
    location / {
        proxy_pass http://127.0.0.1:8010;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 86400;
    }

    # RAG backend API
    location /api/rag/ {
        rewrite ^/api/rag/(.*) /$1 break;
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_buffering off;  # Required for SSE streaming
        proxy_read_timeout 300s;
    }

    # Static assets (cache)
    location /static/ {
        alias /path/to/LiveTalking/web/;
        expires 7d;
        add_header Cache-Control "public, immutable";
    }
}
```

---

## 8. Production Checklist

### Before Going Live

- [ ] **GPU**: Verify FPS ≥ 25 under load with `max_session` concurrent users
- [ ] **Network**: Configure TURN server for WebRTC (NAT traversal)
- [ ] **Firewall**: Open TCP 8010 + UDP 1-65535 (or restrict to WebRTC range)
- [ ] **SSL**: Deploy HTTPS via Nginx + Let's Encrypt
- [ ] **Auth**: Enable API key authentication on `/offer` endpoint
- [ ] **CORS**: Restrict to your frontend domain
- [ ] **Rate Limiting**: Configure per-IP rate limiting
- [ ] **Monitoring**: Set up Prometheus + Grafana or at minimum health check alerts
- [ ] **Logging**: Configure log rotation (logrotate or Python RotatingFileHandler)
- [ ] **Backup**: Backup `data/` directory and `.env` configuration
- [ ] **ASR Model**: Pre-download SenseVoice model to avoid startup delay

### Startup Script (systemd)

Create `/etc/systemd/system/livetalking.service`:

```ini
[Unit]
Description=LiveTalking Digital Human Service
After=network.target

[Service]
Type=simple
User=livetalking
WorkingDirectory=/opt/LiveTalking
Environment="PATH=/home/livetalking/miniconda3/envs/livetalking/bin:/usr/local/bin:/usr/bin:/bin"
ExecStart=/home/livetalking/miniconda3/envs/livetalking/bin/python app.py --config /opt/LiveTalking/config.yaml
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable livetalking
sudo systemctl start livetalking
sudo systemctl status livetalking
```

### Startup Script (Windows Service)

Use `nssm` (Non-Sucking Service Manager):

```powershell
nssm install LiveTalking "D:\Anaconda\envs\livetalking\python.exe" "D:\LiveTalking\app.py --config config.yaml"
nssm set LiveTalking AppDirectory "D:\LiveTalking"
nssm set LiveTalking DisplayName "LiveTalking Digital Human Service"
nssm start LiveTalking
```

---

## 9. Troubleshooting

### Common Issues

#### 9.1 CUDA / GPU Issues

| Symptom | Solution |
|---------|----------|
| `CUDA out of memory` | Reduce `--batch_size` to 8 or 4; reduce `--max_session` |
| `torch.cuda.is_available() = False` | Check CUDA toolkit matches PyTorch CUDA version; reinstall PyTorch |
| `No GPU detected` | Run `nvidia-smi`; check NVIDIA driver installation |
| Slow inference FPS | Close other GPU processes; check GPU power limit with `nvidia-smi` |

#### 9.2 WebRTC Issues

| Symptom | Solution |
|---------|----------|
| ICE connection failed | Deploy TURN server; check firewall UDP ports |
| No video in browser | Check browser console for WebRTC errors; verify STUN server reachable |
| Connection timeout | Check server firewall; verify `listenport` is accessible from client |
| One-way audio | Symmetric NAT issue — deploy TURN relay server |

#### 9.3 TTS Issues

| Symptom | Solution |
|---------|----------|
| Edge TTS network error | Check internet connection; Edge TTS requires Microsoft service access |
| Remote TTS timeout | Verify `TTS_SERVER` URL; check TTS server is running |
| No sound output | Check `REF_FILE` is valid; verify audio format is 16kHz WAV mono |

#### 9.4 LLM / RAG Issues

| Symptom | Solution |
|---------|----------|
| `DASHSCOPE_API_KEY` not found | Create `.env` file with valid API key; run `load_dotenv()` |
| RAG connection refused | Start RAG backend: `cd Role_playing system/data-main && python run.py serve` |
| RAG login failed | Check `RAG_USERNAME` / `RAG_PASSWORD` in `.env` |
| RAG SSE timeout | Increase `RAG_TIMEOUT` in `.env`; check RAG backend logs |
| Fallback to direct LLM | This is expected when RAG is unavailable — no action needed |

#### 9.5 ASR Issues

| Symptom | Solution |
|---------|----------|
| ASR model download stuck | First run downloads SenseVoice from ModelScope (~200MB); ensure network access |
| ASR WebSocket connection failed | Verify ASR server started (check logs for "ASR server started") |
| ASR accuracy low | Ensure input audio is 16kHz mono; reduce background noise |

#### 9.6 General Issues

| Symptom | Solution |
|---------|----------|
| Port 8010 already in use | Change `--listenport` or kill existing process |
| `ModuleNotFoundError` | Run `pip install -r requirements.txt`; check Conda environment is active |
| Avatar loading fails | Check `data/avatars/<avatar_id>/` exists with `avatar.mp4` and `avatar.json` |
| Recording has no audio | Ensure FFmpeg is installed and in PATH |

### Diagnostic Scripts

The project includes diagnostic tools:

```bash
# Test RAG backend connectivity
python diag_rag.py

# Quick health check of both services
python quick_test.py

# Analyze RAG timing from logs
python check_log.py

# Check RAG log entries
python check_log2.py

# Extract timing statistics
python check_timing.py
```

### Logs

- LiveTalking logs: Console output (stdout)
- RAG backend logs: Console output (stdout)
- To enable file logging, set environment variable in `.env` or modify `utils/logger.py`

---

## Reference

- **Repository**: [github.com/lipku/LiveTalking](https://github.com/lipku/LiveTalking)
- **Mirror (CN)**: [gitee.com/lipku/LiveTalking](https://gitee.com/lipku/LiveTalking)
- **API Documentation**: See `docs/api.md`, `docs/admin_api.md`, `docs/avatar_api.md`
- **Contact**: lipku@foxmail.com
