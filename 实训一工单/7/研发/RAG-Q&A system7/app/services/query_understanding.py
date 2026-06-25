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
        "legal_representative": ["法定代表人", "法人代表", "法定代表"],
        "chart_structure": [
            "组织结构图", "组织架构图", "组织架构", "架构图",
            "流程图", "结构图", "示意图", "趋势图", "折线图",
            "柱状图", "饼图", "雷达图", "散点图", "曲线图",
            "图表", "哪个部门", "哪些部门", "销售处", "销售部",
        ],
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
        "legal_representative": ["发行人基本情况", "发行概况"],
        "chart_structure": ["组织结构", "公司治理", "发行人基本情况"],
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
        "legal_representative": "定位发行人基本信息并提取法定代表人",
        "chart_structure": "定位组织结构图/架构图并提取部门、层级、人员关系",
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
        "法定代表人",
        "法人代表",
        "法定代表",
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
        "组织结构图",
        "组织架构图",
        "组织架构",
        "架构图",
        "流程图",
        "销售部",
        "销售处",
        "部门",
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
        # 新增扩展同义词
        "主营业务": ["主要业务", "核心业务"],
        "利润": ["净利润", "利润总额", "营业利润", "毛利"],
        "毛利率": ["毛利", "毛利率"],
        "现金流": ["经营活动现金流", "现金流量"],
        "负债": ["负债总额", "资产负债", "负债率"],
        "资产": ["总资产", "资产总额", "净资产"],
        "研发": ["研发投入", "研发费用", "研发支出", "R&D"],
        "专利": ["发明专利", "实用新型", "知识产权"],
        "员工": ["职工", "人员", "雇员"],
        "供应商": ["供货商", "供应方"],
        "采购": ["采购金额", "采购量"],
        "产能": ["生产能力", "产量", "产能利用率"],
        "募投": ["募集资金", "募投项目", "IPO募资"],
        "分红": ["股利", "现金分红", "利润分配"],
        "子公司": ["控股子公司", "全资子公司", "参股公司"],
        "关联交易": ["关联方", "关联往来"],
        "合规": ["诉讼", "行政处罚", "违规"],
        "行业地位": ["市场占有率", "市场份额", "排名"],
        "出口": ["海外", "境外", "出口业务"],
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
        r"[\u4e00-\u9fff0-9]{2,}?(?:股份有限公司|有限责任公司|有限公司|集团|公司|研究院|研究所)"
    )

    def detect_language(self, question: str) -> str:
        """Detect whether the user question is primarily Chinese or English."""
        chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", question))
        english_chars = len(re.findall(r"[A-Za-z]", question))
        if english_chars > chinese_chars:
            return "en"
        return "zh"

    def understand(self, question: str) -> QueryUnderstandingResult:
        """入口方法：对问题执行完整的理解流程并返回结构化结果。"""
        normalized_question = self.normalize(question)
        detected_language = self.detect_language(normalized_question)
        intent = self.detect_intent(normalized_question)
        ambiguous_terms = self.detect_ambiguity(normalized_question)
        clarification_question = self.build_clarification_question(
            ambiguous_terms=ambiguous_terms,
            question=normalized_question,
            detected_language=detected_language,
        )
        sub_questions = self.decompose(normalized_question)
        abstracted_goal = self.abstract_goal(intent, normalized_question, detected_language)
        retrieval_hints = self.build_retrieval_hints(
            normalized_question, intent, abstracted_goal=abstracted_goal,
        )

        return QueryUnderstandingResult(
            intent=intent,
            normalized_question=normalized_question,
            detected_language=detected_language,
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

    def abstract_goal(self, intent: str, question: str, detected_language: str = "zh") -> str:
        """根据意图生成抽象回答目标描述，附加原始问题。"""
        if detected_language == "en":
            return f"Find the relevant evidence and answer the original question directly; original question: {question}"
        goal = self.ABSTRACT_GOAL_MAP.get(intent, self.ABSTRACT_GOAL_MAP["general_information"])
        return f"{goal}；原问题：{question}"

    def build_clarification_question(
        self,
        ambiguous_terms: list[str],
        question: str,
        detected_language: str = "zh",
    ) -> str | None:
        """若存在必须追问的歧义项，生成澄清追问语句。"""
        clarification_terms = [
            term for term in ambiguous_terms if term in self.CLARIFICATION_REQUIRED_TERMS
        ]
        if not clarification_terms:
            return None
        if detected_language == "en":
            joined_terms = ", ".join(clarification_terms[:3])
            return (
                f"Your question contains ambiguous references ({joined_terms}). "
                "Please clarify who or what they refer to, and specify the business item or time range if needed. "
                f"Original question: {question}"
            )
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
        abstracted_goal: str | None = None,
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

        if abstracted_goal:
            hints["abstracted_goal"] = abstracted_goal

        if entities:
            hints["entities"] = entities[:5]

        time_constraints = self._to_str_list(seed.get("time_constraints")) or self._extract_time_constraints(question)
        if time_constraints:
            hints["time_constraints"] = time_constraints

        notes = self._to_str_list(seed.get("notes"))
        notes = self._merge_unique(notes, self._build_notes(question, intent))
        if notes:
            hints["notes"] = notes

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
        # 过滤指示代词伪实体：如 "这个公司"、"那个企业" 等
        entities = [
            e for e in entities
            if not re.match(r"^[这个那个该某]{1,2}(?:公司|企业|集团|研究院|研究所)$", e)
        ]
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

    FOLLOWUP_REWRITE_SYSTEM_PROMPT = """
You rewrite follow-up questions into standalone retrieval-ready questions.
Return JSON only with keys: rewritten_question, rewrite_needed, reason.
If the current question is already standalone, return it unchanged.
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

    def rewrite_followup_question(
        self,
        question: str,
        conversation_messages: list[dict[str, str]],
    ) -> dict[str, object]:
        """Rewrite a follow-up question into a standalone query."""
        history_lines: list[str] = []
        for item in conversation_messages[-6:]:
            role = str(item.get("role", "user")).strip() or "user"
            content = str(item.get("content", "")).strip()
            if content:
                history_lines.append(f"{role}: {content}")

        response = self._create_chat_completion(
            {
                "model": self.model,
                "temperature": 0,
                "messages": [
                    {"role": "system", "content": self.FOLLOWUP_REWRITE_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": (
                            "Conversation history:\n"
                            f"{chr(10).join(history_lines)}\n\n"
                            f"Current question:\n{question}"
                        ),
                    },
                ],
            }
        )
        content = self._extract_content(response)
        stripped_content = self._strip_code_fences(content)

        try:
            parsed = json.loads(stripped_content)
        except json.JSONDecodeError as exc:
            raise QueryUnderstandingRemoteError("Follow-up rewrite did not return valid JSON.") from exc

        if not isinstance(parsed, dict):
            raise QueryUnderstandingRemoteError("Follow-up rewrite JSON payload is invalid.")
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
    FOLLOWUP_MARKERS = {
        "它", "他们", "她", "它们", "其",
        "该公司", "这家公司", "这家企业", "这个公司",
        "这个", "那个", "这个企业", "那个公司",
        "上述", "前者", "后者", "这", "该",
        "what about", "how about", "and what about", "then what about",
        "it", "they", "them", "this", "that",
    }
    LOCAL_FIRST_INTENTS = {
        "award_project",
        "technical_standard",
        "financial_metric",
        "business_overview",
        "shareholding",
        "industry_chain",
        "competition",
        "legal_representative",
        "chart_structure",
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

    def contextualize_question(
        self,
        question: str,
        conversation_messages: list[dict[str, str]] | None = None,
    ) -> tuple[str, dict[str, object]]:
        """Rewrite a follow-up question into a standalone retrieval query when needed."""
        normalized_question = self.rule_based_service.normalize(question)
        history = [
            {
                "role": str(item.get("role", "")).strip(),
                "content": str(item.get("content", "")).strip(),
            }
            for item in (conversation_messages or [])
            if str(item.get("content", "")).strip()
        ]
        if not history:
            return normalized_question, {"rewritten": False, "reason": "no_history"}
        if not self._should_rewrite_followup(normalized_question):
            return normalized_question, {"rewritten": False, "reason": "already_standalone"}

        local_rewritten_question = self._rewrite_followup_locally(normalized_question, history)
        if self._is_precise_local_rewrite(local_rewritten_question, normalized_question):
            return local_rewritten_question, {
                "rewritten": True,
                "reason": "followup_context_local",
                "source": "local",
            }

        if self.remote_client and self.settings.query_understanding_mode.strip().lower() in self.ONLINE_MODES:
            try:
                payload = self.remote_client.rewrite_followup_question(normalized_question, history)
                rewritten_question = self._to_non_empty_str(payload.get("rewritten_question"))
                rewrite_needed = self._to_bool(payload.get("rewrite_needed"))
                reason = self._to_non_empty_str(payload.get("reason")) or "remote_rewrite"
                if rewritten_question and (rewrite_needed or rewritten_question != normalized_question):
                    return rewritten_question, {
                        "rewritten": True,
                        "reason": reason,
                        "source": "remote",
                    }
            except QueryUnderstandingRemoteError:
                pass

        rewritten_question = local_rewritten_question
        if rewritten_question != normalized_question:
            return rewritten_question, {
                "rewritten": True,
                "reason": "followup_context_local",
                "source": "local",
            }
        return normalized_question, {"rewritten": False, "reason": "local_no_change"}

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

    def _should_rewrite_followup(self, question: str) -> bool:
        lowered = question.lower()
        if any(marker in question for marker in self.FOLLOWUP_MARKERS):
            return True
        if any(marker in lowered for marker in self.FOLLOWUP_MARKERS):
            return True
        if re.match(r"^(那|那么|那这|那它|and |then |so )", question, re.IGNORECASE):
            return True
        if re.fullmatch(r"(20\d{2}年?|报告期内?)[\s，,。？?呢吗]*", question):
            return True
        if len(question) <= 12 and question.endswith(("呢", "吗", "？", "?")):
            return True
        return False

    def _rewrite_followup_locally(
        self,
        question: str,
        conversation_messages: list[dict[str, str]],
    ) -> str:
        last_user_question = self._find_last_message(conversation_messages, "user")
        if not last_user_question:
            return question

        language = self.rule_based_service.detect_language(question)
        if language == "en":
            return f"Previous user question: {last_user_question}. Current follow-up: {question}"

        last_assistant_answer = self._find_last_message(conversation_messages, "assistant") or ""
        current_entity = self._extract_followup_entity(question)
        previous_entity = self._extract_prior_entity(
            last_user_question, last_assistant_answer,
            all_messages=conversation_messages,
        )
        current_topic = self._extract_followup_topic(question)
        previous_topic = self._extract_followup_topic(last_user_question) or self._extract_followup_topic(
            last_assistant_answer
        )

        if current_entity and (current_topic or previous_topic):
            return self._format_topic_question(current_entity, current_topic or previous_topic)

        if previous_entity and current_topic:
            return self._format_topic_question(previous_entity, current_topic)

        return f"上一轮用户问题：{last_user_question}；当前追问：{question}"

    def _is_precise_local_rewrite(self, rewritten_question: str, original_question: str) -> bool:
        if rewritten_question == original_question:
            return False
        if rewritten_question.startswith(("上一轮用户问题：", "Previous user question:")):
            return False
        # 检查是否为有效的改写：不应包含重复的问句后缀（如"的法定代表人是谁？的法定代表人是谁？"）
        if re.search(r"的\S+？的\S+？$", rewritten_question):
            return False
        # 不应比原问题短太多（说明丢失了信息）
        if len(rewritten_question) < len(original_question) * 0.3:
            return False
        return True

    def _extract_followup_entity(self, question: str) -> str | None:
        cleaned = re.sub(r"^(那|那么|那这|那这个|还有|至于|what about|how about)\s*", "", question, flags=re.IGNORECASE)
        cleaned = re.sub(r"[\s，,。？?呢吗]+$", "", cleaned).strip()

        entities = self.rule_based_service._extract_entities(cleaned)
        if entities:
            return entities[0]

        if cleaned in self.FOLLOWUP_MARKERS or len(cleaned) < 2:
            return None
        if any(marker in cleaned for marker in ("它", "他们", "该公司", "这个", "那个", "上述")):
            return None
        # 验证：cleaned 必须以公司/机构后缀结尾，不能只是包含"公司"
        if not re.search(
            r"(?:股份有限公司|有限责任公司|有限公司|集团公司?|研究院|研究所)$",
            cleaned,
        ):
            return None
        return cleaned

    def _extract_prior_entity(
        self, last_user_question: str, last_assistant_answer: str,
        all_messages: list[dict[str, str]] | None = None,
    ) -> str | None:
        """从前一轮对话中提取公司实体名称。

        优先搜索完整对话历史（所有 user 和 assistant 消息），
        确保能在多轮对话中找到最早提到的公司实体。
        """
        texts_to_search: list[str] = []
        if all_messages:
            # 按时间顺序搜索所有历史消息
            for msg in all_messages:
                content = msg.get("content", "").strip()
                if content:
                    texts_to_search.append(content)
        else:
            texts_to_search = [last_user_question, last_assistant_answer]

        for text in texts_to_search:
            entities = self.rule_based_service._extract_entities(text)
            if entities:
                return entities[0]
        return None

    def _extract_followup_topic(self, text: str) -> str | None:
        topic_aliases = {
            "legal_representative": ("法定代表人", "法人代表", "法定代表"),
            "actual_controller": ("实际控制人", "实控人"),
            "chairman": ("董事长",),
            "controlling_shareholder": ("控股股东",),
            "main_business": ("主营业务", "主要业务", "业务"),
            "registered_capital": ("注册资本",),
            "registered_address": ("注册地址", "住所"),
            "established_date": ("成立日期", "成立时间", "设立日期"),
        }
        for topic, aliases in topic_aliases.items():
            if any(alias in text for alias in aliases):
                return topic
        return None

    def _format_topic_question(self, entity: str, topic: str | None) -> str:
        topic_questions = {
            "legal_representative": "法定代表人是谁？",
            "actual_controller": "实际控制人是谁？",
            "chairman": "董事长是谁？",
            "controlling_shareholder": "控股股东是谁？",
            "main_business": "主营业务是什么？",
            "registered_capital": "注册资本是多少？",
            "registered_address": "注册地址在哪里？",
            "established_date": "成立日期是什么时候？",
        }
        suffix = topic_questions.get(topic or "", "相关情况是什么？")
        return f"{entity}的{suffix}"

    def _find_last_message(
        self,
        conversation_messages: list[dict[str, str]],
        role: str,
    ) -> str | None:
        for item in reversed(conversation_messages):
            if item.get("role") != role:
                continue
            content = item.get("content", "").strip()
            if content:
                return content
        return None

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
        detected_language = (
            self._to_non_empty_str(payload.get("detected_language"))
            or fallback_result.detected_language
        )

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
                detected_language=detected_language,
            )

        retrieval_hints_seed = payload.get("retrieval_hints")
        retrieval_hints = self.rule_based_service.build_retrieval_hints(
            online_normalized_question,
            intent,
            retrieval_hints_seed if isinstance(retrieval_hints_seed, dict) else None,
            abstracted_goal=abstracted_goal,
        )
        retrieval_hints["understanding_strategy"] = "online"

        return QueryUnderstandingResult(
            intent=intent,
            normalized_question=online_normalized_question,
            detected_language=detected_language,
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
