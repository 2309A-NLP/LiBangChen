# RAG Q&A SYSTEM4 部署文档

## 1. 文档目的

本文档用于指导 `RAG-Q&A system4` 在新环境中的部署、启动和验收，覆盖两种部署模式：

- 轻量模式：`keyword` 检索，不依赖 Milvus，适合本地验证和单机演示
- 完整模式：`hybrid_rrf` / `milvus` 检索，依赖 Milvus 和本地向量模型，适合正式环境

## 2. 部署前说明

当前项目是一个基于 FastAPI 的 RAG 问答系统，包含以下运行组件：

- Web 服务：FastAPI + Uvicorn
- 文档解析：`pypdf`
- 检索方式：`keyword`、`milvus`、`hybrid_rrf`
- 向量模型：`sentence-transformers`
- 可选重排：`bge-reranker-base`
- 可选会话存储：内存 / Redis
- 可选向量库：Milvus

项目启动入口有两个：

- 开发入口：`python run.py`
- 推荐部署入口：`uvicorn app.main:app --host 0.0.0.0 --port 8000`

说明：

- `run.py` 中固定使用 `127.0.0.1:8000` 且开启 `reload=True`，适合开发，不适合生产部署
- 生产环境建议直接使用 `uvicorn app.main:app`

## 3. 环境要求

建议环境：

- Windows 10/11 或 Linux
- Python 3.10 或 3.11
- `pip`
- Docker Desktop 或 Docker Engine

可选依赖：

- Redis：多实例部署或需要持久会话时启用
- Milvus：使用向量检索或混合检索时必须启用

硬件建议：

- 轻量模式：8GB 内存起
- 完整模式：16GB 内存起
- 如需更快推理，可将 embedding / reranker 部署到 GPU 环境

## 4. 运行目录说明

运行时重点目录如下：

- `data/source/`：上传或预置的 PDF 文件
- `data/processed/feedback.jsonl`：用户反馈
- `data/processed/milvus_state.json`：Milvus 索引签名缓存
- `milvus/volumes/`：Milvus、etcd、MinIO 数据卷

部署时建议将以下目录做持久化备份：

- `data/source`
- `data/processed`
- `milvus/volumes`

## 5. 必须关注的配置项

项目配置来自 `.env`，配置定义在 [app/core/config.py](C:/Users/26332/Desktop/工单/RAG工单/RAG-Q&A system4/app/core/config.py:1)。

需要特别注意：

- 当前代码中的 `EMBEDDING_MODEL_NAME` 默认值指向开发者本机绝对路径
- 当前代码中的 `RERANKER_MODEL_PATH` 默认值指向开发者本机绝对路径
- 当前默认 `RETRIEVER_TYPE=hybrid_rrf`

因此，新机器部署时必须显式配置以下字段，否则完整模式大概率无法启动：

- `RETRIEVER_TYPE`
- `EMBEDDING_MODEL_NAME`
- `RERANKER_ENABLED`
- `RERANKER_MODEL_PATH`
- `MILVUS_HOST`
- `MILVUS_PORT`

## 6. 轻量模式部署

### 6.1 适用场景

适合以下情况：

- 先把系统跑起来
- 不准备部署 Milvus
- 仅做功能验证、接口联调、演示环境

### 6.2 安装依赖

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Linux/macOS:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 6.3 准备 `.env`

在项目根目录创建 `.env`，可使用以下最小配置：

```env
APP_NAME=RAG Q&A SYSTEM4
APP_ENV=production
API_PREFIX=/api

SOURCE_PDF_DIR=data/source
FEEDBACK_STORE_PATH=data/processed/feedback.jsonl
MILVUS_STATE_PATH=data/processed/milvus_state.json

LLM_PROVIDER=openai_compatible
LLM_API_KEY=your_api_key
LLM_BASE_URL=https://your-openai-compatible-endpoint
LLM_MODEL=your-model-name
LLM_TIMEOUT_SECONDS=30
LLM_TEMPERATURE=0.2

QUERY_UNDERSTANDING_MODE=rules
QUERY_UNDERSTANDING_LOCAL_FIRST_ENABLED=true
QUERY_UNDERSTANDING_FALLBACK_ENABLED=true

RETRIEVER_TYPE=keyword
DEFAULT_TOP_K=8
MAX_CHUNK_LENGTH=4000
TABLE_CHUNK_LENGTH=1800

RERANKER_ENABLED=false

SESSION_STORE_BACKEND=memory
SESSION_STORE_TTL_SECONDS=86400
```

如果暂时不接入真实大模型，可改为：

```env
LLM_PROVIDER=mock
```

### 6.4 启动服务

```powershell
.venv\Scripts\activate
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### 6.5 验证部署

启动后访问：

- 首页：`http://127.0.0.1:8000/`
- 知识库页面：`http://127.0.0.1:8000/kb`
- OpenAPI：`http://127.0.0.1:8000/docs`
- 健康检查：`http://127.0.0.1:8000/api/health`

首次启动时，系统会在后台自动执行：

1. 扫描 `data/source/*.pdf`
2. 解析 PDF
3. 构建检索器
4. 更新 warmup 状态

可通过以下接口查看状态：

- `GET /api/document/status`
- `GET /api/document/warmup`

## 7. 完整模式部署

### 7.1 适用场景

适合以下情况：

- 需要向量检索或混合检索
- 需要更稳定的召回效果
- 需要本地 embedding 模型和可选 reranker

### 7.2 启动 Milvus

项目已提供 Milvus 编排文件：[milvus/docker-compose.milvus.v2.6.17.yml](C:/Users/26332/Desktop/工单/RAG工单/RAG-Q&A system4/milvus/docker-compose.milvus.v2.6.17.yml:1)

启动命令：

```powershell
docker compose -f milvus/docker-compose.milvus.v2.6.17.yml up -d
```

默认端口：

- Milvus：`19530`
- Milvus health/metrics：`9091`
- MinIO：`9000`
- MinIO Console：`9001`
- Attu：`8001`

建议确认容器状态正常后再启动应用服务。

### 7.3 准备本地模型

完整模式至少需要本地 embedding 模型。

推荐准备：

- embedding 模型：`bge-m3`
- reranker 模型：`bge-reranker-base`

示例目录：

```text
D:\models\bge-m3
D:\models\bge-reranker-base
```

### 7.4 准备 `.env`

完整模式示例配置如下：

```env
APP_NAME=RAG Q&A SYSTEM4
APP_ENV=production
API_PREFIX=/api

SOURCE_PDF_DIR=data/source
FEEDBACK_STORE_PATH=data/processed/feedback.jsonl
MILVUS_STATE_PATH=data/processed/milvus_state.json

LLM_PROVIDER=openai_compatible
LLM_API_KEY=your_api_key
LLM_BASE_URL=https://your-openai-compatible-endpoint
LLM_MODEL=your-model-name
LLM_TIMEOUT_SECONDS=30
LLM_TEMPERATURE=0.2

QUERY_UNDERSTANDING_MODE=online
QUERY_UNDERSTANDING_LOCAL_FIRST_ENABLED=true
QUERY_UNDERSTANDING_FALLBACK_ENABLED=true
QUERY_UNDERSTANDING_API_KEY=your_api_key
QUERY_UNDERSTANDING_BASE_URL=https://your-openai-compatible-endpoint
QUERY_UNDERSTANDING_MODEL=your-model-name
QUERY_UNDERSTANDING_TIMEOUT_SECONDS=15
QUERY_UNDERSTANDING_TEMPERATURE=0.1

RETRIEVER_TYPE=hybrid_rrf
DEFAULT_TOP_K=8
MAX_CHUNK_LENGTH=4000
TABLE_CHUNK_LENGTH=1800
RRF_K=60

EMBEDDING_PROVIDER=sentence_transformers
EMBEDDING_MODEL_NAME=D:\models\bge-m3
EMBEDDING_DEVICE=cpu
EMBEDDING_BATCH_SIZE=64

MILVUS_HOST=127.0.0.1
MILVUS_PORT=19530
MILVUS_COLLECTION_NAME=rag_qna_chunks
MILVUS_INDEX_TYPE=IVF_FLAT
MILVUS_METRIC_TYPE=COSINE
MILVUS_NLIST=1024
MILVUS_SEARCH_NPROBE=16

RERANKER_ENABLED=true
RERANKER_MODEL_PATH=D:\models\bge-reranker-base
RERANKER_DEVICE=cpu
RERANKER_MAX_LENGTH=512
RERANKER_TOP_N=8

SESSION_STORE_BACKEND=memory
SESSION_STORE_TTL_SECONDS=86400
```

如果需要 Redis 会话存储，追加：

```env
SESSION_STORE_BACKEND=redis
REDIS_URL=redis://127.0.0.1:6379/0
SESSION_STORE_KEY_PREFIX=rag:qna:session:
SESSION_STORE_TTL_SECONDS=86400
```

### 7.5 启动应用

```powershell
.venv\Scripts\activate
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### 7.6 完整模式验证

建议依次检查：

1. `GET /api/health`
2. `GET /api/document/status`
3. `GET /api/document/warmup`
4. 打开首页上传 PDF
5. 提交一次问答
6. 检查是否返回引用片段

## 8. 生产部署建议

### 8.1 启动方式

不要直接使用 [run.py](C:/Users/26332/Desktop/工单/RAG工单/RAG-Q&A system4/run.py:1) 作为生产启动命令，原因如下：

- 固定绑定 `127.0.0.1`
- 固定端口 `8000`
- 开启 `reload=True`

生产建议：

```powershell
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### 8.2 反向代理

如果需要对外提供服务，建议在前面增加 Nginx 或企业网关，用于：

- HTTPS 终止
- 域名接入
- 请求日志
- 访问控制
- 上传大小限制

### 8.3 CORS

当前代码在 [app/main.py](C:/Users/26332/Desktop/工单/RAG工单/RAG-Q&A system4/app/main.py:1) 中对 `allow_origins` 使用了 `["*"]`。

如果系统需要公网暴露，建议改为明确允许的前端域名，而不是全开放。

### 8.4 数据持久化

至少保证以下数据持久化：

- `data/source`
- `data/processed`
- `milvus/volumes`

否则会出现以下问题：

- 上传的 PDF 丢失
- 反馈记录丢失
- Milvus 向量索引丢失

### 8.5 会话存储

默认会话存储为内存，仅适合单实例。

如果有以下需求，建议启用 Redis：

- 多实例部署
- 重启后尽量保留会话窗口期
- 统一会话状态

## 9. 部署检查清单

上线前至少确认以下项目：

- 已安装 Python 依赖
- `.env` 已完成并与目标环境路径一致
- 若使用 `hybrid_rrf` 或 `milvus`，Milvus 已正常启动
- 若开启 reranker，本地模型目录可访问
- `data/source`、`data/processed` 具备读写权限
- `GET /api/health` 返回正常
- `GET /api/document/warmup` 最终状态为 `ready`
- 首页、知识库页、问答接口均可访问

## 10. 常见问题

### 10.1 服务能启动，但问答失败

常见原因：

- `LLM_PROVIDER=openai_compatible` 时缺少 `LLM_API_KEY`、`LLM_BASE_URL` 或 `LLM_MODEL`
- 上游模型服务不可达
- 问答模式依赖的 Query Understanding 在线配置缺失

### 10.2 完整模式启动后 warmup 失败

常见原因：

- `MILVUS_HOST` / `MILVUS_PORT` 配置错误
- Milvus 容器未完全启动
- `EMBEDDING_MODEL_NAME` 指向不存在的目录
- `RERANKER_MODEL_PATH` 指向不存在的目录

### 10.3 上传 PDF 成功，但没有内容可检索

常见原因：

- PDF 为扫描件，当前项目未实现 OCR
- PDF 中无可提取文本
- PDF 已加密或结构异常

### 10.4 新机器直接启动报模型路径错误

原因通常是未覆盖代码中的默认绝对路径。

必须在 `.env` 中显式设置：

- `EMBEDDING_MODEL_NAME`
- `RERANKER_MODEL_PATH`

## 11. 建议的上线顺序

推荐按以下顺序部署：

1. 先按轻量模式跑通
2. 验证 PDF 上传、解析、问答、引用返回
3. 再启用 Milvus 和 embedding 模型
4. 最后根据需要启用 reranker 和 Redis

这样更容易定位问题，也能避免一次性引入过多变量。

## 12. 验收接口

部署完成后，建议至少检查以下接口：

- `GET /api/health`
- `GET /api/document/status`
- `GET /api/document/warmup`
- `POST /api/document/upload`
- `POST /api/query`
- `POST /api/query/stream`
- `GET /api/kb/documents`

如果以上接口均正常，再进入业务问答验收。
