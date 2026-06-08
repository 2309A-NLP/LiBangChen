from app.core.config import Settings
from app.schemas.query import QueryRequest, QueryUnderstandingResult
from app.services.pipeline import QAPipelineService
from app.services.query_understanding import QueryUnderstandingRemoteError, QueryUnderstandingService
from app.services.session_service import SessionService
from app.services.session_store import InMemorySessionStore


def test_query_understanding_decomposes_question():
    service = QueryUnderstandingService(Settings(query_understanding_mode="rules"))

    result = service.understand("公司的主营业务和主要风险分别是什么？")

    assert result.strategy == "rules"
    assert result.intent in {"business_overview", "risk_factor", "general_information"}
    assert result.normalized_question == "公司的主营业务和主要风险分别是什么？"
    assert result.sub_questions
    assert result.abstracted_goal


def test_query_understanding_uses_local_first_for_simple_question():
    service = QueryUnderstandingService(
        Settings(query_understanding_mode="online", query_understanding_local_first_enabled=True)
    )

    result = service.understand("主营业务是什么？")

    assert result.strategy == "local_first_rules"
    assert result.retrieval_hints["understanding_strategy"] == "local_first_rules"
    assert result.retrieval_hints["local_first_reason"] == "simple_question"


def test_query_understanding_detects_english_question_language():
    service = QueryUnderstandingService(Settings(query_understanding_mode="rules"))

    result = service.understand("What is the company's main business?")

    assert result.detected_language == "en"
    assert result.normalized_question == "What is the company's main business?"
    assert result.abstracted_goal.startswith("Find the relevant evidence")


def test_query_understanding_extracts_focus_keywords_without_company_noise():
    service = QueryUnderstandingService(Settings(query_understanding_mode="rules"))

    result = service.understand("武汉兴图新科电子股份有限公司参与制定了哪个技术标准？")

    assert "技术标准" in result.retrieval_hints["keywords"]
    assert "参与制定" in result.retrieval_hints["keywords"]
    assert result.retrieval_hints["entities"] == ["武汉兴图新科电子股份有限公司"]


def test_query_understanding_extracts_award_project_keywords():
    service = QueryUnderstandingService(Settings(query_understanding_mode="rules"))

    result = service.understand("武汉兴图新科电子股份有限公司参与的哪个工程获得了国家科技进步一等奖")

    assert result.intent == "award_project"
    assert "国家科技进步一等奖" in result.retrieval_hints["keywords"]
    assert "工程" in result.retrieval_hints["keywords"]
    assert result.retrieval_hints["prefer_sections"] == ["技术先进性", "科研实力和成果", "主营业务"]


def test_query_understanding_detects_financial_metric_for_defense_revenue_question():
    service = QueryUnderstandingService(
        Settings(query_understanding_mode="online", query_understanding_local_first_enabled=True)
    )

    result = service.understand("报告期内，武汉兴图新科电子股份有限公司来自军用领域的收入分别是多少")

    assert result.intent == "financial_metric"
    assert result.strategy == "local_first_rules"
    assert result.retrieval_hints["understanding_strategy"] == "local_first_rules"
    assert result.retrieval_hints["local_first_reason"] in {"simple_question", "intent:financial_metric"}
    assert "收入" in result.retrieval_hints["keywords"]
    assert "国防领域" in result.retrieval_hints["keywords"]
    assert "按客户群体划分的销售情况" in result.retrieval_hints["prefer_sections"]
    assert "报告期" in result.retrieval_hints["time_constraints"]


def test_query_understanding_adds_alias_keywords_for_military_revenue_question():
    service = QueryUnderstandingService(Settings(query_understanding_mode="rules"))

    result = service.understand("报告期内，公司来自军工领域的收入分别是多少？")

    assert result.intent == "financial_metric"
    assert "收入" in result.retrieval_hints["keywords"]
    assert "军用领域" in result.retrieval_hints["keywords"]
    assert "国防领域" in result.retrieval_hints["keywords"]
    assert "按客户群体划分的销售情况" in result.retrieval_hints["keywords"]


def test_query_understanding_adds_org_chart_keywords_for_sales_office_question():
    service = QueryUnderstandingService(Settings(query_understanding_mode="rules"))

    result = service.understand("组织结构图里，哪个销售部的销售处最多？有哪些销售处？")

    assert "组织结构图" in result.retrieval_hints["keywords"]
    assert "销售部" in result.retrieval_hints["keywords"]
    assert "销售处" in result.retrieval_hints["keywords"]
    assert "发行人组织结构" in result.retrieval_hints["prefer_sections"]
    assert "公司内部职能部门、分公司简介" in result.retrieval_hints["prefer_sections"]


def test_query_understanding_expands_customer_table_synonyms():
    service = QueryUnderstandingService(Settings(query_understanding_mode="rules"))

    result = service.understand("前五大客户分别是谁")

    assert result.intent in {"financial_metric", "business_overview", "general_information"}
    assert "前五大客户" in result.retrieval_hints["keywords"]
    assert "前五名客户" in result.retrieval_hints["keywords"]


def test_query_understanding_uses_online_payload_and_marks_clarification(monkeypatch):
    settings = Settings(
        query_understanding_mode="online",
        query_understanding_api_key="test-key",
        query_understanding_base_url="https://example.com/v1",
        query_understanding_model="test-model",
    )
    service = QueryUnderstandingService(settings)

    def fake_understand(question: str) -> dict[str, object]:
        assert question == "报告期内它的主营业务和毛利率分别是什么？"
        return {
            "intent": "business_overview",
            "intent_confidence": 0.93,
            "normalized_question": question,
            "ambiguous_terms": ["它", "报告期"],
            "clarification_needed": True,
            "clarification_question": "你说的“它”是指公司主体、某条产品线，还是某家子公司？报告期是哪个年份？",
            "sub_questions": ["报告期内公司的主营业务是什么？", "报告期内公司的毛利率是多少？"],
            "abstracted_goal": "先明确主体和时间范围，再分别检索业务介绍与财务指标。",
            "assumptions": ["暂不默认报告期年份。"],
            "retrieval_hints": {
                "keywords": ["主营业务", "毛利率", "报告期"],
                "prefer_sections": ["主营业务", "财务会计信息"],
                "entities": ["公司"],
            },
        }

    monkeypatch.setattr(service.remote_client, "understand", fake_understand)

    result = service.understand("报告期内它的主营业务和毛利率分别是什么？")

    assert result.strategy == "online"
    assert result.intent == "business_overview"
    assert result.intent_confidence == 0.93
    assert result.clarification_needed is True
    assert "它" in result.ambiguous_terms
    assert result.sub_questions == ["报告期内公司的主营业务是什么？", "报告期内公司的毛利率是多少？"]
    assert result.retrieval_hints["prefer_sections"] == ["主营业务", "财务会计信息"]


def test_query_understanding_falls_back_when_online_unavailable(monkeypatch):
    settings = Settings(
        query_understanding_mode="online",
        query_understanding_api_key="test-key",
        query_understanding_base_url="https://example.com/v1",
        query_understanding_model="test-model",
        query_understanding_fallback_enabled=True,
        query_understanding_local_first_enabled=False,
    )
    service = QueryUnderstandingService(settings)

    def fake_understand(_: str) -> dict[str, object]:
        raise QueryUnderstandingRemoteError("timeout")

    monkeypatch.setattr(service.remote_client, "understand", fake_understand)

    result = service.understand("公司的主营业务是什么？")

    assert result.strategy == "rules_fallback"
    assert "在线理解不可用" in result.assumptions[0]
    assert result.retrieval_hints["online_error"] == "timeout"


def test_query_understanding_can_reuse_llm_api_settings(monkeypatch):
    settings = Settings(
        llm_provider="openai_compatible",
        llm_api_key="shared-key",
        llm_base_url="https://example.com/v1",
        llm_model="shared-model",
        query_understanding_mode="online",
        query_understanding_local_first_enabled=False,
    )
    service = QueryUnderstandingService(settings)

    def fake_understand(question: str) -> dict[str, object]:
        assert question == "公司的主营业务是什么？"
        return {
            "intent": "business_overview",
            "normalized_question": question,
            "ambiguous_terms": [],
            "clarification_needed": False,
            "sub_questions": [],
            "abstracted_goal": "定位主营业务并概括回答。",
            "assumptions": [],
            "retrieval_hints": {"keywords": ["主营业务"]},
        }

    monkeypatch.setattr(service.remote_client, "understand", fake_understand)

    result = service.understand("公司的主营业务是什么？")

    assert result.strategy == "online"
    assert result.intent == "business_overview"
    assert result.retrieval_hints["keywords"] == ["主营业务"]


def test_query_understanding_uses_online_for_complex_question(monkeypatch):
    settings = Settings(
        query_understanding_mode="online",
        query_understanding_local_first_enabled=True,
        query_understanding_api_key="test-key",
        query_understanding_base_url="https://example.com/v1",
        query_understanding_model="test-model",
    )
    service = QueryUnderstandingService(settings)

    def fake_understand(question: str) -> dict[str, object]:
        assert question == "报告期内公司的主营业务和主要风险分别是什么？"
        return {
            "intent": "general_information",
            "normalized_question": question,
            "ambiguous_terms": [],
            "clarification_needed": False,
            "sub_questions": ["报告期内公司的主营业务是什么？", "报告期内公司的主要风险是什么？"],
            "abstracted_goal": "拆解为业务和风险两个子问题后分别检索。",
            "assumptions": [],
            "retrieval_hints": {"keywords": ["报告期", "主营业务", "主要风险"]},
        }

    monkeypatch.setattr(service.remote_client, "understand", fake_understand)

    result = service.understand("报告期内公司的主营业务和主要风险分别是什么？")

    assert result.strategy == "online"
    assert result.sub_questions == ["报告期内公司的主营业务是什么？", "报告期内公司的主要风险是什么？"]


def test_query_understanding_contextualizes_followup_locally():
    service = QueryUnderstandingService(Settings(query_understanding_mode="rules"))

    rewritten_question, debug = service.contextualize_question(
        "那它的主营业务呢？",
        [
            {"role": "user", "content": "武汉兴图新科电子股份有限公司是什么公司？"},
            {"role": "assistant", "content": "这是一家..."},
        ],
    )

    assert rewritten_question == "上一轮用户问题：武汉兴图新科电子股份有限公司是什么公司？；当前追问：那它的主营业务呢？"
    assert debug["rewritten"] is True
    assert debug["source"] == "local"


def test_query_understanding_keeps_standalone_question_without_history():
    service = QueryUnderstandingService(Settings(query_understanding_mode="rules"))

    rewritten_question, debug = service.contextualize_question("公司的主营业务是什么？", [])

    assert rewritten_question == "公司的主营业务是什么？"
    assert debug["rewritten"] is False
    assert debug["reason"] == "no_history"


def test_query_understanding_contextualizes_followup_locally():
    service = QueryUnderstandingService(Settings(query_understanding_mode="rules"))

    rewritten_question, debug = service.contextualize_question(
        "那它的主营业务呢？",
        [
            {"role": "user", "content": "武汉兴图新科电子股份有限公司是什么公司？"},
            {"role": "assistant", "content": "这是一家..."},
        ],
    )

    assert rewritten_question == "上一轮用户问题：武汉兴图新科电子股份有限公司是什么公司？；当前追问：那它的主营业务呢？"
    assert debug["rewritten"] is True
    assert debug["source"] == "local"


def test_query_understanding_keeps_standalone_question_without_history():
    service = QueryUnderstandingService(Settings(query_understanding_mode="rules"))

    rewritten_question, debug = service.contextualize_question("公司的主营业务是什么？", [])

    assert rewritten_question == "公司的主营业务是什么？"
    assert debug["rewritten"] is False
    assert debug["reason"] == "no_history"


def test_pipeline_returns_clarification_without_retrieval():
    understanding = QueryUnderstandingResult(
        intent="general_information",
        normalized_question="它的情况怎么样？",
        strategy="online",
        ambiguous_terms=["它"],
        clarification_needed=True,
        clarification_question="你说的“它”具体指哪家公司或哪条产品线？",
        sub_questions=[],
        abstracted_goal="先澄清指代对象。",
        assumptions=[],
        retrieval_hints={"keywords": ["它"]},
    )

    class StubQueryUnderstandingService:
        def understand(self, question: str) -> QueryUnderstandingResult:
            assert question == "它的情况怎么样？"
            return understanding

    class StubRetrievalGenerationService:
        def answer(self, **_: object):
            raise AssertionError("clarification flow should not call retrieval_generation_service")

    pipeline = QAPipelineService(
        query_understanding_service=StubQueryUnderstandingService(),
        retrieval_generation_service=StubRetrievalGenerationService(),
        session_service=SessionService(InMemorySessionStore()),
    )

    response = pipeline.answer_question(QueryRequest(question="它的情况怎么样？", include_debug=True))

    assert response.answer == "你说的“它”具体指哪家公司或哪条产品线？"
    assert response.citations == []
    assert response.debug["mode"] == "clarification_requested"
    assert response.debug["retrieval_hints"] == {"keywords": ["它"]}
    assert "understanding" in response.debug["timing_ms"]
    assert response.session_id


def test_pipeline_returns_english_clarification_without_retrieval():
    understanding = QueryUnderstandingResult(
        intent="general_information",
        normalized_question="What about it?",
        detected_language="en",
        strategy="online",
        ambiguous_terms=["it"],
        clarification_needed=True,
        clarification_question="Please clarify what \"it\" refers to.",
        sub_questions=[],
        abstracted_goal="Clarify the referent first.",
        assumptions=[],
        retrieval_hints={"keywords": ["it"]},
    )

    class StubQueryUnderstandingService:
        def understand(self, question: str) -> QueryUnderstandingResult:
            assert question == "What about it?"
            return understanding

    class StubRetrievalGenerationService:
        def answer(self, **_: object):
            raise AssertionError("clarification flow should not call retrieval_generation_service")

    pipeline = QAPipelineService(
        query_understanding_service=StubQueryUnderstandingService(),
        retrieval_generation_service=StubRetrievalGenerationService(),
        session_service=SessionService(InMemorySessionStore()),
    )

    response = pipeline.answer_question(QueryRequest(question="What about it?", include_debug=True))

    assert response.answer == "Please clarify what \"it\" refers to."
    assert response.understanding.detected_language == "en"
