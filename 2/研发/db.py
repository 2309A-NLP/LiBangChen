"""
日程提醒 — 数据库操作模块
========================
SQLite 数据库建表、增删改查操作。
工单编号: 人工智能NLP-Agent数字人项目-日程提醒智能体任务
"""

import sqlite3
import os
import threading
from contextlib import contextmanager
from datetime import date, datetime
from typing import Any, Generator

from config import DB_PATH, get_logger

logger = get_logger(__name__)

# ── 连接管理 ──────────────────────────────────────────────────────────────────

_conn_local = threading.local()


def get_conn() -> sqlite3.Connection:
    """获取当前线程的数据库连接（复用，减少连接开销）"""
    if not hasattr(_conn_local, "conn") or _conn_local.conn is None:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        _conn_local.conn = conn
        logger.debug("新建数据库连接: %s", DB_PATH)
    return _conn_local.conn


def close_conn() -> None:
    """关闭当前线程的数据库连接"""
    if hasattr(_conn_local, "conn") and _conn_local.conn is not None:
        _conn_local.conn.close()
        _conn_local.conn = None
        logger.debug("关闭数据库连接")


@contextmanager
def transaction() -> Generator[sqlite3.Connection, None, None]:
    """事务上下文管理器，自动 commit/rollback。"""
    conn = get_conn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        logger.exception("事务回滚")
        raise


# ── 初始化 ────────────────────────────────────────────────────────────────────

def init_db() -> None:
    conn = get_conn()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS schedules (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                time        TEXT    NOT NULL,       -- HH:MM 格式
                content     TEXT    NOT NULL,       -- 事项内容
                date        TEXT    NOT NULL,       -- 日期 YYYY-MM-DD，循环日程用 start_date
                repeat_rule TEXT    NOT NULL DEFAULT 'none'
                            CHECK(repeat_rule IN ('none','daily','weekly','monthly','weekday')),
                enabled     INTEGER NOT NULL DEFAULT 1,
                created_at  TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sch_date ON schedules(date)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sch_time ON schedules(time)")
        conn.commit()
        logger.info("数据库初始化完成: %s", DB_PATH)
    finally:
        pass  # 连接复用，不关闭


# ── 增 ────────────────────────────────────────────────────────────────────────

def add_schedule(
    time_str: str,
    content: str,
    date_str: str,
    repeat_rule: str = "none",
) -> dict[str, Any]:
    """添加日程（自动去重：同日期+同时间+同内容的不重复添加）。"""
    with transaction() as conn:
        # 去重检查：同一天、同一时间、同一内容且 enabled=1 的已存在则跳过
        existing = conn.execute(
            """SELECT * FROM schedules
               WHERE date = ? AND time = ? AND content = ? AND enabled = 1""",
            (date_str, time_str, content),
        ).fetchone()
        if existing:
            result = dict(existing)
            logger.info("日程已存在，跳过添加: %s %s %s [%s]", date_str, time_str, content, repeat_rule)
            return result

        cur = conn.execute(
            """INSERT INTO schedules (time, content, date, repeat_rule)
               VALUES (?, ?, ?, ?)""",
            (time_str, content, date_str, repeat_rule),
        )
        row = conn.execute(
            "SELECT * FROM schedules WHERE id = ?", (cur.lastrowid,)
        ).fetchone()
        result = dict(row)
        logger.info("添加日程: %s %s %s [%s]", date_str, time_str, content, repeat_rule)
        return result


# ── 查 ────────────────────────────────────────────────────────────────────────

def query_schedules(
    date_str: str | None = None,
    keyword: str | None = None,
    schedule_id: int | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """查询日程，支持按日期、关键词、ID 过滤。

    相比旧版新增:
    - keyword: SQL LIKE 模糊搜索（content 字段）
    - schedule_id: 按 ID 精确查询
    """
    conn = get_conn()
    try:
        conditions = ["enabled = 1"]
        params: list[Any] = []

        if schedule_id is not None:
            conditions.append("id = ?")
            params.append(schedule_id)
        else:
            if date_str:
                conditions.append(
                    "(date = ? OR (repeat_rule != 'none' AND date <= ?))"
                )
                params.extend([date_str, date_str])
            if keyword:
                conditions.append("content LIKE ?")
                params.append(f"%{keyword}%")

        sql = f"""SELECT * FROM schedules
                  WHERE {' AND '.join(conditions)}
                  ORDER BY time ASC, id ASC LIMIT ?"""
        params.append(limit)
        rows = conn.execute(sql, params).fetchall()

        results = []
        for r in rows:
            row = dict(r)
            if date_str and row["repeat_rule"] != "none":
                d = date.fromisoformat(date_str)
                start = date.fromisoformat(row["date"])
                if d < start:
                    continue
                if row["repeat_rule"] == "daily":
                    pass
                elif row["repeat_rule"] == "weekday":
                    if d.weekday() >= 5:
                        continue
                elif row["repeat_rule"] == "weekly":
                    if d.weekday() != start.weekday():
                        continue
                elif row["repeat_rule"] == "monthly":
                    if d.day != start.day:
                        continue
            results.append(row)
        return results
    finally:
        pass  # 连接复用


# ── 删 ────────────────────────────────────────────────────────────────────────

def delete_schedule(schedule_id: int) -> bool:
    with transaction() as conn:
        cur = conn.execute("DELETE FROM schedules WHERE id = ?", (schedule_id,))
        deleted = cur.rowcount > 0
        if deleted:
            logger.info("删除日程 ID=%d", schedule_id)
        else:
            logger.warning("删除失败: 未找到 ID=%d", schedule_id)
        return deleted


# ── 改 ────────────────────────────────────────────────────────────────────────

def update_schedule(
    schedule_id: int,
    time_str: str | None = None,
    content: str | None = None,
    date_str: str | None = None,
    repeat_rule: str | None = None,
) -> dict[str, Any] | None:
    with transaction() as conn:
        fields: list[str] = []
        params: list[Any] = []
        if time_str is not None:
            fields.append("time = ?")
            params.append(time_str)
        if content is not None:
            fields.append("content = ?")
            params.append(content)
        if date_str is not None:
            fields.append("date = ?")
            params.append(date_str)
        if repeat_rule is not None:
            fields.append("repeat_rule = ?")
            params.append(repeat_rule)

        if not fields:
            logger.warning("update_schedule: 无字段需要更新 (ID=%d)", schedule_id)
            return None

        params.append(schedule_id)
        conn.execute(
            f"UPDATE schedules SET {', '.join(fields)} WHERE id = ?",
            params,
        )
        row = conn.execute(
            "SELECT * FROM schedules WHERE id = ?", (schedule_id,)
        ).fetchone()
        if row:
            logger.info("更新日程 ID=%d: %s", schedule_id, fields)
        return dict(row) if row else None


# ── 提醒检查 ──────────────────────────────────────────────────────────────────

def get_due_schedules(current_time_str: str, current_date_str: str) -> list[dict[str, Any]]:
    """获取当前时间应提醒的日程（精确到分钟）。

    优化: 先用 SQL 过滤时间（减少数据传输），再做循环规则匹配。
    """
    conn = get_conn()
    try:
        conditions = ["enabled = 1", "time = ?"]
        params: list[Any] = [current_time_str]

        conditions.append(
            "(date = ? OR (repeat_rule != 'none' AND date <= ?))"
        )
        params.extend([current_date_str, current_date_str])

        sql = f"""SELECT * FROM schedules
                 WHERE {' AND '.join(conditions)}
                 ORDER BY id ASC"""
        rows = conn.execute(sql, params).fetchall()

        due = []
        for r in rows:
            row = dict(r)
            if row["repeat_rule"] != "none":
                d = date.fromisoformat(current_date_str)
                start = date.fromisoformat(row["date"])
                if d < start:
                    continue
                if row["repeat_rule"] == "daily":
                    pass
                elif row["repeat_rule"] == "weekday":
                    if d.weekday() >= 5:
                        continue
                elif row["repeat_rule"] == "weekly":
                    if d.weekday() != start.weekday():
                        continue
                elif row["repeat_rule"] == "monthly":
                    if d.day != start.day:
                        continue
            due.append(row)
        return due
    finally:
        pass  # 连接复用


# ── 工具函数 ──────────────────────────────────────────────────────────────────

def today_str() -> str:
    return date.today().isoformat()


def now_time_str() -> str:
    return datetime.now().strftime("%H:%M")


def format_schedule(row: dict[str, Any]) -> str:
    repeat_tag = {
        "none": "", "daily": " [每天]", "weekday": " [工作日]",
        "weekly": " [每周]", "monthly": " [每月]",
    }.get(row["repeat_rule"], "")
    return f"  [{row['id']}] {row['time']} {row['content']}{repeat_tag}"
