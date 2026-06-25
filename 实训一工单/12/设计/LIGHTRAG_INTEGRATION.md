# LightRAG 集成说明

本项目以 opt-in 方式接入 LightRAG sidecar。默认线上检索仍为 `hybrid`，只有请求显式传入 `lightrag_*` 时才会调用 LightRAG。

## 运行架构

- `:9621` LightRAG Server
- `:9622` Embedding Server，模型为 bge-m3
- `:11434` Ollama，模型为 qwen2.5:7b

LightRAG Server 的 embedding 模型必须与主 RAG 系统一致。`entity_types` / `relation_types` 不能通过 HTTP API 注入，需要在 LightRAG Server 或 SDK 侧配置。

## 检索模式

- `hybrid`: 主系统默认混合检索
- `fulltext`: 主系统全文检索
- `vector`: 主系统 Milvus 向量检索
- `keyword`: 主系统关键词检索
- `lightrag_mix`: LightRAG local + global
- `lightrag_local`: LightRAG 局部实体邻域
- `lightrag_global`: LightRAG 全局图谱摘要
- `lightrag_hybrid`: LightRAG 完整混合模式

## 实际 HTTP API 适配

- Insert: `POST /documents/text`
  - payload: `{ "text": "...", "file_source": "prospectus_2024" }`
- Batch insert: `POST /documents/texts`
  - payload: `{ "texts": ["..."], "file_sources": ["prospectus_2024"] }`
- Query: `POST /query/data`
  - payload: `{ "query": "...", "mode": "mix" }`
  - response: `data.entities` + `data.relationships`

`/query/data` 不支持 `file_ids`，所以主系统会在 `LightRAGRetriever` 层按返回结果里的 `file_source` / `file_id` / `file_path` / `source_id` 做后过滤。若响应没有来源字段，结果会保留，并在 metadata 标记 `lightrag_source_filter_unavailable=true`。

## 查询示例

```json
{
  "question": "公司实际控制人是谁？",
  "retrieval_mode": "lightrag_mix",
  "top_k": 8,
  "include_debug": true
}
```

## 建图流程

小样本验证，先取每份 PDF 前 50 页：

```bash
python scripts/lightrag_build_index.py --clean --force-rebuild --sample-pages 50 --validate-query "公司实际控制人是谁？" --validate-query "公司的主要股东有哪些？"
```

全量建图：

```bash
python scripts/lightrag_build_index.py --clean --force-rebuild --backup --validate-query "公司实际控制人是谁？"
```

脚本会写入 `reports/lightrag_index_report.json`。`--clean` 会清理 `LIGHTRAG_WORKING_DIR` 下除 `.env` / `.env.example` 之外的内容。

## 对比评估

准备问题集：

```json
[
  {"question": "公司实际控制人是谁？"},
  {"question": "公司与关联方之间有哪些持续性关联交易？"}
]
```

运行：

```bash
python scripts/compare_rag_lightrag.py --questions questions.json
```

输出：

- `reports/rag_lightrag_compare.json`
- `reports/rag_lightrag_compare.md`
