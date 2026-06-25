# 角色扮演系统 - 代码注释与架构文档

## 一、系统架构概览

```
┌──────────────────────────────────────────────────────────────────────┐
│                        前端 (Frontend)                               │
│                  frontend/index.html (单页应用)                       │
└────────────────────────────┬─────────────────────────────────────────┘
                             │ HTTP/JSON
┌────────────────────────────▼─────────────────────────────────────────┐
│                    API 层 (FastAPI)                                   │
│  ┌──────────┬──────────┬──────────┬──────────┬──────────┬──────────┐ │
│  │ system   │  auth    │conversat.│  files   │knowledge │   llm    │ │
│  │ routes   │  routes  │  routes  │  routes  │  routes  │  routes  │ │
│  └──────────┴──────────┴──────────┴──────────┴──────────┴──────────┘ │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  app_factory.py (应用工厂 - 中间件/路由注册/生命周期)          │   │
│  │  dependencies.py (认证/限流/错误处理/IP获取)                   │   │
│  │  schemas.py (Pydantic 请求/响应模型)                          │   │
│  │  services.py (生命周期/知识同步调度/Milvus状态)                │   │
│  └──────────────────────────────────────────────────────────────┘   │
└────────────────────────────┬─────────────────────────────────────────┘
                             │
┌────────────────────────────▼─────────────────────────────────────────┐
│                    业务逻辑层 (Business Logic)                        │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  chat_bot.py (核心业务 - 用户/会话/聊天/知识/文件)            │   │
│  │  rag_chain.py (RAG 编排 - 检索/Prompt/LLM调用/降级)          │   │
│  │  security.py (安全 - PBKDF2哈希/JWT令牌/速率限制)             │   │
│  │  llm_settings.py (LLM配置 - 多源加载/保存/测试/诊断)          │   │
│  │  config.py (配置中心 - 环境变量/默认值/角色定义)               │   │
│  │  models.py (ORM模型 - User/Role/Conversation/Message等)      │   │
│  │  prompts.py (Prompt模板 - 7角色模板 + 通用要求)               │   │
│  └──────────────────────────────────────────────────────────────┘   │
└────────────────────────────┬─────────────────────────────────────────┘
                             │
┌────────────────────────────▼─────────────────────────────────────────┐
│                     数据层 (Data Layer)                               │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌─────────┐  │
│  │  SQLite/MySQL│  │  Milvus      │  │  Redis       │  │ 文件系统 │  │
│  │  (用户/会话/  │  │  (向量检索)   │  │  (短期记忆)   │  │ (知识源/ │  │
│  │   消息/知识)  │  │              │  │              │  │  上传)   │  │
│  └──────────────┘  └──────────────┘  └──────────────┘  └─────────┘  │
└──────────────────────────────────────────────────────────────────────┘
```

## 二、核心模块详细说明

### 2.1 API 路由模块 (`api/routes/`)

| 文件 | 功能 | 接口数 | 说明 |
|------|------|--------|------|
| `system.py` | 系统状态、角色列表、健康检查 | 3 | 提供前端页面、角色配置、健康检查 |
| `auth.py` | 用户注册、登录 | 2 | 注册/登录，带速率限制 |
| `conversations.py` | 会话管理、聊天 | 6 | 创建/重命名/删除会话、聊天、历史记录 |
| `files.py` | 文件上传、管理、分析 | 4 | 上传/删除/列表/角色分析 |
| `knowledge.py` | 知识库管理、检索配置 | 8 | 添加/同步/PDF/Milvus/检索配置 |
| `llm.py` | LLM 模型配置管理 | 5 | 状态/配置/测试/诊断 |

### 2.2 API 基础设施 (`api/`)

| 文件 | 功能 | 关键函数/类 | 说明 |
|------|------|-------------|------|
| `__init__.py` | 包入口 | - | 导出 app 和 create_app |
| `app_factory.py` | 应用工厂 | `create_app()` | 创建 FastAPI 实例，注册 CORS/TrustedHost/日志中间件，注册 6 个路由模块，配置 lifespan 生命周期 |
| `dependencies.py` | 依赖注入 | `get_client_ip()`, `get_current_user()`, `require_admin()`, `enforce_rate_limit()`, `issue_auth_payload()`, `http_error()`, `raise_http_error()` | 认证验证、速率限制（6 个限流器）、错误处理、IP 获取 |
| `schemas.py` | 数据模型 | `UserCreate`, `UserLogin`, `ConversationCreate`, `ChatRequest`, `LLMConfigPayload`, `RetrievalConfigPayload` | Pydantic 请求体模型，数据验证 |
| `services.py` | 服务管理 | `lifespan()`, `get_knowledge_pdf_info()`, `get_role_compendium_info()`, `get_milvus_connection_info()`, `build_knowledge_sync_status()` | 应用生命周期（数据库初始化、知识同步调度）、Milvus 状态检查、知识 PDF 信息 |

### 2.3 业务逻辑模块

| 文件 | 功能 | 关键类/函数 | 说明 |
|------|------|-------------|------|
| `chat_bot.py` | 核心业务逻辑 | `ChatBot` 类 | 用户管理（create/authenticate/get_active_user）、会话管理（create/delete/rename）、消息处理（chat/save_message_pair/get_history）、知识库管理（add_knowledge_document）、文件管理（upload/delete/list/analyze）。核心方法 `chat()` 流程：验证会话 → 请求去重 → 获取历史 → 自动生成标题 → 调用 RAGChain → 持久化消息对 |
| `rag_chain.py` | RAG 编排引擎 | `RAGChain` 类 | 协调知识检索、Prompt 组装、LLM 调用和降级策略。核心方法 `generate_response()` 按优先级尝试 5 种回答模式：社交开场白 → 轻量聊天 → 短期记忆 → 知识库回答（RAG） → 在线模型降级。支持 PDF 知识库、用户上传文件、系统知识库三种检索源。包含输出规范化（去 Markdown、去重段落）、文档概览/全文输出、高风险内容拦截等特性 |
| `security.py` | 安全工具 | `hash_password()`, `verify_password()`, `issue_access_token()`, `verify_access_token()`, `verify_admin_api_key()`, `FixedWindowRateLimiter` 类 | PBKDF2-SHA256 密码哈希（120000 次迭代，16 字节随机盐）、HMAC-SHA256 JWT 令牌签发/验证、管理员 API Key 验证、固定窗口速率限制器（线程安全） |
| `llm_settings.py` | LLM 配置管理 | `load_llm_config()`, `save_llm_config()`, `clear_llm_config()`, `get_llm_status()`, `build_openai_client()`, `test_llm_connection()`, `diagnose_llm_runtime()` | 从 .env 文件、本地 JSON 配置文件和环境变量三种来源加载配置。支持模型名称、API Key、API 地址、温度、最大 Token 数、超时时间。连接测试支持 models.list() 和 chat.completions 双接口回退 |
| `config.py` | 系统配置 | 全局常量 | 集中管理所有模块的配置参数，从环境变量和 .env 文件加载。包含：数据库（SQLite/MySQL）、Redis、Milvus、LLM、7 种角色定义、应用服务器、认证安全、文件上传、知识同步、检索模式、重排序等配置 |
| `models.py` | 数据模型 | `User`, `Role`, `Conversation`, `Message`, `ChatRequestLog`, `UploadedFile`, `UserDocumentChunk`, `KnowledgeDocument` | SQLAlchemy ORM 模型，支持 SQLite（默认）和 MySQL 两种后端。自动创建数据库（MySQL 下） |
| `prompts.py` | 提示词模板 | `PROMPT_TEMPLATES` 字典 | 定义 7 个角色的 Prompt 模板（lawyer/stock_analyst/teacher/psychological_counselor/doctor/scientist/custom_persona）和 11 条通用回答要求。每个模板包含角色身份、知识库上下文、对话历史和用户问题的格式化占位符 |

### 2.4 数据处理模块

| 文件 | 功能 | 关键类/函数 | 说明 |
|------|------|-------------|------|
| `data_crawler.py` | 种子知识数据 | - | 6 个角色各 5 条内置知识样本 |
| `data_processor.py` | 文本处理 | `DataProcessor` 类 | 文本清洗、中文分词、关键词提取、文本分块 |
| `knowledge_sync.py` | 知识同步 | `KnowledgeSyncManager` 类 | 定时同步知识源到向量库 |
| `knowledge_sync_service.py` | 同步服务 | `sync_knowledge_documents()` | 知识同步的业务逻辑 |
| `knowledge_sources.py` | 知识源管理 | - | 知识源目录和文件管理 |
| `vector_store.py` | 向量存储 | `MilvusStore` 类 | Milvus 向量数据库操作，支持稠密/词项重合词法/BM25/混合检索（RRF 融合 + 重排序），自动降级到本地 SQLite + 内存向量检索 |

### 2.5 工具模块

| 文件 | 功能 | 说明 |
|------|------|------|
| `console_utils.py` | 控制台编码 | Windows UTF-8 编码配置 |
| `logging_utils.py` | 日志工具 | 日志配置和获取 |
| `redis_memory.py` | Redis 记忆 | 会话短期记忆存储 |
| `ocr_worker.py` | OCR 处理 | 图片文字识别（子进程） |
| `rerank_worker.py` | 重排序 | 检索结果重排序（子进程） |
| `file_service.py` | 文件服务 | `UserFileService` 类：文件上传/解析/分块/向量化同步。支持 PDF（多模态/布局/基础）、DOCX、XLSX、CSV、JSON、TXT、MD、图片（OCR）等多种格式 |

## 三、数据流详细说明

### 3.1 聊天请求完整流程

```
用户 → POST /api/chat → conversations.py
  → chat_bot.chat()
    ├── 1. 验证会话所有权 (get_owned_conversation)
    ├── 2. 请求去重检查 (client_request_id)
    ├── 3. 获取对话历史 (Redis 短期记忆)
    ├── 4. 自动生成会话标题 (去除开场白短语)
    ├── 5. 调用 RAGChain.generate_response()
    │   ├── 5a. 尝试社交开场白 (打招呼/咨询开场)
    │   ├── 5b. 尝试轻量聊天 (谢谢/你是谁/在吗)
    │   ├── 5c. 尝试短期记忆 (我叫什么/你还记得我吗)
    │   ├── 5d. 知识库回答 (RAG 检索 + LLM 生成)
    │   │   ├── 构建检索查询 (含历史上下文)
    │   │   ├── 检索 PDF 知识库 (Milvus/本地)
    │   │   ├── 检索用户上传文件 (Milvus/本地)
    │   │   ├── 检索系统知识库 (Milvus/本地)
    │   │   ├── 合并上下文 (RRF 融合 + 重排序)
    │   │   ├── 构建 Prompt (角色身份 + 历史 + 上下文)
    │   │   └── 调用 LLM (OpenAI 兼容 API)
    │   └── 5e. 在线模型降级 (LLM 不可用时)
    ├── 6. 保存消息对到 SQLite
    ├── 7. 更新请求日志状态
    └── 8. 返回 {reply, meta}
```

### 3.2 知识同步流程

```
定时调度 / 手动触发
  → knowledge_sync_manager.run_once()
    ├── 1. 扫描 knowledge_sources/ 目录
    ├── 2. 读取 PDF/JSON 文件
    ├── 3. DataProcessor 处理（清洗、分块）
    ├── 4. 写入 Milvus 向量库 (insert_documents)
    ├── 5. 写入 SQLite 数据库 (KnowledgeDocument)
    └── 6. 生成知识 PDF (roleplay_knowledge_base.pdf)
```

### 3.3 文件上传流程

```
用户 → POST /api/files/upload → files.py
  → chat_bot.upload_conversation_file()
    → UserFileService.upload_file()
      ├── 1. 验证文件类型和大小
      ├── 2. 保存文件到磁盘 (UUID 文件名)
      ├── 3. 解析文件内容 (PDF/DOCX/XLSX/CSV/JSON/TXT/MD/图片)
      │   ├── PDF: 多模态解析 → 布局解析 → 基础文本提取
      │   ├── 图片: OCR 子进程解析
      │   └── 其他: 直接文本提取
      ├── 4. 文本分块 (重叠分块)
      ├── 5. 保存分块到 SQLite (UserDocumentChunk)
      ├── 6. 同步分块到 Milvus (insert_user_document_chunks)
      └── 7. 返回文件信息
```

### 3.4 检索模式选择流程

```
MilvusStore._public_search_by_mode()
  ├── 模式 = "auto": 执行所有对比模式，自动选择最佳
  ├── 模式 = "compare": 执行所有对比模式，记录结果
  ├── 模式 = "dense": 稠密向量检索 (Milvus → 本地 embedding)
  ├── 模式 = "sparse": 词项重合词法检索（为兼容旧接口保留 sparse 命名）
  ├── 模式 = "bm25": BM25 词法检索
  ├── 模式 = "hybrid": 三路召回 + RRF 融合
  └── 模式 = "hybrid_rerank": 三路召回 + RRF 融合 + 重排序
```

## 四、配置说明

| 配置项 | 文件 | 环境变量 | 默认值 | 说明 |
|--------|------|----------|--------|------|
| 应用端口 | `config.py` | `APP_PORT` | 8000 | 服务器监听端口 |
| 数据库后端 | `config.py` | `DATABASE_BACKEND` | sqlite | sqlite/mysql |
| Milvus 启用 | `config.py` | `ENABLE_MILVUS` | False | 是否启用 Milvus 向量库 |
| 检索模式 | `config.py` | `RETRIEVAL_MODE` | hybrid_rerank | dense/sparse/bm25/hybrid/hybrid_rerank/auto |
| 重排序启用 | `config.py` | `ENABLE_RERANK` | True | 是否启用 BGE-Reranker |
| LLM 模型 | `config.py` | `LLM_MODEL` | gpt-4o-mini | 模型名称 |
| LLM API 地址 | `config.py` | `OPENAI_API_BASE` | https://api.openai.com/v1 | API 基础地址 |
| JWT 密钥 | `config.py` | `AUTH_SECRET_KEY` | 自动生成 | JWT 签名密钥 |
| Token 过期 | `config.py` | `AUTH_TOKEN_EXPIRE_HOURS` | 168 | Token 过期时间（小时） |
| 管理员 Key | `config.py` | `ADMIN_API_KEY` | 空 | 管理员 API Key |
| 知识同步间隔 | `config.py` | `KNOWLEDGE_SYNC_INTERVAL_MINUTES` | 10080 | 同步间隔（分钟，默认 7 天） |
| 上传文件大小 | `config.py` | `UPLOAD_MAX_FILE_SIZE` | 20MB | 最大文件大小 |
| 分块大小 | `config.py` | `PUBLIC_KNOWLEDGE_CHUNK_SIZE` | 900 | 知识分块大小（字符数） |

## 五、角色定义

| 角色类型 | 角色名称 | 描述 | 关键词 |
|----------|----------|------|--------|
| `lawyer` | 王律师 | 资深法律顾问，精通民商法、刑法 | 合同、劳动、仲裁、诉讼、证据 |
| `stock_analyst` | 张分析师 | 证券投资专家，技术+基本面分析 | 财报、利润、营收、现金流、估值 |
| `teacher` | 李老师 | 资深教师，各学科知识讲解 | 学生、考试、复习、作业、课程 |
| `psychological_counselor` | 心理咨询师 | 情绪疏导、压力管理、睡眠支持 | 焦虑、抑郁、情绪、失眠、压力 |
| `doctor` | 陈医生 | 常见症状判断、就医建议、健康指导 | 发热、咳嗽、血压、血糖、症状 |
| `scientist` | 周科学家 | 科研思维、实验设计、论文阅读 | 实验、假设、变量、对照、数据 |
| `custom_persona` | 全能型人格 | 灵活回答，不依赖固定角色知识库 | - |

## 六、数据库模型关系

```
User (1) ──── (N) Conversation (N) ──── (1) Role
                      │
                      ├── (N) Message
                      ├── (N) ChatRequestLog
                      └── (N) UploadedFile ──── (N) UserDocumentChunk

KnowledgeDocument (独立表，系统知识库)
```

## 七、安全机制

| 机制 | 实现 | 说明 |
|------|------|------|
| 密码哈希 | PBKDF2-SHA256 | 120000 次迭代，16 字节随机盐，常量时间比较 |
| JWT 令牌 | HMAC-SHA256 | 包含 sub/username/iat/exp/type，自动回退密钥 |
| 管理员认证 | API Key | X-Admin-Key 请求头，常量时间比较 |
| 速率限制 | 固定窗口 | 6 个独立限流器（登录/注册/聊天/聊天IP/上传/分析），线程安全 |
| 请求去重 | client_request_id | 防止重复提交，缓存已完成回复 |
| 高风险拦截 | 关键词匹配 | 阻止直接返回武器/毒品等高风险内容 |

## 八、RAG 回答模式优先级

```
1. 社交开场白 (social_opening)
   - 匹配：打招呼、咨询开场
   - 特点：角色化回复，不调用 LLM

2. 轻量聊天 (lightweight_chat)
   - 匹配：谢谢、你是谁、在吗、好的
   - 特点：短回复，不调用 LLM

3. 短期记忆 (short_term_memory)
   - 匹配：我叫什么、你还记得我吗、我刚才说了什么
   - 特点：从对话历史提取信息，不调用 LLM

4. 知识库回答 (local_knowledge / uploaded_file_analysis)
   - 匹配：有实质内容的咨询问题
   - 特点：RAG 检索 + LLM 生成，支持多源上下文

5. 在线模型降级 (online_model)
   - 匹配：知识库未命中
   - 特点：使用通用知识回答，添加安全提示
```

## 九、JMeter 性能测试报告分析

### 9.1 报告文件
- **位置**: `components/jmeter/reports/jmeter_smoke_report/statistics.json`
- **分析文件**: `components/jmeter/reports/jmeter_smoke_report_analysis.json`

### 9.2 测试结果摘要

| 接口 | 样本数 | 错误率 | 平均响应时间 | 吞吐量 | 分析 |
|------|--------|--------|-------------|--------|------|
| Create User | 1 | 0% | 73 ms | 13.7 req/s | 响应极快，性能优秀 |
| Create Conversation | 1 | 0% | 15 ms | 66.7 req/s | 响应极快，性能极佳 |
| Chat | 1 | 0% | 17,708 ms | 0.056 req/s | 响应慢（LLM 调用固有延迟） |

### 9.3 结论与建议

1. **非 LLM 接口性能优秀**：Create User 和 Create Conversation 响应时间 < 100ms
2. **Chat 接口是瓶颈**：17.7 秒响应时间，主要受 LLM 推理速度限制
3. **样本量不足**：每个接口仅 1 个样本，建议增加至 10-50 次
4. **建议优化**：
   - 启用流式响应（SSE）改善用户体验
   - 使用更快的 LLM 模型
   - 增加并发测试场景

## 十、关键设计决策

### 10.1 为什么使用子进程运行 OCR 和 Reranker？
- **问题**：protobuf 库与 Milvus 的 pymilvus 存在版本冲突
- **解决方案**：使用 `subprocess.run()` 在独立进程中运行 OCR worker 和 Rerank worker
- **文件**：`ocr_worker.py`, `rerank_worker.py`

### 10.2 为什么 Milvus 不可用时自动降级？
- **问题**：Milvus 是可选依赖，不是所有部署环境都有 Milvus 服务
- **解决方案**：当 Milvus 连接失败时，自动降级到 SQLite + 内存向量检索（本地 embedding 相似度计算）
- **文件**：`vector_store.py` 中的 `_search_public_from_db_embeddings()` 和 `_search_user_document_chunks_from_db_embeddings()`

### 10.3 为什么使用 RRF 融合多路召回？
- **问题**：单一检索模式（如仅稠密向量）可能遗漏重要结果
- **解决方案**：并行执行 dense/sparse/bm25 三路召回，使用 RRF（Reciprocal Rank Fusion）算法融合排序
- **文件**：`vector_store.py` 中的 `_merge_hits()` 方法

### 10.4 为什么 LLM 配置支持多源加载？
- **问题**：不同部署环境需要不同的配置管理方式
- **解决方案**：支持三种配置来源，优先级：环境变量 > 本地 JSON 配置文件 > 默认值
- **文件**：`llm_settings.py` 中的 `load_llm_config()` 方法

### 10.5 为什么聊天请求需要去重？
- **问题**：前端网络波动可能导致重复提交聊天请求
- **解决方案**：使用 `client_request_id` 进行请求去重，已完成的请求直接返回缓存回复
- **文件**：`chat_bot.py` 中的 `_get_request_log()` 和 `_create_request_log()` 方法
