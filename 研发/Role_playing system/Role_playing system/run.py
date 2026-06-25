# -*- coding: utf-8 -*-
# !/usr/bin/env python
"""
项目启动入口
============
功能：提供多种启动模式，包括初始化数据库、测试聊天、启动服务、创建公网隧道等。
使用方式：python run.py [serve|init|test|tunnel|share]
"""

import os           # 操作系统接口（环境变量、路径操作）
import re           # 正则表达式（用于解析公网 URL）
import shutil       # 文件操作工具（查找可执行文件路径）
import socket       # 网络套接字（获取局域网 IP、检测端口占用）
import subprocess   # 子进程管理（启动 Cloudflare Tunnel）
import sys          # 系统参数（命令行参数、Python 解释器路径）
import time         # 时间工具（等待服务就绪）
import urllib.error     # HTTP 请求错误处理
import urllib.request   # HTTP 请求（检测服务是否就绪）

# 导入项目配置
from config import APP_CONFIG, KNOWLEDGE_SYNC_CONFIG, LOW_MEMORY_MODE_CONFIG, PUBLIC_ACCESS_CONFIG, RERANK_CONFIG
from console_utils import configure_console_encoding  # 控制台编码配置
from llm_settings import build_openai_client, load_llm_config, load_multimodal_llm_config  # LLM 配置管理

# 配置控制台编码（解决 Windows 终端中文乱码问题）
configure_console_encoding()


def init_system():
    """
    初始化系统：创建数据库表并填充内置知识库。
    
    执行流程：
    1. 初始化数据库（创建所有 ORM 表）
    2. 使用 DataCrawler 获取 6 个角色的内置种子数据（共 30 条）
    3. 使用 DataProcessor 清洗和分块文档
    4. 通过 ChatBot 将知识文档写入数据库
    """
    from chat_bot import ChatBot
    from data_crawler import DataCrawler
    from data_processor import DataProcessor
    from models import init_database

    print("Initializing database...")
    init_database()  # 创建所有数据库表
    print("Database ready.")

    print("Seeding built-in knowledge...")
    crawler = DataCrawler()       # 数据爬虫：提供内置种子知识
    processor = DataProcessor()   # 数据处理：清洗和分块
    chat = ChatBot()              # 聊天服务：写入数据库

    try:
        # 获取所有角色的内置知识数据
        documents = crawler.crawl_all_data()
        # 批量清洗和分块
        processed_docs = processor.process_batch(documents)
        # 逐条写入数据库
        for doc in processed_docs:
            chat.add_knowledge_document(
                doc["title"],
                doc["content"],
                doc["source"],
                doc["role_type"],
            )
        print(f"Seeded {len(processed_docs)} knowledge documents.")
    finally:
        chat.close()  # 确保关闭数据库会话


def test_chat():
    """
    端到端聊天测试：创建测试用户，对每个角色发送测试问题。
    
    测试角色：lawyer, stock_analyst, teacher, psychological_counselor, doctor, scientist
    每个角色使用预设的测试问题，验证 RAG 检索和 LLM 回答是否正常。
    """
    from chat_bot import ChatBot

    print("\n=== Chat Sanity Test ===")
    chat = ChatBot()

    try:
        # 创建测试用户
        user = chat.create_user("test_user", "123456", "test@example.com")
        print(f"Created user: {user.username} (ID: {user.id})")

        # 定义测试角色和对应的问题
        roles = ["lawyer", "stock_analyst", "teacher", "psychological_counselor", "doctor", "scientist"]
        test_questions = {
            "lawyer": "什么是劳动合同纠纷中的赔偿责任？",
            "stock_analyst": "A 股短线和长线投资分别该怎么看风险？",
            "teacher": "如何提高学生课堂参与度？",
            "psychological_counselor": "面对持续焦虑时有哪些基础应对方法？",
            "doctor": "高血压患者日常管理要注意什么？",
            "scientist": "如何理解科研中的可重复性问题？",
        }

        # 逐个角色测试
        for role_type in roles:
            print(f"\n--- Testing role: {role_type} ---")
            conversation = chat.create_conversation(user.id, role_type)
            question = test_questions[role_type]
            print(f"Question: {question}")
            reply = chat.chat(conversation.id, question)
            print(f"Reply: {reply}")
            time.sleep(1)  # 避免请求过快
    finally:
        chat.close()


def _get_local_ip() -> str:
    """
    获取当前设备的局域网 IP 地址。
    
    通过 UDP 连接到一个外部地址（8.8.8.8:80）来获取本机网卡 IP。
    这种方式不会真正发送数据包，只是获取路由信息。
    
    Returns:
        str: 局域网 IP 地址，获取失败时返回 "127.0.0.1"
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def _check_llm_runtime() -> None:
    """
    检查 LLM 后端运行状态。
    
    功能：
    1. 加载 LLM 配置（模型名称、API 地址）
    2. 构建 OpenAI 客户端
    3. 查询可用模型列表        
    4. 检查配置的模型是否可用
    
    如果 LLM 后端不可用，会打印错误信息但不会中断启动。
    """
    config = load_llm_config()
    model_name = config["model_name"]
    api_base = config["api_base"]

    print("Checking chat LLM backend...")
    print(f"Model: {model_name}")
    print(f"API base: {api_base}")

    try:
        # 构建 OpenAI 兼容客户端
        client = build_openai_client(config)
    except Exception as exc:
        print(f"LLM client init failed: {exc}")
        return

    try:
        # 查询后端可用模型列表
        models = client.models.list()
        model_ids = [getattr(item, "id", "") for item in (getattr(models, "data", None) or [])]
    except Exception as exc:
        print(f"Chat LLM backend query failed: {exc}")
        return

    if model_ids:
        print(f"Available models: {len(model_ids)}")
    else:
        print("No model list returned by backend.")

    # 检查配置的模型是否在可用列表中
    if model_name in model_ids:
        print(f"Configured model is available: {model_name}")
    else:
        print(f"Configured model is not listed by backend: {model_name}")
        for item in model_ids[:5]:
            print(f"- {item}")


def _is_local_port_in_use(port: int) -> bool:
    """
    检测本地端口是否已被占用。
    
    尝试连接到 127.0.0.1:port，如果连接成功说明端口已被占用。
    用于防止重复启动多个服务实例。
    
    Args:
        port: 要检测的端口号
        
    Returns:
        bool: True 表示端口已被占用
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.5)
            return sock.connect_ex(("127.0.0.1", port)) == 0
    except OSError:
        return False


def _wait_for_http_ready(url: str, timeout_seconds: int = 60) -> bool:
    """
    轮询 HTTP 端点直到返回正常响应。
    
    用于等待子进程启动的 API 服务就绪。
    最多等待 timeout_seconds 秒，每 1 秒轮询一次。
    
    Args:
        url: 要检测的 HTTP URL
        timeout_seconds: 超时时间（秒），默认 60 秒
        
    Returns:
        bool: True 表示服务已就绪
    """
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as response:
                if response.status < 500:
                    return True
        except (urllib.error.URLError, TimeoutError, OSError):
            time.sleep(1)
    return False


def _build_cloudflared_install_hint() -> str:
    """
    根据当前平台返回 cloudflared 安装提示。
    
    Windows: 使用 winget 安装
    Linux: 从 Cloudflare 官方源安装
    
    Returns:
        str: 安装命令或提示
    """
    if sys.platform.startswith("win"):
        return "winget install --id Cloudflare.cloudflared -e"
    if sys.platform.startswith("linux"):
        return "Install cloudflared from Cloudflare's Linux package or binary release."
    return "Install cloudflared and ensure it is available in PATH."


def _find_cloudflared_path() -> str | None:
    """
    查找 cloudflared 可执行文件路径。
    
    除了 PATH 环境变量外，还会检查 Windows 的常见安装位置
    （如 WinGet 安装目录），因为新安装后 PATH 可能未刷新。
    
    Returns:
        str | None: cloudflared 的完整路径，未找到返回 None
    """
    # 首先尝试从 PATH 环境变量查找
    direct = shutil.which("cloudflared")
    if direct:
        return direct

    # 如果 PATH 中找不到，检查 Windows 常见安装位置
    local_app_data = os.getenv("LOCALAPPDATA", "").strip()
    candidates = []
    if local_app_data:
        candidates.extend(
            [
                os.path.join(local_app_data, "Microsoft", "WinGet", "Links", "cloudflared.exe"),
                os.path.join(local_app_data, "Microsoft", "WindowsApps", "cloudflared.exe"),
                os.path.join(
                    local_app_data,
                    "Microsoft",
                    "WinGet",
                    "Packages",
                    "Cloudflare.cloudflared_Microsoft.Winget.Source_8wekyb3d8bbwe",
                    "cloudflared.exe",
                ),
            ]
        )

    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate
    return None


def _run_cloudflare_tunnel(target_url: str) -> None:
    """
    通过 Cloudflare Tunnel 将本地服务暴露到公网。
    
    支持两种模式：
    1. 命名隧道（配置了 tunnel_token）：持久化隧道，使用固定域名
    2. 临时隧道（未配置 token）：生成 trycloudflare.com 随机域名
    
    Args:
        target_url: 本地服务的 URL（如 http://127.0.0.1:8010）
    """
    cloudflared_path = _find_cloudflared_path()

    if not cloudflared_path:
        print("cloudflared is not installed.")
        print(f"Install hint: {_build_cloudflared_install_hint()}")
        return

    tunnel_token = PUBLIC_ACCESS_CONFIG["cloudflare_tunnel_token"]
    public_base_url = PUBLIC_ACCESS_CONFIG["base_url"]

    if tunnel_token:
        # 命名隧道模式：使用持久化 token
        print("Starting persistent Cloudflare Tunnel...")
        if public_base_url:
            print(f"Expected public URL: {public_base_url}")
        process_args = [cloudflared_path, "tunnel", "run", "--token", tunnel_token]
        public_url_pattern = None
    else:
        # 临时隧道模式：生成随机域名
        print("Starting temporary Cloudflare Tunnel...")
        process_args = [cloudflared_path, "tunnel", "--url", target_url]
        public_url_pattern = re.compile(r"https://[-a-z0-9]+\.trycloudflare\.com")

    print(f"Target URL: {target_url}")

    # 启动 cloudflared 子进程
    process = subprocess.Popen(
        process_args,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="ignore",
    )

    public_url = None

    try:
        # 监控子进程输出，提取公网 URL
        start_time = time.time()
        while True:
            line = process.stdout.readline() if process.stdout else ""
            if line:
                line = line.strip()
                # 尝试匹配临时隧道 URL
                if public_url_pattern:
                    matched = public_url_pattern.search(line)
                    if matched and not public_url:
                        public_url = matched.group(0)
                        print("")
                        print(f"公网地址：{public_url}")
                        print("按 Ctrl+C 停止公网访问。")
                        print("")
                # 命名隧道连接成功提示
                elif public_base_url and "Registered tunnel connection" in line and not public_url:
                    public_url = public_base_url
                    print("")
                    print(f"公网地址：{public_url}")
                    print("这是当前固定公网地址。")
                    print("按 Ctrl+C 停止公网访问。")
                    print("")
                elif tunnel_token and "Registered tunnel connection" in line and not public_url:
                    public_url = "(named tunnel connected; set PUBLIC_BASE_URL to display your fixed domain)"
                    print("")
                    print(f"公网地址：{public_url}")
                    print("按 Ctrl+C 停止公网访问。")
                    print("")

                # 打印错误信息
                if "error" in line.lower() or "failed" in line.lower():
                    print(line)

            # 检查子进程是否已退出
            if process.poll() is not None:
                break

            # 超时处理（60 秒未获取到 URL）
            if not public_url and time.time() - start_time > 60:
                print("Timed out while waiting for a public tunnel URL.")
                break

        # 等待子进程结束
        if process.poll() is None:
            process.wait()
    except KeyboardInterrupt:
        # 用户按 Ctrl+C 停止隧道
        print("\nStopping Cloudflare Tunnel...")
    finally:
        # 确保子进程被终止
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()


def serve():
    """
    启动 FastAPI 服务（主入口）。
    
    功能：
    1. 检测端口是否被占用（防止重复启动）
    2. 打印服务地址信息（本地、局域网）
    3. 检查 LLM 后端状态
    4. 启动 uvicorn 服务器
    
    支持低内存模式、知识同步、热重载等配置。
    """
    import uvicorn
    from app import app as fastapi_app

    host = APP_CONFIG["host"]       # 监听地址
    port = APP_CONFIG["port"]       # 监听端口
    reload_enabled = APP_CONFIG["reload"]  # 热重载开关
    lan_ip = _get_local_ip()        # 局域网 IP
    llm_config = load_llm_config()  # LLM 配置

    # 端口占用检测
    if _is_local_port_in_use(port):
        print(f"Port {port} is already in use. Refusing to start a second Python API process.")
        print("Stop the existing service first, then run `python run.py serve` again.")
        return

    print("Starting API service...")
    print(f"Browser URL: http://127.0.0.1:{port}")
    if host == "0.0.0.0":
        print(f"LAN URL: http://{lan_ip}:{port}")
    else:
        print(f"Bind URL: http://{host}:{port}")
    print(f"LLM backend: {llm_config['model_name']} / {llm_config['api_base']}")
    multimodal_config = load_multimodal_llm_config()
    print(
        "Multimodal backend: "
        f"{multimodal_config['model_name']} / {multimodal_config['api_base'] or '(not set)'}"
    )

    # 低内存模式提示
    if LOW_MEMORY_MODE_CONFIG["enabled"]:
        print("Low-memory mode: enabled")
        print(f"Rerank enabled: {RERANK_CONFIG['enabled']}")

    # 知识同步配置提示
    if KNOWLEDGE_SYNC_CONFIG["enabled"]:
        print(f"Knowledge sync interval: {KNOWLEDGE_SYNC_CONFIG['interval_minutes']} minutes")
    else:
        print("Knowledge sync: disabled")

    # 热重载 + 外部绑定警告
    if reload_enabled and host == "0.0.0.0":
        print("Warning: reload mode with external binding may create extra processes.")

    # 检查 LLM 后端
    _check_llm_runtime()
    
    # 启动 uvicorn 服务器
    if reload_enabled:
        uvicorn.run("app:app", host=host, port=port, reload=True)
    else:
        uvicorn.run(fastapi_app, host=host, port=port, reload=False)


def tunnel():
    """
    创建 Cloudflare 临时隧道。
    
    仅启动隧道，不启动 API 服务。
    需要先手动启动 API 服务（python run.py serve）。
    """
    port = APP_CONFIG["port"]
    target_url = f"http://127.0.0.1:{port}"
    _run_cloudflare_tunnel(target_url)


def share():
    """
    一键分享：自动启动 API 服务并通过 Cloudflare Tunnel 暴露到公网。
    
    流程：
    1. 检测端口是否已被占用
    2. 如果未启动，自动启动 API 服务子进程
    3. 等待服务就绪（最多 60 秒）
    4. 启动 Cloudflare Tunnel
    5. 用户按 Ctrl+C 停止时，自动清理子进程
    """
    port = APP_CONFIG["port"]
    target_url = f"http://127.0.0.1:{port}"
    service_process = None

    # 检测是否已有服务在运行
    if _is_local_port_in_use(port):
        print(f"Detected an existing local service on port {port}.")
    else:
        # 启动 API 服务子进程
        print("Starting API service for public sharing...")
        child_env = dict(**__import__("os").environ)
        child_env["APP_RELOAD"] = "false"  # 公网分享时禁用热重载
        service_process = subprocess.Popen([sys.executable, __file__, "serve"], env=child_env)
        
        # 等待服务就绪
        if not _wait_for_http_ready(target_url, timeout_seconds=60):
            print("The API service did not become ready in time.")
            if service_process.poll() is None:
                service_process.terminate()
                try:
                    service_process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    service_process.kill()
            return

    print("Local service is ready.")
    
    # 打印公网访问提示
    if PUBLIC_ACCESS_CONFIG["cloudflare_tunnel_token"]:
        if PUBLIC_ACCESS_CONFIG["base_url"]:
            print(f"已配置固定公网地址：{PUBLIC_ACCESS_CONFIG['base_url']}")
            print(
                "建议 APP_TRUSTED_HOSTS 配置为："
                f"localhost,127.0.0.1,{PUBLIC_ACCESS_CONFIG['base_url'].replace('https://', '').replace('http://', '').split('/')[0]}"
            )
        else:
            print("已检测到命名隧道 token。设置 PUBLIC_BASE_URL 后，日志会直接显示固定公网地址。")
    else:
        print("建议 APP_TRUSTED_HOSTS 配置为：localhost,127.0.0.1,*.trycloudflare.com")
    
    try:
        # 启动 Cloudflare Tunnel
        _run_cloudflare_tunnel(target_url)
    finally:
        # 清理 API 服务子进程
        if service_process and service_process.poll() is None:
            print("Stopping API service...")
            service_process.terminate()
            try:
                service_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                service_process.kill()


if __name__ == "__main__":
    """
    命令行入口：根据参数执行不同命令。
    
    用法：
        python run.py init    - 初始化数据库和知识库
        python run.py test    - 运行端到端聊天测试
        python run.py serve   - 启动 API 服务
        python run.py tunnel  - 创建 Cloudflare 隧道
        python run.py share   - 启动服务并创建公网隧道
    """
    command = sys.argv[1].lower() if len(sys.argv) > 1 else "serve"

    if command == "init":
        init_system()
    elif command == "test":
        test_chat()
    elif command == "serve":
        serve()
    elif command == "tunnel":
        tunnel()
    elif command == "share":
        share()
    else:
        print("Usage: python run.py [serve|init|test|tunnel|share]")
