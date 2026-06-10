# 技术文档 — PDF文档问答系统

## 1. 系统概述

基于 RAG 的 PDF 文档问答系统。上传 PDF 后自动解析分块，支持关键词/全文/向量/混合检索，LLM 生成带引用溯源的回答。包含知识库管理功能。

## 2. 系统架构

```
┌─────────────────────────────────────────────────┐
│                   前端 (HTML/JS)                 │
│  index.html (问答)    kb.html (知识库管理)       │
│  app.js (SSE流式/预热轮询/会话管理)              │
└───────────────┬─────────────────────────────────┘
                │ HTTP / SSE
┌───────────────▼─────────────────────────────────┐
│              FastAPI 后端 (app/)                  │
│                                                   │
│  routes.py ──→ pipeline.py ──→ 各 service        │
│       ↑            ↑                              │
│  container.py (依赖注入)                          │
│                                                   │
│  ┌───────────────────────────────────────────┐   │
│  │  Services                                 │   │
│  │                                            │   │
│  │  DocumentIngestion ── PDF解析/分块/管理     │   │
│  │  QueryUnderstanding ── 意图/歧义/分解      │   │
│  │  RetrievalGeneration ── 检索+LLM生成       │   │
│  │  QAPipeline ── 问答编排/会话上下文          │   │
│  │  WarmupStatus ── 后台预热状态跟踪           │   │
│  │  SessionService ── 会话管理 (内存/Redis)    │   │
│  │  FeedbackService ── 反馈持久化              │   │
│  │                                            │   │
│  │  Retrievers:                               │   │
│  │    keyword (兼容旧版关键词)                 │   │
│  │    fulltext (倒排索引全文检索)              │   │
│  │    milvus/vector (向量)                     │   │
│  │    hybrid (rrf/weighted/vote 融合)          │   │
│  │                                            │   │
│  │  LLM: openai_compatible / mock             │   │
│  │  Embeddings: sentence-transformers (bge-m3)│   │
│  │  Reranker: cross_encoder/tfidf/feedback/llm │   │
│  └───────────────────────────────────────────┘   │
└──────────────────────────────────────────────────┘
```

## 3. 技术选型

| 组件 | 技术 | 说明 |
|------|------|------|
| Web 框架 | FastAPI 0.136+ | 异步，自动 OpenAPI 文档 |
| 配置管理 | pydantic-settings 2.14+ | .env 文件驱动 |
| PDF 解析 | pypdf 5.9+ | 文本提取，表格页面特殊处理 |
| 嵌入模型 | sentence-transformers 3.4+ (bge-m3) | 中文向量检索 |
| 向量数据库 | Milvus 2.3+ (pymilvus 2.6+) | 可选，docker-compose |
| 重排器 | bge-reranker-base | 可选，需 transformers>=4.36 |
| LLM | 火山引擎 doubao-seed-1-8-251228 | OpenAI 兼容 API |
| 会话存储 | 内存 / Redis | 可配置 |
| 前端 | 原生 HTML/JS/CSS | 无框架依赖 |

## 4. 启动流程

```
run.py
  └─ uvicorn(app.main:app, reload=True)
       └─ lifespan()
            ├─ AppContainer.build()        # 构建所有 service
            ├─ load_document()             # 解析 data/source/*.pdf
            └─ _start_background_prepare() # 后台线程预热检索索引
                 ├─ warmup_status_service.start()
                 ├─ prepare_retrieval()
                 └─ warmup_status_service.succeed()/fail()
```

启动时不阻塞，检索预热在后台线程执行。前端通过轮询 `GET /api/document/warmup` 获取预热状态。

## 5. 核心流程

### 5.1 文档上传与解析

```
POST /api/document/upload
  → save_uploaded_pdf()        # 保存到 data/source/
  → load_document(force=True)  # pypdf 解析 → 分块
  → select_sources([file])     # 设为活跃文档
  → start_background_prepare() # 后台重建索引
```

分块策略：
- 普通文本：段落分割，最大 `MAX_CHUNK_LENGTH` 字符
- 表格页面：检测表格特征（数字行+表头行），使用 `TABLE_CHUNK_LENGTH`
- 超大段落：按句子切分，再按字符数硬切

### 5.2 问答流程

```
POST /api/query/stream (SSE)
  → select_sources()                    # 设定检索范围
  → pipeline.answer_question()
      ├─ query_understanding.understand()  # 意图/关键词/歧义
      ├─ retrieval_generation.answer()
      │    ├─ retriever.retrieve()         # 检索分块
      │    ├─ reranker.rerank()            # 可选重排
      │    ├─ _try_local_extraction()      # 本地规则提取
      │    └─ llm_client.generate_answer() # LLM 生成
      └─ session_service.save()            # 保存会话
  → SSE: status → result → done
```

### 5.3 知识库管理

```
GET  /api/kb/documents              → 文档列表+分块统计
GET  /api/kb/documents/{id}/chunks  → 分块详情
DELETE /api/kb/documents/{id}       → 删除文件+重建索引
```

删除流程：`delete_source()` 删除物理文件 → `load_document(force=True)` 重建内存状态 → `start_background_prepare()` 后台重建索引。

### 5.4 预热状态

`WarmupStatusService` 跟踪后台预热进度：

- `idle` — 未开始
- `running` — 预热中
- `ready` — 预热完成
- `warmup_failed` — 预热失败（如 Milvus 不可用）

前端轮询 `GET /api/document/warmup` 获取状态，显示提示信息。

## 6. 配置项

### .env 完整配置

```env
# 应用
APP_NAME=Prospectus Q&A Framework
APP_ENV=development
SOURCE_PDF_PATH=data/source/xxx.pdf
FEEDBACK_STORE_PATH=data/processed/feedback.jsonl

# LLM
LLM_PROVIDER=openai_compatible
LLM_API_KEY=your_key
LLM_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
LLM_MODEL=doubao-seed-1-8-251228
LLM_TIMEOUT_SECONDS=30
LLM_TEMPERATURE=0.2

# Query Understanding
QUERY_UNDERSTANDING_MODE=online
QUERY_UNDERSTANDING_LOCAL_FIRST_ENABLED=true
QUERY_UNDERSTANDING_FALLBACK_ENABLED=true

# 检索器
RETRIEVER_TYPE=hybrid  # keyword / fulltext / vector / milvus / hybrid
FULLTEXT_DEFAULT_OPERATOR=smart
FULLTEXT_TITLE_WEIGHT=2.4
FULLTEXT_SUMMARY_WEIGHT=1.4
FULLTEXT_BODY_WEIGHT=1.0
FULLTEXT_FUZZY_MAX_DISTANCE=1
HYBRID_TEXT_RETRIEVER=fulltext
HYBRID_FUSION_STRATEGY=rrf  # rrf / weighted / vote
HYBRID_FULLTEXT_WEIGHT=0.45
HYBRID_VECTOR_WEIGHT=0.55
HYBRID_CANDIDATE_MULTIPLIER=5
HYBRID_VOTE_MIN_AGREEMENT=1
DEFAULT_TOP_K=8
MAX_CHUNK_LENGTH=4000
TABLE_CHUNK_LENGTH=1800

# 嵌入模型
EMBEDDING_MODEL_NAME=path/to/bge-m3
EMBEDDING_DEVICE=cpu
EMBEDDING_BATCH_SIZE=64

# Milvus（仅 vector/milvus/hybrid 需要）
MILVUS_HOST=127.0.0.1
MILVUS_PORT=19530
MILVUS_COLLECTION_NAME=rag_qna_chunks

# 重排器（可选）
RERANKER_ENABLED=true
RERANKER_TYPES=cross_encoder
RERANKER_MODEL_PATH=path/to/bge-reranker-base
RERANKER_LLM_API_KEY=
RERANKER_LLM_BASE_URL=
RERANKER_LLM_MODEL=
RERANKER_LLM_TIMEOUT_SECONDS=15
RERANKER_FEEDBACK_POSITIVE_RATING=4

# 会话存储
SESSION_STORE_BACKEND=memory  # memory / redis
REDIS_URL=redis://127.0.0.1:6379/0
```

## 7. API 端点一览

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/health | 健康检查 |
| GET | /api/document/status | 文档状态 |
| GET | /api/document/warmup | 检索预热状态 |
| POST | /api/document/upload | 上传 PDF |
| POST | /api/document/reload | 重新加载+预热 |
| POST | /api/document/select | 选择活跃文档 |
| GET | /api/kb/documents | 知识库文档列表 |
| GET | /api/kb/documents/{id}/chunks | 文档分块详情 |
| DELETE | /api/kb/documents/{id} | 删除文档 |
| POST | /api/query | 问答 (JSON) |
| POST | /api/query/stream | 问答 (SSE 流式) |
| POST | /api/feedback | 提交反馈 |
| GET | /api/session/{id} | 会话历史 |

## 8. 检索器对比

| 检索器 | RETRIEVER_TYPE | 依赖 | 说明 |
|--------|---------------|------|------|
| 关键词兼容 | keyword | 无 | 旧版关键词检索实现，保留兼容 |
| 全文 | fulltext | 无 | 倒排索引，多字段 + 布尔/短语/模糊匹配 |
| 向量 | vector / milvus | Milvus + 嵌入模型 | 语义相似度检索 |
| 混合 | hybrid | Milvus + 全文检索 | 支持 `rrf / weighted / vote` 融合 |

## 9. 重排器对比

| 重排器 | RERANKER_TYPES | 依赖 | 说明 |
| --- | --- | --- | --- |
| Cross Encoder | cross_encoder | transformers + torch | 交叉编码器精排，适合高精度召回后重排 |
| TF-IDF | tfidf | 无 | 轻量本地重排，便于离线部署 |
| Feedback | feedback | 无 | 基于历史反馈词项偏好的自适应重排 |
| LLM | llm | 在线 LLM | 基于 LLM 判断候选片段相关性，可回退启发式模式 |
