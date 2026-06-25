# RAGAS 0.1.9 项目测评教程

这份教程适配当前仓库，默认评测入口不是 `/api/chat`，而是直接调用项目内部的 `ChatBot + vector_store.search()`。

这样做的原因很直接：

- `chat_bot.py` 返回的是回答结果，不直接返回 RAGAS 需要的 `contexts`
- `vector_store.py` 里已经有原始检索结果
- `rag_chain.py` 会把检索结果拼成大段字符串，不利于 RAGAS 逐条评估上下文质量

## 一、当前仓库里的关键入口

- 对话生成：`chat_bot.py`
- 原始检索：`vector_store.py`
- RAG 组装链路：`rag_chain.py`
- 在线模型配置：`llm_settings.py`

## 二、已经生成好的文件

- 评测脚本：`eval_ragas_019.py`
- 手工测试集：`evals/testset_manual.jsonl`
- 输出结果：`evals/ragas_result_019.csv`
- 评测输入留档：`evals/ragas_inputs_019.jsonl`

## 三、建议先评哪些指标

当前项目建议优先看这几个指标：

- `faithfulness`
  检查回答是否被检索内容支撑，适合看幻觉问题。
- `context_precision`
  检查检索回来的上下文是否真的有用，适合看召回噪声。
- `answer_relevancy`
  检查回答是否切题。这个指标需要 embeddings。
- `context_recall`
  检查检索上下文是否把标准答案需要的信息找全。这个指标需要 `ground_truth`。

如果你只是先跑通流程，最小闭环就是：

```python
[faithfulness, context_precision]
```

## 四、运行方法

在项目根目录执行：

```powershell
cd C:\Users\26332\roleplay_system
D:\Anaconda\envs\n2\python.exe eval_ragas_019.py
```

## 五、脚本默认行为

脚本默认会：

- 读取 `evals/testset_manual.jsonl`
- 调用项目内部 `ChatBot` 生成真实回答
- 同时调用 `vector_store.search()` 抽取原始 `contexts`
- 用当前项目的 LLM 配置作为 RAGAS judge 模型默认值
- 默认使用同步评测，避免 Windows 下异步事件循环告警
- 自动保存明细结果到 `evals/ragas_result_019.csv`

## 六、可选环境变量

如果你不想复用项目当前模型配置，可以临时覆盖：

```powershell
$env:RAGAS_MODEL="Qwen/Qwen3-VL-32B-Instruct"
$env:RAGAS_API_BASE="https://api.siliconflow.cn/v1"
$env:RAGAS_API_KEY="你的在线APIKey"
$env:RAGAS_MAX_TOKENS="2048"
```

如果你本地 embedding 模型不在默认位置，可以设置：

```powershell
$env:EMBEDDING_MODEL_PATH="C:\Users\26332\.cache\modelscope\hub\models\BAAI\bge-m3"
```

如果你确实想改成异步评测，可以再加：

```powershell
$env:RAGAS_ASYNC="1"
```

## 七、测试集怎么扩充

`evals/testset_manual.jsonl` 每一行是一条 JSON，对应一个测试问题。建议先按角色各补 5 到 10 条。

字段说明：

- `role_type`
  必须与系统角色值一致，如 `lawyer`、`doctor`、`scientist`
- `question`
  用户真实提问
- `ground_truth`
  你认可的标准答案。没有时可以先留空，但这样会跳过 `context_recall`

示例格式：

```json
{"role_type":"doctor","question":"成年人连续发热两天并伴有咳嗽，哪些情况提示需要尽快去医院就诊？","ground_truth":"若出现高热持续不退、呼吸困难、胸痛、意识异常、血氧下降、明显脱水、基础病加重，或老人儿童孕妇等特殊人群症状明显，应尽快到正规医疗机构就诊。"}
```

## 八、怎么看分数

- `faithfulness` 低
  说明回答里有内容没有被检索上下文支撑。
- `context_precision` 低
  说明检索到了较多无关内容。
- `context_recall` 低
  说明检索上下文没有把正确答案所需的信息找全。
- `answer_relevancy` 低
  说明回答不够切题，或者答得太空泛。

这些分数更适合做版本对比，不建议只看单次绝对值。

## 九、对你当前项目的实际建议

- 先重点评 `lawyer`、`doctor`、`scientist`、`psychological_counselor`
- 每个角色先整理 5 到 10 条高质量问题
- 第一轮只跑 `faithfulness + context_precision`
- 第二轮补齐 `ground_truth` 后，再看 `context_recall`

## 十、一个现实提醒

如果你用稳定的在线大模型做 judge 模型，通常更适合做版本对比和基线评测。

## 参考资料

- RAGAS 0.1 系列评测文档: https://docs.ragas.io/en/v0.1.21/getstarted/evaluation.html
- RAGAS 0.1 系列自定义 LLM / Embeddings: https://docs.ragas.io/en/v0.1.21/howtos/customisations/bring-your-own-llm-or-embs.html
- RAGAS 0.1 系列 LangChain 集成: https://docs.ragas.io/en/v0.1.21/howtos/integrations/langchain.html
