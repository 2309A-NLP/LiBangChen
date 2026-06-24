# LiveTalking System Architecture Mind Map

> Compatible with Markmap / MindMap Markdown renderers.  
> Open this file with [Markmap VS Code Extension](https://marketplace.visualstudio.com/items?itemName=gera2ld.markmap) or [markmap.js.org](https://markmap.js.org/).

---

## 1. Overview

- **LiveTalking** — Real-time Interactive Digital Human Engine
  - Author: lipku (lipku@foxmail.com)
  - License: Apache 2.0
  - Repository: github.com/lipku/LiveTalking
  - Use Cases
    - Virtual Streamer / Live Commerce
    - AI Customer Service
    - Online Education
    - Voice Assistant
    - Large-Screen Presenter
    - Batch Short-Video Generation

---

## 2. System Architecture (4 Layers)

### 2.1 API Layer
- Web Server: aiohttp + Flask (legacy)
- Port: 8010 (default, configurable)
- Core Endpoints
  - `POST /offer` — WebRTC SDP Exchange
  - `POST /human` — Text Input (echo / chat)
  - `POST /humanaudio` — Audio File Upload
  - `POST /interrupt_talk` — Interrupt Speaking
  - `POST /is_speaking` — Query Speaking State
  - `POST /record` — Recording Control
  - `GET /record/{sessionid}` — Download Recording
  - `POST /set_audiotype` — Action Choreography
  - `WS /api/asr` — Local ASR WebSocket
- Admin Endpoints
  - `GET /api/admin/config` — Server Configuration
  - `GET /api/admin/sessions` — Session Monitoring
  - `POST /api/avatar/task` — Avatar Generation

### 2.2 Logic Layer
- LLM Engine
  - Direct Mode: DashScope (Qwen-Plus)
  - RAG Mode: External Role-Playing Backend
    - REST API + SSE Streaming
    - Auto Login + Conversation Management
    - Fallback to Direct LLM
- TTS Engine (Plugin System)
  - Edge TTS (default, free)
  - GPT-SoVITS
  - CosyVoice
  - FishSpeech
  - Tencent Cloud TTS
  - Doubao (ByteDance)
  - IndexTTS2
  - Azure Cognitive Services
  - Qwen TTS
  - OmniTTS
  - XTTS
- ASR Engine
  - Local SenseVoice (FunASR + ModelScope)
  - VAD: fsmn-vad
  - WebSocket Protocol
- Feature Extraction
  - 16kHz / 20ms Audio Chunking
  - Mel-Spectrogram / HuBERT Features

### 2.3 Rendering Layer
- Avatar Models (Plugin System)
  - MuseTalk
    - Higher Quality
    - GPU: RTX 3080Ti+ → 42 FPS
    - GPU: RTX 4090 → 72 FPS
  - Wav2Lip
    - Lightweight
    - GPU: RTX 3060 → 60 FPS
    - GPU: RTX 3080Ti → 120 FPS
  - Ultralight Digital Human
    - Minimal Resource
  - BaseAvatar (Abstract Class)
    - Audio Frame Management
    - TTS Auto-Loading
    - Output Auto-Loading
    - Custom Action / Video Cycling
    - Recording (ffmpeg subprocess)
    - Past-Back (Lip Region Blending)

### 2.4 Streaming Layer
- Output Transports (Plugin System)
  - WebRTC (aiortc)
    - STUN: stun.freeswitch.org
    - ICE / DTLS / SRTP
  - RTMP Push
  - RTC Push (WHIP)
  - Virtual Camera

---

## 3. Plugin Registration System

- registry.py
  - Categories
    - `stt` — Speech-to-Text
    - `llm` — Language Models
    - `tts` — Text-to-Speech
    - `avatar` — Avatar Models
    - `output` — Streaming Output
  - Decorator: `@register(category, name)`
  - Factory: `registry.create(category, name, **kwargs)`

---

## 4. External RAG Backend (Role-Playing System)

### 4.1 Architecture
- FastAPI (uvicorn, port 8000)
- SQLite / MySQL Database
- Redis Short-Term Memory
- Milvus Vector Database (optional)
- Docker Compose: Milvus + etcd + MinIO + Attu

### 4.2 Core Components
- RAG Chain Orchestration (rag_chain.py)
- Hybrid Retrieval
  - Dense (BGE-M3 Embedding)
  - BM25 Sparse
  - RRF Fusion
  - BGE-Reranker Re-rank
- Security
  - JWT Authentication
  - Rate Limiting
- Knowledge Management
  - PDF / DOCX / Image / OCR
  - Web Crawler
  - Text Chunking
- Predefined Roles (7)
  - Lawyer
  - Stock Analyst
  - Teacher
  - Psychological Counselor
  - Doctor
  - Scientist
  - Custom Persona

### 4.3 LLM Configuration
- Provider: SiliconFlow (OpenAI-Compatible)
- Model: Qwen/Qwen3-VL-30B-A3B-Instruct
- Multimodal: Doubao (ByteDance Volcengine)
- Embedding: BGE-M3
- Reranker: BGE-Reranker-Base

---

## 5. Data Flow

- User Input
  - Text
    - echo mode → TTS → Avatar
    - chat mode → LLM → TTS → Avatar
  - Audio
    - ASR (SenseVoice) → LLM → TTS → Avatar
    - Direct Upload → Avatar
- Processing Pipeline
  - Input → LLM/RAG → TTS → Audio Chunking → Feature Extraction → Avatar Inference → Lip-Sync Pasting → Output Stream
- Streaming Flow
  - WebRTC
    - Browser → SDP Offer → ICE Negotiation → Video Track → Display
  - RTMP/RTC Push
    - Server → Push URL → Streaming Server → Client Player

---

## 6. Session Management

- SessionManager (Singleton)
  - Max Concurrent Sessions (default: 5)
  - Session Lifecycle
    - Create → Build Avatar → Active → Remove
  - MaxSessionError on Overflow
- RTCManager
  - WebRTC Peer Connection Pool
  - Offer Handling
  - ICE Candidate Management
  - Track Transceiver

---

## 7. Configuration System

- CLI Arguments (argparse)
  - `--model` / `--avatar_id` / `--tts` / `--transport`
  - `--listenport` / `--max_session` / `--batch_size`
- YAML Config File (`config.yaml`)
  - Overrides argparse defaults
  - Priority: CLI > YAML > code defaults
- Environment Variables (`.env`)
  - `DASHSCOPE_API_KEY` — Alibaba LLM
  - `TENCENT_APPID` / `TENCENT_SECRET_KEY` / `TENCENT_SECRET_ID` — Tencent TTS
  - `DOUBAO_APPID` / `DOUBAO_TOKEN` — ByteDance TTS
  - `RAG_API_URL` / `RAG_USERNAME` / `RAG_PASSWORD` / `RAG_ROLE_TYPE` — RAG Backend

---

## 8. Frontend (web/)

- Main Pages
  - index.html — WebRTC Client (CN)
  - index-en.html — WebRTC Client (EN)
  - dashboard.html — Advanced Dashboard
  - admin.html — Admin Console
  - avatar.html — Avatar Generation
- Test Pages
  - webrtcapi.html — API Test
  - webrtcapi-asr.html — ASR Test
  - rtmpapi.html / rtcpushapi.html — RTMP/RTC Push
- JavaScript Libraries
  - client.js — WebRTC Client Logic
  - srs.sdk.js — SRS Streaming SDK
  - mpegts-1.7.3.min.js — MPEG-TS Playback

---

## 9. Utility Modules

- utils/logger.py — Logging
- utils/audio.py — Audio Processing
- utils/async.py — Async Helpers
- utils/image.py — Image Processing
- utils/device.py — Device Detection

---

## 10. Performance Benchmarks

- FPS Requirements: ≥ 25 for real-time
- Infer FPS (GPU Inference)
  - Wav2Lip256 @ RTX 3060: 60 FPS
  - Wav2Lip256 @ RTX 3080Ti: 120 FPS
  - MuseTalk @ RTX 3080Ti: 42 FPS
  - MuseTalk @ RTX 4090: 72 FPS
- Final FPS (Streaming Output): depends on transport + encoding
- Batch Size: 16 (default)

---

## 11. External Service Dependencies

- Alibaba DashScope — Direct LLM (Qwen)
- SiliconFlow — RAG Backend LLM
- ByteDance Volcengine — Multimodal LLM
- Microsoft Edge TTS — Default Free TTS
- Tencent Cloud — Optional TTS
- Azure Cognitive Services — Optional TTS
- STUN Server — WebRTC NAT Traversal
- ModelScope — ASR Model Download

---

## 12. Directory Structure

```
LiveTalking/
├── app.py                  # Main entry point
├── config.py               # CLI + YAML config parser
├── registry.py             # Plugin registration system
├── llm.py                  # Direct LLM (Qwen via DashScope)
├── llm_rag.py              # RAG-bridged LLM
├── requirements.txt        # Python dependencies
├── Dockerfile              # Docker build
├── .env / .env.example     # Environment variables
├── config.yaml.example     # YAML config template
├── start_livetalking.bat   # Windows launcher
│
├── server/                 # Web server modules
│   ├── routes.py           # API route definitions
│   ├── rtc_manager.py      # WebRTC connection manager
│   ├── session_manager.py  # Session lifecycle
│   ├── webrtc.py           # WebRTC track handler
│   └── asr_server.py       # Local ASR WebSocket
│
├── tts/                    # TTS plugins (13 implementations)
├── avatars/                # Avatar models (3 implementations)
├── streamout/              # Output streaming plugins
├── utils/                  # Utility modules
├── web/                    # Frontend HTML/JS
├── data/                   # Runtime data
├── models/                 # Model weights
├── docs/                   # API documentation
├── assets/                 # Images / screenshots
│
└── Role_playing system/    # External RAG backend
    └── data-main/
        ├── run.py          # RAG entry point
        ├── app.py          # FastAPI app
        ├── rag_chain.py    # RAG engine
        ├── vector_store.py # Hybrid retrieval
        ├── models.py       # ORM models
        └── ...
```
