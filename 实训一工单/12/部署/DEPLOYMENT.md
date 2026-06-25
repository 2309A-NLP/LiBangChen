# RAG-Q&A 系统部署文档

本文档用于在 Windows 环境中部署、启动和验收当前项目。

项目根目录示例：

```powershell
C:\Users\26332\Desktop\工单\RAG工单\RAG-Q&A system12
```

## 1. 部署模式

| 模式 | 适用场景 | 外部依赖 | 推荐配置 |
|---|---|---|---|
| 最小部署 | 快速启动、PDF 上传解析、全文检索问答 | 仅 Python 和 LLM 服务 | `RETRIEVER_TYPE=fulltext`，`RERANKER_ENABLED=false` |
| 混合检索部署 | 全文检索 + 向量检索，召回效果更完整 | Python、LLM、Milvus、Embedding 模型 | `RETRIEVER_TYPE=hybrid` |
| LightRAG 图谱部署 | 股权、关联方、任职关系等图谱类问题 | Python、LLM、LightRAG sidecar | 请求时使用 `retrieval_mode=lightrag_mix` 等模式 |

建议首次部署先使用“最小部署”。确认 API、页面、上传和问答流程正常后，再接入 Milvus 或 LightRAG。

## 2. 环境要求

- Windows 10/11
- PowerShell
- Python 3.10+
- 可用的 OpenAI-compatible LLM 服务
- 可选：Milvus 服务，用于 `vector` / `hybrid` 检索
- 可选：本地 embedding/reranker 模型，用于向量检索和交叉编码重排
- 可选：LightRAG 服务，用于图谱检索

当前项目推荐解释器示例：

```powershell
D:\Anaconda\envs\python_3_10\python.exe
```

如果使用系统 Python，也可以把以下命令中的解释器路径替换为 `python`。

## 3. 安装依赖

进入项目根目录：

```powershell
cd "C:\Users\26332\Desktop\工单\RAG工单\RAG-Q&A system12"
```

安装 Python 依赖：

```powershell
D:\Anaconda\envs\python_3_10\python.exe -m pip install -r requirements.txt
```

主要依赖包括：

- FastAPI / Uvicorn：API 服务
- pydantic / pydantic-settings：配置加载
- pypdf / pypdfium2 / pillow：PDF 解析
- httpx：LLM 和 sidecar HTTP 调用
- pymilvus：Milvus 向量检索
- sentence-transformers / transformers / torch：本地 embedding 和 reranker

## 4. 配置 `.env`

如果根目录没有 `.env`，先复制模板：

```powershell
Copy-Item .env.example .env
```

### 4.1 最小部署配置

适合快速启动和普通全文检索，不依赖 Milvus 和本地 reranker：

```env
APP_ENV=development

LLM_PROVIDER=openai_compatible
LLM_API_KEY=你的APIKey
LLM_BASE_URL=https://你的模型服务/v1
LLM_MODEL=你的模型名称
LLM_TIMEOUT_SECONDS=60
LLM_TEMPERATURE=0.2

QUERY_UNDERSTANDING_MODE=rules

RETRIEVER_TYPE=fulltext
RERANKER_ENABLED=false

SOURCE_PDF_DIR=data/source
DOCUMENT_CACHE_PATH=data/processed/document_cache.json
FEEDBACK_STORE_PATH=data/processed/feedback.jsonl
SESSION_STORE_BACKEND=memory
```

### 4.2 混合检索配置

如需启用向量检索或混合检索，需要先保证 Milvus 可访问，并准备 embedding 模型：

```env
RETRIEVER_TYPE=hybrid
HYBRID_TEXT_RETRIEVER=fulltext
HYBRID_FUSION_STRATEGY=rrf
HYBRID_FULLTEXT_WEIGHT=0.45
HYBRID_VECTOR_WEIGHT=0.55

EMBEDDING_PROVIDER=sentence_transformers
EMBEDDING_MODEL_NAME=C:\Users\26332\.cache\modelscope\hub\models\BAAI\bge-m3
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
RERANKER_TYPES=cross_encoder
RERANKER_MODEL_PATH=C:\Users\26332\.cache\modelscope\hub\models\BAAI\bge-reranker-base\bge-reranker-base\bge-reranker-base
RERANKER_DEVICE=cpu
RERANKER_TOP_N=8
```

支持的检索模式：

| 模式 | 说明 |
|---|---|
| `keyword` | 关键词检索 |
| `fulltext` | 内置全文检索，不依赖 Milvus |
| `vector` / `milvus` | Milvus 向量检索 |
| `hybrid` | 全文检索 + Milvus 向量检索 |
| `lightrag_mix` | LightRAG local + global 图谱检索 |
| `lightrag_local` | LightRAG 局部实体邻域检索 |
| `lightrag_global` | LightRAG 全局图谱检索 |
| `lightrag_hybrid` | LightRAG 混合图谱检索 |

### 4.3 LightRAG 配置

LightRAG 是可选 sidecar。主服务即使连接不上 LightRAG，也不影响 `fulltext` / `hybrid` 等标准检索模式。

主项目 `.env` 中保留以下配置：

```env
LIGHTRAG_BASE_URL=http://localhost:9621
LIGHTRAG_WORKING_DIR=./data/lightrag
LIGHTRAG_EMBEDDING_MODEL_PATH=BAAI/bge-m3
LIGHTRAG_DEFAULT_MODE=mix
LIGHTRAG_TIMEOUT=300
LIGHTRAG_TOP_K=20
LIGHTRAG_MIN_SCORE=0.3
LIGHTRAG_MAX_PARALLEL_INSERT=4
LIGHTRAG_INSERT_RETRY=3
```

如果需要启动 LightRAG sidecar，确认 `data/lightrag/.env` 已配置好 LightRAG 所需模型参数，然后运行：

```powershell
D:\Anaconda\envs\python_3_10\python.exe start_lightrag.py
```

如需本地 OpenAI-compatible embedding server，可单独启动：

```powershell
D:\Anaconda\envs\python_3_10\python.exe scripts\embedding_server.py --port 9622
```

更多 LightRAG 说明见 `docs/LIGHTRAG_INTEGRATION.md`。

## 5. 准备 PDF 文档

默认 PDF 目录：

```text
data/source/
```

部署前可以直接把 PDF 放入该目录，也可以启动服务后通过首页上传。系统启动后会后台加载文档并预热检索器。

相关数据文件：

| 路径 | 说明 |
|---|---|
| `data/source/` | 原始 PDF 文件 |
| `data/processed/document_cache.json` | PDF 解析缓存 |
| `data/processed/feedback.jsonl` | 用户反馈记录 |
| `data/processed/milvus_state.json` | Milvus 索引状态 |
| `data/lightrag/` | LightRAG 工作目录 |

更换大量 PDF 后，建议调用 reload 接口或删除缓存后重启服务。

## 6. 启动应用

`run.py` 默认监听：

- Host：`127.0.0.1`
- Port：`8000`

建议显式指定端口：

```powershell
$env:HOST="127.0.0.1"
$env:PORT="8010"
$env:RELOAD="false"
D:\Anaconda\envs\python_3_10\python.exe run.py
```

如果指定端口被占用，`run.py` 会从该端口开始向后查找可用端口，并在控制台打印实际启动地址。

后台启动示例：

```powershell
New-Item -ItemType Directory -Force logs

$env:HOST="127.0.0.1"
$env:PORT="8010"
$p = Start-Process `
  -FilePath "D:\Anaconda\envs\python_3_10\python.exe" `
  -ArgumentList "run.py" `
  -WorkingDirectory "C:\Users\26332\Desktop\工单\RAG工单\RAG-Q&A system12" `
  -WindowStyle Hidden `
  -RedirectStandardOutput ".\logs\rag-api.out.log" `
  -RedirectStandardError ".\logs\rag-api.err.log" `
  -PassThru

$p.Id | Set-Content .rag-api.pid
```

停止后台服务：

```powershell
$servicePid = Get-Content .rag-api.pid
Stop-Process -Id $servicePid -Force
```

## 7. 访问地址

假设服务启动在 `8010` 端口：

| 页面/接口 | 地址 |
|---|---|
| 首页 | `http://127.0.0.1:8010/` |
| 知识库管理 | `http://127.0.0.1:8010/kb` |
| Swagger API | `http://127.0.0.1:8010/docs` |
| 健康检查 | `http://127.0.0.1:8010/api/health` |
| 文档状态 | `http://127.0.0.1:8010/api/document/status` |
| 预热状态 | `http://127.0.0.1:8010/api/document/warmup` |

健康检查：

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:8010/api/health
```

文档状态：

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:8010/api/document/status
```

重新加载文档：

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:8010/api/document/reload -Method Post
```

## 8. API 调用示例

### 8.1 同步问答

```powershell
$body = @{
  question = "公司实际控制人是谁？"
  retrieval_mode = "fulltext"
  top_k = 8
  include_debug = $true
  reranker_enabled = $false
} | ConvertTo-Json -Depth 6

Invoke-RestMethod `
  -Uri http://127.0.0.1:8010/api/query `
  -Method Post `
  -ContentType "application/json" `
  -Body $body
```

### 8.2 指定文档范围问答

```powershell
$body = @{
  question = "该公司的主营业务是什么？"
  source_files = @("招股说明书1-无水印.pdf")
  retrieval_mode = "fulltext"
  top_k = 8
  include_debug = $true
} | ConvertTo-Json -Depth 6

Invoke-RestMethod `
  -Uri http://127.0.0.1:8010/api/query `
  -Method Post `
  -ContentType "application/json" `
  -Body $body
```

### 8.3 流式问答

```powershell
Invoke-WebRequest `
  -Uri http://127.0.0.1:8010/api/query/stream `
  -Method Post `
  -ContentType "application/json" `
  -Body $body
```

### 8.4 上传 PDF

```powershell
Invoke-RestMethod `
  -Uri http://127.0.0.1:8010/api/document/upload `
  -Method Post `
  -Form @{ files = Get-Item ".\data\source\招股说明书1-无水印.pdf" }
```

### 8.5 查询知识库文档

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:8010/api/kb/documents
```

## 9. 验收清单

部署完成后按顺序检查：

1. `GET /api/health` 返回 `status=ok`
2. `GET /api/document/status` 中 `document_loaded=true`
3. `chunk_count` 大于 0
4. `GET /api/document/warmup` 最终返回 `status=ready`
5. 首页 `http://127.0.0.1:8010/` 可以打开
6. 可以上传 PDF，上传后文档状态变为处理中并最终 ready
7. 可以在首页或 `POST /api/query` 提问
8. 问答响应中包含 `answer` 和 `citations`
9. 知识库页面 `http://127.0.0.1:8010/kb` 可以查看文档列表
10. 如果使用 `hybrid` / `vector`，确认 Milvus `19530` 端口可访问
11. 如果使用 `lightrag_*`，确认 LightRAG `9621` 端口可访问

## 10. 测试

运行核心测试：

```powershell
pytest tests\test_api_routes.py -q
pytest tests\test_document_ingestion.py -q
pytest tests\test_query_understanding.py -q
pytest tests\test_retriever.py -q
```

如需一次运行全部测试：

```powershell
pytest
```

## 11. RAGAS 评估

进程内采样，不需要启动 API 服务：

```powershell
D:\Anaconda\envs\python_3_10\python.exe scripts\collect_ragas_samples_inprocess.py `
  --questions "问题集路径.json" `
  --output-dir .tmp\ragas_eval `
  --retrieval-mode fulltext `
  --top-k 8
```

运行 RAGAS 指标：

```powershell
D:\Anaconda\envs\python_3_10\python.exe scripts\run_ragas_eval.py `
  --questions "问题集路径.json" `
  --samples .tmp\ragas_eval\ragas_eval_samples.json `
  --output-dir .tmp\ragas_eval `
  --metric-set llm-only
```

输出文件：

```text
.tmp/ragas_eval/ragas_eval_samples.json
.tmp/ragas_eval/ragas_eval_scores.json
.tmp/ragas_eval/ragas_eval_scores.csv
```

## 12. 常见问题

### 12.1 API 无法访问

检查端口和进程：

```powershell
netstat -ano | findstr :8010
Get-Content .\logs\rag-api.err.log
```

如果 `8010` 被占用，可以改用其他端口：

```powershell
$env:PORT="8020"
D:\Anaconda\envs\python_3_10\python.exe run.py
```

### 12.2 启动时报 Milvus 连接失败

仅 `vector`、`milvus`、`hybrid` 模式需要 Milvus。先确认：

```powershell
netstat -ano | findstr :19530
```

如果暂时不需要向量检索，改成最小部署：

```env
RETRIEVER_TYPE=fulltext
RERANKER_ENABLED=false
```

### 12.3 首次启动慢

首次启动会解析 PDF、构建文档缓存、预热检索器。如果启用了 `hybrid` 或 `cross_encoder`，还会加载本地模型。

查看状态：

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:8010/api/document/status
Invoke-RestMethod -Uri http://127.0.0.1:8010/api/document/warmup
```

### 12.4 LLM 超时

提高超时时间：

```env
LLM_TIMEOUT_SECONDS=60
QUERY_UNDERSTANDING_TIMEOUT_SECONDS=30
```

同时确认 `LLM_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL` 可用。

### 12.5 LightRAG 不可用

如果请求 `retrieval_mode=lightrag_mix` 等模式时报错，先检查 sidecar：

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:9621/health
```

如果暂时不使用 LightRAG，将请求中的 `retrieval_mode` 改为：

```json
"fulltext"
```

或：

```json
"hybrid"
```

### 12.6 PDF 上传成功但没有内容

可能原因：

- PDF 是扫描件，页面主要是图片
- PDF 加密或权限受限
- PDF 文本层为空
- PDF 文件损坏

可以先换用可复制文本的 PDF 验证解析链路。

## 13. 推荐启动顺序

### 最小部署

```powershell
cd "C:\Users\26332\Desktop\工单\RAG工单\RAG-Q&A system12"
Copy-Item .env.example .env
# 修改 .env：LLM_*、RETRIEVER_TYPE=fulltext、RERANKER_ENABLED=false
D:\Anaconda\envs\python_3_10\python.exe -m pip install -r requirements.txt
$env:PORT="8010"
D:\Anaconda\envs\python_3_10\python.exe run.py
Invoke-RestMethod -Uri http://127.0.0.1:8010/api/health
```

### 混合检索部署

```powershell
cd "C:\Users\26332\Desktop\工单\RAG工单\RAG-Q&A system12"
# 先启动外部 Milvus，并确认 127.0.0.1:19530 可访问
D:\Anaconda\envs\python_3_10\python.exe -m pip install -r requirements.txt
# 修改 .env：RETRIEVER_TYPE=hybrid，并配置 EMBEDDING_*、MILVUS_*、RERANKER_*
$env:PORT="8010"
D:\Anaconda\envs\python_3_10\python.exe run.py
Invoke-RestMethod -Uri http://127.0.0.1:8010/api/health
Invoke-RestMethod -Uri http://127.0.0.1:8010/api/document/status
```

### LightRAG 部署

```powershell
cd "C:\Users\26332\Desktop\工单\RAG工单\RAG-Q&A system12"
# 先配置 data\lightrag\.env
D:\Anaconda\envs\python_3_10\python.exe scripts\embedding_server.py --port 9622
D:\Anaconda\envs\python_3_10\python.exe start_lightrag.py
```

主服务启动后，请求中使用：

```json
{
  "question": "公司实际控制人是谁？",
  "retrieval_mode": "lightrag_mix",
  "top_k": 8,
  "include_debug": true
}
```
