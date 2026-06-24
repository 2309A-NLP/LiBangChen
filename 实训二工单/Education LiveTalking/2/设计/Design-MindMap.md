# 日程提醒智能体 — 设计思维导图

> 工单编号: 人工智能NLP-Agent数字人项目-日程提醒智能体任务

---

## 1. 项目总览

- **项目名称**: 日程提醒智能体 (Schedule Reminder Agent)
- **技术栈**: Python 3.11 + SQLite + SiliconFlow LLM API
- **核心能力**: 自然语言驱动的日程增删改查 + 定时提醒
- **交互方式**: 命令行交互式 (CLI)

---

## 2. 系统架构

### 2.1 分层架构

- **表示层 (main.py)**
  - 命令行交互入口
  - 交互模式 / 测试模式双入口
  - 会话历史管理 (最近20轮)
  - 输入/输出编码处理 (UTF-8)

- **业务逻辑层 (agent.py)**
  - 自然语言理解 → Function Calling 路由
  - System Prompt 工程
  - 工具定义与调度
  - 后台提醒线程

- **数据访问层 (db.py)**
  - SQLite CRUD 封装
  - 循环日程逻辑计算
  - 到期日程检查

- **外部服务层 (llm.py)**
  - SiliconFlow API 封装
  - OpenAI 兼容协议
  - SSL 证书处理

### 2.2 数据流

- **用户输入 → LLM Function Calling → 工具执行 → 数据库操作 → 结果返回**
- **后台线程 → 定时检查 → 匹配到期日程 → 控制台提醒输出**

---

## 3. 模块设计

### 3.1 main.py — 主入口

- `interactive_mode()`
  - 初始化数据库
  - 启动后台提醒线程
  - REPL 循环：读取 → 处理 → 输出 → 记录历史
  - 退出条件：exit / quit / 退出 / Ctrl+C / EOF

- `run_test()`
  - 预置测试数据 (5条日程)
  - 执行4个验收用例
  - 展示数据库最终状态

- `main()`
  - 参数路由：`--test` 进入测试模式，否则交互模式

### 3.2 agent.py — 核心智能体

- **System Prompt 设计**
  - 时间解析规则 (口语→标准格式)
  - 日期处理规则 (今天/明天)
  - 100% 调库原则 (不捏造数据)
  - 信息完整性校验
  - 删除流程规范
  - 提醒格式模板

- **工具定义 (4个Function Tools)**
  - `add_schedule` — 添加日程 (time, content, date, repeat_rule)
  - `query_schedules` — 查询日程 (date)
  - `search_schedules_for_delete` — 搜索待删除日程 (keyword, schedule_id)
  - `delete_schedule` — 确认删除 (schedule_id)

- **工具执行 `_execute_tool()`**
  - 参数解析 + 函数路由
  - ID 数字提取 (正则)
  - 关键词模糊匹配

- **主处理 `handle_message()`**
  - 多轮工具调用循环 (最多5轮)
  - 历史消息拼接
  - 异常容错

- **提醒线程**
  - daemon 线程，30秒轮询
  - 分钟级精度匹配
  - 随机温馨提醒语

### 3.3 db.py — 数据库操作

- **表结构 `schedules`**
  - id (INTEGER PK AUTOINCREMENT)
  - time (TEXT, HH:MM)
  - content (TEXT)
  - date (TEXT, YYYY-MM-DD)
  - repeat_rule (none/daily/weekly/monthly/weekday)
  - enabled (INTEGER, 0/1)
  - created_at (TEXT)

- **索引**
  - idx_sch_date (date)
  - idx_sch_time (time)

- **CRUD 操作**
  - `add_schedule()` → INSERT
  - `query_schedules()` → SELECT + 循环规则过滤
  - `delete_schedule()` → DELETE BY id
  - `update_schedule()` → UPDATE (动态字段)

- **循环日程逻辑**
  - daily → 每天匹配
  - weekday → 跳过周六日
  - weekly → 同星期几匹配
  - monthly → 同日期号匹配

- **提醒查询**
  - `get_due_schedules()` → 按时间+日期精确匹配

### 3.4 llm.py — LLM API

- **配置**
  - API: SiliconFlow `api.siliconflow.cn/v1`
  - Model: `Qwen/Qwen3-14B`
  - Temperature: 0.1 (低随机性，确保确定性输出)
  - Max Tokens: 2048
  - Timeout: 30s

- **请求构建**
  - OpenAI 兼容 JSON payload
  - 支持 tools + tool_choice=auto
  - Bearer Token 认证

- **错误处理**
  - HTTPError → 解析响应体
  - 通用异常 → RuntimeError

---

## 4. 核心流程

### 4.1 添加日程流程

1. 用户: "提醒我下午5点开会"
2. LLM 解析 → Function Call: `add_schedule(time="17:00", content="开会", date=today, repeat_rule="none")`
3. `_execute_tool()` → `db.add_schedule()` → INSERT
4. 返回: "[已添加] 2026-06-22 17:00 开会"

### 4.2 查询日程流程

1. 用户: "我今天的日程有哪些？"
2. LLM → Function Call: `query_schedules(date=today)`
3. 查询数据库 + 循环日程过滤
4. 返回格式化列表

### 4.3 删除日程流程

1. 用户: "取消日程1"
2. LLM → Function Call: `search_schedules_for_delete(keyword="日程1")`
3. 正则提取数字 → 查询 ID=1 → 展示确认信息
4. 用户确认 → LLM → Function Call: `delete_schedule(schedule_id=1)`
5. 执行 DELETE → 返回结果

### 4.4 定时提醒流程

1. `start_reminder()` → daemon 线程启动
2. 每30秒检查当前分钟
3. 匹配 `schedules` 中 time == HH:MM 的日程
4. 随机选择温馨提醒模板 → 控制台打印

---

## 5. 依赖关系

- **Python 标准库**: `sqlite3`, `json`, `threading`, `datetime`, `urllib`, `ssl`, `re`, `random`, `sys`, `os`
- **第三方库**: `certifi` (SSL 证书)
- **外部服务**: SiliconFlow API (Qwen/Qwen3-14B)

---

## 6. 数据模型

```
┌─────────────── schedules ───────────────┐
│ id          INTEGER  PK AUTOINCREMENT   │
│ time        TEXT     "HH:MM"            │
│ content     TEXT     "开会"             │
│ date        TEXT     "2026-06-22"       │
│ repeat_rule TEXT     "none|daily|..."   │
│ enabled     INTEGER  1                  │
│ created_at  TEXT     auto               │
└─────────────────────────────────────────┘
```

---

> 💡 **提示**: 此思维导图兼容 Markmap / MindMap Markdown 等工具，可直接导入生成可视化脑图。
