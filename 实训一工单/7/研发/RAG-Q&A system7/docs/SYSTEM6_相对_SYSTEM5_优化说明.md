# RAG Q&A SYSTEM6 相对 RAG Q&A SYSTEM5 优化说明

## 1. 文档目的

本文用于说明 `RAG Q&A SYSTEM6` 相对于 `C:\Users\26332\Desktop\工单\RAG工单\RAG-Q&A system5` 的主要优化点，便于项目汇报、版本说明和阶段验收。

## 2. 对比口径

- 对比基线：`RAG-Q&A system5`
- 当前版本：`RAG-Q&A system6`
- 对比依据：当前仓库中的代码、配置、前端页面、测试和说明文档
- 本文只描述已经在代码中落地的优化，不将尚未实现的规划项写入结论

## 3. 总体结论

相较于 `SYSTEM5`，`SYSTEM6` 的核心提升不再是单点功能补丁，而是把检索链路升级成了“多检索模式 + 多融合策略 + 多重排算法 + 可切换文档解析方式”的可配置框架。

可以概括为四点：

- 检索模式从 `keyword / milvus / hybrid_rrf` 扩展为 `keyword / fulltext / vector(milvus) / hybrid`
- 混合检索从固定 RRF 升级为支持 `rrf / weighted / vote` 的通用融合框架
- 重排能力从单一 `cross_encoder` 升级为可串联的多重排体系
- PDF 摄取从单一路径 `pypdf` 扩展为 `pypdf / doubao / auto` 三种解析模式

## 4. 主要优化点

### 4.1 新增全文检索能力

`SYSTEM6` 新增了独立的 `FullTextRetriever`，在 `app/services/retrievers/fulltext.py` 中实现，补齐了 `SYSTEM5` 缺少标准全文检索层的问题。

具体能力包括：

- 基于倒排索引组织文档片段
- 支持布尔查询：`AND / OR / NOT`
- 支持短语检索：如 `"工业软件"`
- 支持模糊匹配：如 `主菅业务~`
- 支持多字段检索：标题、摘要、正文分别计分
- 支持字段权重配置：`FULLTEXT_TITLE_WEIGHT`、`FULLTEXT_SUMMARY_WEIGHT`、`FULLTEXT_BODY_WEIGHT`

这意味着 `SYSTEM6` 在“关键词明确、字段偏好明显、需要布尔筛选”的问题上，比 `SYSTEM5` 更精确，也更容易调优。

### 4.2 混合检索从固定 RRF 升级为通用融合框架

`SYSTEM5` 的混合检索主要依赖 `hybrid_rrf`。`SYSTEM6` 在兼容旧命名的同时，将其升级为通用 `HybridRetriever`。

主要变化包括：

- 支持选择文本检索侧使用 `keyword` 或 `fulltext`
- 支持三种融合策略：
  - `rrf`
  - `weighted`
  - `vote`
- 支持融合相关配置：
  - `HYBRID_TEXT_RETRIEVER`
  - `HYBRID_FUSION_STRATEGY`
  - `HYBRID_FULLTEXT_WEIGHT`
  - `HYBRID_VECTOR_WEIGHT`
  - `HYBRID_CANDIDATE_MULTIPLIER`
  - `HYBRID_VOTE_MIN_AGREEMENT`
- 融合结果会携带策略和分量信息，便于调试和验收

这使得 `SYSTEM6` 的混合检索不再是固定实现，而是可实验、可比较、可配置的正式能力。

### 4.3 向量检索融入统一检索框架

`SYSTEM6` 保留了 `SYSTEM5` 的 Milvus 向量检索能力，并做了统一化和工程化增强：

- 在检索器工厂中支持 `vector` 和 `milvus` 两种等价入口
- 允许按请求动态切换到向量检索模式
- 向量检索可作为混合检索中的独立一路参与融合
- Milvus 管理逻辑改为通过 `MilvusClient` 完成集合和索引管理
- 对集合失效、索引状态异常等场景保留自动重建逻辑

因此，`SYSTEM6` 的向量检索不只是“可用”，而是已经成为统一检索框架中的标准组件。

### 4.4 重排能力从单一模型扩展为多算法组合

`SYSTEM5` 的重排能力主要是单一 `cross_encoder`。`SYSTEM6` 在 `app/services/reranker.py` 中扩展出了完整的重排器体系。

当前支持的重排策略包括：

- `cross_encoder`
- `tfidf`
- `feedback`
- `llm`

其中：

- `cross_encoder`：适合高精度精排
- `tfidf`：适合轻量、离线、本地化部署
- `feedback`：基于历史反馈做自适应加权
- `llm`：支持调用在线模型进行语义重排，失败时自动回退为启发式模式

同时，`SYSTEM6` 支持通过 `RERANKER_TYPES=tfidf,feedback` 这类配置串联多个重排器，形成“召回后多阶段重排”的处理链路。

### 4.5 请求级检索与重排控制能力增强

`SYSTEM6` 在请求模型和检索生成流程中补充了按次控制能力，前后端都能使用。

新增请求字段包括：

- `retrieval_mode`
- `score_threshold`
- `reranker_enabled`
- `reranker_types`

后端能力变化包括：

- 单次请求可切换 `fulltext / vector / hybrid / keyword`
- 单次请求可关闭重排
- 单次请求可指定重排策略列表
- 检索后可按分数阈值过滤低质量候选

这意味着 `SYSTEM6` 已经支持“同一套服务、不同检索方案”的对比验证，而不是只能依赖全局 `.env`。

### 4.6 调试信息与可观测性增强

`SYSTEM6` 在 `RetrievalGenerationService` 中补充了更清晰的调试元数据输出，便于排查和验收。

新增调试字段包括：

- `retriever_type`
- `requested_retrieval_mode`
- `score_threshold`
- `reranker_enabled`
- `reranker_strategies`
- `retrieved_chunk_count`

这能直接回答以下问题：

- 这次请求走的是全文、向量还是混合检索
- 当前是否启用了重排
- 实际启用的是哪几种重排策略
- 检索候选在进入生成前有多少条

### 4.7 PDF 文档摄取链路增强

`SYSTEM5` 主要依赖 `pypdf` 文本提取。`SYSTEM6` 在 `app/services/document_ingestion.py` 中新增了可切换的解析提供方。

新增能力包括：

- `PDF_PARSER_PROVIDER=pypdf`
- `PDF_PARSER_PROVIDER=doubao`
- `PDF_PARSER_PROVIDER=auto`

当使用 `doubao` 或 `auto` 时，系统会：

- 使用 `pypdfium2 + pillow` 将 PDF 页面渲染为图片
- 复用现有 OpenAI 兼容接口配置调用 Doubao/Ark
- 要求模型输出带页码标记的 Markdown
- 对表格、图表、流程图、组织结构图等内容输出可检索描述

这使得 `SYSTEM6` 对图片型页面、图表型页面和复杂版面文档的适配能力明显强于 `SYSTEM5`。

### 4.8 前端交互与接口体验同步升级

`SYSTEM6` 首页已新增与后端能力对应的操作入口，前端不再只是简单问答框。

可见增强包括：

- 首页增加检索模式卡片，支持选择 `hybrid`、`fulltext` 等模式
- 增加重排开关和重排策略多选
- 请求体会带上 `retrieval_mode`、`score_threshold`、`reranker_enabled`、`reranker_types`
- SSE 流式接口对 Milvus 不可用场景给出更明确的错误提示

这说明 `SYSTEM6` 的优化不只停留在服务端实现，而是已经同步映射到用户操作层。

### 4.9 启动与运行体验优化

`SYSTEM6` 对运行方式做了小幅但实用的优化：

- `run.py` 默认端口调整为 `8010`
- 启动时会自动寻找可用端口，避免端口冲突直接启动失败
- `README.md`、`TECHNICAL.md`、`.env.example` 已同步补充新配置项和新能力说明

## 5. 对原始需求的对应关系

结合本次需求，`SYSTEM6` 已具备以下三类核心能力：

### 5.1 向量检索（召回 + 重排）

已支持：

- Milvus 向量召回
- 向量检索与混合检索切换
- 向量召回后接入 `cross_encoder / tfidf / feedback / llm` 重排
- 单次请求控制是否启用重排和使用哪些重排策略

### 5.2 全文检索

已支持：

- 倒排索引
- 布尔查询
- 短语匹配
- 模糊匹配
- 标题 / 摘要 / 正文多字段检索

### 5.3 混合检索

已支持：

- 文本检索 + 向量检索双路并行
- `rrf / weighted / vote` 三种融合策略
- 文本侧选择 `keyword` 或 `fulltext`
- 权重、候选倍数、投票阈值等融合参数配置

## 6. 测试与验证

围绕本次优化，代码中已补充对应测试，覆盖内容包括：

- 全文检索的短语匹配、模糊匹配和多字段命中
- 混合检索的 `rrf / weighted / vote` 融合行为
- 多重排策略的行为与串联顺序
- 请求级检索模式切换、阈值过滤、重排开关
- API 路由对新字段的透传和调试信息输出

本次已执行的验证命令为：

```bash
pytest tests\test_retriever.py tests\test_reranker.py tests\test_retrieval_generation.py tests\test_api_routes.py -q
```

验证结果：

```text
29 passed in 0.99s
```

此外，本次还修正了一个测试稳定性问题：避免 `test_milvus_retriever_rebuilds_collection_on_stale_local_path_error` 受到本地 `milvus_state.json` 缓存签名影响。

## 7. 可对外使用的版本总结

如果用一句话概括，可以表述为：

> `RAG Q&A SYSTEM6` 在 `SYSTEM5` 的基础上，将检索层升级为支持全文检索、向量检索、混合检索和多重排算法的可配置 RAG 框架。

如果用于项目汇报，也可以表述为：

> 相比 `SYSTEM5`，`SYSTEM6` 的核心价值在于：检索模式更多样、融合策略更灵活、重排算法更丰富、文档解析能力更强、调试与验收更方便。

## 8. 结论

`SYSTEM6` 相对 `SYSTEM5` 的升级是体系化的，不是简单增加一个检索按钮，而是完成了以下三层演进：

- 从“关键词/向量检索”扩展到“关键词/全文/向量/混合”的完整检索矩阵
- 从“固定 RRF + 单一重排器”扩展到“多融合策略 + 多重排算法”的可配置链路
- 从“单一路径 PDF 文本抽取”扩展到“文本抽取 + 视觉解析”的更强文档摄取体系

因此，可以将 `SYSTEM6` 定义为 `SYSTEM5` 的“检索架构增强版”和“可配置实验版”。
