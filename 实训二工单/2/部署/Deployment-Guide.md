# 日程提醒智能体 — 部署文档

> 工单编号: 人工智能NLP-Agent数字人项目-日程提醒智能体任务  
> 版本: v1.0 | 日期: 2026-06-22

---

## 一、环境要求

| 项目 | 最低要求 | 推荐 |
|------|---------|------|
| 操作系统 | Windows 10+ / Linux / macOS | Windows 11 / Ubuntu 22.04+ |
| Python | 3.10+ | 3.11+ |
| 内存 | 512 MB | 1 GB+ |
| 磁盘 | 100 MB | 500 MB+ |
| 网络 | 可访问 `api.siliconflow.cn` | 稳定互联网连接 |

---

## 二、依赖安装

### 2.1 Python 环境准备

```bash
# 确认 Python 版本
python --version  # 应输出 3.10 或更高

# (推荐) 创建虚拟环境
python -m venv venv

# 激活虚拟环境
# Windows:
venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate
```

### 2.2 安装依赖包

```bash
pip install certifi
```

> **说明**: 其他依赖均为 Python 标准库 (`sqlite3`, `json`, `threading`, `datetime`, `urllib`, `ssl`, `re`, `random`, `sys`, `os`)，无需额外安装。

### 2.3 验证安装

```bash
python -c "import certifi; print('OK')"
```

---

## 三、配置

### 3.1 设置 API Key (环境变量)

```bash
# Windows (CMD):
set SILICONFLOW_API_KEY=sk-your-api-key-here

# Windows (PowerShell):
$env:SILICONFLOW_API_KEY="sk-your-api-key-here"

# Linux/macOS:
export SILICONFLOW_API_KEY="sk-your-api-key-here"
```

> ⚠️ **安全警告**: 请勿将 API Key 硬编码在代码中或提交到版本控制系统。

### 3.2 (可选) 修改模型配置

编辑 `llm.py` 中的配置项：

```python
MODEL = "Qwen/Qwen3-14B"        # 可替换为其他 SiliconFlow 支持的模型
TEMPERATURE = 0.1                # 0.0-1.0，越低越确定
MAX_TOKENS = 2048                # 最大输出 token 数
TIMEOUT = 30                     # API 请求超时 (秒)
```

---

## 四、项目结构

```
研发/
├── main.py          # 主入口 (交互模式 + 测试模式)
├── agent.py         # 智能体核心逻辑 (Function Calling + 提醒线程)
├── db.py            # 数据库操作 (SQLite CRUD)
├── llm.py           # LLM API 封装 (SiliconFlow)
├── schedule.db      # SQLite 数据库文件 (首次运行自动创建)
├── 设计-思维导图.md   # 架构设计文档
├── 优化点总结.md      # 优化建议
└── 部署文档.md        # 本文件
```

---

## 五、启动运行

### 5.1 交互模式

```bash
cd 研发/
python main.py
```

启动后显示：

```
==================================================
  日程提醒智能体
==================================================

示例：
  '添加日程：下午5点开会'
  '每天早上8点起床'
  '我今天的日程有哪些？'
  '取消日程1'
  '提醒我买咖啡'
  'exit' 退出

>
```

### 5.2 运行验收测试

```bash
python main.py --test
```

输出包含4个测试用例的执行结果和数据库最终状态。

---

## 六、使用说明

### 6.1 支持的操作

| 操作 | 示例输入 | 说明 |
|------|---------|------|
| 添加日程 | `提醒我下午5点开会` | 默认今天，时间+事项 |
| 添加循环日程 | `每天早上8点起床` | 支持 daily/weekday/weekly/monthly |
| 查询日程 | `我今天的日程有哪些？` | 默认查今天 |
| 删除日程 | `取消日程1` | 先确认后删除 |
| 退出 | `exit` / `quit` / `退出` | 按 Ctrl+C 也可退出 |

### 6.2 时间表达

| 用户表达 | 解析结果 |
|---------|---------|
| 下午5点 | 17:00 |
| 早上8点 | 08:00 |
| 中午12点 | 12:00 |
| 15:15 | 15:15 |
| 下午3点半 | 15:30 |

### 6.3 循环规则

| 规则 | 说明 | 示例 |
|------|------|------|
| none | 不循环 (默认) | 一次性日程 |
| daily | 每天重复 | 起床提醒 |
| weekday | 工作日 (周一至周五) | 上班打卡 |
| weekly | 每周同一天 | 周会 |
| monthly | 每月同一天 | 月度报告 |

---

## 七、数据库管理

### 7.1 数据库文件

- **位置**: `研发/schedule.db`
- **类型**: SQLite3
- **表**: `schedules`

### 7.2 查看数据

```bash
# 使用 sqlite3 命令行
sqlite3 schedule.db "SELECT * FROM schedules;"
```

### 7.3 备份数据库

```bash
# Windows:
copy schedule.db schedule_backup_20260622.db

# Linux/macOS:
cp schedule.db schedule_backup_$(date +%Y%m%d).db
```

### 7.4 重置数据库

```bash
rm schedule.db
# 下次运行 python main.py 时会自动重建
```

---

## 八、常见问题 (FAQ)

### Q1: 启动报错 `ModuleNotFoundError: No module named 'certifi'`

```bash
pip install certifi
```

### Q2: API 调用报错 `API HTTP 401`

API Key 无效或已过期。请检查 `llm.py` 中的 `API_KEY` 变量，或重新设置环境变量。

### Q3: API 调用报错 `API HTTP 429`

请求频率过高，触发限流。等待几秒后重试。

### Q4: 提醒不生效

检查程序是否正在运行。提醒功能仅在程序运行期间有效。

### Q5: 中文输出乱码 (Windows)

确保终端编码为 UTF-8：
```bash
chcp 65001
```
或在 PowerShell / Windows Terminal 中运行。

### Q6: SSL 证书错误

```bash
pip install --upgrade certifi
```

---

## 九、生产部署建议

### 9.1 作为系统服务运行

**Windows (使用 NSSM)**:

```bash
# 下载 nssm: https://nssm.cc/download
nssm install ScheduleAgent "C:\path\to\python.exe" "C:\path\to\main.py"
nssm set ScheduleAgent AppDirectory "C:\path\to\研发"
nssm start ScheduleAgent
```

**Linux (使用 systemd)**:

创建 `/etc/systemd/system/schedule-agent.service`:

```ini
[Unit]
Description=日程提醒智能体
After=network.target

[Service]
Type=simple
User=your-user
WorkingDirectory=/path/to/研发
Environment=SILICONFLOW_API_KEY=sk-your-key
ExecStart=/usr/bin/python3 /path/to/研发/main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable schedule-agent
sudo systemctl start schedule-agent
```

### 9.2 Docker 部署

```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY . .
RUN pip install certifi

ENV SILICONFLOW_API_KEY=sk-your-key

CMD ["python", "main.py"]
```

```bash
docker build -t schedule-agent .
docker run -it --name schedule-agent schedule-agent
```

### 9.3 生产环境检查清单

- [ ] API Key 已通过环境变量配置 (非硬编码)
- [ ] 数据库文件有定期备份策略
- [ ] 日志已接入监控系统
- [ ] 服务已配置自动重启
- [ ] SSL 证书信任链正常
- [ ] 防火墙允许访问 `api.siliconflow.cn:443`
- [ ] 已配置 `.gitignore` 排除 `schedule.db` 和 `.env`

---

## 十、版本信息

| 组件 | 版本 |
|------|------|
| Python | 3.11 |
| SQLite | 3.x (随 Python 分发) |
| certifi | latest |
| SiliconFlow API | v1 |
| LLM Model | Qwen/Qwen3-14B |

---

> 📧 **技术支持**: 请参考项目工单: 人工智能NLP-Agent数字人项目-日程提醒智能体任务
