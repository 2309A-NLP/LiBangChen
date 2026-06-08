# SYSTEM4 相对 SYSTEM3 技术提升说明

## 1. 说明

本文档用于总结当前 `RAG-Q&A system4` 相对 `system3` 的主要技术提升点。

对比基线说明：

- `system3` 基线主要参考现有 `docs/USER_MANUAL.md`、`README.md` 中保留的旧版本说明与配置示例
- `system4` 现状以当前代码实现为准，重点参考 `app/`、`tests/`、`docs/TECHNICAL.md`

因此，本文档优先描述“已经落地到代码中的能力提升”，而不是只看文档描述。

## 2. 总体结论

`system4` 相比 `system3`，已经从“基础 PDF RAG 问答”升级为“查询理解 + 混合检索 + 重排 + 本地精确抽取 + 多轮会话 + 流式交互 + 后台预热”的完整问答系统。

核心提升体现在五个方向：

1. 检索能力更强
2. 问题理解更完整
3. 问答链路更工程化
4. 用户交互与系统可用性更好
5. 可维护性、可测试性更强

## 3. 技术提升总表

| 维度 | SYSTEM3 基线 | SYSTEM4 提升 |
|------|--------------|--------------|
| 检索策略 | 以关键词检索为主 | 支持关键词、向量、Hybrid RRF 混合检索 |
| 排序能力 | 无重排或默认关闭 | 支持 Cross-encoder Reranker，默认开启 |
| Query Understanding | 基础规则/在线理解能力 | 增加 local-first、online、fallback 混合策略 |
| 歧义处理 | 以直接回答为主 | 支持歧义检测、澄清追问、子问题拆解 |
| 问答编排 | 偏单轮调用 | 引入统一 Pipeline 编排层 |
| 结构化抽取 | 主要依赖 LLM 生成 | 支持财务指标/技术标准/获奖工程本地精确抽取 |
| 会话能力 | 偏单轮问答 | 支持 session_id、历史消息、上下文拼接 |
| 会话存储 | 简单或未抽象 | 支持 Memory / Redis 双后端 |
| 返回方式 | 同步问答为主 | 支持同步问答 + SSE 流式问答 |
| 启动体验 | 初始化阻塞风险较高 | 支持后台预热与预热状态查询 |
| 知识库管理 | 上传与基础问答 | 支持文档列表、分块查看、删除、检索范围切换 |
| 反馈闭环 | 较弱 | 支持反馈提交与持久化 |
| 工程质量 | 基础测试 | 补齐 Query Understanding / Retriever / API / Embedding 等测试 |

## 4. 主要提升点

### 4.1 检索架构升级

`system3` 文档示例仍保留：

- `RETRIEVER_TYPE=keyword`
- `RERANKER_ENABLED=false`

而 `system4` 当前代码默认配置已升级为：

- `retriever_type = hybrid_rrf`
- `reranker_enabled = true`

这意味着 `system4` 已形成如下检索链路：

1. 关键词检索召回
2. 向量检索召回
3. 使用 RRF 做融合
4. 使用 reranker 做精排

技术价值：

- 比纯关键词检索更能处理同义表达和语义近似问题
- 比单一路径召回更稳
- 对复杂问题、多表达方式问题、跨表述问题的命中率更高

对应实现：

- `app/core/config.py`
- `app/services/retrievers/factory.py`
- `app/services/retrievers/hybrid_rrf.py`
- `app/services/retrievers/milvus.py`
- `app/services/reranker.py`

### 4.2 Query Understanding 升级为混合理解策略

`system4` 的 Query Understanding 不再是单一方式，而是形成了分层策略：

- 规则理解
- 在线 LLM 理解
- `local-first`
- 在线失败后的 `fallback`

同时补齐了以下能力：

- 意图识别
- 语言识别
- 歧义检测
- 澄清问题生成
- 子问题拆解
- 检索提示构建

技术价值：

- 在简单问题上优先本地规则，降低延迟与成本
- 在复杂问题上可引入在线模型提升理解效果
- 在线能力异常时可自动回退，避免整个链路直接失败

对应实现：

- `app/services/query_understanding.py`

### 4.3 新增统一问答 Pipeline 编排层

`system4` 引入了 `QAPipelineService`，把问答流程显式拆成：

1. 生成或确认 `session_id`
2. 读取历史上下文
3. 执行 Query Understanding
4. 如需澄清则先返回追问
5. 执行检索、重排、答案生成
6. 写回会话历史

技术价值：

- 问答主链路更清晰
- 便于插入调试、监控、降级和新策略
- 便于后续继续扩展多轮对话和复杂编排

对应实现：

- `app/services/pipeline.py`

### 4.4 对结构化问题增加本地精确抽取

`system4` 在检索结果基础上，优先尝试本地精确抽取，而不是所有问题都直接交给 LLM。

当前已覆盖的典型场景：

- 财务指标类问题
- 技术标准类问题
- 获奖工程类问题

技术价值：

- 减少表格类问题的幻觉
- 提高确定性答案的准确率
- 降低无必要的模型调用成本
- 对财务问答、指标问答更友好

对应实现：

- `app/services/retrieval_generation.py`

### 4.5 多轮会话能力增强

`system4` 已具备标准化的会话层：

- 支持 `session_id`
- 支持会话历史读取
- 支持历史消息拼接进上下文
- 支持内存存储与 Redis 存储

技术价值：

- 从单轮文档问答升级到可持续对话
- 为“基于上文追问”“连续分析”提供基础设施
- 为后续接入生产级会话持久化做好准备

对应实现：

- `app/services/session_service.py`
- `app/services/session_store.py`
- `app/api/routes.py`

### 4.6 流式输出与后台预热增强了用户体验

`system4` 支持：

- `POST /api/query/stream` 的 SSE 流式问答
- 应用启动后的后台文档加载与检索预热
- `GET /api/document/warmup` 查询预热状态

技术价值：

- 启动时不必完全阻塞首页访问
- 用户可以更早感知系统状态
- 大模型问答等待期间可以采用流式反馈机制

对应实现：

- `app/main.py`
- `app/services/warmup_status.py`
- `app/api/routes.py`

### 4.7 知识库管理更完整

`system4` 已不只是“上传 PDF 然后提问”，还包括：

- 多 PDF 上传
- 检索范围选择
- 文档列表查询
- 文档分块查看
- 文档删除
- 删除后的状态重建与重新预热

技术价值：

- 知识库管理从“临时试用”提升到“可维护使用”
- 为后续多文档问答、精确范围控制提供基础

对应实现：

- `app/api/routes.py`
- `app/services/document_ingestion.py`

### 4.8 工程化和可测试性增强

`system4` 在工程组织上明显更完整：

- 使用 `AppContainer` 统一依赖装配
- Query Understanding、Retriever、Embedding、API 已有独立测试
- 支持反馈采集与持久化
- 支持 debug 信息返回

技术价值：

- 便于定位问题
- 便于持续迭代
- 降低后续维护成本

对应实现：

- `app/core/container.py`
- `app/services/feedback.py`
- `app/schemas/query.py`
- `tests/test_api_routes.py`
- `tests/test_query_understanding.py`
- `tests/test_retriever.py`
- `tests/test_embeddings.py`

## 5. 对业务效果的直接影响

从业务角度看，`system4` 的提升主要会体现在以下几个方面：

- 对复杂问法、同义表达、非标准提问的适应性更强
- 对财务表格类问题的准确率更高
- 多轮追问能力更强
- 首问体验与系统就绪状态更可控
- 知识库管理更适合持续使用而不只是演示

## 6. 当前仍需注意的遗留问题

虽然 `system4` 代码能力已有明显提升，但仓库内仍存在一些文档遗留：

- `README.md` 仍保留 `system3` 命名
- `docs/USER_MANUAL.md` 仍以 `system3` 为主
- 部分配置示例仍是旧默认值，和当前代码默认值不完全一致

这说明：

- `system4` 的代码能力已经领先于现有文档
- 如果对外汇报，应以当前实现和测试覆盖为准
- 后续建议补一次文档统一清理

## 7. 一句话总结

`system4` 相对 `system3` 的核心提升，不是单点功能增强，而是整体架构从“基础 RAG 问答”升级到了“具备查询理解、混合检索、重排、本地抽取、多轮会话、流式交互和后台预热能力的完整问答系统”。

## 8. 可直接汇报版本

可直接用于对内或对上汇报：

> `system4` 在 `system3` 基础上，完成了从基础文档问答到完整 RAG 问答系统的升级，重点增强了查询理解、混合检索、重排优化、结构化答案抽取、多轮会话、流式输出与后台预热等能力，整体提升了复杂问题处理能力、检索准确率、表格类问答稳定性和系统可用性。
