# LiveTalking 实时交互数字人引擎 — 系统架构思维导图

> 兼容 Markmap / MindMap Markdown 渲染器  
> 用 [Markmap VS Code 扩展](https://marketplace.visualstudio.com/items?itemName=gera2ld.markmap) 或 [markmap.js.org](https://markmap.js.org/) 打开

---

## 1. 项目概览

- **LiveTalking** — 实时交互数字人引擎
  - 作者: lipku (lipku@foxmail.com)
  - 协议: Apache 2.0
  - 仓库: github.com/lipku/LiveTalking
  - 应用场景
    - 虚拟主播 / 直播带货
    - AI 智能客服
    - 在线教育
    - 语音助手
    - 大屏演讲人
    - 批量短视频生成

---

## 2. 四层系统架构

### 2.1 API 层
- Web 框架: aiohttp + Flask (遗留)
- 默认端口: 8010 (可配置)
- 核心接口
  - `POST /offer` — WebRTC SDP 协商
  - `POST /human` — 文本输入 (echo / 对话)
  - `POST /humanaudio` — 音频文件上传
  - `POST /interrupt_talk` — 打断当前说话
  - `POST /is_speaking` — 查询说话状态
  - `POST /record` — 录制控制
  - `GET /record/{sessionid}` — 下载录制文件
  - `POST /set_audiotype` — 动作编排
  - `WS /api/asr` — 本地 ASR WebSocket
- 管理接口
  - `GET /api/admin/config` — 服务器配置
  - `GET /api/admin/sessions` — 会话监控
  - `POST /api/avatar/task` — 数字人生成

### 2.2 逻辑层
- LLM 引擎
  - Direct 模式: DashScope (Qwen-Plus)
  - RAG 模式: 外部角色扮演后端
    - REST API + SSE 流式传输
    - 自动登录 + 会话管理
    - LLM 回退机制
- TTS 引擎 (插件体系, 共12种)
  - Edge TTS (默认, 免费)
  - GPT-SoVITS
  - CosyVoice
  - FishSpeech
  - 腾讯云 TTS
  - 豆包 (字节跳动)
  - IndexTTS2
  - Azure 认知服务
  - Qwen TTS
  - OmniTTS
  - XTTS
- ASR 引擎
  - 本地 SenseVoice (FunASR + ModelScope)
  - VAD: fsmn-vad
  - WebSocket 协议
- 特征提取
  - 16kHz / 20ms 音频分块
  - Mel-Spectrogram / HuBERT 特征

### 2.3 渲染层
- 数字人模型 (插件体系)
  - **MuseTalk**
    - 高质量, 效果最佳
    - RTX 3080Ti → 42 FPS
    - RTX 4090 → 72 FPS
  - **Wav2Lip**
    - 轻量级, 速度快
    - RTX 3060 → 60 FPS
    - RTX 3080Ti → 120 FPS
  - **Ultralight 数字人**
    - 资源占用最小
  - **BaseAvatar (抽象基类)**
    - 音频帧管理
    - TTS 自动加载
    - 输出自动加载
    - 自定义动作 / 视频循环
    - 录制 (ffmpeg 子进程)
    - Past-Back (唇部区域融合)

### 2.4 推流层
- 输出传输 (插件体系)
  - **WebRTC** (aiortc)
    - STUN: stun.freeswitch.org
    - ICE / DTLS / SRTP
  - **RTMP 推流**
  - **RTC 推流** (WHIP)
  - **虚拟摄像头**

---

## 3. 插件注册系统

- `registry.py` — 统一插件注册中心
  - 五大类别
    - `stt` — 语音识别
    - `llm` — 大语言模型
    - `tts` — 语音合成
    - `avatar` — 数字人模型
    - `output` — 流式输出
  - 装饰器注册: `@register(category, name)`
  - 工厂创建: `registry.create(category, name, **kwargs)`

---

## 4. 外部 RAG 后端 (角色扮演系统)

### 4.1 基础架构
- FastAPI (uvicorn, 端口 8000)
- SQLite / MySQL 数据库
- Redis 短期记忆
- Milvus 向量数据库 (可选)
- Docker Compose: Milvus + etcd + MinIO + Attu

### 4.2 核心组件
- RAG 链编排 (`rag_chain.py`)
- 混合检索
  - 稠密检索 (BGE-M3 Embedding)
  - BM25 稀疏检索
  - RRF 融合
  - BGE-Reranker 重排序
- 安全机制
  - JWT 认证
  - 速率限制
- 知识管理
  - PDF / DOCX / 图片 / OCR
  - 网页爬虫
  - 文本分块
- 7 种预定义角色
  - 律师
  - 股票分析师
  - 教师
  - 心理咨询师
  - 医生
  - 科学家
  - 自定义角色

### 4.3 LLM 配置
- 模型供应商: SiliconFlow (兼容 OpenAI)
- 对话模型: Qwen/Qwen3-VL-30B-A3B-Instruct
- 多模态: 豆包 (字节火山引擎)
- Embedding: BGE-M3
- Reranker: BGE-Reranker-Base

---

## 5. 数据流

### 5.1 输入路径
- **文本输入**
  - echo 模式 → TTS → 数字人
  - chat 模式 → LLM → TTS → 数字人
- **语音输入**
  - ASR (SenseVoice) → LLM → TTS → 数字人
  - 音频文件直接上传 → 数字人

### 5.2 处理管线
- 输入 → LLM/RAG → TTS → 音频分块 → 特征提取 → 数字人推理 → 唇形融合 → 输出推流

### 5.3 推流流程
- **WebRTC**: 浏览器 → SDP Offer → ICE 协商 → Video Track → 显示
- **RTMP/RTC 推流**: 服务器 → 推流地址 → 流媒体服务器 → 客户端播放

---

## 6. 会话管理

- SessionManager (单例)
  - 最大并发会话 (默认: 5)
  - 会话生命周期
    - 创建 → 构建数字人 → 活跃 → 销毁
  - 超限抛出 MaxSessionError
- RTCManager
  - WebRTC 对等连接池
  - Offer 处理
  - ICE 候选管理
  - Track 收发器

---

## 7. 配置系统

- **CLI 参数** (argparse)
  - `--model` / `--avatar_id` / `--tts` / `--transport`
  - `--listenport` / `--max_session` / `--batch_size`
- **YAML 配置** (`config.yaml`)
  - 覆盖 argparse 默认值
  - 优先级: CLI > YAML > 代码默认值
- **环境变量** (`.env`)
  - `DASHSCOPE_API_KEY` — 阿里 LLM
  - `TENCENT_APPID` / `TENCENT_SECRET_KEY` / `TENCENT_SECRET_ID` — 腾讯 TTS
  - `DOUBAO_APPID` / `DOUBAO_TOKEN` — 字节 TTS
  - `RAG_API_URL` / `RAG_USERNAME` / `RAG_PASSWORD` / `RAG_ROLE_TYPE` — RAG 后端

---

## 8. 前端 (`web/`)

- 主要页面
  - `index.html` — WebRTC 客户端 (中文)
  - `index-en.html` — WebRTC 客户端 (英文)
  - `dashboard.html` — 高级仪表盘
  - `admin.html` — 管理控制台
  - `avatar.html` — 数字人生成
- 测试页面
  - `webrtcapi.html` — API 测试
  - `webrtcapi-asr.html` — ASR 测试
  - `rtmpapi.html` / `rtcpushapi.html` — RTMP/RTC 推流测试
- JS 库
  - `client.js` — WebRTC 客户端逻辑
  - `srs.sdk.js` — SRS 流媒体 SDK
  - `mpegts-1.7.3.min.js` — MPEG-TS 播放

---

## 9. 工具模块 (`utils/`)

- `logger.py` — 日志系统
- `audio.py` — 音频处理
- `async.py` — 异步辅助
- `image.py` — 图像处理
- `device.py` — 设备检测

---

## 10. 性能基准

- 实时要求: ≥ 25 FPS
- GPU 推理性能
  - Wav2Lip256 @ RTX 3060: 60 FPS
  - Wav2Lip256 @ RTX 3080Ti: 120 FPS
  - MuseTalk @ RTX 3080Ti: 42 FPS
  - MuseTalk @ RTX 4090: 72 FPS
- 最终推流 FPS: 取决于传输协议 + 编码
- 批处理大小: 默认 16

---

## 11. 外部服务依赖

- 阿里 DashScope — Direct LLM (Qwen)
- SiliconFlow — RAG 后端 LLM
- 字节火山引擎 — 多模态 LLM
- 微软 Edge TTS — 默认免费 TTS
- 腾讯云 — 可选 TTS
- Azure 认知服务 — 可选 TTS
- STUN Server — WebRTC NAT 穿透
- ModelScope — ASR 模型下载

---

## 12. 目录结构

```
LiveTalking/
├── app.py                    # 主入口
├── config.py                 # CLI + YAML 配置解析
├── registry.py               # 插件注册系统
├── llm.py                    # Direct LLM (Qwen via DashScope)
├── llm_rag.py                # RAG 桥接 LLM
├── requirements.txt          # Python 依赖
├── Dockerfile                # Docker 构建
├── .env / .env.example       # 环境变量
├── config.yaml.example       # YAML 配置模板
├── start_livetalking.bat     # Windows 启动脚本
│
├── server/                   # Web 服务模块
│   ├── routes.py             # API 路由
│   ├── rtc_manager.py        # WebRTC 连接管理
│   ├── session_manager.py    # 会话生命周期
│   ├── webrtc.py             # WebRTC Track 处理
│   └── asr_server.py         # 本地 ASR WebSocket
│
├── tts/                      # TTS 插件 (12 种实现)
├── avatars/                  # 数字人模型 (3 种实现)
├── streamout/                # 输出推流插件
├── utils/                    # 工具模块
├── web/                      # 前端 HTML/JS
├── data/                     # 运行时数据
├── models/                   # 模型权重
├── docs/                     # API 文档
├── assets/                   # 图片 / 截图
│
└── Role_playing system/      # 外部 RAG 后端
    └── data-main/
        ├── run.py            # RAG 入口
        ├── app.py            # FastAPI 应用
        ├── rag_chain.py      # RAG 引擎
        ├── vector_store.py   # 混合检索
        ├── models.py         # ORM 模型
        └── ...
```
