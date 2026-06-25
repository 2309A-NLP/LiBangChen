"""
日程提醒智能体 — 核心逻辑
========================
基于 SiliconFlow LLM + Function Calling 实现日程管理。
工单编号: 人工智能NLP-Agent数字人项目-日程提醒智能体任务
"""

import json
import re
import random
import threading
import time as time_module
from datetime import date, datetime
from typing import Any

from db import (
    add_schedule,
    query_schedules,
    delete_schedule as db_delete,
    update_schedule as db_update,
    get_due_schedules,
    today_str,
    now_time_str,
    format_schedule,
)
from llm import chat_completion
from config import MAX_TOOL_ROUNDS, MAX_HISTORY, CHECK_INTERVAL, get_logger

logger = get_logger(__name__)

# ── 提醒模板（统一管理，避免重复） ──────────────────────────────────────────────

REMINDER_TEMPLATES = [
    "温馨提醒：（{content}）的时间到啦，主人！",
    "主人！是时候{content}了喔~",
    "亲爱的主人，现在是{content}的时候啦！",
    "嘿，主人，该{content}了哦~",
]

REPEAT_LABELS = {
    "none": "",
    "daily": "（每天重复）",
    "weekly": "（每周重复）",
    "monthly": "（每月重复）",
    "weekday": "（工作日重复）",
}

# ── 工具定义 ───────────────────────────────────────────────────────────────────

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "add_schedule",
            "description": "添加日程。用户说'添加日程'/'提醒我'/'记一下'时调用。缺少时间或事项时追问。",
            "parameters": {
                "type": "object",
                "properties": {
                    "time": {
                        "type": "string",
                        "description": "时间，格式 HH:MM。如'下午5点'→17:00，'早上8点'→08:00，'15:15'→15:15。",
                    },
                    "content": {
                        "type": "string",
                        "description": "事项内容，如'开会'、'买咖啡'、'起床'。",
                    },
                    "date": {
                        "type": "string",
                        "description": "日期 YYYY-MM-DD。用户没说则默认今天。'今天'用今天日期，'明天'用明天日期。",
                    },
                    "repeat_rule": {
                        "type": "string",
                        "enum": ["none", "daily", "weekly", "monthly", "weekday"],
                        "description": "循环规则：none=不循环(默认)，daily=每天，weekly=每周，monthly=每月，weekday=工作日(周一至周五)",
                    },
                },
                "required": ["time", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_schedules",
            "description": "查询日程。用户问'今天的日程'/'有哪些日程'/'查一下'时调用。默认查今天。",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {
                        "type": "string",
                        "description": "日期 YYYY-MM-DD。默认今天。用户说'今天'/'明天'要换算。",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_schedule",
            "description": "修改已有日程。用户说'修改日程'/'改一下'/'更新日程'时调用。必须先确认要修改的日程ID。",
            "parameters": {
                "type": "object",
                "properties": {
                    "schedule_id": {
                        "type": "integer",
                        "description": "要修改的日程ID。",
                    },
                    "time": {
                        "type": "string",
                        "description": "新时间，格式 HH:MM。不修改则不传。",
                    },
                    "content": {
                        "type": "string",
                        "description": "新事项内容。不修改则不传。",
                    },
                    "date": {
                        "type": "string",
                        "description": "新日期 YYYY-MM-DD。不修改则不传。",
                    },
                    "repeat_rule": {
                        "type": "string",
                        "enum": ["none", "daily", "weekly", "monthly", "weekday"],
                        "description": "新循环规则。不修改则不传。",
                    },
                },
                "required": ["schedule_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_schedules_for_delete",
            "description": "搜索待删除的候选日程。用户说'取消日程'/'删除日程'时先调这个，展示结果让用户确认。",
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {
                        "type": "string",
                        "description": "搜索关键词，提取核心词。如'取消日程1'→keyword='日程1'（提取ID）。如'取消开会'→keyword='开会'。",
                    },
                    "schedule_id": {
                        "type": "integer",
                        "description": "如果用户明确说了ID（如'日程1'），直接传入ID。",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_schedule",
            "description": "删除日程。必须先搜索出日程让用户确认ID，确认后才执行删除。",
            "parameters": {
                "type": "object",
                "properties": {
                    "schedule_id": {
                        "type": "integer",
                        "description": "要删除的日程ID，用户确认后传入。",
                    },
                },
                "required": ["schedule_id"],
            },
        },
    },
]

# ── 工具函数实现 ───────────────────────────────────────────────────────────────

def _execute_tool(name: str, args: dict[str, Any]) -> str:
    """执行单个工具调用，返回结果文本。"""
    logger.info("执行工具: %s, 参数: %s", name, args)

    if name == "add_schedule":
        row = add_schedule(
            time_str=args["time"],
            content=args["content"],
            date_str=args.get("date", today_str()),
            repeat_rule=args.get("repeat_rule", "none"),
        )
        repeat_info = REPEAT_LABELS.get(row["repeat_rule"], "")
        return f"[已添加] {row['date']} {row['time']} {row['content']}{repeat_info}"

    elif name == "query_schedules":
        qdate = args.get("date", today_str())
        rows = query_schedules(date_str=qdate)
        if not rows:
            return f"{qdate} 没有日程安排。"
        lines = [f"{qdate} 的日程："]
        lines.extend(format_schedule(r) for r in rows)
        return "\n".join(lines)

    elif name == "update_schedule":
        sid = args["schedule_id"]
        updated = db_update(
            schedule_id=sid,
            time_str=args.get("time"),
            content=args.get("content"),
            date_str=args.get("date"),
            repeat_rule=args.get("repeat_rule"),
        )
        if updated:
            repeat_info = REPEAT_LABELS.get(updated["repeat_rule"], "")
            return f"[已更新] {updated['date']} {updated['time']} {updated['content']}{repeat_info}"
        return f"未找到 ID={sid} 的日程，修改失败。"

    elif name == "search_schedules_for_delete":
        sid = args.get("schedule_id")
        keyword = args.get("keyword", "")

        # 从 keyword 中提取数字 ID："日程1"、"取消1"、"1号"等
        if not sid and keyword:
            nums = re.findall(r"\d+", keyword)
            if nums:
                sid = int(nums[0])

        if sid:
            # 按 ID 查询（数据库层过滤）
            matched = query_schedules(date_str=None, schedule_id=sid, limit=100)
            if not matched:
                return f"未找到 ID={sid} 的日程。"
        elif keyword:
            # 按关键词模糊搜索（数据库层 LIKE 查询）
            matched = query_schedules(date_str=None, keyword=keyword, limit=100)
        else:
            matched = []

        if not matched:
            return "未找到匹配的日程。请提供更具体的关键词或日程ID。"

        lines = ["找到以下日程，请告诉我需要删除哪一条（回复ID数字）："]
        lines.extend(format_schedule(r) for r in matched)
        return "\n".join(lines)

    elif name == "delete_schedule":
        success = db_delete(args["schedule_id"])
        if success:
            return f"已删除日程 ID={args['schedule_id']}"
        return f"未找到 ID={args['schedule_id']} 的日程。"

    logger.warning("未知工具调用: %s", name)
    return f"未知工具: {name}"


# ── System Prompt ───────────────────────────────────────────────────────────────

SYSTEM_PROMPT_TEMPLATE = """你是一个日程提醒智能体，帮助管理每日日程。

## 格式要求
用户可能口语化表达，如：
- "添加日程：下午5点开会" → 调 add_schedule(time=17:00, content=开会)
- "提醒我买咖啡" → 调 add_schedule，缺时间就追问
- "15:15提醒我买咖啡" → 时间15:15，内容=买咖啡
- "每天早上8点起床" → time=08:00, content=起床, repeat_rule=daily
- "工作日9点上班打卡" → time=09:00, content=上班打卡, repeat_rule=weekday
- "把日程1改到明天下午3点" → 调 update_schedule(schedule_id=1, date=明天, time=15:00)

## 核心规则

1. **100% 调库**: 涉及添加/查询/删除/修改日程时，必须调用对应工具，绝不能捏造数据。

2. **时间解析**:
   - "下午X点" → X+12:00，如"下午5点"→17:00
   - "早上X点" / "上午X点" → X:00
   - "中午12点" → 12:00
   - "X点X分" → XX:XX 格式
   - "X:XX" 直接使用
   确保时间始终为 HH:MM 格式（两位数小时和分钟）。

3. **日期处理**: 今天={today}。用户说"今天"用它，"明天"用明天的日期。没说日期默认今天。

4. **信息完整性**: 缺少时间或事项内容时追问，不记录残缺数据。

5. **口语化理解**: "提醒我XX"=添加日程，"15:15|000001|提醒我买咖啡"中的"|000001|"是ID标识，忽略它，提取时间和内容。

6. **删除流程**: 用户说"取消日程X"或"删除日程X"时：
   - "取消日程1"、"删除日程1" → keyword 填"日程1"，search_schedules_for_delete 会自动提取 ID=1
   - 如果用户直接说"取消1"，keyword 也填"1"
   - 展示结果让用户确认ID，然后调 delete_schedule 执行
   - 回复要包含删除的日程内容

7. **修改流程**: 用户说"修改日程X"或"改一下日程X"时：
   - 调 update_schedule(schedule_id=X, ...)
   - 只传需要修改的字段，不改的字段不要传

8. **添加与删除的区分**:
   - 用户说"添加日程""提醒我""记一下"都是添加操作 → 调 add_schedule
   - 用户说"取消""删除""移除"都是删除操作 → 调 search_schedules_for_delete
   - 用户说"修改""改""更新"都是修改操作 → 调 update_schedule
   - 注意：如果时间格式（如"下午5点"）出现在添加场景中，要正确识别为添加，不是删除

9. **提醒格式（重要）**: 提醒消息由系统后台线程在日程到点时自动触发，你绝对不可以在回复中输出提醒语（如"温馨提醒"、"时间到啦"等）。你只需简洁确认操作结果即可，例如"已为您添加日程：2026-06-25 14:45 签到"或"已删除日程 ID=1"。

当前日期：{today}
"""


def _build_system_prompt() -> str:
    """动态构建 System Prompt（注入当前日期和提醒模板）。"""
    templates_str = "\n".join(f"   - \"{t}\"" for t in REMINDER_TEMPLATES)
    return SYSTEM_PROMPT_TEMPLATE.format(
        today=today_str(),
        templates=templates_str,
    )


# ── 主处理函数 ─────────────────────────────────────────────────────────────────

def handle_message(user_input: str, history: list[dict[str, str]]) -> str:
    """处理用户输入，返回助手回复。

    Args:
        user_input: 用户输入文本
        history: 完整对话历史 [{"role": "...", "content": "..."}, ...]

    Returns:
        助手回复文本
    """
    messages = [{"role": "system", "content": _build_system_prompt()}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_input})

    for _ in range(MAX_TOOL_ROUNDS):
        raw = chat_completion(messages, tools=TOOLS)
        choice = raw["choices"][0]
        msg = choice["message"]

        content = msg.get("content") or ""
        tool_calls = msg.get("tool_calls")

        if not tool_calls:
            logger.debug("LLM 直接回复（无工具调用）")
            return content

        assistant_msg = {"role": "assistant", "content": content, "tool_calls": tool_calls}
        messages.append(assistant_msg)

        for tc in tool_calls:
            fn_name = tc["function"]["name"]
            try:
                fn_args = json.loads(tc["function"]["arguments"])
            except json.JSONDecodeError:
                logger.warning("工具参数 JSON 解析失败: %s", tc["function"]["arguments"])
                fn_args = {}

            result_text = _execute_tool(fn_name, fn_args)
            messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": result_text,
            })

    logger.warning("达到最大工具调用轮数 (%d)", MAX_TOOL_ROUNDS)
    return "操作步骤较多，请简化一下您的需求。"


# ── 提醒线程 ────────────────────────────────────────────────────────────────────

_reminder_stop = threading.Event()


def _reminder_worker() -> None:
    """后台线程：每30秒检查是否有到时的日程需要提醒。"""
    last_minute = ""
    reminded_ids: set[int] = set()  # 当前分钟已提醒的 schedule ID
    logger.info("提醒线程已启动，检查间隔=%ds", CHECK_INTERVAL)

    while not _reminder_stop.is_set():
        now = datetime.now()
        current_minute = now.strftime("%H:%M")
        current_date = now.strftime("%Y-%m-%d")

        if current_minute != last_minute:
            last_minute = current_minute
            reminded_ids.clear()  # 新分钟，重置已提醒记录

        try:
            due = get_due_schedules(current_minute, current_date)
            for s in due:
                if s["id"] not in reminded_ids:
                    reminded_ids.add(s["id"])
                    msg = random.choice(REMINDER_TEMPLATES).format(content=s["content"])
                    print(f"\n{'='*50}")
                    print(f"  *** {msg} ***")
                    print(f"{'='*50}\n")
                    logger.info("提醒触发: %s %s %s", current_date, current_minute, s["content"])
        except Exception:
            logger.exception("提醒检查异常")

        _reminder_stop.wait(CHECK_INTERVAL)

    logger.info("提醒线程已停止")


def start_reminder() -> None:
    """启动后台提醒线程"""
    _reminder_stop.clear()
    t = threading.Thread(target=_reminder_worker, daemon=True, name="reminder")
    t.start()


def stop_reminder() -> None:
    """停止后台提醒线程"""
    _reminder_stop.set()
    logger.info("已发送停止信号给提醒线程")
