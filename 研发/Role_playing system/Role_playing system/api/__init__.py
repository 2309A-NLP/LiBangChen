# -*- coding: utf-8 -*-
"""
API 包入口
功能：导出 FastAPI 应用实例和应用工厂函数。
所有 API 路由和中间件通过此包暴露给外部使用。

导出：
  - app: 已配置好的 FastAPI 应用实例
  - create_app(): 应用工厂函数（用于创建新的应用实例）
"""

from .app_factory import app, create_app

__all__ = ["app", "create_app"]
