# RAG-Q&A 系统部署文档

本文档用于在 Windows 环境部署、启动和验收本项目。项目根目录示例：

```powershell
C:\Users\26332\Desktop\工单\RAG工单\RAG-Q&A system7
```

## 1. 部署模式

系统支持两种常用部署模式。

| 模式 | 适用场景 | 是否需要 Milvus | 推荐配置 |
|---|---|---:|---|
| 最小部署 | 快速启动、全文检索、RAGAS 测试 | 否 | `RETRIEVER_TYPE=fulltext`，`RERANKER_ENABLED=false` |
| 完整部署 | 向量检索、混合检索、语义召回 | 是 | `RETRIEVER_TYPE=hybrid` 或 `vector` |

如果只是复现当前 RAGAS 测试，建议先使用最小部署，启动更快、依赖更少。

## 2. 环境要求

- Windows 10/11
- PowerShell
- Python 3.10+
- Docker Desktop，仅完整部署需要
- 可用的 OpenAI-compatible LLM 服务，用于在线回答和 RAGAS 评估
- 本地 embedding/reranker 模型，仅向量检索或重排需要

推荐解释器：

```powershell
D:\Anaconda\envs\python_3_10\python.exe
```

## 3. 安装依赖

进入项目根目录：

```powershell
cd "C:\Users\26332\Desktop\工单\RAG工单\RAG-Q&A system7"
```

安装 Python 依赖：

```powershell
D:\Anaconda\envs\python_3_10\python.exe -m pip install -r requirements.txt
```

主要依赖包括 FastAPI、Uvicorn、Pydantic、pypdf、pymilvus、sentence-transformers、torch 等。

## 4. 配置 `.env`

如果根目录没有 `.env`，先复制模板：

```powershell
Copy-Item .env.example .env
```

### 4.1 最小部署配置

适合全文检索和当前 RAGAS 复测：

```env
APP_ENV=development

LLM_PROVIDER=openai_compatible
LLM_API_KEY=你的模型APIKey
LLM_BASE_URL=https://你的模型服务/v1
LLM_MODEL=你的模型名
LLM_TIMEOUT_SECONDS=60
LLM_TEMPERATURE=0.2

QUERY_UNDERSTANDING_MODE=rules

RETRIEVER_TYPE=fulltext
RERANKER_ENABLED=false

SOURCE_PDF_DIR=data/source
DOCUMENT_CACHE_PATH=data/processed/document_cache.json
```

### 4.2 完整部署配置

如果需要 Milvus 向量检索或混合检索：

```env
RETRIEVER_TYPE=hybrid
HYBRID_TEXT_RETRIEVER=fulltext
HYBRID_FUSION_STRATEGY=rrf

EMBEDDING_PROVIDER=sentence_transformers
EMBEDDING_MODEL_NAME=C:\Users\26332\.cache\modelscope\hub\models\BAAI\bge-m3
EMBEDDING_DEVICE=cpu

MILVUS_HOST=127.0.0.1
MILVUS_PORT=19530
MILVUS_COLLECTION_NAME=rag_qna_chunks

RERANKER_ENABLED=true
RERANKER_TYPES=cross_encoder
RERANKER_MODEL_PATH=C:\Users\26332\.cache\modelscope\hub\models\BAAI\bge-reranker-base\bge-reranker-base\bge-reranker-base
RERANKER_DEVICE=cpu
```

## 5. 准备文档

系统默认读取：

```text
data/source/
```

将 PDF 放入该目录。当前 RAGAS 测试涉及的年报和招股说明书也应放在这里。

文档缓存位于：

```text
data/processed/document_cache.json
```

如果替换了大量 PDF，建议通过接口触发 reload，或删除缓存后重启服务。

## 6. 启动 Milvus

仅完整部署需要执行本节。

启动：

```powershell
docker compose -f .\milvus\docker-compose.milvus.v2.6.17.yml up -d
```

检查：

```powershell
docker ps
netstat -ano | findstr :19530
```

默认端口：

| 服务 | 端口 |
|---|---:|
| Milvus | 19530 |
| Milvus health/metrics | 9091 |
| Attu 管理页面 | 8001 |

停止：

```powershell
docker compose -f .\milvus\docker-compose.milvus.v2.6.17.yml down
```

## 7. 启动应用

`run.py` 默认端口是 `8000`。如果想与前期测试保持一致，建议显式使用 `8010`：

```powershell
$env:HOST="127.0.0.1"
$env:PORT="8010"
$env:RELOAD="false"
D:\Anaconda\envs\python_3_10\python.exe run.py
```

如果端口被占用，`run.py` 会从指定端口开始向后寻找可用端口。

后台启动示例：

```powershell
$env:HOST="127.0.0.1"
$env:PORT="8010"
$p = Start-Process `
  -FilePath "D:\Anaconda\envs\python_3_10\python.exe" `
  -ArgumentList "run.py" `
  -WorkingDirectory "C:\Users\26332\Desktop\工单\RAG工单\RAG-Q&A system7" `
  -WindowStyle Hidden `
  -RedirectStandardOutput ".\logs\rag-api.out.log" `
  -RedirectStandardError ".\logs\rag-api.err.log" `
  -PassThru
$p.Id | Set-Content .rag-api.pid
```

停止后台服务：

```powershell
$pid = Get-Content .rag-api.pid
Stop-Process -Id $pid -Force
```

## 8. 访问地址

假设端口为 `8010`：

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

## 9. API 调用示例

同步问答：

```powershell
$body = @{
  question = "平安银行2019年度报告的审计机构是哪家会计师事务所？"
  source_files = @("2020-02-14__平安银行股份有限公司__000001__平安银行__2019年__年度报告.pdf")
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

流式问答：

```powershell
Invoke-WebRequest `
  -Uri http://127.0.0.1:8010/api/query/stream `
  -Method Post `
  -ContentType "application/json" `
  -Body $body
```

## 10. RAGAS 复测

当前优化后的 RAGAS 结果目录：

```text
.tmp/ragas_eval_optimized/
```

重新采样，不启动 API 服务，直接进程内调用 pipeline：

```powershell
D:\Anaconda\envs\python_3_10\python.exe scripts\collect_ragas_samples_inprocess.py `
  --questions "C:\Users\26332\Desktop\RAG 工单\附件\ccf_competition\ragas_test_questions.json" `
  --output-dir .tmp\ragas_eval_optimized
```

运行 RAGAS LLM-only 指标：

```powershell
D:\Anaconda\envs\python_3_10\python.exe scripts\run_ragas_eval.py `
  --questions "C:\Users\26332\Desktop\RAG 工单\附件\ccf_competition\ragas_test_questions.json" `
  --samples .tmp\ragas_eval_optimized\ragas_eval_samples.json `
  --output-dir .tmp\ragas_eval_optimized `
  --metric-set llm-only
```

输出文件：

```text
.tmp/ragas_eval_optimized/ragas_eval_samples.json
.tmp/ragas_eval_optimized/ragas_eval_scores.json
.tmp/ragas_eval_optimized/ragas_eval_scores.csv
```

说明：

- `llm-only` 指标包含 `faithfulness`、`context_precision`、`context_recall`。
- `answer_correctness` 依赖 embedding。当前环境加载本地 torch embedding 时可能出现 Windows DLL 初始化错误，因此默认不跑 full metric set。

## 11. 验收清单

部署完成后按顺序检查：

1. API 健康检查返回 `status=ok`
2. `/api/document/status` 中 `document_loaded=true`
3. `chunk_count` 大于 0
4. `/api/document/warmup` 返回 `ready`
5. 首页可以打开并提问
6. 指定 `source_files` 时只在对应 PDF 内检索
7. 问答响应中包含 `citations`
8. RAGAS 脚本能生成新的 `scores.json` 和 `scores.csv`

## 12. 常见问题

### 12.1 API 无法访问

检查服务进程和端口：

```powershell
netstat -ano | findstr :8010
Get-Content .\logs\rag-api.err.log
```

### 12.2 Milvus 连接失败

仅 `vector` 或 `hybrid` 模式需要 Milvus。检查：

```powershell
docker ps
netstat -ano | findstr :19530
```

如果只需要全文检索，可改为：

```env
RETRIEVER_TYPE=fulltext
RERANKER_ENABLED=false
```

### 12.3 首次启动慢

首次启动会解析 PDF、构建缓存、预热检索器。可通过以下接口观察：

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

### 12.5 RAGAS full 指标失败

如果 `answer_correctness` 报 torch 或 embedding 加载错误，先使用：

```powershell
--metric-set llm-only
```

待本地 embedding 环境修复后再运行 full metric set。

## 13. 推荐启动顺序

最小部署：

```powershell
cd "C:\Users\26332\Desktop\工单\RAG工单\RAG-Q&A system7"
Copy-Item .env.example .env
# 修改 .env：RETRIEVER_TYPE=fulltext，RERANKER_ENABLED=false
D:\Anaconda\envs\python_3_10\python.exe -m pip install -r requirements.txt
$env:PORT="8010"
D:\Anaconda\envs\python_3_10\python.exe run.py
Invoke-RestMethod -Uri http://127.0.0.1:8010/api/health
```

完整部署：

```powershell
cd "C:\Users\26332\Desktop\工单\RAG工单\RAG-Q&A system7"
D:\Anaconda\envs\python_3_10\python.exe -m pip install -r requirements.txt
docker compose -f .\milvus\docker-compose.milvus.v2.6.17.yml up -d
$env:PORT="8010"
D:\Anaconda\envs\python_3_10\python.exe run.py
Invoke-RestMethod -Uri http://127.0.0.1:8010/api/health
Invoke-RestMethod -Uri http://127.0.0.1:8010/api/document/status
```
