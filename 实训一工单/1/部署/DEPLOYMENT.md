# 部署文档

## 1. 文档目标

本文档用于说明 `RAG-Q&A system1` 的部署方式，覆盖以下两种常见场景：

- 最低成本部署：仅使用关键词检索，不依赖 Milvus
- 完整能力部署：启用向量检索或混合检索，接入 Milvus

如果你的目标是先快速跑通系统，建议优先使用“最低成本部署”。  
如果你的目标是获得更好的语义检索效果，再切换到“完整能力部署”。

## 2. 系统说明

本项目是一个基于 FastAPI 的 PDF 智能问答系统，启动后会：

1. 加载 `data/source/` 目录下的 PDF 文件
2. 自动解析并分块
3. 根据配置初始化检索器
4. 在后台执行检索预热
5. 提供 Web 页面和 API 接口

默认访问地址：

- 问答主页：`http://127.0.0.1:8000/`
- 知识库管理页：`http://127.0.0.1:8000/kb`
- API 文档：`http://127.0.0.1:8000/docs`

## 3. 部署前准备

### 3.1 基础环境

建议准备以下环境：

- Python 3.10 及以上
- `pip`
- Windows、Linux 或 macOS

项目 Python 依赖见 `requirements.txt`，核心包括：

- `fastapi`
- `uvicorn`
- `pypdf`
- `sentence-transformers`
- `torch`
- `pymilvus`
- `redis`

### 3.2 目录说明

部署时重点关注以下目录：

- `app/`：后端代码
- `app/static/`：前端静态页面
- `data/source/`：待问答 PDF 文件目录
- `data/processed/`：反馈、缓存和状态文件
- `milvus/`：Milvus 的 Docker Compose 文件
- `.env`：运行配置

### 3.3 启动入口

当前项目自带入口文件为：

```python
python run.py
```

`run.py` 会以如下方式启动：

- Host：`127.0.0.1`
- Port：`8000`
- `reload=True`

这更适合本地开发环境。  
如果是生产环境，建议直接使用 `uvicorn` 命令启动，并关闭热重载。

## 4. 快速部署方案

## 4.1 方案 A：最低成本部署

适用场景：

- 先快速跑通系统
- 不希望依赖 Docker / Milvus
- 更关注部署简单、成本低

能力特点：

- 使用关键词检索
- 不依赖向量数据库
- 启动更轻量
- 精度通常低于混合检索

### 步骤 1：安装依赖

在项目根目录执行：

```bash
pip install -r requirements.txt
```

### 步骤 2：配置 `.env`

建议至少配置如下内容：

```env
APP_NAME=Prospectus Q&A Framework
APP_ENV=development

SOURCE_PDF_DIR=data/source
FEEDBACK_STORE_PATH=data/processed/feedback.jsonl
MILVUS_STATE_PATH=data/processed/milvus_state.json

RETRIEVER_TYPE=keyword
DEFAULT_TOP_K=8
MAX_CHUNK_LENGTH=4000
TABLE_CHUNK_LENGTH=1800

LLM_PROVIDER=openai_compatible
LLM_API_KEY=your_api_key
LLM_BASE_URL=your_base_url
LLM_MODEL=your_model
LLM_TIMEOUT_SECONDS=30
LLM_TEMPERATURE=0.2

QUERY_UNDERSTANDING_MODE=rules
QUERY_UNDERSTANDING_LOCAL_FIRST_ENABLED=true
QUERY_UNDERSTANDING_FALLBACK_ENABLED=true

RERANKER_ENABLED=false
SESSION_STORE_BACKEND=memory
```

说明：

- `RETRIEVER_TYPE=keyword` 表示只使用关键词检索
- `RERANKER_ENABLED=false` 可以减少部署复杂度和资源占用
- `QUERY_UNDERSTANDING_MODE=rules` 可以进一步降低对在线模型的依赖和成本

### 步骤 3：准备 PDF 文件

将需要问答的 PDF 文件放入：

```text
data/source/
```

### 步骤 4：启动服务

开发方式：

```bash
python run.py
```

更适合部署的方式：

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### 步骤 5：验证服务

启动后访问：

- `http://127.0.0.1:8000/`
- `http://127.0.0.1:8000/api/health`
- `http://127.0.0.1:8000/docs`

如果 `health` 接口返回正常，说明服务已经启动成功。

## 4.2 方案 B：完整能力部署

适用场景：

- 需要语义检索能力
- 需要更好的召回效果
- 计划使用 `milvus` 或 `hybrid_rrf`

能力特点：

- 支持向量检索
- 支持混合检索
- 效果通常更好
- 部署和资源要求更高

### 步骤 1：启动 Milvus

项目已提供 Docker Compose 文件：

`milvus/docker-compose.milvus.v2.6.17.yml`

该编排文件包含：

- `etcd`
- `minio`
- `milvus standalone`
- `attu`

在 `milvus/` 目录下执行：

```bash
docker compose -f docker-compose.milvus.v2.6.17.yml up -d
```

默认端口：

- Milvus：`19530`
- Milvus 健康/管理：`9091`
- MinIO：`9000`
- MinIO Console：`9001`
- Attu：`8001`

### 步骤 2：配置向量检索相关参数

`.env` 建议配置为：

```env
RETRIEVER_TYPE=hybrid_rrf

EMBEDDING_PROVIDER=sentence_transformers
EMBEDDING_MODEL_NAME=path/to/bge-m3
EMBEDDING_DEVICE=cpu
EMBEDDING_BATCH_SIZE=64

MILVUS_HOST=127.0.0.1
MILVUS_PORT=19530
MILVUS_COLLECTION_NAME=rag_qna_chunks
MILVUS_INDEX_TYPE=IVF_FLAT
MILVUS_METRIC_TYPE=COSINE
MILVUS_NLIST=1024
MILVUS_SEARCH_NPROBE=16
```

如果你只想使用纯向量检索，可改为：

```env
RETRIEVER_TYPE=milvus
```

### 步骤 3：可选启用 Reranker

如果希望进一步提升排序效果，可以启用：

```env
RERANKER_ENABLED=true
RERANKER_MODEL_PATH=path/to/bge-reranker-base
RERANKER_DEVICE=cpu
RERANKER_MAX_LENGTH=512
RERANKER_TOP_N=8
```

如果部署机器资源有限，建议保持：

```env
RERANKER_ENABLED=false
```

### 步骤 4：启动服务

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

启动后，系统会自动：

- 解析 `data/source/` 中的 PDF
- 构建检索索引
- 在后台预热检索器

### 步骤 5：验证向量服务

可重点检查以下接口：

- `GET /api/health`
- `GET /api/document/status`
- `GET /api/document/warmup`

如果 warmup 状态变为 `ready`，通常说明检索器初始化成功。

## 5. 推荐配置模板

## 5.1 开发环境

```env
APP_ENV=development
RETRIEVER_TYPE=keyword
QUERY_UNDERSTANDING_MODE=rules
RERANKER_ENABLED=false
SESSION_STORE_BACKEND=memory
```

特点：

- 启动快
- 成本低
- 适合本地联调

## 5.2 演示环境

```env
APP_ENV=staging
RETRIEVER_TYPE=hybrid_rrf
QUERY_UNDERSTANDING_MODE=rules
RERANKER_ENABLED=false
SESSION_STORE_BACKEND=memory
```

特点：

- 检索效果优于纯关键词
- 成本仍相对可控
- 适合答辩或功能演示

## 5.3 生产环境

```env
APP_ENV=production
RETRIEVER_TYPE=hybrid_rrf
QUERY_UNDERSTANDING_MODE=online
QUERY_UNDERSTANDING_LOCAL_FIRST_ENABLED=true
QUERY_UNDERSTANDING_FALLBACK_ENABLED=true
RERANKER_ENABLED=true
SESSION_STORE_BACKEND=redis
REDIS_URL=redis://127.0.0.1:6379/0
```

特点：

- 效果更完整
- 支持更稳定的会话存储
- 资源占用和部署复杂度更高

## 6. 生产部署建议

### 6.1 不建议直接使用 `python run.py`

原因：

- `run.py` 中启用了 `reload=True`
- 默认只监听 `127.0.0.1`
- 更适合开发调试

生产环境建议使用：

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### 6.2 建议加反向代理

如果要对外提供服务，建议在前面增加 Nginx 或其他反向代理，用于：

- 统一域名入口
- 处理 HTTPS
- 转发静态与 API 请求
- 控制访问权限

### 6.3 建议使用 Redis 存储会话

默认会话存储是内存，服务重启后会话会丢失。  
如果希望多轮对话历史更稳定，建议配置：

```env
SESSION_STORE_BACKEND=redis
REDIS_URL=redis://127.0.0.1:6379/0
```

### 6.4 建议把模型路径改成可迁移配置

当前 `config.py` 中部分默认路径为本机绝对路径，例如：

- `EMBEDDING_MODEL_NAME`
- `RERANKER_MODEL_PATH`

部署到新机器时，建议务必在 `.env` 中显式覆盖这些路径，否则可能因为路径不存在而启动失败或预热失败。

## 7. 部署检查清单

启动前确认：

- 已安装 Python 依赖
- `.env` 已配置完成
- `data/source/` 下已有 PDF 或允许后续上传
- 如果启用 Milvus，则 Docker 服务已正常运行
- 如果启用 Redis，则 Redis 可连接
- 如果启用在线 LLM，则 `LLM_API_KEY`、`LLM_BASE_URL`、`LLM_MODEL` 已正确填写

启动后确认：

- `GET /api/health` 正常
- `GET /api/document/status` 返回文档状态
- `GET /api/document/warmup` 状态合理
- 主页可打开
- 上传 PDF 后能生成分块
- 提问后能返回答案和引用

## 8. 常见问题

### 8.1 服务能启动，但问答不可用

优先检查：

- `data/source/` 是否有可解析 PDF
- PDF 是否为纯图片扫描件
- 文档是否成功分块
- LLM 配置是否正确

### 8.2 warmup 失败

常见原因：

- Milvus 未启动
- 向量模型路径错误
- Reranker 模型路径错误

如果当前只想先用系统，可切换为：

```env
RETRIEVER_TYPE=keyword
RERANKER_ENABLED=false
```

### 8.3 模型路径报错

说明部署环境与原开发环境路径不同。  
请在 `.env` 中覆盖：

- `EMBEDDING_MODEL_NAME`
- `RERANKER_MODEL_PATH`

### 8.4 会话刷新后丢失

原因通常是当前使用内存会话存储。  
如果希望服务重启后仍尽可能保留会话，建议改用 Redis。

## 9. 建议的部署顺序

建议按下面顺序推进：

1. 先用 `keyword` 模式完成最低成本部署
2. 确认 PDF 上传、解析、问答链路完全正常
3. 再接入 Milvus 和向量模型
4. 最后再考虑启用 reranker、Redis 和在线 Query Understanding

这样可以更快定位问题，也更适合逐步扩展能力。
