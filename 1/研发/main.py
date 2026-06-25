"""
记账本智能体 — 主入口
=====================
命令行交互式记账本，基于 SiliconFlow LLM + SQLite。
工单编号: 人工智能NLP-Agent数字人项目-记账本任务

用法:
    python main.py          # 交互模式
    python main.py --test   # 运行验收测试
"""

import sys
import os
import numpy
import warnings
warnings.filterwarnings('ignore')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 修复 Windows GBK 编码
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from db import init_db
from agent import handle_message


def interactive_mode() -> None:
    """交互式 CLI 模式"""
    init_db()
    history: list[dict[str, str]] = []
    first_message = True

    print("=" * 50)
    print("  家庭记账本智能体")
    print("=" * 50)

    if first_message:
        # 开场白由 LLM 生成（system prompt 里定义了）
        response = handle_message("你好", history)
        print(f"\n💬 {response}")
        first_message = False



    while True:
        try:
            user_input = input("👤 ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见！")
            break

        if not user_input:
            continue
        if user_input.lower() in ("exit", "quit", "退出"):
            print("再见！记得记账哦～")
            break

        try:
            response = handle_message(user_input, history)
            print(f"💬 {response}")

            # 更新历史（用户 + 助手都要保存，否则模型没有上下文）
            history.append({"role": "user", "content": user_input})
            history.append({"role": "assistant", "content": response})
            if len(history) > 30:
                history = history[-30:]
        except Exception as e:
            print(f"❌ 出错: {e}")


def run_test(test_cases: list[str]) -> None:
    """运行验收测试"""
    init_db()
    history: list[dict[str, str]] = []

    print("=" * 60)
    print("  记账本智能体 — 验收测试")
    print("=" * 60)

    for i, test_input in enumerate(test_cases, 1):
        print(f"\n{'─' * 50}")
        print(f"  测试 {i}: {test_input}")
        print(f"{'─' * 50}")

        try:
            response = handle_message(test_input, history)
            print(f"\n  输入: {test_input}")
            print(f"  回复: {response}")

            history.append({"role": "user", "content": test_input})
            history.append({"role": "assistant", "content": response})
            if len(history) > 30:
                history = history[-30:]
        except Exception as e:
            print(f"  ❌ 出错: {e}")

    print(f"\n{'=' * 60}")
    print("  测试完成")
    print(f"{'=' * 60}")

    # 打印数据库全部记录
    from db import query_transactions
    all_rows = query_transactions(limit=100)
    print(f"\n数据库中共 {len(all_rows)} 条记录：")
    for r in all_rows:
        sign = "+" if r["type"] == "收入" else "-"
        print(f"  [{r['id']}] {r['date']} {r['member']} | {r['category']} {sign}{r['amount']}元{r['note']}")


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        test_cases = [
            "今天女儿买了双登山鞋499元",
            "7月5日妈妈收到报销1000元",
            "看下这个月家里花钱明细",
            "这个月女儿花了多少钱？",
            # 录入一条旅游团记录用于测试删除
            "6月10日女儿报旅游团花了800元",
            "删除女儿报旅游团的费用",
        ]
        run_test(test_cases)
    else:
        interactive_mode()


if __name__ == "__main__":
    main()
