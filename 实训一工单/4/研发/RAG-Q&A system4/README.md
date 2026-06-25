# Prospectus Q&A Framework

基于 RAG（检索增强生成）的 PDF 文档问答系统。当前版本聚焦 3 条主线能力：

- 支持上传一个或多个 PDF 并自动解析
- 支持知识库管理与引用溯源问答
- 支持中文提问/中文回答、英文提问/英文回答

## 当前版本能力

### 1. PDF 上传与解析

- 首页支持一次选择多个 PDF 文件上传
- 上传后自动保存到 `data/source/`
- 系统自动解析 PDF 文本并按页面内容分块
- 普通文本页与表格页采用不同分块策略
- 上传完成后，系统会在首页输出框提示解析结果

### 2. 当前检索范围

- 首页保持简洁，不增加“手动选择知识库提问”的额外控件
- 默认行为是：本次上传的文档会自动成为当前提问的检索范围
- 如果系统启动时已经存在历史 PDF，则首页初始提问范围默认为全部已加载文档
- 如需精细指定检索范围，可调用 `POST /api/document/select`

### 3. 文档问答

- 支持同步问答接口 `POST /api/query`
- 支持 SSE 流式问答接口 `POST /api/query/stream`
- 返回答案时附带引用来源
- 引用信息包含：
  - 文档名
  - 页码
  - 片段摘要

### 4. 中英文问答

- 自动检测用户问题语言
- 中文问题优先返回中文答案
- 英文问题优先返回英文答案
- Query Understanding 与回答生成都已接入语言识别

说明：

- 当前英文问答已可用
- 但检索规则与部分关键词逻辑仍然偏中文语料，因此英文问题整体效果可能弱于中文

### 5. 知识库管理

知识库页地址：

`http://127.0.0.1:8000/kb`

支持：

- 查看全部已上传文档
- 查看每个文档的分块详情
- 删除指定文档

删除文档后，系统会自动重建内存状态并重新预热检索器。

### 6. 后台初始化与预热

- 系统启动时首页会先可访问
- PDF 加载与检索器预热在后台线程执行
- 首页会轮询预热状态并在输出框显示提示

## 项目结构

```text
RAG-Q&A system3/
├── app/
│   ├── main.py
│   ├── api/routes.py
│   ├── core/
│   ├── schemas/query.py
│   ├── services/
│   └── static/
├── data/
│   ├── source/
│   └── processed/
├── docs/
│   ├── TECHNICAL.md
│   └── USER_MANUAL.md
├── tests/
├── milvus/
├── requirements.txt
└── run.py
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置 `.env`

示例：

```env
LLM_PROVIDER=openai_compatible
LLM_API_KEY=your_api_key
LLM_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
LLM_MODEL=doubao-seed-1-8-251228

QUERY_UNDERSTANDING_MODE=online
RETRIEVER_TYPE=keyword
RERANKER_ENABLED=false
```

### 3. 启动系统

```bash
cd "C:\Users\26332\Desktop\工单\RAG工单\RAG-Q&A system3"
python run.py
```

### 4. 访问地址

- 首页：`http://127.0.0.1:8000/`
- 知识库管理：`http://127.0.0.1:8000/kb`
- API 文档：`http://127.0.0.1:8000/docs`

## 首页使用流程

1. 点击“上传”区域，选择一个或多个 PDF
2. 点击“上传”按钮
3. 等待系统完成解析
4. 在输出框中查看解析完成提示与当前检索范围
5. 输入中文或英文问题
6. 点击“发送”获取答案

## API 概览

### 文档相关

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查 |
| GET | `/api/document/status` | 当前文档加载状态 |
| GET | `/api/document/warmup` | 后台预热状态 |
| POST | `/api/document/upload` | 上传一个或多个 PDF |
| POST | `/api/document/reload` | 重新加载全部文档 |
| POST | `/api/document/select` | 指定当前检索文档范围 |

### 知识库管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/kb/documents` | 文档列表 |
| GET | `/api/kb/documents/{source_id}/chunks` | 查看指定文档的全部分块 |
| DELETE | `/api/kb/documents/{source_id}` | 删除指定文档 |

### 问答相关

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/query` | 同步问答 |
| POST | `/api/query/stream` | 流式问答 |
| GET | `/api/session/{session_id}` | 会话历史 |
| POST | `/api/feedback` | 提交反馈 |

## 当前版本的明确取舍

当前版本明确不做：

- 首页知识库手动选择器

原因：

- 你前面明确要求首页保持简单
- 当前版本优先保证“上传 → 解析 → 提问”这条主流程稳定
- 精细检索范围控制暂时保留给 API

## 测试

```bash
python -m pytest tests/test_api_routes.py tests/test_query_understanding.py
```

## 常见问题

### 上传时报 `Field required: file`

通常是浏览器连接到了旧服务进程。重启 `python run.py` 后重新打开首页即可。

### 上传成功但没有解析出内容

可能原因：

- PDF 为扫描件，仅包含图片
- PDF 被加密或存在权限限制
- PDF 内容为空

### 英文问题效果不稳定

当前英文回答能力已经接入，但检索规则仍偏中文语料，因此英文问题效果可能不如中文问题稳定。
