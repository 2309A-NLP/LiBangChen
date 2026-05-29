# 项目架构思维导图

下面这份脑图基于 [CODE_ANNOTATION_AND_ARCHITECTURE.md](./CODE_ANNOTATION_AND_ARCHITECTURE.md) 和 [technical_overview.md](./technical_overview.md) 整理，适合快速理解项目整体结构。

```mermaid
mindmap
  root((角色扮演系统))
    前端
      单页应用
        frontend/index.html
      主要能力
        登录注册
        角色选择
        会话历史
        文件上传
        聊天对话
        管理与状态展示
    API层 FastAPI
      app_factory.py
        创建应用
        注册路由
        中间件
        生命周期
      dependencies.py
        用户认证
        管理员校验
        限流
        错误处理
      schemas.py
        请求模型
        响应模型
      services.py
        启动初始化
        知识同步调度
        Milvus状态
      routes
        system.py
          健康检查
          角色列表
        auth.py
          注册
          登录
        conversations.py
          创建会话
          历史消息
          聊天接口
        files.py
          上传文件
          删除文件
          文件分析
        knowledge.py
          知识同步
          检索配置
          Milvus状态
        llm.py
          LLM配置
          连接测试
          运行诊断
    业务层
      chat_bot.py
        用户管理
        会话管理
        消息存储
        文件管理
        知识库写入
        聊天总编排入口
      rag_chain.py
        检索查询构建
        Prompt组装
        LLM调用
        降级策略
        输出规范化
        文件问答模式
      prompts.py
        律师
        股票分析师
        教师
        心理咨询师
        医生
        科学家
        全能型人格
      llm_settings.py
        多来源加载配置
        OpenAI兼容客户端
        连接测试
        运行诊断
      security.py
        密码哈希
        Token签发
        Token校验
        限流器
      config.py
        应用配置
        数据库配置
        Milvus配置
        检索配置
        Rerank配置
        角色定义
    检索与知识处理
      vector_store.py
        Milvus dense检索
        BM25词法检索
        RRF融合
        Rerank重排
        用户文件向量检索
      data_processor.py
        文本清洗
        中文分词
        关键词提取
        分块
      knowledge_sync.py
        扫描知识源
        触发同步
      knowledge_sync_service.py
        同步业务入口
      knowledge_sources.py
        知识源目录管理
      file_service.py
        PDF解析
        OCR
        DOCX/XLSX/CSV/JSON/TXT/MD解析
        文件分块
        向量同步
      worker
        ocr_worker.py
        rerank_worker.py
    数据层
      SQLite 或 MySQL
        User
        Role
        Conversation
        Message
        UploadedFile
        UserDocumentChunk
        KnowledgeDocument
        ChatRequestLog
      Milvus
        knowledge_base
        user_documents
      Redis
        短期记忆
        最近会话上下文
      文件系统
        uploads
        knowledge_sources
        generated
        logs
        models
    关键流程
      聊天流程
        用户请求
        ChatBot校验与取历史
        RAGChain检索
        Prompt组装
        LLM回复
        消息持久化
      文件上传流程
        保存文件
        提取文本
        文本分块
        SQLite落库
        Milvus向量化
      知识同步流程
        扫描知识目录
        清洗分块
        写入数据库
        写入Milvus
    外部依赖
      OpenAI兼容模型接口
      DeepSeek或其他聊天模型
      多模态模型接口
      Milvus
      Redis
      OCR与Embedding模型
    评测与运维
      eval_ragas_019.py
      ragas_project_suite
      JMeter压测
      docker-compose.milvus.yml
      deploy目录
```

## 快速阅读顺序

1. 先看 `前端 → API层 → 业务层`，理解请求是怎么进来的。
2. 再看 `检索与知识处理`，理解 RAG 为什么会慢、为什么会命中知识库。
3. 最后看 `数据层` 和 `关键流程`，理解数据落在哪里、链路怎么走。

## 你现在最常关心的部分

- 聊天入口：`conversations.py -> chat_bot.py -> rag_chain.py`
- 检索核心：`vector_store.py`
- 文件问答：`files.py -> file_service.py -> vector_store.py`
- 模型配置：`.env + llm_settings.py + config.py`
- 知识库同步：`knowledge_sync.py + knowledge_sync_service.py`
