# 部署文档

## 1. 适用范围

本文档适用于当前仓库中的 PDF 文档问答系统，覆盖两种部署方式：

- 最小可用部署：仅使用关键词检索，依赖最少，适合本地试运行或内网验证
- 完整部署：使用 `Milvus + 向量检索 + 可选重排器 + 可选 OCR`，适合正式环境

当前项目的服务入口为：

- Web/API 服务：`uvicorn app.main:app`
- 默认访问地址：`http://127.0.0.1:8000`
- 健康检查：`GET /api/health`

`run.py` 仅适合本地开发，因为它固定监听 `127.0.0.1:8000`，并开启了 `reload=True`。生产环境请直接使用 `uvicorn` 命令启动。

## 2. 目录说明

部署时需要重点关注以下目录：

- `app/`：后端代码
- `app/static/`：前端静态页面
- `data/source/`：待解析的 PDF 源文件目录
- `data/processed/`：反馈、Milvus 状态等运行数据
- `milvus/docker-compose.milvus.v2.6.17.yml`：Milvus 部署文件
- `.env`：运行配置

## 3. 环境要求

### 3.1 基础要求

- Python 3.10 及以上
- `pip`
- 可访问的 LLM 接口，且接口兼容 OpenAI 风格

项目 Python 依赖见 `requirements.txt`。

### 3.2 完整部署附加要求

- Docker Desktop 或 Docker Engine
- 本地嵌入模型目录
- 可选本地重排模型目录

当前代码默认使用本地模型路径：

- `EMBEDDING_MODEL_NAME`
- `RERANKER_MODEL_PATH`

如果这些路径不存在，完整部署会失败或自动降级。

### 3.3 OCR 附加要求

项目内 OCR 由 `pytesseract + pdf2image` 提供，适合扫描版 PDF。若启用 OCR，通常还需要在操作系统层安装：

- Tesseract OCR
- Poppler

如果未安装，系统仍可启动，但扫描件提取能力会不可用。可通过 `GET /api/document/ocr/status` 检查 OCR 状态。

## 4. 部署方式一：最小可用部署

这种方式不依赖 Milvus、本地嵌入模型和重排器，最快落地。

### 4.1 安装依赖

```bash
pip install -r requirements.txt
```

### 4.2 准备配置

在项目根目录创建 `.env`，可基于 `.env.example` 修改，建议最小配置如下：

```env
APP_NAME=PDF Document Q&A System
APP_ENV=production
API_PREFIX=/api

SOURCE_PDF_DIR=data/source
FEEDBACK_STORE_PATH=data/processed/feedback.jsonl
MILVUS_STATE_PATH=data/processed/milvus_state.json

LLM_PROVIDER=openai_compatible
LLM_API_KEY=your_api_key
LLM_BASE_URL=your_base_url
LLM_MODEL=your_model
LLM_TIMEOUT_SECONDS=30
LLM_TEMPERATURE=0.2

QUERY_UNDERSTANDING_MODE=rules
QUERY_UNDERSTANDING_FALLBACK_ENABLED=true
QUERY_UNDERSTANDING_LOCAL_FIRST_ENABLED=true

RETRIEVER_TYPE=keyword
DEFAULT_TOP_K=8
MAX_CHUNK_LENGTH=4000
TABLE_CHUNK_LENGTH=1800

RERANKER_ENABLED=false
OCR_ENABLED=false

SESSION_STORE_BACKEND=memory
SESSION_STORE_TTL_SECONDS=86400
```

说明：

- `RETRIEVER_TYPE=keyword` 时，不依赖 Milvus 和嵌入模型
- `RERANKER_ENABLED=false` 可以避免本地重排模型缺失导致的额外初始化开销
- `OCR_ENABLED=false` 可以避免扫描件 OCR 的系统依赖问题

### 4.3 准备 PDF 文件

将待问答的 PDF 放入：

```text
data/source/
```

服务启动后会自动加载该目录中的 PDF，并在后台进行检索预热。

### 4.4 启动服务

生产部署建议使用：

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

本地开发可使用：

```bash
python run.py
```

### 4.5 验证部署

启动后依次检查：

```bash
curl http://127.0.0.1:8000/api/health
curl http://127.0.0.1:8000/api/document/status
curl http://127.0.0.1:8000/api/document/warmup
```

浏览器访问：

- `http://127.0.0.1:8000/`：问答主页
- `http://127.0.0.1:8000/kb`：知识库管理页
- `http://127.0.0.1:8000/docs`：Swagger API 文档

## 5. 部署方式二：完整部署

完整部署适用于 `milvus` 或 `hybrid_rrf` 检索模式。

### 5.1 启动 Milvus

在项目根目录执行：

```bash
docker compose -f milvus/docker-compose.milvus.v2.6.17.yml up -d
```

该文件会启动以下组件：

- `etcd`
- `minio`
- `milvus-standalone`
- `attu`

默认端口：

- Milvus：`19530`
- Milvus 监控：`9091`
- MinIO：`9000`
- MinIO Console：`9001`
- Attu：`8001`

### 5.2 准备完整配置

示例：

```env
APP_NAME=PDF Document Q&A System
APP_ENV=production
API_PREFIX=/api

SOURCE_PDF_DIR=data/source
FEEDBACK_STORE_PATH=data/processed/feedback.jsonl
MILVUS_STATE_PATH=data/processed/milvus_state.json

LLM_PROVIDER=openai_compatible
LLM_API_KEY=your_api_key
LLM_BASE_URL=your_base_url
LLM_MODEL=your_model

QUERY_UNDERSTANDING_MODE=online
QUERY_UNDERSTANDING_API_KEY=your_api_key
QUERY_UNDERSTANDING_BASE_URL=your_base_url
QUERY_UNDERSTANDING_MODEL=your_model
QUERY_UNDERSTANDING_FALLBACK_ENABLED=true
QUERY_UNDERSTANDING_LOCAL_FIRST_ENABLED=true

RETRIEVER_TYPE=hybrid_rrf
DEFAULT_TOP_K=8
MAX_CHUNK_LENGTH=4000
TABLE_CHUNK_LENGTH=1800
RRF_K=60

EMBEDDING_PROVIDER=sentence_transformers
EMBEDDING_MODEL_NAME=your_embedding_model_path
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
RERANKER_MODEL_PATH=your_reranker_model_path
RERANKER_DEVICE=cpu
RERANKER_MAX_LENGTH=512
RERANKER_TOP_N=8

OCR_ENABLED=true
OCR_LANGUAGE=chi_sim+eng

SESSION_STORE_BACKEND=memory
```

说明：

- `RETRIEVER_TYPE=milvus`：纯向量检索
- `RETRIEVER_TYPE=hybrid_rrf`：关键词检索和向量检索融合，通常更稳妥
- 若 `RERANKER_ENABLED=true` 但模型路径不可用，系统会记录告警并自动禁用重排器

### 5.3 启动应用

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### 5.4 验证完整部署

建议检查以下内容：

```bash
curl http://127.0.0.1:8000/api/health
curl http://127.0.0.1:8000/api/document/status
curl http://127.0.0.1:8000/api/document/warmup
curl http://127.0.0.1:8000/api/document/ocr/status
```

如果使用 `hybrid_rrf` 或 `milvus`，启动后首次预热会触发：

- PDF 解析与分块
- 向量化
- Milvus Collection 建立或重建
- 检索器后台预热

## 6. 数据初始化与更新

### 6.1 初次加载

应用启动时会自动：

1. 构建 `AppContainer`
2. 加载 `data/source/` 下的 PDF
3. 在后台线程中执行检索预热

### 6.2 增量上传

可通过页面上传，或调用：

```text
POST /api/document/upload
```

上传后系统会在后台解析 PDF、更新索引并触发预热。

### 6.3 手动重载

当你直接修改 `data/source/` 中的文件后，可调用：

```text
POST /api/document/reload
```

### 6.4 文档选择

如果需要限定检索范围，可调用：

```text
POST /api/document/select
```

## 7. 生产部署建议

- 不要在生产环境使用 `python run.py`
- 建议使用 `uvicorn app.main:app --host 0.0.0.0 --port 8000`
- 建议在外层增加反向代理，例如 Nginx 或企业网关
- 建议将 `.env` 中的密钥、模型路径和存储路径纳入环境管理
- 建议将 `data/source/` 与 `data/processed/` 做持久化备份
- 若需跨进程或跨实例共享会话，可切换 `SESSION_STORE_BACKEND=redis`

## 8. 常见问题

### 8.1 服务能启动，但外部机器访问不到

原因通常是使用了：

```bash
python run.py
```

因为 `run.py` 固定监听 `127.0.0.1`。请改为：

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### 8.2 启动时报 `Retriever warmup failed`

常见原因：

- `RETRIEVER_TYPE` 使用了 `milvus` 或 `hybrid_rrf`，但 Milvus 未启动
- `EMBEDDING_MODEL_NAME` 指向的模型目录不存在
- Milvus 端口或集合配置错误

可先改为最小配置验证：

```env
RETRIEVER_TYPE=keyword
RERANKER_ENABLED=false
OCR_ENABLED=false
```

### 8.3 扫描件无法提取文本

常见原因：

- `OCR_ENABLED=false`
- 未安装 Tesseract
- 未安装 Poppler
- OCR 语言包不完整

建议先检查：

```text
GET /api/document/ocr/status
```

### 8.4 重排器初始化失败

当前代码会在重排器加载失败时自动降级，不会阻塞主服务启动。常见原因：

- `RERANKER_MODEL_PATH` 不存在
- `transformers` 版本与模型不兼容
- 机器内存不足

### 8.5 Redis 不可用

当前代码会自动回退到内存会话存储。若希望显式关闭 Redis 依赖，可配置：

```env
SESSION_STORE_BACKEND=memory
```

## 9. 推荐部署顺序

### 9.1 本地验证

1. 使用 `keyword` 模式启动
2. 验证 PDF 上传、问答和知识库页面
3. 确认 LLM 接口可用

### 9.2 能力升级

1. 启动 Milvus
2. 配置本地嵌入模型
3. 切换到 `hybrid_rrf`
4. 根据需要启用 `RERANKER_ENABLED` 和 `OCR_ENABLED`

### 9.3 正式上线

1. 使用 `uvicorn app.main:app --host 0.0.0.0 --port 8000`
2. 增加反向代理和访问控制
3. 做好 `.env` 与数据目录备份
