"""
日程提醒智能体 — 主入口
======================
命令行交互式日程管理，支持添加/查询/删除/修改/循环日程 + 到时提醒。
工单编号: 人工智能NLP-Agent数字人项目-日程提醒智能体任务

用法:
    python main.py          # 交互模式
    python main.py --test   # 运行验收测试
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from db import init_db, query_schedules, format_schedule, today_str
from agent import handle_message, start_reminder, stop_reminder
from config import MAX_HISTORY, get_logger

logger = get_logger(__name__)


def interactive_mode() -> None:
    """命令行交互模式。"""
    init_db()
    start_reminder()

    # 完整对话历史：[{"role": "user/assistant/tool", "content": "..."}, ...]
    history: list[dict[str, str]] = []



    try:
        while True:
            try:
                user_input = input("> ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n再见！")
                break

            if not user_input:
                continue
            if user_input.lower() in ("exit", "quit", "退出"):
                print("再见！记得来看日程哦~")
                break

            try:
                # 将历史传给 agent（agent 内部会拼接 system prompt）
                response = handle_message(user_input, history)

                print(response)

                # 保存完整的用户消息和助手回复到历史
                history.append({"role": "user", "content": user_input})
                history.append({"role": "assistant", "content": response})

                # 限制历史长度（保留最近 N 轮）
                if len(history) > MAX_HISTORY * 2:  # 用户+助手 = 2条/轮
                    history = history[-(MAX_HISTORY * 2):]

            except Exception as e:
                logger.exception("处理消息时出错")
                print(f"出错: {e}")

    finally:
        # 优雅关闭：确保停止提醒线程
        stop_reminder()
        logger.info("程序已退出")


def run_test() -> None:
    """运行验收测试"""
    init_db()

    # 先预设几条日程用于测试
    from db import add_schedule
    add_schedule("08:00", "起床", today_str(), "daily")
    add_schedule("09:00", "上班打卡", today_str(), "weekday")
    add_schedule("17:00", "开会", today_str())
    add_schedule("15:15", "提醒我买咖啡", today_str())
    add_schedule("12:00", "午餐", today_str(), "daily")

    print("=" * 60)
    print("  日程提醒智能体 -- 验收测试")
    print("=" * 60)

    test_cases = [
        "我今天的日程有哪些？",
        "取消日程1",
        "添加日程：下午5点开会",
        "15:15 | 000001 | 提醒我买咖啡",
        # 新增：修改日程测试
        "修改日程3 改成明天下午4点",
    ]

    for i, test_input in enumerate(test_cases, 1):
        print(f"\n{'-' * 50}")
        print(f"  测试 {i}: {test_input}")
        print(f"{'-' * 50}")
        try:
            history: list[dict[str, str]] = []
            response = handle_message(test_input, history)
            print(f"  输入: {test_input}")
            print(f"  回复: {response}")
        except Exception as e:
            logger.exception("测试用例执行异常")
            print(f"  出错: {e}")

    print(f"\n{'=' * 60}")
    print("  测试完成")
    print(f"{'=' * 60}")

    # 显示数据库全部日程
    all_rows = query_schedules(date_str=None, limit=100)
    print(f"\n数据库中共 {len(all_rows)} 条日程：")
    for r in all_rows:
        print(format_schedule(r))
    print()


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        run_test()
    else:
        interactive_mode()


if __name__ == "__main__":
    main()

