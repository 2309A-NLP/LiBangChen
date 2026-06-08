# 部署文档

## 1. 适用范围

本文档适用于当前仓库的 PDF 文档问答系统部署，覆盖：

- 单机最小部署
- 带 Milvus 的完整部署
- Windows 环境部署
- 通用生产启动建议

当前系统由以下部分组成：

- FastAPI 后端
- 原生 HTML/JS 前端
- PDF 文本解析与分块
- 可选的向量检索组件 `Milvus`
- 可选的会话存储组件 `Redis`

## 2. 部署模式

### 2.1 最小可用模式

适合先跑通系统，依赖最少：

- 后端：FastAPI
- 检索：`keyword`
- 会话：内存
- 不依赖 Milvus
- 不依赖 Redis

特点：

- 部署最快
- 适合单机验证
- 对中文规则检索问题效果可接受
- 不适合高并发和大规模知识库

### 2.2 完整模式

适合正式使用：

- 后端：FastAPI
- 检索：`hybrid_rrf` 或 `milvus`
- 向量库：Milvus
- Embedding：`sentence-transformers`
- 可选重排：`bge-reranker-base`
- 可选会话存储：Redis

特点：

- 召回更稳定
- 对复杂问题更友好
- 组件更多，部署更复杂

## 3. 目录说明

关键目录如下：

```text
app/                    后端代码
app/static/             前端静态页面
data/source/            PDF 源文件目录
data/processed/         中间产物与状态文件
docs/                   项目文档
milvus/                 Milvus docker-compose 与数据卷
requirements.txt        Python 依赖
run.py                  开发启动入口
```

## 4. 环境要求

建议准备以下基础环境：

- Python
- pip
- Docker Desktop 或 Docker Engine

完整模式额外需要：

- 可用的 embedding 模型目录
- 可用的 reranker 模型目录（如果启用重排）
- 可用的 LLM API

当前项目依赖见 [requirements.txt](C:/Users/26332/Desktop/工单/RAG工单/RAG-Q%26A%20system5/requirements.txt:1)，核心包括：

- `fastapi`
- `uvicorn`
- `pypdf`
- `PyMuPDF`
- `pymilvus`
- `sentence-transformers`
- `transformers`
- `torch`

## 5. 安装依赖

在项目根目录执行：

```powershell
pip install -r requirements.txt
```

如果你使用 Conda，也可以先激活环境再执行上面的命令。

## 6. 数据目录准备

确认以下目录存在：

```text
data/source
data/processed
```

如果不存在，可手动创建。

系统运行后会在这些目录中读写：

- 上传的 PDF
- 反馈文件
- Milvus 状态文件

## 7. 配置文件

项目通过 `.env` 读取配置，配置定义见 [app/core/config.py](C:/Users/26332/Desktop/工单/RAG工单/RAG-Q%26A%20system5/app/core/config.py:1)。

### 7.1 最小可用配置

适合先启动系统：

```env
APP_NAME=PDF Document Q&A System
APP_ENV=production

SOURCE_PDF_DIR=data/source
SOURCE_PDF_PATH=data/source/sample.pdf
FEEDBACK_STORE_PATH=data/processed/feedback.jsonl
MILVUS_STATE_PATH=data/processed/milvus_state.json

LLM_PROVIDER=mock

QUERY_UNDERSTANDING_MODE=rules
QUERY_UNDERSTANDING_LOCAL_FIRST_ENABLED=true
QUERY_UNDERSTANDING_FALLBACK_ENABLED=true

RETRIEVER_TYPE=keyword
DEFAULT_TOP_K=8
MAX_CHUNK_LENGTH=4000
TABLE_CHUNK_LENGTH=1800

SESSION_STORE_BACKEND=memory
RERANKER_ENABLED=false
```

说明：

- `LLM_PROVIDER=mock` 适合本地联调，不依赖真实模型
- `RETRIEVER_TYPE=keyword` 不需要 Milvus
- `SESSION_STORE_BACKEND=memory` 不需要 Redis

### 7.2 带在线模型的配置

如果要接入真实大模型，可使用：

```env
APP_NAME=PDF Document Q&A System
APP_ENV=production

SOURCE_PDF_DIR=data/source
SOURCE_PDF_PATH=data/source/sample.pdf
FEEDBACK_STORE_PATH=data/processed/feedback.jsonl
MILVUS_STATE_PATH=data/processed/milvus_state.json

LLM_PROVIDER=openai_compatible
LLM_API_KEY=your_api_key
LLM_BASE_URL=https://your-openai-compatible-endpoint/v1
LLM_MODEL=your_model_name
LLM_TIMEOUT_SECONDS=30
LLM_TEMPERATURE=0.2

QUERY_UNDERSTANDING_MODE=online
QUERY_UNDERSTANDING_API_KEY=your_api_key
QUERY_UNDERSTANDING_BASE_URL=https://your-openai-compatible-endpoint/v1
QUERY_UNDERSTANDING_MODEL=your_model_name
QUERY_UNDERSTANDING_TIMEOUT_SECONDS=15
QUERY_UNDERSTANDING_TEMPERATURE=0.1
QUERY_UNDERSTANDING_LOCAL_FIRST_ENABLED=true
QUERY_UNDERSTANDING_FALLBACK_ENABLED=true

RETRIEVER_TYPE=keyword
DEFAULT_TOP_K=8
MAX_CHUNK_LENGTH=4000
TABLE_CHUNK_LENGTH=1800

SESSION_STORE_BACKEND=memory
RERANKER_ENABLED=false
```

### 7.3 完整检索配置

如果启用向量检索或混合检索：

```env
LLM_PROVIDER=openai_compatible
LLM_API_KEY=your_api_key
LLM_BASE_URL=https://your-openai-compatible-endpoint/v1
LLM_MODEL=your_model_name

QUERY_UNDERSTANDING_MODE=online
QUERY_UNDERSTANDING_LOCAL_FIRST_ENABLED=true
QUERY_UNDERSTANDING_FALLBACK_ENABLED=true

RETRIEVER_TYPE=hybrid_rrf
DEFAULT_TOP_K=8

EMBEDDING_PROVIDER=sentence_transformers
EMBEDDING_MODEL_NAME=E:\path\to\bge-m3
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
RERANKER_MODEL_PATH=E:\path\to\bge-reranker-base
RERANKER_DEVICE=cpu
RERANKER_MAX_LENGTH=512
RERANKER_TOP_N=8

SESSION_STORE_BACKEND=memory
```

如果启用 Redis 会话存储：

```env
SESSION_STORE_BACKEND=redis
REDIS_URL=redis://127.0.0.1:6379/0
SESSION_STORE_KEY_PREFIX=rag:qna:session:
SESSION_STORE_TTL_SECONDS=86400
```

## 8. Milvus 部署

如果 `RETRIEVER_TYPE` 使用 `milvus` 或 `hybrid_rrf`，需要先启动 Milvus。

项目已提供 Compose 文件：

[milvus/docker-compose.milvus.v2.6.17.yml](C:/Users/26332/Desktop/工单/RAG工单/RAG-Q%26A%20system5/milvus/docker-compose.milvus.v2.6.17.yml:1)

启动命令：

```powershell
docker compose -f milvus/docker-compose.milvus.v2.6.17.yml up -d
```

默认暴露端口：

- `19530`：Milvus
- `9091`：Milvus 健康相关端口
- `9000`：MinIO API
- `9001`：MinIO Console
- `8001`：Attu

启动后可通过 `docker ps` 确认以下容器状态：

- `milvus-etcd`
- `milvus-minio`
- `milvus-standalone`
- `milvus-attu`

## 9. 启动应用

### 9.1 开发模式

当前 [run.py](C:/Users/26332/Desktop/工单/RAG工单/RAG-Q%26A%20system5/run.py:1) 使用：

- `host=127.0.0.1`
- `port=8000`
- `reload=True`

启动命令：

```powershell
python run.py
```

适合：

- 本机调试
- 代码开发
- 热重载

### 9.2 生产模式

生产环境不要直接用 `run.py`，建议直接启动 `uvicorn`：

```powershell
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

如果使用 Linux，也可执行：

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

说明：

- `0.0.0.0` 允许外部访问
- 不建议生产环境保留 `reload=True`
- 当前系统包含后台预热与内存态服务，建议先以单进程运行验证

## 10. 首次启动后的检查

应用启动后，按顺序检查：

### 10.1 健康检查

访问：

- `http://127.0.0.1:8000/api/health`

预期返回：

- `status=ok`

### 10.2 文档加载状态

访问：

- `http://127.0.0.1:8000/api/document/status`

重点检查：

- `document_loaded`
- `document_count`
- `chunk_count`
- `warnings`

### 10.3 预热状态

访问：

- `http://127.0.0.1:8000/api/document/warmup`

预期状态：

- `idle`
- `running`
- `ready`

如果是向量模式，建议确认最终进入 `ready`。

### 10.4 前端页面

访问：

- `http://127.0.0.1:8000/`
- `http://127.0.0.1:8000/kb`
- `http://127.0.0.1:8000/docs`

## 11. 初次使用流程

1. 启动服务。
2. 打开首页。
3. 上传一个或多个 PDF。
4. 等待系统解析与预热完成。
5. 先测试一个简单问题，例如“公司的主营业务是什么？”
6. 再测试一个表格问题，例如“报告期内收入分别是多少？”

## 12. 生产部署建议

### 12.1 进程管理

建议使用进程管理工具托管 `uvicorn`，例如：

- Windows 服务
- NSSM
- supervisor
- systemd

### 12.2 反向代理

建议在应用前放置反向代理，例如：

- Nginx
- IIS

用于处理：

- 域名
- HTTPS
- 超时控制
- 请求体大小限制
- 静态访问策略

### 12.3 文件与磁盘

重点关注以下目录的可写权限与容量：

- `data/source`
- `data/processed`
- `milvus/volumes`（如果启用 Milvus）

### 12.4 模型路径

如果启用 embedding 或 reranker，确保以下路径真实存在：

- `EMBEDDING_MODEL_NAME`
- `RERANKER_MODEL_PATH`

### 12.5 会话存储

如果要跨进程或跨实例保存会话，建议启用 Redis：

- 内存模式只适合单实例
- 多实例不建议继续使用 `memory`

## 13. 常见故障

### 13.1 访问不到首页

排查：

- 服务是否启动成功
- 端口 `8000` 是否被占用
- 是否仍绑定在 `127.0.0.1`

### 13.2 上传成功但没有解析内容

常见原因：

- PDF 是扫描件或纯图片页
- PDF 被加密
- PDF 本身没有可提取文字

当前系统对图表页做了 `PyMuPDF` 版面文本增强，但纯图片扫描页仍可能无法解析。

### 13.3 Milvus 连接失败

排查：

- `docker compose` 是否启动成功
- `MILVUS_HOST` / `MILVUS_PORT` 是否正确
- `19530` 端口是否可访问

### 13.4 模型加载失败

排查：

- 模型路径是否正确
- 本机是否具备对应依赖
- 是否有足够内存

### 13.5 问答效果差

优先排查：

- `RETRIEVER_TYPE` 是否符合当前场景
- PDF 是否真的被解析成 chunk
- `document/status` 的 `warnings`
- 图表或扫描页是否超出当前解析能力

## 14. 推荐部署顺序

建议按以下顺序推进：

1. 先用 `keyword + mock` 跑通最小闭环。
2. 再切换到真实 LLM。
3. 再接入 Milvus 与 embedding。
4. 最后再启用 reranker 和 Redis。

这样更容易定位问题，不会在第一天把所有组件耦合在一起。

