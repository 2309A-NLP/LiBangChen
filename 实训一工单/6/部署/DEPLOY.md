# 部署说明

本文档说明如何在当前 Windows 环境下部署并运行本项目。

## 1. 环境要求

- Windows PowerShell
- Python 3.10 及以上
- Docker Desktop
- 已准备好 `.env` 配置文件

如果项目根目录下没有 `.env`，先复制一份：

```powershell
Copy-Item .env.example .env
```

然后按实际环境修改以下关键项：

```env
LLM_API_KEY=
LLM_BASE_URL=
LLM_MODEL=
QUERY_UNDERSTANDING_API_KEY=
QUERY_UNDERSTANDING_BASE_URL=
QUERY_UNDERSTANDING_MODEL=
EMBEDDING_MODEL_NAME=
RERANKER_MODEL_PATH=
```

## 2. 安装依赖

在项目根目录执行：

```powershell
python -m pip install -r requirements.txt
```

如果你使用指定解释器：

```powershell
D:\Anaconda\envs\python_3_10\python.exe -m pip install -r requirements.txt
```

## 3. 启动 Milvus

项目依赖独立的 Milvus 服务，compose 文件位于：

`milvus/docker-compose.milvus.v2.6.17.yml`

启动命令：

```powershell
docker compose -f .\milvus\docker-compose.milvus.v2.6.17.yml up -d
```

默认会启动以下组件：

- `milvus-etcd`
- `milvus-minio`
- `milvus-standalone`
- `milvus-attu`

Milvus 默认端口：

- `19530`: Milvus 服务
- `9091`: 健康与监控
- `8001`: Attu 管理界面

## 4. 启动应用

在项目根目录执行：

```powershell
python run.py
```

如果需要指定监听地址和端口：

```powershell
$env:HOST="127.0.0.1"
$env:PORT="8010"
$env:RELOAD="false"
python run.py
```

说明：

- 默认地址：`127.0.0.1`
- 默认端口：`8010`
- `run.py` 会自动探测端口占用情况，并在可用范围内顺延启动

## 5. 访问地址

- 首页：`http://127.0.0.1:8010/`
- 知识库管理：`http://127.0.0.1:8010/kb`
- Swagger 文档：`http://127.0.0.1:8010/docs`
- 健康检查：`http://127.0.0.1:8010/api/health`

## 6. 启动后检查

先检查 Milvus 端口：

```powershell
netstat -ano | findstr :19530
```

再检查 API 健康状态：

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:8010/api/health
```

正常返回应包含：

```json
{
  "status": "ok"
}
```

还可以查看文档加载状态：

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:8010/api/document/status
Invoke-RestMethod -Uri http://127.0.0.1:8010/api/document/warmup
```

## 7. 停止服务

停止应用：

- 如果是当前终端前台运行，直接 `Ctrl + C`
- 如果是后台运行，按实际 PID 结束进程

示例：

```powershell
Stop-Process -Id <PID> -Force
```

停止 Milvus：

```powershell
docker compose -f .\milvus\docker-compose.milvus.v2.6.17.yml down
```

## 8. 常见问题

### 8.1 `http://127.0.0.1:8010/api/health` 无法访问

排查顺序：

1. 确认 `python run.py` 进程仍在运行
2. 确认端口未被其他程序占用
3. 确认 `.env` 中模型路径和 API Key 配置有效

### 8.2 问答时报 Milvus 连接错误

通常表示 `127.0.0.1:19530` 不可用。先确认：

```powershell
docker ps
netstat -ano | findstr :19530
```

### 8.3 首次启动较慢

这是正常现象。系统会在启动后后台完成：

- 文档加载
- 检索器预热
- 向量索引准备

可通过以下接口观察预热状态：

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:8010/api/document/warmup
```

## 9. 推荐部署顺序

```powershell
Copy-Item .env.example .env
python -m pip install -r requirements.txt
docker compose -f .\milvus\docker-compose.milvus.v2.6.17.yml up -d
python run.py
Invoke-RestMethod -Uri http://127.0.0.1:8010/api/health
```
