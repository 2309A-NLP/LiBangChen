# 部署文档

## 1. 适用范围

本文档用于部署当前仓库中的 PDF RAG 问答系统。系统包含以下组件：

- FastAPI 应用服务
- 本地静态前端页面 `/` 与知识库页面 `/kb`
- 可选的 Milvus 向量检索
- 可选的 Redis 会话存储
- 外部兼容 OpenAI 的大模型接口

当前仓库自带 `milvus/docker-compose.milvus.v2.6.17.yml`，适合单机或测试环境快速部署。应用本身通过 Python 直接启动。

## 2. 部署模式

建议按实际场景选择两种模式之一：

### 模式 A：最小可用部署

适用于快速验收、内网测试、不依赖向量检索的场景。

- `RETRIEVER_TYPE=keyword`
- `RERANKER_ENABLED=false`
- 不需要 Milvus
- 不需要本地 embedding / reranker 模型

### 模式 B：推荐部署

适用于正式联调或效果优先的场景。

- `RETRIEVER_TYPE=hybrid_rrf`
- 启动 Milvus
- 配置本地 embedding 模型目录
- 可选开启 reranker

## 3. 环境要求

### 基础软件

- Python 3.10 或 3.11
- pip
- Docker Desktop 或 Docker Engine + Docker Compose

### Python 依赖

项目依赖定义在 `requirements.txt`，核心包括：

- `fastapi`
- `uvicorn`
- `pydantic-settings`
- `pypdf`
- `redis`
- `pymilvus`
- `sentence-transformers`
- `transformers`
- `torch`

说明：

- 如果使用模式 A，虽然 `requirements.txt` 仍会安装向量相关依赖，但运行时可以不启用 Milvus。
- 如果服务器不能稳定安装 `torch` / `sentence-transformers`，建议先做模式 A 验证，再扩展到模式 B。

## 4. 目录约定

部署时需要关注以下目录：

- `app/`：应用代码
- `app/static/`：前端页面
- `data/source/`：原始 PDF 存放目录
- `data/processed/`：处理结果、反馈、状态文件
- `milvus/`：Milvus Docker Compose 与持久化目录
- `.env`：运行配置

建议将以下目录纳入持久化或备份范围：

- `data/source/`
- `data/processed/`
- `milvus/volumes/`（仅模式 B）

## 5. 配置说明

### 5.1 复制环境变量模板

在项目根目录执行：

```powershell
Copy-Item .env.example .env
```

Linux/macOS 可使用：

```bash
cp .env.example .env
```

### 5.2 必改配置

至少确认以下变量：

```env
APP_ENV=production
LLM_PROVIDER=openai_compatible
LLM_API_KEY=你的密钥
LLM_BASE_URL=你的兼容 OpenAI 接口地址
LLM_MODEL=你的模型名
```

如果不需要在线 Query Understanding，建议改为：

```env
QUERY_UNDERSTANDING_MODE=rules
```

### 5.3 最小可用配置示例

不依赖 Milvus，本地最快启动：

```env
APP_ENV=production

LLM_PROVIDER=openai_compatible
LLM_API_KEY=your_api_key
LLM_BASE_URL=https://your-llm-endpoint/v1
LLM_MODEL=your-model

QUERY_UNDERSTANDING_MODE=rules
RETRIEVER_TYPE=keyword
RERANKER_ENABLED=false
SESSION_STORE_BACKEND=memory
```

### 5.4 推荐配置示例

启用混合检索：

```env
APP_ENV=production

LLM_PROVIDER=openai_compatible
LLM_API_KEY=your_api_key
LLM_BASE_URL=https://your-llm-endpoint/v1
LLM_MODEL=your-model

QUERY_UNDERSTANDING_MODE=online
QUERY_UNDERSTANDING_API_KEY=your_api_key
QUERY_UNDERSTANDING_BASE_URL=https://your-llm-endpoint/v1
QUERY_UNDERSTANDING_MODEL=your-model
QUERY_UNDERSTANDING_FALLBACK_ENABLED=true
QUERY_UNDERSTANDING_LOCAL_FIRST_ENABLED=true

RETRIEVER_TYPE=hybrid_rrf
EMBEDDING_PROVIDER=sentence_transformers
EMBEDDING_MODEL_NAME=/opt/models/bge-m3

RERANKER_ENABLED=true
RERANKER_MODEL_PATH=/opt/models/bge-reranker-base
RERANKER_DEVICE=cpu

MILVUS_HOST=127.0.0.1
MILVUS_PORT=19530

SESSION_STORE_BACKEND=memory
```

### 5.5 模型路径说明

仓库中的默认模型路径是开发机本地路径，部署时必须替换：

- `EMBEDDING_MODEL_NAME`
- `RERANKER_MODEL_PATH`

如果服务器上没有这些模型：

- 将 `RETRIEVER_TYPE` 改为 `keyword`
- 将 `RERANKER_ENABLED` 改为 `false`

### 5.6 Redis 说明

Redis 不是必需组件。

- `SESSION_STORE_BACKEND=memory`：单机可用
- `SESSION_STORE_BACKEND=redis`：多实例或需要持久会话时使用

若配置 Redis 但 Redis 不可用，代码会回退到内存存储。

## 6. 部署步骤

### 6.1 安装 Python 依赖

```bash
pip install -r requirements.txt
```

### 6.2 启动 Milvus（仅模式 B）

在项目根目录执行：

```bash
docker compose -f milvus/docker-compose.milvus.v2.6.17.yml up -d
```

验证容器状态：

```bash
docker compose -f milvus/docker-compose.milvus.v2.6.17.yml ps
```

预期至少包含以下服务：

- `milvus-etcd`
- `milvus-minio`
- `milvus-standalone`
- `milvus-attu`

说明：

- 应用默认连接 `127.0.0.1:19530`
- Attu 管理界面默认映射到 `http://127.0.0.1:8001`

### 6.3 准备 PDF 目录

确保目录存在：

- `data/source/`
- `data/processed/`

如果需要预置知识库，可直接将 PDF 放入 `data/source/`，服务启动后会在后台自动加载。

### 6.4 启动应用

#### 开发启动方式

仓库中的 `run.py` 使用：

- `host=127.0.0.1`
- `port=8000`
- `reload=True`

这适合本地开发，不建议直接用于生产。

#### 生产启动方式

建议直接使用 uvicorn：

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

如果需要后台常驻，请使用进程管理器托管，不要依赖交互式终端。

## 7. 进程托管

### 7.1 Linux systemd 示例

可在 `/etc/systemd/system/rag-qna.service` 中配置：

```ini
[Unit]
Description=RAG Q&A API
After=network.target

[Service]
WorkingDirectory=/opt/rag-qna
EnvironmentFile=/opt/rag-qna/.env
ExecStart=/usr/bin/env uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5
User=www-data

[Install]
WantedBy=multi-user.target
```

生效命令：

```bash
sudo systemctl daemon-reload
sudo systemctl enable rag-qna
sudo systemctl start rag-qna
sudo systemctl status rag-qna
```

### 7.2 Windows 服务化建议

Windows 服务器建议使用以下任一方式托管：

- NSSM
- WinSW
- 企业内部现有进程托管工具

启动命令建议使用：

```powershell
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

不要使用 `python run.py` 作为长期服务进程。

## 8. 反向代理建议

如果需要对外提供服务，建议在应用前增加 Nginx 或企业网关，并处理：

- HTTPS 证书
- 域名访问
- 访问日志
- 请求大小限制
- 超时控制

本系统包含文件上传接口，反向代理需要放宽上传限制。

Nginx 至少需要关注：

- `client_max_body_size`
- `proxy_read_timeout`
- `proxy_send_timeout`

## 9. 验收检查

### 9.1 健康检查

```bash
curl http://127.0.0.1:8000/api/health
```

预期返回类似：

```json
{
  "status": "ok",
  "environment": "production",
  "llm_provider": "openai_compatible",
  "query_understanding_mode": "rules"
}
```

### 9.2 页面检查

访问以下地址：

- `http://127.0.0.1:8000/`
- `http://127.0.0.1:8000/kb`
- `http://127.0.0.1:8000/docs`

### 9.3 预热状态检查

```bash
curl http://127.0.0.1:8000/api/document/warmup
```

如果服务刚启动，状态可能经历：

- `idle`
- `running`
- `ready`

若返回 `warmup_failed`，优先检查：

- Milvus 是否可连接
- embedding 模型路径是否正确
- reranker 模型路径是否正确

### 9.4 文档状态检查

```bash
curl http://127.0.0.1:8000/api/document/status
```

确认：

- 文档数量正常
- 分块数量正常
- 当前选中文档范围符合预期

## 10. 常见运维操作

### 10.1 重新加载全部文档

```bash
curl -X POST http://127.0.0.1:8000/api/document/reload
```

### 10.2 查看知识库文档列表

```bash
curl http://127.0.0.1:8000/api/kb/documents
```

### 10.3 删除指定文档

```bash
curl -X DELETE http://127.0.0.1:8000/api/kb/documents/<source_id>
```

### 10.4 上传 PDF

```bash
curl -X POST http://127.0.0.1:8000/api/document/upload \
  -F "files=@/path/to/file.pdf"
```

## 11. 故障排查

### 11.1 服务可启动但无法问答

重点检查：

- `LLM_API_KEY` 是否有效
- `LLM_BASE_URL` 是否正确
- `LLM_MODEL` 是否存在

### 11.2 启动后预热失败

重点检查：

- `RETRIEVER_TYPE` 是否依赖 Milvus
- `MILVUS_HOST` / `MILVUS_PORT` 是否可达
- `EMBEDDING_MODEL_NAME` 是否为真实可访问目录
- `RERANKER_MODEL_PATH` 是否为真实可访问目录

### 11.3 仅需先恢复可用性

如果线上先要求服务可用，再逐步恢复向量能力，可临时切换为：

```env
QUERY_UNDERSTANDING_MODE=rules
RETRIEVER_TYPE=keyword
RERANKER_ENABLED=false
SESSION_STORE_BACKEND=memory
```

这样可以绕开：

- Milvus 故障
- embedding 模型缺失
- reranker 模型缺失
- Redis 故障

### 11.4 上传失败

重点检查：

- 反向代理上传大小限制
- PDF 文件是否损坏
- 服务是否连接到了旧进程

## 12. 上线建议

正式上线前建议完成以下检查：

1. `.env` 中不再保留开发机本地绝对路径。
2. `APP_ENV` 已切换为 `production`。
3. 生产环境不再使用 `python run.py`。
4. 反向代理已放开 PDF 上传大小限制。
5. 至少完成一次 `/api/health`、`/api/document/status`、`/api/document/warmup` 验证。
6. 已明确当前采用模式 A 还是模式 B，并与实际依赖保持一致。

