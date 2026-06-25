"""
数据库操作模块
=============
负责 SQLite 数据库的建表、增删查改操作。
工单编号: 人工智能NLP-Agent数字人项目-记账本任务
"""

import sqlite3
import os
from datetime import datetime, date
from typing import Any

DB_PATH = os.path.join(os.path.dirname(__file__), "ledger.db")


def get_conn() -> sqlite3.Connection:
    """获取数据库连接（每次调用返回新连接，线程安全）"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    """初始化数据库表结构"""
    conn = get_conn()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                date        TEXT    NOT NULL,       -- 日期 YYYY-MM-DD
                member      TEXT    NOT NULL,       -- 成员: 爸爸/妈妈/女儿
                category    TEXT    NOT NULL,       -- 类别: 买书/登山鞋/报销/旅游团费...
                type        TEXT    NOT NULL CHECK(type IN ('收入', '支出')),
                amount      REAL    NOT NULL,       -- 金额(正数)
                note        TEXT    DEFAULT '',     -- 备注
                created_at  TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_txn_date ON transactions(date)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_txn_member ON transactions(member)
        """)
        conn.commit()
    finally:
        conn.close()


# ── 增 ──────────────────────────────────────────────────────────────────────

def add_transaction(
    date_str: str,
    member: str,
    category: str,
    txn_type: str,
    amount: float,
    note: str = "",
) -> dict[str, Any]:
    """添加一条收支记录。返回插入后的记录字典。"""
    conn = get_conn()
    try:
        cur = conn.execute(
            """INSERT INTO transactions (date, member, category, type, amount, note)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (date_str, member, category, txn_type, amount, note),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM transactions WHERE id = ?", (cur.lastrowid,)
        ).fetchone()
        return dict(row)
    finally:
        conn.close()


# ── 查 ──────────────────────────────────────────────────────────────────────

def query_transactions(
    member: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    category: str | None = None,
    keyword: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """按条件查询收支记录。所有条件均为可选，支持模糊关键词搜索。"""
    conditions: list[str] = []
    params: list[Any] = []

    if member:
        conditions.append("member = ?")
        params.append(member)
    if start_date:
        conditions.append("date >= ?")
        params.append(start_date)
    if end_date:
        conditions.append("date <= ?")
        params.append(end_date)
    if category:
        conditions.append("category = ?")
        params.append(category)
    if keyword:
        conditions.append("(category LIKE ? OR note LIKE ?)")
        kw = f"%{keyword}%"
        params.extend([kw, kw])

    where = "WHERE " + " AND ".join(conditions) if conditions else ""
    sql = f"SELECT * FROM transactions {where} ORDER BY date DESC, id DESC LIMIT ?"
    params.append(limit)

    conn = get_conn()
    try:
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_summary(
    member: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    category: str | None = None,
) -> dict[str, Any]:
    """按条件汇总收支统计。"""
    conditions: list[str] = []
    params: list[Any] = []

    if member:
        conditions.append("member = ?")
        params.append(member)
    if start_date:
        conditions.append("date >= ?")
        params.append(start_date)
    if end_date:
        conditions.append("date <= ?")
        params.append(end_date)
    if category:
        conditions.append("category = ?")
        params.append(category)

    where = "WHERE " + " AND ".join(conditions) if conditions else ""

    conn = get_conn()
    try:
        # 总收入
        income = conn.execute(
            f"SELECT COALESCE(SUM(amount), 0) FROM transactions {where} AND type = '收入'",
            params,
        ).fetchone()[0]
        # 总支出
        expense = conn.execute(
            f"SELECT COALESCE(SUM(amount), 0) FROM transactions {where} AND type = '支出'",
            params,
        ).fetchone()[0]
        # 按类别汇总
        cat_rows = conn.execute(
            f"SELECT category, type, SUM(amount) as total, COUNT(*) as cnt "
            f"FROM transactions {where} GROUP BY category, type ORDER BY total DESC",
            params,
        ).fetchall()

        return {
            "total_income": round(income, 2),
            "total_expense": round(expense, 2),
            "balance": round(income - expense, 2),
            "category_breakdown": [dict(r) for r in cat_rows],
        }
    finally:
        conn.close()


# ── 删 ──────────────────────────────────────────────────────────────────────

def delete_transaction(txn_id: int) -> bool:
    """按 ID 删除一条记录。返回是否删除成功。"""
    conn = get_conn()
    try:
        cur = conn.execute("DELETE FROM transactions WHERE id = ?", (txn_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def search_transactions_to_delete(
    keyword: str,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """模糊搜索要删除的记录（按关键词匹配 category 和 note，支持拆分多个词）"""
    conn = get_conn()
    try:
        # 拆分关键词为单个词，任何一个词匹配都返回
        terms = [t.strip() for t in keyword.replace(" ", ",").replace("，", ",").split(",") if len(t.strip()) >= 2]
        if not terms:
            terms = [keyword]
        conditions = " OR ".join(["(category LIKE ? OR note LIKE ?)" for _ in terms])
        params = []
        for t in terms:
            kw = f"%{t}%"
            params.extend([kw, kw])

        rows = conn.execute(
            f"""SELECT * FROM transactions
               WHERE {conditions}
               ORDER BY date DESC, id DESC LIMIT ?""",
            (*params, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ── 工具 ─────────────────────────────────────────────────────────────────────

def today_str() -> str:
    """返回今天的日期字符串 YYYY-MM-DD"""
    return date.today().isoformat()


def current_month_range() -> tuple[str, str]:
    """返回当前月的起始和结束日期"""
    today = date.today()
    start = today.replace(day=1).isoformat()
    # 下个月第一天
    if today.month == 12:
        end = today.replace(year=today.year + 1, month=1, day=1).isoformat()
    else:
        end = today.replace(month=today.month + 1, day=1).isoformat()
    return start, end


def format_transaction(row: dict[str, Any]) -> str:
    """格式化单条记录为可读文本"""
    sign = "+" if row["type"] == "收入" else "-"
    return (
        f"  [{row['id']}] {row['date']} {row['member']} "
        f"| {row['category']} {sign}{row['amount']}元"
        f"{' (' + row['note'] + ')' if row['note'] else ''}"
    )
