# -*- coding: utf-8 -*-
"""
FastAPI 应用入口
================
功能：创建 FastAPI 应用实例，注册所有路由和中间件。
启动方式：直接运行此文件或通过 run.py serve 命令启动。
"""

# 从应用工厂导入已配置好的 FastAPI 应用实例
from api.app_factory import app
# 导入应用配置（host、port、reload 等参数）
from config import APP_CONFIG


if __name__ == "__main__":
    # 当直接运行此文件时，使用 uvicorn 启动开发服务器
    import uvicorn

    # 启动 uvicorn 服务器
    # host: 监听地址（默认 0.0.0.0）
    # port: 监听端口（默认 8010）
    # reload: 是否启用热重载（开发时启用）
    uvicorn.run(
        app,
        host=APP_CONFIG["host"],      # 服务器监听地址
        port=APP_CONFIG["port"],      # 服务器监听端口
        reload=APP_CONFIG["reload"]   # 是否启用热重载
    )
