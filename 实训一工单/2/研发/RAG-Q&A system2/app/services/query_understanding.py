"""
查询理解模块
============
对用户输入的问题进行意图识别、歧义检测、问题拆分和检索提示构建。

提供三种实现策略：
1. RuleBasedQueryUnderstandingService —— 纯规则，零外部依赖，速度快。
2. OpenAICompatibleQueryUnderstandingClient —— 调用在线 LLM 获取理解结果。
3. QueryUnderstandingService —— 顶层门面，根据配置自动选择在线/本地/混合策略。
"""
from __future__ import annotations

import json
import re
import socket
from urllib import error, request

from app.core.config import Settings
from app.schemas.query import QueryUnderstandingResult


class QueryUnderstandingRemoteError(RuntimeError):
    """在线查询理解服务调用失败时抛出的异常。"""
    pass


class RuleBasedQueryUnderstandingService:
    """基于规则的查询理解服务。

    不依赖任何外部模型，通过关键词匹配、正则表达式和同义词表
    完成意图识别、歧义检测、问题拆分和检索提示构建。
    """
    INTENT_KEYWORDS = {
        "financial_metric": ["营收", "收入", "利润", "毛利", "毛利率", "现金流", "负债", "资产"],
        "risk_factor": ["风险", "不确定", "隐患", "挑战"],
        "business_overview": ["主营业务", "业务模式", "产品", "客户", "供应商"],
        "shareholding": ["股东", "持股", "控股", "实际控制人"],
        "timeline": ["时间", "什么时候", "报告期", "年份", "日期"],
        "industry_chain": ["上游", "下游", "产业链", "供应链"],
        "technical_standard": ["技术标准", "标准", "规范"],
        "competition": ["竞争对手", "同行", "竞争格局"],
        "award_project": ["工程", "项目", "获奖", "一等奖", "科技进步奖", "参与的哪个工程"],
    }
    AMBIGUITY_TERMS = ["它", "他们", "这个", "那个", "上述", "该公司", "报告期"]
    CLARIFICATION_REQUIRED_TERMS = {"它", "他们", "这个", "那个", "上述"}
    DECOMPOSE_SPLITTERS = ["以及", "并且", "同时", "和", "，", "。"]
    SECTION_MAP = {
        "financial_metric": ["财务会计信息", "管理层讨论与分析", "销售情况和主要客户", "按客户群体划分的销售情况"],
        "risk_factor": ["风险因素"],
        "business_overview": ["业务与技术", "主营业务"],
        "shareholding": ["发行人基本情况", "股本结构"],
        "timeline": ["重大事项", "发行概况"],
        "industry_chain": ["行业基本情况", "电子信息行业上下游"],
        "technical_standard": ["技术先进性", "核心技术", "发行人技术先进性"],
        "competition": ["行业及主要竞争对手", "竞争优势与劣势"],
        "award_project": ["技术先进性", "科研实力和成果", "主营业务"],
        "general_information": ["发行人基本情况", "招股说明书摘要"],
    }
    ABSTRACT_GOAL_MAP = {
        "financial_metric": "定位财务指标、金额、占比或表格数据，并按问题要求组织回答",
        "risk_factor": "定位风险章节并总结核心风险点",
        "business_overview": "定位业务介绍并归纳公司经营情况",
        "shareholding": "定位股权结构并说明关键主体关系",
        "timeline": "定位时间信息并按时间顺序回答",
        "industry_chain": "定位行业上下游描述并提取相关企业或角色",
        "technical_standard": "定位技术标准或规范内容并明确名称",
        "competition": "定位竞争格局与主要竞争对手信息并归纳回答",
        "award_project": "定位获奖工程或项目名称并明确奖项对应关系",
        "general_information": "从招股说明书中定位相关事实并作答",
    }
    DOMAIN_PHRASES = [
        "主营业务",
        "业务模式",
        "营收",
        "收入",
        "利润",
        "毛利率",
        "现金流",
        "负债",
        "资产",
        "风险因素",
        "实际控制人",
        "股权结构",
        "报告期",
        "行业基本情况",
        "电子信息行业",
        "产业链",
        "供应链",
        "上游",
        "下游",
        "技术标准",
        "技术规范",
        "参与制定",
        "核心技术",
        "竞争对手",
        "竞争格局",
        "供应商",
        "客户",
        "军用",
        "国防",
        "军队",
        "军用领域",
        "国防领域",
        "民用领域",
        "客户群体",
        "按客户群体划分的销售情况",
        "销售情况和主要客户",
        "前五名客户",
        "前五大客户",
        "销售金额",
        "占比",
        "金额",
        "国家科技进步一等奖",
        "科技进步一等奖",
        "一等奖",
        "获奖工程",
        "获奖项目",
        "一体化工程",
        "工程",
        "项目",
    ]
    SYNONYM_MAP = {
        "军用": ["国防", "军队"],
        "军用领域": ["国防领域"],
        "军用客户": ["国防领域", "军方", "直接军方", "间接军方"],
        "军方": ["国防领域", "直接军方", "间接军方"],
        "营收": ["收入", "主营业务收入", "销售金额"],
        "销售额": ["销售金额", "收入"],
        "客户分类": ["客户群体", "按客户群体划分的销售情况"],
        "客户群体": ["按客户群体划分的销售情况"],
        "前五大客户": ["前五名客户"],
        "前五名客户": ["前五大客户"],
    }
    LEADING_NOISE_TERMS = ("根据", "依据", "按照", "结合")
    STOP_TERMS = {
        "根据",
        "关于",
        "请问",
        "一个",
        "这个",
        "那个",
        "哪些",
        "哪个",
        "多少",
        "什么",
        "为何",
        "为什么",
        "如何",
        "怎么",
        "是否",
        "情况",
        "内容",
        "涉及",
        "参与",
        "制定",
        "说明",
        "公司",
        "企业",
        "股份",
        "有限公司",
        "股份有限公司",
        "招股",
        "招股书",
        "招股说明书",
        "发行人",
    }
    ENTITY_PATTERN = re.compile(
        r"[\u4e00-\u9fff0-9]{2,}(?:股份有限公司|有限责任公司|有限公司|集团|公司|研究院|研究所)"
    )

    def understand(self, question: str) -> QueryUnderstandingResult:
        """入口方法：对问题执行完整的理解流程并返回结构化结果。"""
        normalized_question = self.normalize(question)
        intent = self.detect_intent(normalized_question)
        ambiguous_terms = self.detect_ambiguity(normalized_question)
        clarification_question = self.build_clarification_question(
            ambiguous_terms=ambiguous_terms,
            question=normalized_question,
        )
        sub_questions = self.decompose(normalized_question)
        abstracted_goal = self.abstract_goal(intent, normalized_question)
        retrieval_hints = self.build_retrieval_hints(normalized_question, intent)

        return QueryUnderstandingResult(
            intent=intent,
            normalized_question=normalized_question,
            strategy="rules",
            ambiguous_terms=ambiguous_terms,
            clarification_needed=bool(clarification_question),
            clarification_question=clarification_question,
            sub_questions=sub_questions,
            abstracted_goal=abstracted_goal,
            assumptions=[],
            retrieval_hints=retrieval_hints,
        )

    def normalize(self, question: str) -> str:
        """规范化问题文本：合并多余空白并去除首尾空格。"""
        return re.sub(r"\s+", " ", question).strip()

    def detect_intent(self, question: str) -> str:
        """检测问题意图：优先匹配财务指标，再按关键词表匹配其他意图。"""
        if self._is_fundraising_usage_question(question):
            return "financial_metric"
        if self._is_financial_metric_question(question):
            return "financial_metric"
        for intent, keywords in self.INTENT_KEYWORDS.items():
            if any(keyword in question for keyword in keywords):
                return intent
        return "general_information"

    def detect_ambiguity(self, question: str) -> list[str]:
        """检测问题中包含的歧义表达（如 '它'、'上述' 等代词）。"""
        return [term for term in self.AMBIGUITY_TERMS if term in question]

    def decompose(self, question: str) -> list[str]:
        """将复合问题按连接词拆分为多个独立子问题。"""
        parts = [question]
        for splitter in self.DECOMPOSE_SPLITTERS:
            next_parts: list[str] = []
            for part in parts:
                next_parts.extend([item.strip() for item in part.split(splitter) if item.strip()])
            parts = next_parts
        return parts if len(parts) > 1 else []

    def abstract_goal(self, intent: str, question: str) -> str:
        """根据意图生成抽象回答目标描述，附加原始问题。"""
        goal = self.ABSTRACT_GOAL_MAP.get(intent, self.ABSTRACT_GOAL_MAP["general_information"])
        return f"{goal}；原问题：{question}"

    def build_clarification_question(self, ambiguous_terms: list[str], question: str) -> str | None:
        """若存在必须追问的歧义项，生成澄清追问语句。"""
        clarification_terms = [
            term for term in ambiguous_terms if term in self.CLARIFICATION_REQUIRED_TERMS
        ]
        if not clarification_terms:
            return None
        joined_terms = "、".join(clarification_terms[:3])
        return (
            f"你的问题里包含可能指代不清的表达（{joined_terms}）。"
            "请补充它具体指的是谁、哪一项业务或哪个时间范围。"
            f"原问题：{question}"
        )

    def build_retrieval_hints(
        self,
        question: str,
        intent: str,
        seed: dict[str, object] | None = None,
    ) -> dict[str, object]:
        """构建检索提示信息，包含关键词、实体、偏好章节、时间约束等。"""
        seed = seed or {}
        entities = self._to_str_list(seed.get("entities")) or self._extract_entities(question)
        keywords = self._to_str_list(seed.get("keywords")) or self._extract_keywords(question, entities)
        prefer_sections = self._to_str_list(seed.get("prefer_sections")) or self._suggest_sections(
            intent
        )

        hints: dict[str, object] = {
            "intent": intent,
            "keywords": keywords[:16],
            "prefer_sections": prefer_sections,
        }

        if entities:
            hints["entities"] = entities[:5]

        time_constraints = self._to_str_list(seed.get("time_constraints")) or self._extract_time_constraints(question)
        if time_constraints:
            hints["time_constraints"] = time_constraints

        notes = self._to_str_list(seed.get("notes"))
        notes = self._merge_unique(notes, self._build_notes(question, intent))
        if notes:
            hints["notes"] = notes

        if intent == "financial_metric":
            self._augment_fundraising_hints(question, hints)

        return hints

    def _extract_keywords(self, question: str, entities: list[str] | None = None) -> list[str]:
        """从问题中提取检索关键词，结合领域短语和同义词扩展。"""
        working_text = question
        for entity in entities or []:
            working_text = working_text.replace(entity, " ")

        preferred_terms = [phrase for phrase in self.DOMAIN_PHRASES if phrase in working_text]
        preferred_terms.extend(self._expand_synonyms(preferred_terms))
        preferred_terms.extend(self._extract_focus_terms(working_text))
        return self._merge_unique(preferred_terms, [])

    def _extract_focus_terms(self, question: str) -> list[str]:
        """提取焦点词：去除停用词和标点后提取有意义的片段。"""
        cleaned = re.sub(r"[，。！？；：、""''（）《》【】[\\],.!?;:\s]", " ", question)
        fragments = [item.strip() for item in cleaned.split(" ") if item.strip()]

        keywords: list[str] = []
        for fragment in fragments:
            normalized_fragment = fragment
            for term in self.STOP_TERMS:
                normalized_fragment = normalized_fragment.replace(term, " ")
            normalized_fragment = re.sub(r"\s+", "", normalized_fragment)

            if not normalized_fragment or normalized_fragment in self.STOP_TERMS:
                continue
            if len(normalized_fragment) <= 1:
                continue

            embedded_phrases = [
                phrase for phrase in self.DOMAIN_PHRASES if phrase in normalized_fragment
            ]
            if embedded_phrases:
                keywords.extend(embedded_phrases)
                keywords.extend(self._expand_synonyms(embedded_phrases))
                continue

            if 2 <= len(normalized_fragment) <= 12:
                keywords.append(normalized_fragment.lower())

        return [
            keyword
            for keyword in keywords
            if keyword not in self.STOP_TERMS
            and not (keyword.endswith(("公司", "企业")) and len(keyword) > 4)
        ]

    def _expand_synonyms(self, terms: list[str]) -> list[str]:
        """对给定术语列表进行同义词扩展。"""
        expanded: list[str] = []
        for term in terms:
            expanded.extend(self.SYNONYM_MAP.get(term, []))
        return expanded

    def _extract_entities(self, question: str) -> list[str]:
        """使用正则从问题中提取公司/机构实体名称。"""
        sanitized_question = question
        for prefix in self.LEADING_NOISE_TERMS:
            sanitized_question = sanitized_question.replace(prefix, " ")
        entities = [match.group(0).strip() for match in self.ENTITY_PATTERN.finditer(sanitized_question)]
        return self._merge_unique(entities, [])

    def _extract_time_constraints(self, question: str) -> list[str]:
        """提取问题中的时间约束（年份或 '报告期'）。"""
        years = re.findall(r"20\d{2}", question)
        if "报告期" in question and not years:
            return ["2016", "2017", "2018", "报告期"]
        return self._merge_unique(years, ["报告期"] if "报告期" in question else [])

    def _build_notes(self, question: str, intent: str) -> list[str]:
        """根据意图和问题内容生成检索备注提示。"""
        notes: list[str] = []
        if intent == "financial_metric":
            if any(term in question for term in ("军用", "国防", "客户群体")):
                notes.append("优先查找按客户群体划分的销售情况表格")
            if "前五" in question and "客户" in question:
                notes.append("优先查找前五名客户销售情况表格")
            if any(term in question for term in ("占比", "比例")):
                notes.append("优先保留带占比列的表格行")
        return notes

    def _suggest_sections(self, intent: str) -> list[str]:
        """根据意图推荐优先检索的文档章节。"""
        return list(self.SECTION_MAP.get(intent, self.SECTION_MAP["general_information"]))

    def _is_financial_metric_question(self, question: str) -> bool:
        """判断是否为财务指标类问题：需同时包含金融术语和表格定位术语。"""
        financial_terms = {"收入", "营收", "主营业务收入", "销售金额", "金额", "占比", "比例", "毛利", "利润"}
        table_terms = {"军用", "国防", "军队", "客户群体", "前五名客户", "前五大客户", "报告期", "2016", "2017", "2018", "分别"}
        return any(term in question for term in financial_terms) and any(
            term in question for term in table_terms
        )

    def _is_fundraising_usage_question(self, question: str) -> bool:
        fundraising_terms = ("募集资金", "募资", "募投", "补充流动资金", "流动资金")
        amount_terms = ("多少", "金额", "几多", "规模", "万元", "亿元", "拟使用", "拟投入")
        return any(term in question for term in fundraising_terms) and any(
            term in question for term in amount_terms
        )

    def _augment_fundraising_hints(self, question: str, hints: dict[str, object]) -> None:
        if not self._is_fundraising_usage_question(question):
            return

        keywords = self._to_str_list(hints.get("keywords"))
        keywords = self._merge_unique(
            keywords,
            ["募集资金", "募集资金用途", "募投项目", "补充流动资金"],
        )
        hints["keywords"] = keywords[:16]

        prefer_sections = self._to_str_list(hints.get("prefer_sections"))
        prefer_sections = self._merge_unique(prefer_sections, ["募集资金运用", "财务会计信息"])
        hints["prefer_sections"] = prefer_sections

        notes = self._to_str_list(hints.get("notes"))
        notes = self._merge_unique(notes, ["优先查找募集资金用途、募投项目和补充流动资金相关段落或表格"])
        hints["notes"] = notes

    def _to_str_list(self, value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        cleaned: list[str] = []
        for item in value:
            if isinstance(item, str):
                normalized = item.strip()
                if normalized:
                    cleaned.append(normalized)
        return cleaned

    def _merge_unique(self, preferred: list[str], fallback: list[str]) -> list[str]:
        seen: set[str] = set()
        merged: list[str] = []
        for item in preferred + fallback:
            normalized = item.strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            merged.append(normalized)
        return merged


class OpenAICompatibleQueryUnderstandingClient:
    """调用 OpenAI 兼容接口的在线查询理解客户端。

    通过 Chat Completions API 将问题发送给 LLM，解析返回的 JSON 结构
    得到意图、歧义、拆分等理解结果。
    """
    SYSTEM_PROMPT = """
你是一个中文 RAG 问答系统的 Query Understanding 模块，负责在检索前理解用户问题。
请只返回 JSON 对象，不要输出 markdown、解释或额外文字。JSON 字段要求如下：
- intent: 字符串，概括核心意图，例如 financial_metric / risk_factor / business_overview / shareholding / timeline / general_information
- intent_confidence: 0 到 1 之间的小数
- normalized_question: 规范化后的问题
- ambiguous_terms: 字符串数组，列出歧义表达
- clarification_needed: 布尔值，是否必须先追问再回答
- clarification_question: 字符串或 null
- sub_questions: 字符串数组，复杂问题拆分后的子问题
- abstracted_goal: 字符串，抽象后的回答目标
- assumptions: 字符串数组，如果你做了默认假设请写在这里
- retrieval_hints: 对象，可包含 keywords、entities、prefer_sections、time_constraints、notes

约束：
1. 如果问题存在关键歧义且会影响答案正确性，clarification_needed 必须为 true。
2. 如果问题是多意图或复合问题，sub_questions 需要拆成独立可检索的问题。
3. 保持和用户问题相同的语言。
4. 不要编造文档事实，这一步只做理解，不做回答。
""".strip()

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: float,
        temperature: float,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.temperature = temperature

    def understand(self, question: str) -> dict[str, object]:
        """调用在线 LLM 理解问题，返回解析后的 JSON 字典。"""
        response = self._create_chat_completion(
            {
                "model": self.model,
                "temperature": self.temperature,
                "messages": [
                    {"role": "system", "content": self.SYSTEM_PROMPT},
                    {"role": "user", "content": question},
                ],
            }
        )
        content = self._extract_content(response)
        stripped_content = self._strip_code_fences(content)

        try:
            parsed = json.loads(stripped_content)
        except json.JSONDecodeError as exc:
            raise QueryUnderstandingRemoteError("在线 Query Understanding 没有返回合法 JSON。") from exc

        if not isinstance(parsed, dict):
            raise QueryUnderstandingRemoteError("在线 Query Understanding 返回的 JSON 根对象不是对象。")
        return parsed

    def _create_chat_completion(self, payload: dict[str, object]) -> dict[str, object]:
        """向 OpenAI 兼容端点发送 Chat Completions 请求并返回响应 JSON。"""
        endpoint = f"{self.base_url}/chat/completions"
        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        req = request.Request(endpoint, data=body, headers=headers, method="POST")

        try:
            with request.urlopen(req, timeout=self.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise QueryUnderstandingRemoteError(
                f"在线 Query Understanding 请求失败，HTTP {exc.code}: {detail}"
            ) from exc
        except error.URLError as exc:
            raise QueryUnderstandingRemoteError(f"在线 Query Understanding 连接失败: {exc.reason}") from exc
        except (TimeoutError, socket.timeout) as exc:
            raise QueryUnderstandingRemoteError("在线 Query Understanding 请求超时。") from exc

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise QueryUnderstandingRemoteError("在线 Query Understanding 返回了非法响应。") from exc

        if not isinstance(parsed, dict):
            raise QueryUnderstandingRemoteError("在线 Query Understanding 响应格式不正确。")
        return parsed

    def _extract_content(self, payload: dict[str, object]) -> str:
        """从 API 响应中提取 assistant 消息的文本内容。"""
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise QueryUnderstandingRemoteError("在线 Query Understanding 响应中缺少 choices。")

        first_choice = choices[0]
        if not isinstance(first_choice, dict):
            raise QueryUnderstandingRemoteError("在线 Query Understanding 响应结构异常。")

        message = first_choice.get("message")
        if not isinstance(message, dict):
            raise QueryUnderstandingRemoteError("在线 Query Understanding 响应中缺少 message。")

        content = message.get("content")
        if isinstance(content, str):
            return content.strip()

        if isinstance(content, list):
            text_blocks = [
                block.get("text", "")
                for block in content
                if isinstance(block, dict) and isinstance(block.get("text"), str)
            ]
            joined = "".join(text_blocks).strip()
            if joined:
                return joined

        raise QueryUnderstandingRemoteError("在线 Query Understanding 响应中缺少可解析的 content。")

    def _strip_code_fences(self, content: str) -> str:
        """去除 LLM 输出中可能包含的 markdown 代码围栏。"""
        stripped = content.strip()
        if stripped.startswith("```") and stripped.endswith("```"):
            stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
            stripped = re.sub(r"\s*```$", "", stripped)
        return stripped.strip()


class QueryUnderstandingService:
    """查询理解门面服务（Facade）。

    根据配置自动选择在线 LLM、本地规则或混合策略完成查询理解。
    支持 local-first 策略：对简单问题或特定意图优先使用本地规则，
    仅在需要时才调用在线 LLM，以降低延迟和成本。
    """
    ONLINE_MODES = {"online", "openai_compatible"}
    SIMPLE_QUESTION_MAX_LENGTH = 40
    COMPLEXITY_MARKERS = {"以及", "并且", "同时", "分别", "对比", "比较", "分析", "原因", "影响"}
    ONLINE_RISK_TERMS = {"它", "他们", "这个", "那个", "上述", "报告期", "同比", "环比"}
    LOCAL_FIRST_INTENTS = {
        "award_project",
        "technical_standard",
        "financial_metric",
        "business_overview",
        "shareholding",
        "industry_chain",
        "competition",
    }

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.rule_based_service = RuleBasedQueryUnderstandingService()
        self.remote_client, self.remote_unavailable_reason = self._build_remote_client()

    def understand(self, question: str) -> QueryUnderstandingResult:
        """入口方法：根据策略选择在线/本地/混合方式理解问题。"""
        normalized_question = self.rule_based_service.normalize(question)
        local_first_result = self._maybe_use_local_first(normalized_question)
        if local_first_result is not None:
            return local_first_result

        if not self.remote_client:
            fallback_result = self.rule_based_service.understand(normalized_question)
            return self._attach_fallback_note_if_needed(fallback_result)

        try:
            remote_payload = self.remote_client.understand(normalized_question)
        except QueryUnderstandingRemoteError as exc:
            if not self.settings.query_understanding_fallback_enabled:
                raise
            fallback_result = self.rule_based_service.understand(normalized_question)
            return self._mark_runtime_fallback(fallback_result, str(exc))

        return self._build_online_result(normalized_question, remote_payload)

    def _build_remote_client(
        self,
    ) -> tuple[OpenAICompatibleQueryUnderstandingClient | None, str | None]:
        """根据配置构建在线 LLM 客户端，缺失配置时返回 None 和原因。"""
        mode = self.settings.query_understanding_mode.strip().lower()
        if mode not in self.ONLINE_MODES:
            return None, None

        api_key = self.settings.query_understanding_api_key or self.settings.llm_api_key
        base_url = self.settings.query_understanding_base_url or self.settings.llm_base_url
        model = self.settings.query_understanding_model or self.settings.llm_model

        missing_fields: list[str] = []
        if not api_key:
            missing_fields.append("QUERY_UNDERSTANDING_API_KEY or LLM_API_KEY")
        if not base_url:
            missing_fields.append("QUERY_UNDERSTANDING_BASE_URL or LLM_BASE_URL")
        if not model:
            missing_fields.append("QUERY_UNDERSTANDING_MODEL or LLM_MODEL")

        if missing_fields:
            return None, f"在线 Query Understanding 缺少配置项: {', '.join(missing_fields)}"

        return (
            OpenAICompatibleQueryUnderstandingClient(
                api_key=api_key,
                base_url=base_url,
                model=model,
                timeout_seconds=self.settings.query_understanding_timeout_seconds,
                temperature=self.settings.query_understanding_temperature,
            ),
            None,
        )

    def _attach_fallback_note_if_needed(
        self,
        result: QueryUnderstandingResult,
    ) -> QueryUnderstandingResult:
        """若在线客户端不可用且开启了回退，在结果中附加回退说明。"""
        if not self.remote_unavailable_reason:
            return result
        if not self.settings.query_understanding_fallback_enabled:
            raise QueryUnderstandingRemoteError(self.remote_unavailable_reason)
        return self._mark_runtime_fallback(result, self.remote_unavailable_reason)

    def _maybe_use_local_first(self, normalized_question: str) -> QueryUnderstandingResult | None:
        """尝试本地优先策略：对简单问题或特定意图直接使用规则结果。"""
        if not self.settings.query_understanding_local_first_enabled:
            return None
        if self.settings.query_understanding_mode.strip().lower() not in self.ONLINE_MODES:
            return None

        result = self.rule_based_service.understand(normalized_question)
        if not self._should_use_local_first(normalized_question, result):
            return None

        retrieval_hints = dict(result.retrieval_hints)
        retrieval_hints["understanding_strategy"] = "local_first_rules"
        retrieval_hints["local_first_reason"] = self._build_local_first_reason(normalized_question, result)
        return result.model_copy(
            update={
                "strategy": "local_first_rules",
                "retrieval_hints": retrieval_hints,
            }
        )

    def _should_use_local_first(
        self,
        question: str,
        result: QueryUnderstandingResult,
    ) -> bool:
        """判断是否应使用本地优先策略：特定意图或简单问题且无歧义。"""
        if result.clarification_needed:
            return False
        if result.intent in self.LOCAL_FIRST_INTENTS:
            return True
        return self._is_simple_question(question)

    def _is_simple_question(self, question: str) -> bool:
        if len(question) > self.SIMPLE_QUESTION_MAX_LENGTH:
            return False
        if any(marker in question for marker in self.COMPLEXITY_MARKERS):
            return False
        if any(term in question for term in self.ONLINE_RISK_TERMS):
            return False

        punctuation_count = sum(question.count(marker) for marker in {"，", "。", "？"})
        if punctuation_count >= 2:
            return False

        return True

    def _build_local_first_reason(
        self,
        question: str,
        result: QueryUnderstandingResult,
    ) -> str:
        """生成使用本地优先策略的原因说明。"""
        if self._is_simple_question(question):
            return "simple_question"
        if result.intent in self.LOCAL_FIRST_INTENTS:
            return f"intent:{result.intent}"
        return "simple_question"

    def _mark_runtime_fallback(
        self,
        result: QueryUnderstandingResult,
        reason: str,
    ) -> QueryUnderstandingResult:
        """在结果中标记运行时回退信息（在线调用失败后降级）。"""
        retrieval_hints = dict(result.retrieval_hints)
        retrieval_hints["online_error"] = reason
        assumptions = self.rule_based_service._merge_unique(
            ["在线理解不可用，已回退到本地规则模式。"],
            result.assumptions,
        )
        return result.model_copy(
            update={
                "strategy": "rules_fallback",
                "assumptions": assumptions,
                "retrieval_hints": retrieval_hints,
            }
        )

    def _build_online_result(
        self,
        normalized_question: str,
        payload: dict[str, object],
    ) -> QueryUnderstandingResult:
        """将在线 LLM 返回的 JSON 与本地规则结果融合，构建最终理解结果。"""
        fallback_result = self.rule_based_service.understand(normalized_question)

        intent = self._to_non_empty_str(payload.get("intent")) or fallback_result.intent
        online_normalized_question = (
            self._to_non_empty_str(payload.get("normalized_question")) or normalized_question
        )
        ambiguous_terms = self.rule_based_service._merge_unique(
            self._to_str_list(payload.get("ambiguous_terms")),
            fallback_result.ambiguous_terms,
        )
        online_sub_questions = self._to_str_list(payload.get("sub_questions"))
        sub_questions = online_sub_questions or fallback_result.sub_questions
        abstracted_goal = (
            self._to_non_empty_str(payload.get("abstracted_goal")) or fallback_result.abstracted_goal
        )
        assumptions = self._to_str_list(payload.get("assumptions"))
        intent_confidence = self._to_confidence(payload.get("intent_confidence"))

        clarification_question = self._to_non_empty_str(payload.get("clarification_question"))
        clarification_needed = self._to_bool(payload.get("clarification_needed"))
        if not clarification_needed and clarification_question:
            clarification_needed = True
        if clarification_needed and not ambiguous_terms:
            clarification_needed = False
            clarification_question = None
        if clarification_needed and not clarification_question:
            clarification_question = self.rule_based_service.build_clarification_question(
                ambiguous_terms=ambiguous_terms,
                question=online_normalized_question,
            )

        retrieval_hints_seed = payload.get("retrieval_hints")
        retrieval_hints = self.rule_based_service.build_retrieval_hints(
            online_normalized_question,
            intent,
            retrieval_hints_seed if isinstance(retrieval_hints_seed, dict) else None,
        )
        retrieval_hints["understanding_strategy"] = "online"

        return QueryUnderstandingResult(
            intent=intent,
            normalized_question=online_normalized_question,
            strategy="online",
            intent_confidence=intent_confidence,
            ambiguous_terms=ambiguous_terms,
            clarification_needed=clarification_needed,
            clarification_question=clarification_question,
            sub_questions=sub_questions,
            abstracted_goal=abstracted_goal,
            assumptions=assumptions,
            retrieval_hints=retrieval_hints,
        )

    def _to_non_empty_str(self, value: object) -> str | None:
        if not isinstance(value, str):
            return None
        normalized = value.strip()
        return normalized or None

    def _to_str_list(self, value: object) -> list[str]:
        return self.rule_based_service._to_str_list(value)

    def _to_bool(self, value: object) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"true", "1", "yes"}
        return False

    def _to_confidence(self, value: object) -> float | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            confidence = float(value)
        elif isinstance(value, str):
            try:
                confidence = float(value.strip())
            except ValueError:
                return None
        else:
            return None

        if 0.0 <= confidence <= 1.0:
            return confidence
        return None
