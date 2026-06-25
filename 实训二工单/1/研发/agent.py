"""
Agent 核心逻辑 — 记账本智能体
=============================
基于 SiliconFlow LLM + Function Calling 实现自然语言记账功能。
工单编号: 人工智能NLP-Agent数字人项目-记账本任务
"""

import json
from datetime import date, timedelta
from typing import Any

from db import (
    add_transaction,
    query_transactions,
    get_summary,
    delete_transaction as db_delete,
    search_transactions_to_delete,
    format_transaction,
)
from llm import chat_completion

FAMILY_MEMBERS = ["爸爸", "妈妈", "女儿"]

# ── Tool 定义 ───────────────────────────────────────────────────────────────

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "record_transaction",
            "description": "记录一笔家庭收支。用户描述消费或收入时调用。信息不全时先追问。",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {
                        "type": "string",
                        "description": "日期 YYYY-MM-DD。用户说今天/昨天等要换算。没说则用今天。",
                    },
                    "member": {
                        "type": "string",
                        "enum": FAMILY_MEMBERS,
                        "description": "家庭成员：爸爸/妈妈/女儿。用户没说明时追问。",
                    },
                    "category": {
                        "type": "string",
                        "description": "类别，如买书/登山鞋/报销/工资/餐饮等，根据描述推断。",
                    },
                    "type": {
                        "type": "string",
                        "enum": ["收入", "支出"],
                        "description": "收支类型。收到钱=收入，花钱=支出。",
                    },
                    "amount": {
                        "type": "number",
                        "description": "金额（正数），单位元。",
                    },
                    "note": {
                        "type": "string",
                        "description": "备注。",
                    },
                },
                "required": ["date", "member", "category", "type", "amount"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_transactions",
            "description": "查询收支记录。用户问'看下明细'/'花了多少钱'/'查一下'时调用。默认查当前月。",
            "parameters": {
                "type": "object",
                "properties": {
                    "member": {"type": "string", "enum": FAMILY_MEMBERS, "description": "成员筛选（可选）"},
                    "start_date": {"type": "string", "description": "起始日期 YYYY-MM-DD，默认当前月1号"},
                    "end_date": {"type": "string", "description": "结束日期 YYYY-MM-DD，默认当前月最后一天"},
                    "category": {"type": "string", "description": "类别筛选（可选）"},
                    "keyword": {"type": "string", "description": "关键词模糊搜索（可选）"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_transaction",
            "description": "删除一条记录。必须先搜索让用户确认ID，确认后才执行删除。",
            "parameters": {
                "type": "object",
                "properties": {
                    "transaction_id": {"type": "integer", "description": "要删除的记录ID，用户确认后传入"},
                },
                "required": ["transaction_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_delete_candidates",
            "description": "搜索待删除的候选记录，向用户展示并让其选择。用户说'删除'时先调这个。",
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "搜索关键词"},
                },
                "required": ["keyword"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_summary_stats",
            "description": "获取收支统计汇总。用户问'花了多少钱'/'总支出'/'花钱明细'时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "member": {"type": "string", "enum": FAMILY_MEMBERS, "description": "成员筛选（可选）"},
                    "start_date": {"type": "string", "description": "起始日期，默认当前月1号"},
                    "end_date": {"type": "string", "description": "结束日期，默认今天"},
                    "category": {"type": "string", "description": "类别筛选（可选）"},
                },
            },
        },
    },
]

# ── 工具函数实现 ───────────────────────────────────────────────────────────

def _today() -> str:
    return date.today().isoformat()

def _yesterday() -> str:
    return (date.today() - timedelta(days=1)).isoformat()

def _month_start() -> str:
    return date.today().replace(day=1).isoformat()

def _execute_tool(name: str, args: dict[str, Any]) -> str:
    if name == "record_transaction":
        row = add_transaction(
            date_str=args["date"],
            member=args["member"],
            category=args["category"],
            txn_type=args["type"],
            amount=args["amount"],
            note=args.get("note", ""),
        )
        return f"[已记录]：{format_transaction(row)}"

    elif name == "query_transactions":
        rows = query_transactions(
            member=args.get("member"),
            start_date=args.get("start_date"),
            end_date=args.get("end_date"),
            category=args.get("category"),
            keyword=args.get("keyword"),
        )
        if not rows:
            return "没有找到匹配的记录。"
        lines = [format_transaction(r) for r in rows]
        total_exp = sum(r["amount"] for r in rows if r["type"] == "支出")
        total_inc = sum(r["amount"] for r in rows if r["type"] == "收入")
        result = f"共 {len(rows)} 条记录：\n" + "\n".join(lines)
        if total_exp > 0:
            result += f"\n支出合计：{total_exp:.2f}元"
        if total_inc > 0:
            result += f"\n收入合计：{total_inc:.2f}元"
        return result

    elif name == "search_delete_candidates":
        rows = search_transactions_to_delete(args["keyword"])
        if not rows:
            return "未找到匹配的记录。"
        lines = "\n".join(
            f"  [{r['id']}] {r['date']} {r['member']} | {r['category']} | "
            f"{'+' if r['type']=='收入' else '-'}{r['amount']}元"
            for r in rows
        )
        return f"找到以下记录，请告诉我需要删除哪一条（回复ID数字）：\n{lines}"

    elif name == "delete_transaction":
        success = db_delete(args["transaction_id"])
        if success:
            return f"已删除 ID={args['transaction_id']} 的记录"
        return f"未找到 ID={args['transaction_id']} 的记录。"

    elif name == "get_summary_stats":
        sm = get_summary(
            member=args.get("member"),
            start_date=args.get("start_date"),
            end_date=args.get("end_date"),
            category=args.get("category"),
        )
        label = f"{args['member']}的" if args.get("member") else "家庭"
        parts = [f"{label}收支汇总："]
        parts.append(f"  总收入：{sm['total_income']:.2f}元")
        parts.append(f"  总支出：{sm['total_expense']:.2f}元")
        parts.append(f"  结余：{sm['balance']:.2f}元")
        if sm["category_breakdown"]:
            parts.append("  各类别明细：")
            for item in sm["category_breakdown"]:
                s = "+" if item["type"] == "收入" else "-"
                parts.append(
                    f"    {item['category']}（{item['type']}）：{s}{item['total']:.2f}元（{item['cnt']}笔）"
                )
        return "\n".join(parts)

    return f"未知工具: {name}"


# ── 上下文记忆提取 ──────────────────────────────────────────────────────────

def _build_memory_context() -> str:
    """
    从数据库中提取简要的家庭记账背景，注入到 system prompt 中。
    让模型在每个轮次都能感知"家里已经记了什么账"，解决长对话上下文丢失的问题。
    """
    from db import get_summary, current_month_range, query_transactions
    start, end = current_month_range()
    sm = get_summary(start_date=start, end_date=end)
    total = sm["total_income"] + sm["total_expense"]
    if total == 0:
        return ""

    brief = f"[背景参考 — 不要直接用来回答查询，查询必须通过工具获取数据] 本月总收入约{sm['total_income']:.0f}元，总支出约{sm['total_expense']:.0f}元，"
    brief += f"结余{sm['balance']:.0f}元。"
    if sm["category_breakdown"]:
        top = sm["category_breakdown"][:5]
        brief += "主要类别：" + "、".join(f"{c['category']}({c['total']:.0f}元)" for c in top) + "。"
    # 统计各成员的记录条数
    members_data = query_transactions(member=None, start_date=start, end_date=end, limit=1000)
    member_counts = {}
    for r in members_data:
        member_counts[r["member"]] = member_counts.get(r["member"], 0) + 1
    if member_counts:
        brief += "成员记账次数：" + "、".join(
            f"{m}{n}笔" for m, n in sorted(member_counts.items(), key=lambda x: -x[1])
        ) + "。"
    return brief


# ── System Prompt ───────────────────────────────────────────────────────────

def _build_system_prompt() -> str:
    memory = _build_memory_context()
    memory_block = f"\n\n{memory}" if memory else ""

    return f"""你是「小当家记账助手」—— 一个热情、细心、有点幽默感的家庭记账智能体。你服务于爸爸、妈妈、女儿组成的三口之家，帮助他们记录和管理每天的收支。

## 角色性格
- 热情亲切，像个靠谱的家庭财务管家
- 记录成功后给一句暖心或俏皮的回应（但不能过于冗长）
- 遇到不完整的信息，耐心引导用户补充完整
- 查询结果时，基于工具返回的实际数据回答，不得捏造不存在的类别或金额

## 格式要求
用户输入格式示例："x年x月x日，谁做什么事收入/支出多少钱"
但用户可能说得不完整或口语化，你要正确理解。

## 核心规则

1. **开场白**: 如果用户说"你好"或"开始"，先用热情的语气打招呼，引导格式。
   但如果用户的第一句话直接就是记账内容（如"今天女儿买鞋花了500"），不要回复任何内容，
   必须先调用 record_transaction 工具完成记录，然后基于工具结果进行回复。

2. **100% 调库**: 涉及记账、查询、删除时，必须调用对应工具。绝不能捏造数据。
   - 用户说"买/花/消费" → record_transaction
   - 用户说"查/看/明细" → query_transactions 或 get_summary_stats
   - 用户说"删/去除" → search_delete_candidates

3. **信息完整性**: 缺少成员/金额时先追问，不记录残缺数据。

4. **日期处理**: 今天={_today()}，昨天={_yesterday()}。
   用户说"今天"用今天，"7月5日"用{_today()[:4]}-07-05。没说日期默认今天。

5. **成员识别**: 固定成员为{"、".join(FAMILY_MEMBERS)}。
   用户说"我"时用上下文判断。如果上下文无法判断，追问是谁。

6. **口语化理解**: "买三体"→类别=买书，"登山鞋"→类别=登山鞋，"报销"→收入类型。

7. **删除流程**: 用户说删除时，先调 search_delete_candidates 搜索。
   - 关键词要精简，只提取核心词。如"删除女儿报旅游团的费用" → 关键词用"旅游团"
   - 搜索后向用户展示找到的记录（带ID）让用户确认
   - 用户确认后调 delete_transaction 执行。确认前不删。

8. **默认时间**: 查询时如用户说"这个月"或没给时间范围，默认当月（{_month_start()} 到今天）。

当前日期：{_today()}
""" + memory_block


GREETING = '您好，欢迎使用咱们小家专属记账本！请按照"x年x月x日，谁做什么事收入/支出多少钱"的格式来输入。请告诉我你的账目需求吧~'

def handle_message(user_input: str, history: list[dict[str, str]]) -> str:
    """处理用户输入，返回智能体回复。history格式：[{"role":"user"/"assistant","content":"..."}]"""
    # 固定开场白：用户说"你好"/"开始"且无历史时直接返回
    if not history and user_input.strip() in ("你好", "您好", "开始", "hi", "hello", "Hi"):
        return GREETING
    messages = [{"role": "system", "content": _build_system_prompt()}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_input})

    for turn in range(5):  # 最多5轮工具调用
        # 第一轮强制调工具，避免模型跳过 function calling
        tc = "required" if turn == 0 else "auto"
        raw = chat_completion(messages, tools=TOOLS, tool_choice=tc)
        choice = raw["choices"][0]
        msg = choice["message"]

        content = msg.get("content") or ""
        tool_calls = msg.get("tool_calls")

        if not tool_calls:
            # 没有工具调用 → 这就是最终回复，使用流式输出提升体验
            return content

        # 有工具调用 → 保留 assistant 消息
        assistant_msg = {"role": "assistant", "content": content, "tool_calls": tool_calls}
        messages.append(assistant_msg)

        for tc in tool_calls:
            fn_name = tc["function"]["name"]
            try:
                fn_args = json.loads(tc["function"]["arguments"])
            except json.JSONDecodeError:
                fn_args = {}

            result_text = _execute_tool(fn_name, fn_args)
            messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": result_text,
            })

    return "操作步骤较多，请简化一下您的需求。"
