# 日程提醒智能体 — 优化点总结

> 工单编号: 人工智能NLP-Agent数字人项目-日程提醒智能体任务  
> 分析日期: 2026-06-22

---

## 一、🔴 严重问题 (Critical)

### 1.1 API Key 硬编码 (安全漏洞)

**位置**: `llm.py:17`

```python
API_KEY = "sk-anzqeikgpjjcxueqwmhcrrmfbwssndlxvughyfcztwbpeefv"
```

**问题**: API Key 明文写在代码中，一旦提交到代码仓库即泄露。  
**影响**: 密钥泄露 → API 被盗用 → 产生费用 / 服务被滥用。  
**建议**:

- 使用环境变量 `os.getenv("SILICONFLOW_API_KEY")`
- 或使用 `.env` 文件 + `python-dotenv` 加载
- 将 `.env` 加入 `.gitignore`

---

### 1.2 日期格式化 Bug (提醒功能失效)

**位置**: `agent.py:279`

```python
current_date = now.strftime("%Y-%M-%d")  # ❌ %M 是分钟，不是月份！
```

**问题**: `%M` 表示分钟 (00-59)，正确应为 `%m` (01-12)。  
**影响**: 提醒线程中的日期比较永远无法正确匹配，**定时提醒功能实际上已损坏**。  
**建议**: 改为 `now.strftime("%Y-%m-%d")`

---

### 1.3 会话历史不完整

**位置**: `main.py:58`

```python
history.append({"role": "user", "content": user_input})
```

**问题**: 只保存了用户消息，不保存 assistant 和 tool 的响应。  
**影响**: LLM 无法获得完整的对话上下文，多轮对话能力受限。  
**建议**: 在 `handle_message()` 中返回完整 messages，或在 main.py 中同时保存 assistant 回复。

---

## 二、🟡 重要优化 (High Priority)

### 2.1 缺少 update_schedule 工具

**位置**: `agent.py` — 工具定义 `TOOLS` 列表中只有4个工具

**问题**: `db.py` 中已经实现了 `update_schedule()`，但 agent 没有暴露"修改日程"的工具给 LLM。用户无法通过自然语言修改日程。  
**建议**: 新增 `update_schedule` 工具定义，参数包含 schedule_id + 可选 time/content/date/repeat_rule。

---

### 2.2 import 语句位置不当

**位置**: `agent.py:143,292`

```python
# 第143行 — 在函数内部
import re

# 第292行 — 在循环内部
import random
```

**问题**: 每次函数调用/循环迭代时重复 import，影响性能。  
**建议**: 将 `import re` 和 `import random` 移到文件顶部。

---

### 2.3 全局 SSL Monkey Patch

**位置**: `llm.py:15`

```python
ssl._create_default_https_context = lambda: ssl.create_default_context(cafile=certifi.where())
```

**问题**: 全局修改 ssl 行为会影响同一进程中所有 HTTPS 请求，副作用不可控。  
**建议**: 使用 `ssl.SSLContext` 在请求级别设置，或使用 `requests` 库的 `verify` 参数。

---

### 2.4 查询效率低 — 全量加载后 Python 过滤

**位置**: `agent.py:150,155` / `db.py:181`

```python
all_rows = query_schedules(date_str=None, limit=100)  # 全量加载
matched = [r for r in all_rows if r["id"] == sid]      # Python 过滤
```

**问题**: 
- `search_schedules_for_delete` 每次加载100条记录到内存再过滤
- `get_due_schedules` 也是全量查询后 Python 过滤
- 数据量增大后性能急剧下降

**建议**:

- `search_schedules_for_delete`: SQL 增加 `WHERE content LIKE ?` 条件
- `get_due_schedules`: SQL 直接加 `WHERE time = ?`，避免 Python 循环

---

### 2.5 无重试机制

**位置**: `llm.py:50-57`

**问题**: API 调用失败直接抛异常，无重试。网络抖动导致用户体验差。  
**建议**: 增加指数退避重试 (exponential backoff)，最多3次。

---

### 2.6 数据库连接未池化

**位置**: `db.py` — 每次操作新建连接

```python
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    ...
    return conn
```

**问题**: 每次 CRUD 操作都创建新连接，频繁连接/断开开销大。  
**建议**: 

- 使用 `sqlite3.connect()` 的单连接 + 线程锁
- 或使用连接池 (如 `sqlite3.Connection` + `threading.local`)

---

## 三、🟢 一般优化 (Medium Priority)

### 3.1 提醒语硬编码重复

**位置**: `agent.py:286-291` 和 `agent.py:222-225`

**问题**: 提醒模板在两个地方重复定义 (System Prompt 和提醒线程)。  
**建议**: 提取为模块级常量 `REMINDER_TEMPLATES`。

---

### 3.2 硬编码的 Magic Numbers

| 位置 | 硬编码值 | 建议 |
|------|---------|------|
| `agent.py:238` | `range(5)` 最大工具调用轮数 | 提取为 `MAX_TOOL_ROUNDS = 5` |
| `agent.py:300` | `wait(30)` 秒 | 提取为 `CHECK_INTERVAL = 30` |
| `llm.py:18-20` | Model / Temperature / Timeout | 移至配置文件或环境变量 |
| `main.py:59` | `history = history[-20:]` | 提取为 `MAX_HISTORY = 20` |

---

### 3.3 异常处理过于宽泛

**位置**: `agent.py:297-298`

```python
except Exception:
    pass
```

**问题**: 提醒线程中静默吞掉所有异常，调试困难。  
**建议**: 至少记录日志 `logging.exception("reminder check failed")`。

---

### 3.4 缺少日志系统

**问题**: 全项目使用 `print()` 输出，无结构化日志。  
**建议**: 引入 `logging` 模块，区分 INFO / WARNING / ERROR 级别。

---

### 3.5 无配置文件支持

**问题**: 所有配置散落在代码中 (API Key, Model, DB Path, 各类参数)。  
**建议**: 使用 `config.yaml` 或 `config.json` 统一管理，或至少用环境变量。

---

### 3.6 无自动化测试

**位置**: `main.py:65` `run_test()` 仅为手动验收脚本

**问题**: 无单元测试，回归验证靠人工。  
**建议**: 使用 `pytest` 编写单元测试：

- `test_db.py` — 数据库 CRUD 测试
- `test_agent.py` — 工具函数测试 (mock LLM)
- `test_llm.py` — API 调用测试 (mock HTTP)

---

### 3.7 缺少数据备份机制

**问题**: 单文件 SQLite (`schedule.db`)，无备份策略。文件损坏则数据全丢。  
**建议**: 

- 定时备份 `schedule.db` → `schedule.backup.db`
- 或使用 SQLite 的 `.backup()` API

---

### 3.8 提醒仅运行中生效

**问题**: 程序关闭后提醒即停止，无法覆盖离线时段的提醒。  
**建议**: 

- 启动时检查错过的提醒并补发
- 或记录提醒历史到数据库

---

### 3.9 异常退出无优雅关闭

**位置**: `main.py:45` — `except KeyboardInterrupt: break`

**问题**: 退出时未调用 `stop_reminder()`，daemon 线程可能未清理。  
**建议**: 增加 `finally` 块调用 `stop_reminder()`。

---

## 四、优化优先级矩阵

| 优先级 | 优化项 | 影响范围 | 实现难度 |
|--------|--------|----------|----------|
| 🔴 P0 | API Key 硬编码 | 安全 | 低 |
| 🔴 P0 | 日期格式化 Bug | 核心功能 | 低 |
| 🔴 P0 | 会话历史不完整 | 用户体验 | 低 |
| 🟡 P1 | 缺少修改日程工具 | 功能完整性 | 中 |
| 🟡 P1 | 查询效率优化 | 性能 | 中 |
| 🟡 P1 | API 重试机制 | 稳定性 | 低 |
| 🟡 P1 | import 位置规范化 | 代码质量 | 低 |
| 🟡 P1 | SSL Monkey Patch | 可维护性 | 中 |
| 🟢 P2 | 日志系统 | 可观测性 | 中 |
| 🟢 P2 | 配置管理 | 可维护性 | 中 |
| 🟢 P2 | 自动化测试 | 质量保障 | 高 |
| 🟢 P2 | 数据备份 | 数据安全 | 低 |

---

## 五、建议重构方向

1. **配置层分离**: 创建 `config.py` 统一管理所有配置项
2. **日志标准化**: 替换 `print()` 为 `logging`
3. **HTTP 客户端升级**: 从 `urllib` 迁移到 `httpx` (支持 async + HTTP/2)
4. **测试覆盖**: 核心逻辑达到 80%+ 测试覆盖率
5. **持久化提醒队列**: 提醒记录入库，支持离线补发
