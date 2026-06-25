# Prospectus Q&A Framework

基于 RAG（检索增强生成）的 PDF 文档问答系统。支持上传 PDF 文档、自动解析分块、知识库管理、自然语言提问和答案引用溯源。

## 当前能力

- **文档问答**：上传 PDF → 自动解析分块 → 自然语言提问 → 引用溯源回答。
- **知识库管理**：查看文档列表、分块详情、删除文档及重建索引。页面：`/kb`。
- **后台预热**：启动时后台线程预热检索索引，支持通过 API 查询预热状态。
- **Query 理解**：意图识别、歧义检测、问题分解、问题抽象（规则/LLM 双模式，支持 local-first）。
- **多检索器支持**：关键词检索（BM25）、向量检索（Milvus）、混合检索（RRF）。
- **可选重排器**：bge-reranker-base 提升检索质量（需兼容 transformers 版本）。
- **多轮对话**：前端自动保存 session_id，刷新页面可恢复会话历史。
- **反馈闭环**：答案评分与文本反馈持久化。
- **配置化设计**：检索器、LLM、嵌入模型、重排器均可通过 `.env` 切换。

## 目录结构

```text
RAG-Q&A system1/
├── app/
│   ├── main.py              # FastAPI 应用入口，后台预热启动
│   ├── api/routes.py        # API 路由（文档/知识库/问答/会话/反馈）
│   ├── core/
│   │   ├── config.py        # 配置项 (pydantic-settings, .env)
│   │   └── container.py     # 依赖注入容器
│   ├── schemas/query.py     # 请求/响应 Pydantic 模型
│   ├── services/
│   │   ├── document_ingestion.py  # PDF 解析与分块
│   │   ├── embeddings.py          # 向量嵌入 (sentence-transformers)
│   │   ├── query_understanding.py # 问题理解 (规则 + LLM)
│   │   ├── retrieval_generation.py# 检索 + LLM 生成
│   │   ├── reranker.py            # 重排序 (可选)
│   │   ├── pipeline.py            # 问答流程编排
│   │   ├── feedback.py            # 反馈收集
│   │   ├── session_service.py     # 会话管理
│   │   ├── session_store.py       # 会话存储 (内存/Redis)
│   │   ├── warmup_status.py       # 检索预热状态跟踪
│   │   ├── retrievers/
│   │   │   ├── base.py            # 检索器基类
│   │   │   ├── keyword.py         # 关键词检索 (BM25)
│   │   │   ├── milvus.py          # 向量检索 (Milvus)
│   │   │   ├── hybrid_rrf.py      # 混合检索 (RRF 融合)
│   │   │   └── factory.py         # 检索器工厂
│   │   └── llm/
│   │       ├── base.py            # LLM 基类
│   │       ├── openai_compatible.py # OpenAI 兼容客户端
│   │       ├── mock.py            # Mock 客户端
│   │       └── factory.py         # LLM 工厂
│   └── static/
│       ├── index.html       # 问答页面
│       ├── kb.html          # 知识库管理页面
│       ├── app.js           # 前端逻辑 (含预热状态轮询)
│       └── styles.css       # 样式
├── data/
│   ├── source/              # PDF 源文件目录
│   └── processed/           # 反馈、缓存、Milvus 状态
├── docs/
│   ├── TECHNICAL.md         # 技术文档
│   └── USER_MANUAL.md       # 用户手册
├── tests/                   # 单元测试
├── milvus/                  # Milvus docker-compose
├── .env                     # 环境变量配置
├── requirements.txt         # Python 依赖
└── run.py                   # 启动脚本
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置

编辑 `.env`，填入 LLM API 配置：

```env
LLM_PROVIDER=openai_compatible
LLM_API_KEY=your_api_key
LLM_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
LLM_MODEL=doubao-seed-1-8-251228
```

### 3. 启动

```bash
cd E:\RAG-Q&A system1
python run.py
```

启动后系统会自动解析 `data/source/` 下的 PDF 文件，并在后台线程预热检索索引。

### 4. 访问

| 页面 | 地址 | 说明 |
|------|------|------|
| 问答主页 | http://127.0.0.1:8000/ | 上传文档、提问 |
| 知识库管理 | http://127.0.0.1:8000/kb | 管理已上传文档 |
| API 文档 | http://127.0.0.1:8000/docs | FastAPI 接口文档 |

## API 概览

### 文档管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/health | 健康检查 |
| GET | /api/document/status | 文档状态（分块数、源文件列表等） |
| GET | /api/document/warmup | 检索预热状态 |
| POST | /api/document/upload | 上传 PDF（自动解析+后台预热） |
| POST | /api/document/reload | 重新加载文档+后台预热 |
| POST | /api/document/select | 选择活跃文档 |

### 知识库管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/kb/documents | 文档列表及分块统计 |
| GET | /api/kb/documents/{id}/chunks | 文档分块详情 |
| DELETE | /api/kb/documents/{id} | 删除文档及分块，自动重建索引 |

### 问答

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /api/query | 问答（JSON 响应） |
| POST | /api/query/stream | 问答（SSE 流式响应） |
| POST | /api/feedback | 提交反馈 |
| GET | /api/session/{id} | 会话历史 |

## 检索器配置

在 `.env` 中通过 `RETRIEVER_TYPE` 切换：

| 值 | 说明 | 外部依赖 |
|----|------|----------|
| `keyword` | 关键词检索（BM25 + 同义词扩展） | 无 |
| `milvus` | 向量检索（需嵌入模型 + Milvus） | Milvus |
| `hybrid_rrf` | 混合检索（关键词+向量，RRF 融合） | Milvus |

## 配置项一览

### LLM

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| LLM_PROVIDER | 提供商：mock/openai_compatible | mock |
| LLM_API_KEY | API Key | - |
| LLM_BASE_URL | API 地址 | - |
| LLM_MODEL | 模型名 | - |
| LLM_TIMEOUT_SECONDS | 超时 | 30 |
| LLM_TEMPERATURE | 温度 | 0.2 |

### Query Understanding

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| QUERY_UNDERSTANDING_MODE | rules/local/online | rules |
| QUERY_UNDERSTANDING_LOCAL_FIRST_ENABLED | 简单问题优先本地规则 | true |
| QUERY_UNDERSTANDING_FALLBACK_ENABLED | 在线失败回退规则 | true |

### 检索

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| RETRIEVER_TYPE | keyword/milvus/hybrid_rrf | keyword |
| DEFAULT_TOP_K | 返回分块数 | 4 |
| MAX_CHUNK_LENGTH | 最大分块长度 | 500 |
| TABLE_CHUNK_LENGTH | 表格分块长度 | 1800 |

### 重排器（可选）

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| RERANKER_ENABLED | 是否启用 | false |
| RERANKER_MODEL_PATH | 模型路径 | - |
| RERANKER_DEVICE | cpu/cuda | cpu |

### 会话

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| SESSION_STORE_BACKEND | memory/redis | memory |
| REDIS_URL | Redis 地址 | - |

## 详细文档

- [技术文档](docs/TECHNICAL.md) — 系统架构、技术选型、核心流程
- [用户手册](docs/USER_MANUAL.md) — 操作指南、常见问题
