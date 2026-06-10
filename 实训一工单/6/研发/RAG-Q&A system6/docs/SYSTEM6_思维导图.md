# SYSTEM6 思维导图

> 兼容方式：本文件优先使用 `Typora` 支持的 `Mermaid` 语法展示思维导图；如果当前 `Typora` 版本未正常渲染，可直接查看文末的 Markdown 层级版。

## Mermaid 思维导图

```mermaid
mindmap
  root((RAG-Q&A System6))
    系统定位
      PDF 文档问答
      RAG 检索增强生成
      招股书场景
      中英文问答
    前端
      index.html
        文档上传
        问答交互
        结果展示
      kb.html
        知识库管理
        文档列表
        分块查看
      app.js
        SSE 流式问答
        预热状态轮询
        会话管理
      styles.css
        页面样式
    后端
      app.main
        FastAPI 应用入口
        生命周期管理
      api.routes
        健康检查
        文档上传
        文档重载
        文档选择
        同步问答
        流式问答
        反馈提交
        会话查询
      core
        config.py
          环境变量配置
        container.py
          依赖注入
          服务装配
    核心服务
      document_ingestion.py
        PDF 解析
        文本分块
        表格页特殊处理
        文档状态维护
      query_understanding.py
        意图理解
        关键词提取
        语言识别
      retrieval_generation.py
        检索调用
        重排调用
        LLM 生成
        引用组装
      pipeline.py
        问答编排
        上下文拼接
        结果输出
      session_service.py
        会话保存
        历史读取
      feedback.py
        用户反馈存储
      warmup_status.py
        预热状态跟踪
    检索体系
      keyword
        兼容旧版关键词检索
      fulltext
        倒排索引
        短语匹配
        模糊匹配
        布尔检索
      milvus
        向量检索
        依赖嵌入模型
      hybrid_rrf
        全文加向量融合
        RRF 策略
        weighted 策略
        vote 策略
    模型能力
      embeddings.py
        bge-m3
        向量化
      reranker.py
        cross_encoder
        tfidf
        feedback
        llm
      llm
        openai_compatible.py
          OpenAI 兼容接口
        mock.py
          本地模拟
        factory.py
          客户端选择
    数据层
      data/source
        原始 PDF
      data/processed
        处理中间结果
        milvus_state.json
      Milvus
        向量存储
        索引数据
      Redis
        可选会话存储
    运行流程
      启动阶段
        run.py 启动服务
        构建容器
        加载已有 PDF
        后台预热检索器
      上传阶段
        保存文件
        解析文档
        生成分块
        设为当前检索范围
      问答阶段
        理解问题
        检索候选
        重排结果
        生成答案
        返回引用
      管理阶段
        查看知识库
        删除文档
        重建索引
    配置项
      LLM_PROVIDER
      LLM_MODEL
      QUERY_UNDERSTANDING_MODE
      RETRIEVER_TYPE
      HYBRID_FUSION_STRATEGY
      RERANKER_TYPES
      SESSION_STORE_BACKEND
    测试
      test_api_routes.py
      test_document_ingestion.py
      test_query_understanding.py
      test_retrieval_generation.py
      test_retriever.py
      test_reranker.py
      test_llm_integration.py
```

## Markdown 层级版

- RAG-Q&A System6
  - 系统定位
    - PDF 文档问答
    - RAG 检索增强生成
    - 招股书场景
    - 中英文问答
  - 前端
    - `app/static/index.html`：上传、问答、结果展示
    - `app/static/kb.html`：知识库管理
    - `app/static/app.js`：SSE、预热轮询、会话处理
    - `app/static/styles.css`：页面样式
  - 后端
    - `app/main.py`：FastAPI 入口
    - `app/api/routes.py`：API 路由
    - `app/core/config.py`：配置管理
    - `app/core/container.py`：依赖注入
  - 核心服务
    - `document_ingestion.py`：PDF 解析与分块
    - `query_understanding.py`：问题理解
    - `retrieval_generation.py`：检索与生成
    - `pipeline.py`：问答编排
    - `session_service.py`：会话管理
    - `feedback.py`：反馈存储
    - `warmup_status.py`：预热状态
  - 检索体系
    - `keyword`
    - `fulltext`
    - `milvus`
    - `hybrid_rrf`
  - 模型能力
    - Embedding：`bge-m3`
    - Reranker：`cross_encoder / tfidf / feedback / llm`
    - LLM：`openai_compatible / mock`
  - 数据层
    - `data/source/`：原始 PDF
    - `data/processed/`：处理结果
    - `milvus/`：向量库相关资源
    - `Redis`：可选会话存储
  - 运行流程
    - 启动：加载文档并后台预热
    - 上传：保存文件并重建分块
    - 问答：理解问题、检索、重排、生成
    - 管理：查看知识库、删除文档、重建索引
  - 关键配置
    - `LLM_PROVIDER`
    - `LLM_MODEL`
    - `RETRIEVER_TYPE`
    - `HYBRID_FUSION_STRATEGY`
    - `RERANKER_TYPES`
    - `SESSION_STORE_BACKEND`
  - 测试覆盖
    - API
    - 文档解析
    - 问题理解
    - 检索生成
    - 重排
    - LLM 集成
