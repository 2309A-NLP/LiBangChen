# 用户手册 — PDF文档问答系统

## 1. 系统简介

基于 RAG 技术的 PDF 文档问答工具。上传 PDF 文档后系统自动解析分块并建立索引，用自然语言提问即可获得带引用溯源的回答。

## 2. 快速开始

### 2.1 启动系统

```bash
cd E:\RAG-Q&A system1
python run.py
```

启动后系统自动解析 `data/source/` 下的 PDF 文件，并在后台预热检索索引。浏览器打开 `http://127.0.0.1:8000`。

### 2.2 上传 PDF 文档

1. 点击页面底部的 **"上传"** 区域选择 PDF 文件
2. 点击 **"上传"** 按钮
3. 等待解析完成，显示已建立的分块数量
4. 系统会在后台自动重建检索索引

也可以直接将 PDF 文件放入 `data/source/` 目录，然后通过 API 刷新：
- 调用 `POST /api/document/reload` 重新加载所有文档

### 2.3 提问

1. 在文本框输入问题
2. 点击 **"发送"** 或按 Enter
3. 系统通过 SSE 流式返回处理状态和回答
4. 回答下方显示引用来源（文档名 + 页码）

### 2.4 查看结果

- **回答内容**：对话区域左侧显示
- **引用来源**：回答下方的标签，格式为 `文档名 · 页码`
- **调试信息**：可通过请求参数开启

### 2.5 预热状态

系统启动后会在后台预热检索索引。页面会自动轮询预热状态：
- 预热中会显示提示
- 预热完成后正常使用
- 如 Milvus 未启动，预热会失败但不影响关键词检索

## 3. 知识库管理

访问 `http://127.0.0.1:8000/kb` 或点击主页的 **"知识库管理"** 链接。

### 3.1 查看文档列表

- **文档数量**和**总分块数**统计卡片
- 文档表格：名称、分块数、页码范围、内容预览

### 3.2 查看文档分块

点击 **"查看分块"** 弹出详情：
- 分块编号、ID、页码、字符数
- 完整文本内容

### 3.3 删除文档

1. 点击 **"删除"** 按钮
2. 确认后系统删除 PDF 文件及所有分块
3. 自动重建索引

> ⚠️ 删除不可恢复。

## 4. 多文档管理

- **上传多个文档**：逐一上传不同的 PDF
- **选择活跃文档**：通过 `POST /api/document/select` 指定检索范围
- **查看全部文档**：知识库管理页面查看所有已上传文档

## 5. 配置说明

### 5.1 检索器选择

编辑 `.env` 中的 `RETRIEVER_TYPE`：

| 值 | 说明 | 依赖 |
|----|------|------|
| `keyword` | 关键词检索（BM25） | 无，快速启动 |
| `milvus` | 向量检索 | 需要 Milvus + 嵌入模型 |
| `hybrid_rrf` | 混合检索 | 需要 Milvus + 嵌入模型 |

### 5.2 LLM 配置

```env
LLM_PROVIDER=openai_compatible
LLM_API_KEY=your_api_key
LLM_BASE_URL=your_base_url
LLM_MODEL=your_model
```

支持任何 OpenAI 兼容 API（OpenAI、DeepSeek、火山引擎 doubao 等）。

### 5.3 重排器

可选组件，提升检索质量：

```env
RERANKER_ENABLED=false
RERANKER_MODEL_PATH=path/to/bge-reranker-base
RERANKER_DEVICE=cpu
```

### 5.4 会话存储

默认内存存储，可切换 Redis：

```env
SESSION_STORE_BACKEND=redis
REDIS_URL=redis://127.0.0.1:6379/0
```

Redis 不可用时自动回退到内存。

## 6. 常见问题

### Q: 上传后提示"没有解析出可检索内容"？

- PDF 是扫描件（纯图片），不含可提取文字
- PDF 加密或有权限限制
- PDF 内容为空

### Q: 回答不准确？

- 换一种问法
- 在知识库管理页面检查分块是否正确
- 确认相关文档已上传且被选中

### Q: Milvus 连接失败？

Milvus 仅在 `RETRIEVER_TYPE=milvus` 或 `hybrid_rrf` 时需要。改为 `keyword` 即可不依赖 Milvus：

```env
RETRIEVER_TYPE=keyword
```

### Q: Reranker 报错 Unrecognized model？

`bge-reranker-base` 需要 `transformers>=4.36`。解决方式：
1. `pip install transformers>=4.36`
2. 或禁用：`RERANKER_ENABLED=false`

### Q: 启动时 Retriever warmup failed？

检索预热在后台执行，失败不影响启动。常见原因：
- Milvus 未启动（使用 keyword 模式可忽略）
- 嵌入模型路径不存在

### Q: 如何重新解析文档？

- 调用 `POST /api/document/reload`
- 或删除后重新上传

## 7. 页面导航

| 页面 | 地址 | 说明 |
|------|------|------|
| 问答主页 | http://127.0.0.1:8000/ | 上传、提问、查看回答 |
| 知识库管理 | http://127.0.0.1:8000/kb | 管理已上传文档 |
| API 文档 | http://127.0.0.1:8000/docs | FastAPI 接口文档 |
| 健康检查 | http://127.0.0.1:8000/api/health | 系统状态 |
| 预热状态 | http://127.0.0.1:8000/api/document/warmup | 检索索引预热进度 |
