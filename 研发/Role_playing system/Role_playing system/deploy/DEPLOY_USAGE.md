# Deployment Script Usage

## 1. 适用范围

这份文档说明如何使用 `deploy/` 目录下的 PowerShell 脚本来启动和停止项目服务。

当前脚本主要面向 Windows 环境，负责两部分：

- Milvus 向量检索栈
- Roleplay API 服务

---

## 2. 脚本列表

- `deploy-roleplay-system.ps1`
  一键部署入口，按需启动 Milvus 和 API。
- `start-milvus.ps1`
  启动 Milvus Docker Compose 服务。
- `stop-milvus.ps1`
  停止 Milvus Docker Compose 服务。
- `start-roleplay-api.ps1`
  后台启动 API，并写入 PID 与日志。
- `stop-roleplay-api.ps1`
  停止 API 进程并清理 PID 文件。

---

## 3. 前置要求

### 3.1 Docker

如果要启动 Milvus，需要先安装并启动 Docker Desktop。

可先手动确认：

```powershell
docker version
```

### 3.2 Python 环境

API 默认优先使用：

```text
D:\Anaconda\envs\python_3_10\python.exe
```

如果你想改成别的 Python，可以在当前终端先设置：

```powershell
$env:ROLEPLAY_PYTHON="D:\Anaconda\envs\python_3_10\python.exe"
```

### 3.3 `.env`

建议项目根目录存在 `.env` 文件。  
其中 `APP_PORT` 会影响 API 启动后的实际端口。

如果没有配置，默认端口是：

```text
8000
```

---

## 4. 一键部署

在项目根目录执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\deploy\deploy-roleplay-system.ps1
```

这个脚本会：

- 启动 Milvus
- 启动 API
- 检查 `/health`
- 输出最终访问地址

---

## 5. 可选参数

### 5.1 只启动 API

如果 Milvus 已经在运行，可以跳过 Milvus：

```powershell
powershell -ExecutionPolicy Bypass -File .\deploy\deploy-roleplay-system.ps1 -SkipMilvus
```

### 5.2 只启动 Milvus

如果你只想先把向量服务拉起来：

```powershell
powershell -ExecutionPolicy Bypass -File .\deploy\deploy-roleplay-system.ps1 -SkipApi
```

---

## 6. 单独启动脚本

### 6.1 启动 Milvus

```powershell
powershell -ExecutionPolicy Bypass -File .\deploy\start-milvus.ps1
```

启动后常见访问地址：

- Milvus gRPC: `localhost:19530`
- Milvus health: `http://localhost:9091/healthz`
- MinIO console: `http://localhost:9001`
- Attu UI: `http://localhost:8001`

### 6.2 启动 API

```powershell
powershell -ExecutionPolicy Bypass -File .\deploy\start-roleplay-api.ps1
```

API 启动成功后会输出：

- PID
- 本地访问地址
- Health 地址
- 日志路径

---

## 7. 停止服务

### 7.1 停止 API

```powershell
powershell -ExecutionPolicy Bypass -File .\deploy\stop-roleplay-api.ps1
```

### 7.2 停止 Milvus

```powershell
powershell -ExecutionPolicy Bypass -File .\deploy\stop-milvus.ps1
```

---

## 8. 日志与运行状态

API 日志默认在项目根目录的 `logs/` 下：

- `logs/roleplay-api.out.log`
- `logs/roleplay-api.err.log`

API 进程 PID 文件：

- `.roleplay-api.pid`

如果启动失败，可以先看错误日志：

```powershell
Get-Content .\logs\roleplay-api.err.log -Tail 50
```

检查健康状态：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

如果你改过 `APP_PORT`，把上面的 `8000` 换成实际端口。

---

## 9. 常见问题

### 9.1 Docker 未启动

现象：

- `start-milvus.ps1` 报错
- 提示 Docker daemon unavailable

处理：

- 先启动 Docker Desktop
- 等 Docker 完全就绪后再重试

### 9.2 API 端口不通

现象：

- 启动脚本提示 health check 未通过

处理：

1. 查看 `logs/roleplay-api.err.log`
2. 检查 `.env` 中的 `APP_PORT`
3. 检查 Python 解释器是否正确
4. 检查依赖是否已安装

### 9.3 PID 文件残留

现象：

- API 实际没运行，但有 `.roleplay-api.pid`

处理：

- 直接重新运行 `start-roleplay-api.ps1`
- 脚本会自动清理失效 PID

---

## 10. 推荐操作顺序

首次部署建议按这个顺序：

1. 启动 Docker Desktop
2. 打开项目根目录 PowerShell
3. 执行一键部署脚本
4. 打开 `/health` 验证服务
5. 如失败，查看 `logs/roleplay-api.err.log`

推荐命令：

```powershell
cd "E:\Role_playing system\Role_playing system"
powershell -ExecutionPolicy Bypass -File .\deploy\deploy-roleplay-system.ps1
```

---

## 11. 常用命令汇总

```powershell
# 一键部署
powershell -ExecutionPolicy Bypass -File .\deploy\deploy-roleplay-system.ps1

# 只启动 API
powershell -ExecutionPolicy Bypass -File .\deploy\deploy-roleplay-system.ps1 -SkipMilvus

# 只启动 Milvus
powershell -ExecutionPolicy Bypass -File .\deploy\deploy-roleplay-system.ps1 -SkipApi

# 单独启动 API
powershell -ExecutionPolicy Bypass -File .\deploy\start-roleplay-api.ps1

# 单独停止 API
powershell -ExecutionPolicy Bypass -File .\deploy\stop-roleplay-api.ps1

# 单独启动 Milvus
powershell -ExecutionPolicy Bypass -File .\deploy\start-milvus.ps1

# 单独停止 Milvus
powershell -ExecutionPolicy Bypass -File .\deploy\stop-milvus.ps1
```
