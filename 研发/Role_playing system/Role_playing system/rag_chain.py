# -*- coding: utf-8 -*-
"""
RAG 编排引擎
============
功能：协调知识检索、Prompt 组装、模型调用和降级策略。
作为 RAG（检索增强生成）的核心，负责：
  1. 从多个来源检索上下文（PDF 知识库、用户上传文件、系统知识库）
  2. 构建 Prompt（角色身份、对话历史、检索上下文）
  3. 调用 LLM 生成回复
  4. 处理社交开场白、轻量聊天、短期记忆等特殊场景
  5. LLM 不可用时提供降级回答
"""

from __future__ import annotations  # 支持延迟求值的类型注解（Python 3.7+）

import re  # 正则表达式（文本清洗、模式匹配）
from typing import Dict, Iterator, List, Optional  # 类型注解

# 导入数据处理模块
from data_processor import DataProcessor
# 导入 LLM 配置管理
from llm_settings import build_openai_client, load_llm_config
# 导入 ORM 模型
from models import SessionLocal, UploadedFile, UserDocumentChunk
# 导入 Prompt 模板
from prompts import PROMPT_TEMPLATES


# ============================================================
# 全局常量
# ============================================================
# 知识库未命中时的默认上下文提示
NO_KNOWLEDGE_CONTEXT = "当前知识库未检索到与该问题直接相关的内容。"
# 禁止直接返回的内容模式（高风险操作关键词）
DISALLOWED_DIRECT_RETURN_PATTERNS = (
    "炸药",
    "爆炸",
    "武器",
    "枪支",
    "手枪",
    "步枪",
    "子弹",
    "炸弹",
    "毒品",
    "制毒",
    "核武",
    "攻击",
    "袭击",
)


class RAGChain:
    """
    RAG 编排引擎。
    
    协调检索、Prompt 组装和模型调用的核心类。
    处理多种回答模式：社交开场白、轻量聊天、短期记忆、知识库回答、在线模型降级。
    """

    def __init__(self):
        """初始化 RAGChain：创建向量库、记忆、处理器和 LLM 客户端。"""
        # 延迟导入避免循环依赖
        from redis_memory import RedisMemory
        from vector_store import MilvusStore

        self.vector_store = MilvusStore()  # Milvus 向量数据库（知识检索）
        self.memory = RedisMemory()        # Redis 短期记忆（对话历史缓存）
        self.processor = DataProcessor()   # 数据处理器（文本清洗）
        self.llm_config = load_llm_config()  # 加载 LLM 配置
        self.model_name = self.llm_config["model_name"]      # 模型名称
        self.temperature = self.llm_config["temperature"]    # 生成温度
        self.top_p = self.llm_config["top_p"]                # nucleus sampling
        self.repetition_penalty = self.llm_config["repetition_penalty"]  # 重复惩罚
        self.max_new_tokens = self.llm_config["max_new_tokens"]          # 最大新生成 Token 数
        self.max_tokens = self.llm_config["max_tokens"]      # 兼容旧字段
        self.client = self._build_client()  # 构建 OpenAI 兼容客户端
        self.last_run_meta: Dict[str, object] = {}  # 上次运行的元数据（用于调试和日志）

    def _build_client(self):
        """
        构建 LLM 客户端。
        
        Returns:
            OpenAI 客户端实例，初始化失败返回 None
        """
        try:
            return build_openai_client(self.llm_config)
        except Exception:
            return None

    def _trim_text(self, text: str, limit: int = 1800) -> str:
        """
        截断文本到指定长度。
        
        用于控制检索上下文的长度，避免超出 LLM 的上下文窗口。
        
        Args:
            text: 原始文本
            limit: 最大字符数，默认 1800
            
        Returns:
            str: 截断后的文本（末尾添加 ...）
        """
        value = (text or "").strip()
        if not value:
            return ""
        if len(value) <= limit:
            return value
        return value[: limit - 3].rstrip() + "..."

    def _normalize_output_format(self, text: str) -> str:
        """
        规范化 LLM 输出格式。
        
        保留可展示的轻量格式（如 **粗体** 与 Markdown 表格），
        仅清理多余标题符号、列表符号、冗余空白和重复段落。
        
        Args:
            text: LLM 原始输出
            
        Returns:
            str: 规范化后的输出
        """
        if not text:
            return text

        # 保留 **粗体** 和 Markdown 表格，仅移除行内代码标记
        text = text.replace("`", "")

        # 逐行处理
        normalized_lines: List[str] = []
        for raw_line in text.splitlines():
            line = raw_line.rstrip()
            # 处理 Markdown 标题（# 开头）
            heading_match = re.match(r"^\s{0,3}#{1,6}\s*(.+?)\s*$", line)
            if heading_match:
                normalized_lines.append(heading_match.group(1).strip())
                continue

            # 保留 Markdown 表格分隔行
            if re.match(r"^\s*\|?(?:\s*:?-{3,}:?\s*\|)+\s*:?-{3,}:?\s*\|?\s*$", line):
                normalized_lines.append(line.strip())
                continue

            # 保留 Markdown 表格内容行
            if "|" in line and re.match(r"^\s*\|?.+\|.+\|?\s*$", line):
                normalized_lines.append(re.sub(r"\s{2,}", " ", line).strip())
                continue

            # 处理无序列表（- * _ 开头）
            bullet_match = re.match(r"^\s*[-*_]+\s+(.+)$", line)
            if bullet_match:
                normalized_lines.append(bullet_match.group(1).strip())
                continue

            # 合并多余空格
            normalized_lines.append(re.sub(r"\s{2,}", " ", line))

        # 合并多余空白行（最多保留一个空行）
        text = "\n".join(normalized_lines)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return self._dedupe_repeated_sections(text.strip())

    def _dedupe_repeated_sections(self, text: str) -> str:
        """
        去重重复的段落。
        
        基于行签名（去除空格后的内容）进行去重，
        避免 LLM 在输出中重复相同的句子。
        
        Args:
            text: 输入文本
            
        Returns:
            str: 去重后的文本
        """
        if not text:
            return text

        seen = set()      # 已见过的行签名集合
        previous = ""     # 上一行的签名（用于连续重复检测）
        deduped_lines: List[str] = []
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                # 空行：最多保留一个连续空行
                if deduped_lines and deduped_lines[-1] != "":
                    deduped_lines.append("")
                previous = ""
                continue

            signature = re.sub(r"\s+", " ", line)  # 行签名（去除多余空格）
            if signature == previous:
                continue  # 跳过连续重复行
            if len(signature) >= 10 and signature in seen:
                continue  # 跳过已出现过的行（长度 >= 10 的才去重）

            deduped_lines.append(line)
            previous = signature
            if len(signature) >= 10:
                seen.add(signature)

        return "\n".join(deduped_lines).strip()

    def retrieve_public_context(self, query: str, role_type: str, top_k: int = 3) -> str:
        """
        从系统知识库（非 PDF）检索上下文。
        
        Args:
            query: 检索查询
            role_type: 角色类型（按角色过滤）
            top_k: 返回的最相关文档数，默认 3
            
        Returns:
            str: 格式化后的检索上下文
        """
        results = self.vector_store.search_non_pdf_documents(query, role_type, top_k)
        return self._format_retrieved_context(results)

    def _is_pdf_source(self, source: str) -> bool:
        """判断来源是否为 PDF 文档。"""
        checker = getattr(self.vector_store, "_is_pdf_source", None)
        if callable(checker):
            return bool(checker(source))

        normalized = (source or "").strip().lower()
        return normalized.endswith(".pdf") or ".pdf" in normalized

    def retrieve_public_contexts(
        self,
        query: str,
        role_type: str,
        public_top_k: int = 3,
        pdf_top_k: int = 4,
    ) -> tuple[str, str]:
        """
        一次公共检索同时拆分出 PDF 与非 PDF 上下文，避免重复检索。
        """
        combined_top_k = max(public_top_k + pdf_top_k, public_top_k, pdf_top_k, 1)
        results = self.vector_store.search(query, role_type, combined_top_k)
        if not results:
            return "", ""

        pdf_results: List[Dict] = []
        public_results: List[Dict] = []
        for result in results:
            if self._is_pdf_source(result.get("source", "")):
                if len(pdf_results) < pdf_top_k:
                    pdf_results.append(result)
            else:
                if len(public_results) < public_top_k:
                    public_results.append(result)

            if len(pdf_results) >= pdf_top_k and len(public_results) >= public_top_k:
                break

        return (
            self._format_retrieved_context(pdf_results),
            self._format_retrieved_context(public_results),
        )

    def retrieve_pdf_context(self, query: str, role_type: str, top_k: int = 4) -> str:
        """
        从 PDF 知识库检索上下文（优先使用）。
        
        Args:
            query: 检索查询
            role_type: 角色类型（按角色过滤）
            top_k: 返回的最相关文档数，默认 4
            
        Returns:
            str: 格式化后的检索上下文
        """
        results = self.vector_store.search_pdf_documents(query, role_type, top_k)
        return self._format_retrieved_context(results)

    def _format_retrieved_context(self, results: List[Dict]) -> str:
        """
        格式化检索结果为可读文本。
        
        每个结果包含标题、内容和来源，用分隔线隔开。
        
        Args:
            results: 检索结果列表 [{title, content, source}]
            
        Returns:
            str: 格式化后的上下文文本
        """
        if not results:
            return ""

        context_parts: List[str] = []
        for result in results:
            # 截断各字段到合理长度
            title = self._trim_text(result.get("title", ""), 200)
            content = self._trim_text(result.get("content", ""), 1800)
            source = self._trim_text(result.get("source", ""), 200)

            # 构建单个文档块
            block_parts: List[str] = []
            if title:
                block_parts.append(f"标题：{title}")
            if content:
                block_parts.append(f"内容：{content}")
            if source:
                block_parts.append(f"来源：{source}")

            if block_parts:
                context_parts.append("\n".join(block_parts))

        return "\n\n".join(context_parts)

    def retrieve_user_file_context(
        self,
        query: str,
        user_id: Optional[int] = None,
        conversation_id: Optional[int] = None,
        top_k: int = 4,
        include_other_conversations: bool = True,
    ) -> str:
        """
        从用户上传的文件中检索上下文。
        
        Args:
            query: 检索查询
            user_id: 用户 ID（可选）
            conversation_id: 会话 ID（可选）
            top_k: 返回的最相关文档数，默认 4
            include_other_conversations: 是否包含其他会话的文件，默认 True
            
        Returns:
            str: 格式化后的文件上下文
        """
        if not user_id:
            return ""

        # 从向量库检索用户文档分块
        results = self.vector_store.search_user_document_chunks(
            query=query,
            user_id=user_id,
            conversation_id=conversation_id,
            top_k=top_k,
            include_other_conversations=include_other_conversations,
        )
        if not results:
            return ""

        # 格式化检索结果
        context_parts: List[str] = []
        for result in results:
            title = self._trim_text(result.get("title", ""), 200)
            content = self._trim_text(result.get("content", ""), 1800)
            source = self._trim_text(result.get("source", ""), 200)

            block_parts: List[str] = []
            if title:
                block_parts.append(f"文件标题：{title}")
            if content:
                block_parts.append(f"文件内容：{content}")
            if source:
                block_parts.append(f"文件来源：{source}")

            if block_parts:
                context_parts.append("\n".join(block_parts))

        return "\n\n".join(context_parts)

    def _get_uploaded_file_request_mode(self, user_message: str) -> str:
        """识别用户对上传文件的请求类型。"""
        if self._is_document_full_output_request(user_message):
            return "full_output"
        if self._is_document_overview_request(user_message):
            return "overview"
        return "search"

    def _retrieve_uploaded_file_context_for_request(
        self,
        query: str,
        user_message: str,
        user_id: Optional[int] = None,
        conversation_id: Optional[int] = None,
        include_other_conversations: bool = True,
    ) -> str:
        """按请求类型选择上传文件的检索策略。"""
        request_mode = self._get_uploaded_file_request_mode(user_message)

        if request_mode == "full_output":
            context = self._build_uploaded_file_full_context(
                user_id=user_id,
                conversation_id=conversation_id,
            )
            if context:
                return context

        if request_mode == "overview":
            context = self._build_uploaded_file_overview_context(
                user_id=user_id,
                conversation_id=conversation_id,
            )
            if context:
                return context

        return self.retrieve_user_file_context(
            query=query,
            user_id=user_id,
            conversation_id=conversation_id,
            include_other_conversations=include_other_conversations,
        )

    def _assemble_retrieval_context(
        self,
        pdf_context: str = "",
        private_context: str = "",
        public_context: str = "",
    ) -> str:
        """按优先级拼接各检索来源的上下文。"""
        sections: List[str] = []
        if pdf_context:
            sections.append(f"PDF知识库内容（优先）：\n{pdf_context}")
        if private_context:
            sections.append(f"用户上传文件内容：\n{private_context}")
        if public_context:
            sections.append(f"系统知识库内容：\n{public_context}")

        if not sections:
            return NO_KNOWLEDGE_CONTEXT
        return "\n\n".join(sections)

    def _has_current_conversation_uploads(
        self,
        user_id: Optional[int] = None,
        conversation_id: Optional[int] = None,
    ) -> bool:
        """
        检查当前会话是否有上传的文件。
        
        Args:
            user_id: 用户 ID
            conversation_id: 会话 ID
            
        Returns:
            bool: True 表示当前会话有上传文件
        """
        if not user_id or not conversation_id:
            return False

        db = SessionLocal()
        try:
            # 查询当前会话是否有已上传的文件
            return (
                db.query(UploadedFile.id)
                .filter(
                    UploadedFile.user_id == int(user_id),
                    UploadedFile.conversation_id == int(conversation_id),
                )
                .first()
                is not None
            )
        finally:
            db.close()

    def build_context(
        self,
        query: str,
        role_type: str,
        user_id: Optional[int] = None,
        conversation_id: Optional[int] = None,
        user_message: Optional[str] = None,
        private_context: Optional[str] = None,
    ) -> str:
        """
        构建完整的检索上下文。
        
        按优先级合并多个来源的上下文：
        1. PDF 知识库（优先）
        2. 用户上传文件
        3. 系统知识库
        
        Args:
            query: 检索查询
            role_type: 角色类型
            user_id: 用户 ID（可选）
            conversation_id: 会话 ID（可选）
            user_message: 用户原始消息（可选，用于判断文档概览请求）
            
        Returns:
            str: 合并后的上下文文本
        """
        pdf_context, public_context = self.retrieve_public_contexts(
            query=query,
            role_type=role_type,
            public_top_k=3,
            pdf_top_k=4,
        )
        resolved_private_context = private_context
        if resolved_private_context is None:
            resolved_private_context = self._retrieve_uploaded_file_context_for_request(
                query=query,
                user_message=user_message or query,
                user_id=user_id,
                conversation_id=conversation_id,
            )
        prepared_private_context = (
            self._prepare_uploaded_file_context(user_message or query, resolved_private_context)
            if resolved_private_context
            else ""
        )
        return self._assemble_retrieval_context(
            pdf_context=pdf_context,
            private_context=prepared_private_context,
            public_context=public_context,
        )

    def _has_knowledge_context(self, context: str) -> bool:
        """
        检查是否检索到了有效的知识上下文。
        
        Args:
            context: 上下文文本
            
        Returns:
            bool: True 表示有有效的知识上下文
        """
        return bool(context and context.strip() and context.strip() != NO_KNOWLEDGE_CONTEXT)

    def _requires_direct_return_block(self, user_message: str, private_context: str) -> bool:
        """
        检查是否需要阻止直接返回文件内容。
        
        如果用户消息或文件内容包含高风险关键词（如武器、毒品等），
        则阻止直接返回原文，防止滥用。
        
        Args:
            user_message: 用户消息
            private_context: 文件上下文
            
        Returns:
            bool: True 表示需要阻止直接返回
        """
        text = f"{user_message or ''}\n{private_context or ''}".lower()
        return any(pattern.lower() in text for pattern in DISALLOWED_DIRECT_RETURN_PATTERNS)

    def _build_direct_return_block_reply(self) -> str:
        """
        构建阻止直接返回时的回复。
        
        Returns:
            str: 安全提示回复
        """
        return (
            "已检索到上传文件内容，但命中的内容涉及高风险操作细节，"
            "不能直接原文返回。请改为说明你的合规用途，我再给你做安全范围内的整理。"
        )

    def _is_document_overview_request(self, user_message: str) -> bool:
        """
        判断用户是否在请求文档概览。
        
        匹配常见的文档概览请求模式，如"文档里有什么"、"总结一下"等。
        
        Args:
            user_message: 用户消息
            
        Returns:
            bool: True 表示是文档概览请求
        """
        text = (user_message or "").strip().lower()
        if not text:
            return False
        patterns = (
            "文档里有什么",
            "文件里有什么",
            "文档讲了什么",
            "文件讲了什么",
            "总结一下文档",
            "总结一下文件",
            "概括一下文档",
            "概括一下文件",
            "介绍一下文档",
            "介绍一下文件",
            "提炼一下",
            "输出一下",
        )
        return any(pattern in text for pattern in patterns)

    def _is_document_full_output_request(self, user_message: str) -> bool:
        """判断用户是否在明确要求输出整份文件内容。"""
        text = (user_message or "").strip().lower()
        if not text:
            return False
        patterns = (
            "输出文件内容",
            "输出全部内容",
            "全部输出",
            "完整输出",
            "全文输出",
            "输出全文",
            "完整内容",
            "原文输出",
            "把文件内容输出",
            "把文档内容输出",
            "显示全文",
            "全文直出",
            "全文直出回复",
        )
        if any(pattern in text for pattern in patterns):
            return True

        return (
            "输出" in text
            and any(token in text for token in ("全文", "全部", "完整", "原文"))
        ) or (
            any(token in text for token in ("文件内容", "文档内容"))
            and any(token in text for token in ("输出", "直出", "全文", "全部"))
        )

    def _build_uploaded_file_prefix(self, user_message: str, private_context: str) -> str:
        """
        构建上传文件回答的前缀指令。
        
        根据是否为文档概览请求，生成不同的 LLM 指令：
        - 概览请求：要求简洁总结，不要逐字输出
        - 普通请求：要求先整理再回答
        
        Args:
            user_message: 用户消息
            private_context: 文件上下文
            
        Returns:
            str: LLM 指令前缀
        """
        if not private_context:
            return ""
        if self._is_document_full_output_request(user_message):
            return (
                "本轮优先基于用户上传文件回答。\n"
                "用户这次是在明确要求输出文件内容或全文。\n"
                "请优先按文档顺序整理并输出主要正文内容，"
                "不要只返回单个表格碎片，也不要只给一句摘要。\n"
                "如果文档里存在页眉页脚、免责声明、联系方式等明显噪声，可以省略。"
            )
        if self._is_document_overview_request(user_message):
            return (
                "本轮优先基于用户上传文件回答。\n"
                "如果用户是在询问文档里有什么、让你概括、总结、提炼，默认先做简洁总结："
                "先说文档主题，再说关键内容和重要数据。\n"
                "不要直接大段逐字输出检索片段，不要把原始碎片拼接成生硬文本；"
                "不要使用项目符号或编号列表；"
                "只有在用户明确要求引用原文时，才允许给出少量短摘录。"
            )
        return (
            "本轮优先基于用户上传文件回答。\n"
            "除非用户明确要求原文摘录，否则不要直接逐字回显检索片段，应先整理后再回答。"
        )

    def _build_uploaded_file_context_digest(self, private_context: str, max_lines: int = 12, max_chars: int = 2400) -> str:
        """
        构建上传文件上下文的摘要。
        
        过滤掉 OCR 标记、结构化标签等噪音，提取有意义的文本行。
        
        Args:
            private_context: 原始文件上下文
            max_lines: 最大行数，默认 12
            max_chars: 最大字符数，默认 2400
            
        Returns:
            str: 摘要文本
        """
        if not private_context:
            return ""

        # 需要跳过的行前缀
        skip_prefixes = (
            "[第 ",     # OCR 页码标记
            "[正文]",   # OCR 正文标记
            "[表格 ",   # OCR 表格标记
            "[OCR]",    # OCR 标记
        )
        # 需要跳过的精确行
        skip_exact = {
            "文件标题",
            "文件内容",
            "资料来源",
        }

        # 逐行过滤
        lines: List[str] = []
        for raw_line in private_context.splitlines():
            line = self.processor.clean_text(raw_line)
            if not line:
                continue
            if any(line.startswith(prefix) for prefix in skip_prefixes):
                continue
            if line in skip_exact:
                continue
            if re.fullmatch(r"[\d\W_]+", line) and len(line) < 12:
                continue  # 跳过纯数字/符号的短行
            lines.append(line)
            if len(lines) >= max_lines:
                break

        digest = "\n".join(lines).strip()
        if not digest:
            digest = self.processor.clean_text(private_context)
        return digest[:max_chars]

    def _build_uploaded_file_overview_context(
        self,
        user_id: Optional[int] = None,
        conversation_id: Optional[int] = None,
        max_chunks: int = 6,
    ) -> str:
        """
        构建上传文件的概览上下文。
        
        从数据库读取文件分块，优先选择包含关键信息（如核心观点、摘要、结论）的分块。
        用于"文档里有什么"这类概览请求。
        
        Args:
            user_id: 用户 ID
            conversation_id: 会话 ID
            max_chunks: 最大分块数，默认 6
            
        Returns:
            str: 概览上下文
        """
        if not user_id or not conversation_id:
            return ""

        db = SessionLocal()
        try:
            # 查询最新的已解析文件
            uploaded_file = (
                db.query(UploadedFile)
                .filter(
                    UploadedFile.user_id == int(user_id),
                    UploadedFile.conversation_id == int(conversation_id),
                    UploadedFile.parse_status == "ready",
                )
                .order_by(UploadedFile.created_at.desc(), UploadedFile.id.desc())
                .first()
            )
            if not uploaded_file:
                return ""

            # 查询文件的所有分块
            chunks = (
                db.query(UserDocumentChunk)
                .filter(
                    UserDocumentChunk.file_id == uploaded_file.id,
                    UserDocumentChunk.user_id == int(user_id),
                    UserDocumentChunk.conversation_id == int(conversation_id),
                )
                .order_by(UserDocumentChunk.chunk_index.asc(), UserDocumentChunk.id.asc())
                .all()
            )
            if not chunks:
                return ""

            # 选择分块：先取前 3 个，再补充包含关键信息的分块
            selected_indexes = set()
            selected_chunks: List[UserDocumentChunk] = []

            # 前 3 个分块（文档开头）
            for chunk in chunks[:3]:
                selected_indexes.add(chunk.chunk_index)
                selected_chunks.append(chunk)

            # 关键信息关键词
            overview_keywords = (
                "核心观点",
                "投资建议",
                "风险提示",
                "摘要",
                "结论",
                "盈利预测",
                "财务指标",
            )
            # 补充包含关键信息的分块
            for chunk in chunks[3:]:
                if len(selected_chunks) >= max_chunks:
                    break
                content = self.processor.clean_text(chunk.content or "")
                if not content:
                    continue
                if chunk.chunk_index in selected_indexes:
                    continue
                if any(keyword in content for keyword in overview_keywords):
                    selected_indexes.add(chunk.chunk_index)
                    selected_chunks.append(chunk)

            # 按索引排序
            selected_chunks.sort(key=lambda item: (item.chunk_index, item.id))

            # 构建概览文本
            parts = [f"文件标题：{uploaded_file.original_name}"]
            for chunk in selected_chunks[:max_chunks]:
                content = self.processor.clean_text(chunk.content or "")
                if content:
                    parts.append(content)
            return "\n\n".join(parts).strip()
        finally:
            db.close()

    def _build_uploaded_file_full_context(
        self,
        user_id: Optional[int] = None,
        conversation_id: Optional[int] = None,
        max_chunks: int = 12,
        max_chars: int = 12000,
    ) -> str:
        """构建更完整的上传文件上下文，用于全文输出类请求。"""
        if not user_id or not conversation_id:
            return ""

        db = SessionLocal()
        try:
            uploaded_file = (
                db.query(UploadedFile)
                .filter(
                    UploadedFile.user_id == int(user_id),
                    UploadedFile.conversation_id == int(conversation_id),
                    UploadedFile.parse_status == "ready",
                )
                .order_by(UploadedFile.created_at.desc(), UploadedFile.id.desc())
                .first()
            )
            if not uploaded_file:
                return ""

            chunks = (
                db.query(UserDocumentChunk)
                .filter(
                    UserDocumentChunk.file_id == uploaded_file.id,
                    UserDocumentChunk.user_id == int(user_id),
                    UserDocumentChunk.conversation_id == int(conversation_id),
                )
                .order_by(UserDocumentChunk.chunk_index.asc(), UserDocumentChunk.id.asc())
                .all()
            )
            if not chunks:
                return ""

            parts = [f"文件标题：{uploaded_file.original_name}"]
            current_chars = len(parts[0])
            for chunk in chunks[:max_chunks]:
                content = self.processor.clean_text(chunk.content or "")
                if not content:
                    continue
                if current_chars + len(content) > max_chars:
                    remaining = max_chars - current_chars
                    if remaining > 80:
                        parts.append(content[:remaining])
                    break
                parts.append(content)
                current_chars += len(content)
            return "\n\n".join(parts).strip()
        finally:
            db.close()

    def _build_uploaded_file_full_output_reply(
        self,
        user_id: Optional[int] = None,
        conversation_id: Optional[int] = None,
        max_chunks: int = 12,
        max_chars: int = 12000,
    ) -> str:
        """为全文输出类请求直接构建回复，绕过 LLM 总结改写。"""
        content = self._build_uploaded_file_full_context(
            user_id=user_id,
            conversation_id=conversation_id,
            max_chunks=max_chunks,
            max_chars=max_chars,
        )
        if not content:
            return ""
        return content

    def _prepare_uploaded_file_context(self, user_message: str, private_context: str) -> str:
        """
        预处理上传文件上下文。
        
        生成摘要并添加 LLM 指令前缀。
        
        Args:
            user_message: 用户消息
            private_context: 原始文件上下文
            
        Returns:
            str: 处理后的上下文
        """
        if not private_context:
            return ""
        # 判断是否为概览请求，调整摘要参数
        is_overview_request = self._is_document_overview_request(user_message)
        digest = self._build_uploaded_file_context_digest(
            private_context,
            max_lines=24 if is_overview_request else 12,    # 概览请求允许更多行
            max_chars=3600 if is_overview_request else 2400,  # 概览请求允许更多字符
        )
        # 添加 LLM 指令前缀
        prefix = self._build_uploaded_file_prefix(user_message, private_context)
        if prefix:
            return f"{prefix}\n\n{digest}"
        return digest

    def _collect_runtime_retrieval_state(
        self,
        user_message: str,
        history_messages: Optional[List[Dict]] = None,
        user_id: Optional[int] = None,
        conversation_id: Optional[int] = None,
    ) -> Dict[str, object]:
        """收集一次回答所需的检索运行态。"""
        retrieval_query = self._build_retrieval_query(user_message, history_messages)
        history = self.format_history(conversation_id, history_messages=history_messages)
        uploaded_file_mode = self._has_current_conversation_uploads(user_id, conversation_id)
        request_mode = self._get_uploaded_file_request_mode(user_message)
        history_priority_prefix = self._build_history_priority_prefix(user_message, history_messages)

        private_context = ""
        if uploaded_file_mode:
            private_context = self._retrieve_uploaded_file_context_for_request(
                query=retrieval_query,
                user_message=user_message,
                user_id=user_id,
                conversation_id=conversation_id,
                include_other_conversations=False,
            )

        return {
            "retrieval_query": retrieval_query,
            "history": history,
            "uploaded_file_mode": uploaded_file_mode,
            "request_mode": request_mode,
            "history_priority_prefix": history_priority_prefix,
            "private_context": private_context,
        }

    def _build_last_run_meta(
        self,
        context: str,
        private_context: str,
        uploaded_file_mode: bool,
        answer_mode: str,
        history_messages: Optional[List[Dict]] = None,
        knowledge_context_used: Optional[bool] = None,
        direct_return_blocked: bool = False,
        llm_reason: Optional[str] = None,
    ) -> Dict[str, object]:
        """统一构造检索/回答元数据。"""
        resolved_knowledge_context_used = (
            self._has_knowledge_context(context)
            if knowledge_context_used is None
            else knowledge_context_used
        )
        return {
            "pdf_context_used": "PDF知识库内容（优先）" in (context or ""),
            "user_file_context_used": "用户上传文件内容" in (context or "") or bool(private_context),
            "public_context_used": "系统知识库内容" in (context or ""),
            "knowledge_context_used": resolved_knowledge_context_used,
            "uploaded_file_mode": uploaded_file_mode,
            "direct_return_blocked": direct_return_blocked,
            "answer_mode": answer_mode,
            "history_used": bool(history_messages),
            "history_message_count": len(history_messages or []),
            "llm_reason": llm_reason,
        }

    def _build_retrieval_query(
        self,
        user_message: str,
        history_messages: Optional[List[Dict]] = None,
    ) -> str:
        """
        构建检索查询。
        
        如果有多轮对话历史，将最近的用户消息和当前问题拼接，
        提供更完整的检索上下文。
        
        Args:
            user_message: 当前用户消息
            history_messages: 历史消息列表（可选）
            
        Returns:
            str: 增强后的检索查询
        """
        if not history_messages:
            return user_message

        # 取最近 6 条消息的内容
        recent_parts: List[str] = []
        for msg in history_messages[-6:]:
            content = (msg.get("content") or "").strip()
            if content:
                recent_parts.append(content)

        if not recent_parts:
            return user_message
        # 拼接历史消息和当前问题
        return "\n".join([*recent_parts, user_message])

    def _build_history_priority_prefix(
        self,
        user_message: str,
        history_messages: Optional[List[Dict]] = None,
    ) -> str:
        """
        构建对话历史优先的 LLM 指令前缀。
        
        告诉 LLM 优先从对话历史中找答案，避免不必要的知识库扩展。
        
        Args:
            user_message: 当前用户消息
            history_messages: 历史消息列表（可选）
            
        Returns:
            str: LLM 指令前缀
        """
        # 提取最近 8 条消息中的用户消息
        recent_user_messages: List[str] = []
        if history_messages:
            for msg in history_messages[-8:]:
                if msg.get("sender_type") != "user":
                    continue
                content = (msg.get("content") or "").strip()
                if content:
                    recent_user_messages.append(self._trim_text(content, 120))

        # 格式化最近用户消息
        recent_user_text = "\n".join(f"- {item}" for item in recent_user_messages[-4:])
        if not recent_user_text:
            recent_user_text = "- 无"

        return (
            "回答前请先检查对话历史。\n"
            "如果用户当前问题可以直接从最近对话中得到答案，优先基于对话历史回答，"
            "不要扩展成知识分析、风险提示或固定模板。\n"
            "这类命中历史的回答应尽量短，通常 1 到 2 句即可。\n"
            "只有当问题确实需要专业知识时，才结合知识库内容展开回答。\n\n"
            f"当前用户问题：{user_message}\n"
            f"最近几条用户信息：\n{recent_user_text}\n"
        )

    def _extract_intro_name(self, user_message: str) -> str:
        """
        从用户消息中提取自我介绍的名字。
        
        支持模式："我是XXX"、"我叫XXX"、"叫我XXX"、"你可以叫我XXX"
        
        Args:
            user_message: 用户消息
            
        Returns:
            str: 提取的名字，未找到返回空字符串
        """
        text = re.sub(r"\s+", "", user_message or "")
        if not text:
            return ""
        # 无效名字（不是真正的名字）
        invalid_names = {
            "什么",
            "什么吗",
            "啥",
            "啥吗",
            "谁",
            "谁吗",
            "名字",
            "姓名",
            "名字吗",
            "姓名吗",
        }
        # 名字提取正则（支持中文、英文、数字、下划线、连字符、间隔号）
        patterns = (
            r"(?:我是|我叫)([A-Za-z0-9_\-\u4e00-\u9fff·]{1,12})",
            r"(?:叫我|你可以叫我)([A-Za-z0-9_\-\u4e00-\u9fff·]{1,12})",
        )
        for pattern in patterns:
            matched = re.search(pattern, text)
            if matched:
                candidate = matched.group(1).strip("，。！？,.!?:：；;（）()[]【】")
                if candidate in invalid_names:
                    continue
                if candidate.endswith(("什么", "啥", "谁", "名字", "姓名")):
                    continue
                return candidate
        return ""

    def _build_social_opening_reply(self, role_type: str, user_message: str) -> Optional[str]:
        """
        构建社交开场白回复。
        
        检测用户是否在打招呼或咨询开场，返回对应的角色化回复。
        如果用户同时包含实质性内容（如"赔偿"、"合同"），则不触发开场白。
        
        Args:
            role_type: 角色类型
            user_message: 用户消息
            
        Returns:
            Optional[str]: 开场白回复，不匹配返回 None
        """
        normalized = re.sub(r"\s+", "", user_message or "").lower()
        if not normalized:
            return None

        # 纯问候语
        pure_greetings = (
            "你好",
            "您好",
            "嗨",
            "hi",
            "hello",
            "在吗",
            "在嘛",
        )
        # 咨询开场白
        consult_openings = (
            "可以问你吗",
            "可以咨询吗",
            "可以咨询",
            "可以请教吗",
            "可以请教",
            "想咨询",
            "想请教",
            "咨询一下",
            "请教一下",
            "有一些法律问题",
            "有一些问题想问",
            "有点问题想问",
            "方便咨询",
            "方便请教",
            "咨询股票",
        )
        # 实质性内容信号（如果包含这些，说明用户有具体问题）
        substantive_signals = (
            "怎么办",
            "怎么处理",
            "如何处理",
            "赔偿",
            "仲裁",
            "起诉",
            "离婚",
            "合同",
            "借款",
            "欠款",
            "劳动",
            "工伤",
            "量刑",
            "财报",
            "估值",
            "股价",
            "买入",
            "卖出",
            "诊断",
            "治疗",
            "症状",
            "实验",
            "论文",
        )

        is_pure_greeting = normalized in pure_greetings
        has_greeting = any(token in normalized for token in pure_greetings)
        has_consult_opening = any(token in normalized for token in consult_openings)
        has_substantive_signal = any(token in normalized for token in substantive_signals)

        # 只有纯问候或咨询开场才触发，有实质性内容时不触发
        if not is_pure_greeting and not has_consult_opening:
            return None
        if has_substantive_signal and not has_consult_opening:
            return None

        # 提取用户名字
        user_name = self._extract_intro_name(user_message)
        salutation = f"你好，{user_name}。" if user_name else "你好。"

        # 各角色的开场白回复
        role_replies = {
            "lawyer": f"{salutation}可以，你直接把具体情况、时间线和你最想解决的问题发我，我帮你一起梳理。",
            "stock_analyst": f"{salutation}可以，你直接说想看哪只股票、哪个行业，或者你的风险偏好，我帮你一起分析。",
            "teacher": f"{salutation}当然可以，你把具体学科、年级或者卡住的题目发我，我带你一步步看。",
            "psychological_counselor": f"{salutation}可以，你愿意的话可以慢慢说，我会尽量陪你一起梳理当前的情况。",
            "doctor": f"{salutation}可以，你把症状、持续时间和最担心的问题告诉我，我先帮你做一般性判断。",
            "scientist": f"{salutation}可以，你把具体问题、研究目标或实验思路发我，我帮你一起拆解。",
            "custom_persona": f"{salutation}可以，你直接说你想问什么就行。",
        }
        return role_replies.get(role_type, f"{salutation}可以，你直接说你的具体问题就行。")

    def _has_substantive_signal(self, text: str) -> bool:
        """
        检查文本是否包含实质性内容信号。
        
        用于区分闲聊和真正的问题咨询。
        
        Args:
            text: 用户消息
            
        Returns:
            bool: True 表示包含实质性内容
        """
        normalized = re.sub(r"\s+", "", text or "").lower()
        if not normalized:
            return False

        # 实质性内容关键词
        substantive_signals = (
            "怎么办",
            "怎么处理",
            "如何处理",
            "赔偿",
            "仲裁",
            "起诉",
            "离婚",
            "合同",
            "借款",
            "欠款",
            "劳动",
            "工伤",
            "量刑",
            "财报",
            "估值",
            "股价",
            "买入",
            "卖出",
            "基金",
            "仓位",
            "止损",
            "诊断",
            "治疗",
            "症状",
            "实验",
            "论文",
            "数学",
            "英语",
            "失眠",
            "焦虑",
        )
        return any(token in normalized for token in substantive_signals)

    def _build_lightweight_chat_reply(
        self,
        role_type: str,
        user_message: str,
        role_name: Optional[str] = None,
    ) -> Optional[str]:
        """
        构建轻量聊天回复。
        
        处理简单的社交互动，如"谢谢"、"你是谁"、"在吗"、"好的"等。
        如果包含实质性内容，则不触发轻量回复。
        
        Args:
            role_type: 角色类型
            user_message: 用户消息
            role_name: 角色名称（可选）
            
        Returns:
            Optional[str]: 轻量回复，不匹配返回 None
        """
        normalized = re.sub(r"\s+", "", user_message or "").lower()
        if not normalized or self._has_substantive_signal(normalized):
            return None

        # 解析角色名称
        resolved_role_name = (role_name or "").strip()
        if not resolved_role_name:
            resolved_role_name = {
                "lawyer": "王律师",
                "stock_analyst": "张分析师",
                "teacher": "李老师",
                "psychological_counselor": "心理咨询师",
                "doctor": "陈医生",
                "scientist": "周科学家",
                "custom_persona": "智能助手",
            }.get(role_type, "智能助手")

        # 感谢回复
        if any(token in normalized for token in ("谢谢", "多谢", "谢了", "感谢")):
            return "不客气，你有需要就直接说。"

        # 身份询问
        if normalized in {"你是谁", "你叫什么", "你是做什么的"} or "你是谁" in normalized:
            return f"我是{resolved_role_name}，你直接说你的问题就行。"

        # 身份确认
        if f"你是{resolved_role_name}".lower() in normalized or normalized.endswith("是吗") and resolved_role_name.lower() in normalized:
            return f"对，我是{resolved_role_name}。"

        # 在吗
        if normalized in {"在吗", "在嘛", "在不在", "有人吗"}:
            return "在，你直接说。"

        # 确认回复
        if normalized in {"好的", "好", "行", "明白了", "知道了", "嗯", "嗯嗯", "哦哦"}:
            return "好，你继续说。"

        return None

    def _is_memory_question(self, user_message: str) -> bool:
        """
        判断用户是否在询问短期记忆相关的问题。
        
        如"我叫什么"、"你还记得我吗"、"我刚才说了什么"等。
        
        Args:
            user_message: 用户消息
            
        Returns:
            bool: True 表示是记忆相关问题
        """
        normalized = re.sub(r"\s+", "", user_message or "").lower()
        if not normalized:
            return False
        # 直接记忆相关问题短语
        direct_phrases = (
            "我叫什么",
            "我叫啥",
            "我是谁",
            "你还记得我吗",
            "还记得我吗",
            "你记得我吗",
            "你认识我吗",
            "还认识我吗",
            "你记得我叫什么",
            "你记得我叫啥",
            "你记得我是谁",
            "还记得我叫什么",
            "还记得我是谁",
            "我刚才说了什么",
            "我刚刚说了什么",
            "你还记得我刚才说了什么",
        )
        return any(phrase in normalized for phrase in direct_phrases)

    def _extract_recent_user_facts(
        self,
        conversation_id: int,
        history_messages: Optional[List[Dict]] = None,
        limit: int = 8,
    ) -> Dict[str, str]:
        """
        从对话历史中提取最近的用户事实。
        
        包括用户最后一条消息和用户自我介绍的名字。
        
        Args:
            conversation_id: 会话 ID
            history_messages: 历史消息列表（可选）
            limit: 最大消息数，默认 8
            
        Returns:
            Dict[str, str]: 事实字典，包含 last_user_message 和 user_name
        """
        messages = (
            history_messages[-limit:]
            if history_messages is not None
            else self.memory.get_recent_messages(conversation_id, limit)
        )
        facts: Dict[str, str] = {}
        # 提取所有用户消息
        recent_user_messages = [
            (msg.get("content") or "").strip()
            for msg in messages
            if msg.get("sender_type") == "user" and (msg.get("content") or "").strip()
        ]
        if not recent_user_messages:
            return facts

        # 记录最后一条用户消息
        facts["last_user_message"] = recent_user_messages[-1]
        # 尝试提取用户名字
        for text in reversed(recent_user_messages):
            user_name = self._extract_intro_name(text)
            if user_name:
                facts["user_name"] = user_name
                break
        return facts

    def _build_memory_reply(
        self,
        conversation_id: int,
        user_message: str,
        history_messages: Optional[List[Dict]] = None,
    ) -> Optional[str]:
        """
        构建短期记忆回复。
        
        处理用户关于记忆的问题，如"我叫什么"、"你还记得我吗"等。
        从对话历史中提取相关信息并回复。
        
        Args:
            conversation_id: 会话 ID
            user_message: 用户消息
            history_messages: 历史消息列表（可选）
            
        Returns:
            Optional[str]: 记忆回复，不匹配返回 None
        """
        if not self._is_memory_question(user_message):
            return None

        normalized = re.sub(r"\s+", "", user_message or "").lower()
        # 提取最近用户事实
        facts = self._extract_recent_user_facts(
            conversation_id=conversation_id,
            history_messages=history_messages,
        )
        user_name = facts.get("user_name", "")
        last_user_message = facts.get("last_user_message", "")

        # 处理"我刚才说了什么"类问题
        if "刚才说了什么" in normalized or "刚刚说了什么" in normalized:
            if last_user_message:
                return f"你刚才说的是：{last_user_message}"
            return "这段对话里你刚才还没有留下可回忆的内容。"

        # 处理"你还记得我吗"类问题
        if any(phrase in normalized for phrase in {"你还记得我吗", "还记得我吗", "你记得我吗", "你认识我吗", "还认识我吗"}):
            if user_name:
                return f"记得，你是{user_name}。"
            if last_user_message:
                return "记得，我们刚才已经聊过。"
            return "这段对话里我还没有记住你的具体信息。"

        # 处理"我是谁"类问题
        if "我是谁" in normalized:
            if user_name:
                return f"你是{user_name}。"
            return "你刚才还没有告诉我你怎么称呼。"

        # 处理"我叫什么"类问题
        if user_name:
            return f"你叫{user_name}。"
        return "你刚才还没有告诉我你叫什么。"

    def _build_persona_prefix(
        self,
        role_type: str,
        role_name: Optional[str] = None,
        role_description: Optional[str] = None,
    ) -> str:
        """
        构建角色身份前缀指令。
        
        告诉 LLM 当前扮演的角色身份，确保回答风格一致。
        如果未提供角色名称或描述，使用默认值。
        
        Args:
            role_type: 角色类型
            role_name: 角色名称（可选）
            role_description: 角色描述（可选）
            
        Returns:
            str: 角色身份指令
        """
        resolved_name = (role_name or "").strip()
        resolved_description = (role_description or "").strip()

        # 默认角色名称
        default_names = {
            "lawyer": "王律师",
            "stock_analyst": "张分析师",
            "teacher": "李老师",
            "psychological_counselor": "心理咨询师",
            "doctor": "陈医生",
            "scientist": "周科学家",
            "custom_persona": "智能助手",
        }
        # 默认角色描述
        fallback_descriptions = {
            "lawyer": "你当前的固定身份是王律师，应以法律顾问的口吻回答，不要否认自己的身份。",
            "stock_analyst": "你当前的固定身份是张分析师，应以股票分析师的口吻回答，不要否认自己的身份。",
            "teacher": "你当前的固定身份是李老师，应以老师的口吻回答，不要否认自己的身份。",
            "psychological_counselor": "你当前的固定身份是心理咨询师，应以支持性咨询师口吻回答，不要否认自己的身份。",
            "doctor": "你当前的固定身份是陈医生，应以医生口吻提供一般性健康建议，不要否认自己的身份。",
            "scientist": "你当前的固定身份是周科学家，应以科学工作者口吻回答，不要否认自己的身份。",
            "custom_persona": "你当前的固定身份是智能助手，不要否认自己的身份。",
        }

        if not resolved_name:
            resolved_name = default_names.get(role_type, "智能助手")
        if not resolved_description:
            resolved_description = fallback_descriptions.get(role_type, "你有明确的角色身份，请保持一致，不要否认自己的身份。")

        return (
            f"你当前扮演的明确身份是“{resolved_name}”。\n"
            f"{resolved_description}\n"
            "当用户直接用这个称呼叫你时，应自然承接，不要回答自己不是这个身份。"
        )

    def format_history(
        self,
        conversation_id: int,
        limit: int = 10,
        history_messages: Optional[List[Dict]] = None,
    ) -> str:
        """
        格式化对话历史为可读文本。
        
        用于构建 Prompt 中的历史上下文。
        
        Args:
            conversation_id: 会话 ID
            limit: 最大消息数，默认 10
            history_messages: 历史消息列表（可选）
            
        Returns:
            str: 格式化后的对话历史
        """
        messages = (
            history_messages[-limit:]
            if history_messages is not None
            else self.memory.get_recent_messages(conversation_id, limit)
        )
        if not messages:
            return "暂无历史对话。"

        # 格式化为"用户：xxx\n助手：xxx"的形式
        history_parts: List[str] = []
        for msg in messages:
            sender_type = msg.get("sender_type")
            prefix = "用户" if sender_type == "user" else "助手"
            history_parts.append(f"{prefix}：{(msg.get('content') or '').strip()}")
        return "\n".join(part for part in history_parts if part.strip())

    def _build_online_fallback_prompt(
        self,
        role_type: str,
        history: str,
        user_message: str,
        role_name: Optional[str] = None,
        role_description: Optional[str] = None,
    ) -> str:
        """
        构建在线模型降级 Prompt。
        
        当本地知识库未命中时，使用通用知识回答。
        添加安全提示，避免高风险领域的绝对化结论。
        
        Args:
            role_type: 角色类型
            history: 格式化后的对话历史
            user_message: 用户消息
            role_name: 角色名称（可选）
            role_description: 角色描述（可选）
            
        Returns:
            str: 降级 Prompt
        """
        # 各角色的在线模型标签
        role_names = {
            "lawyer": "法律咨询助手",
            "stock_analyst": "投资分析助手",
            "teacher": "学习辅导助手",
            "psychological_counselor": "心理支持助手",
            "doctor": "健康科普助手",
            "scientist": "科研方法助手",
            "custom_persona": "全能型在线问答助手",
        }
        role_label = role_names.get(role_type, "智能助手")
        persona_prefix = self._build_persona_prefix(
            role_type=role_type,
            role_name=role_name,
            role_description=role_description,
        )
        return (
            f"{persona_prefix}\n\n"
            f"你现在是一名{role_label}。\n\n"
            "本地知识库检索结果：未找到与用户问题直接相关的内容。\n"
            "因此请使用通用知识回答，但不要声称答案来自本地知识库。\n"
            "如果问题涉及法律、医疗、心理、投资等高风险领域，请保持谨慎，避免绝对化结论。\n"
            "输出不要使用 Markdown 符号。\n\n"
            f"对话历史：\n{history}\n\n"
            f"用户问题：\n{user_message}"
        )

    def _call_llm(
        self,
        prompt: str,
        role_type: str,
        user_message: str,
        context: str,
        knowledge_context_used: bool,
        role_name: Optional[str] = None,
        role_description: Optional[str] = None,
    ) -> str:
        """
        调用 LLM 生成回复。
        
        如果 LLM 调用失败或返回空内容，自动降级到 _fallback_response。
        
        Args:
            prompt: 完整的 Prompt
            role_type: 角色类型
            user_message: 用户消息
            context: 检索上下文
            knowledge_context_used: 是否使用了知识库上下文
            role_name: 角色名称（可选）
            role_description: 角色描述（可选）
            
        Returns:
            str: LLM 回复或降级回复
        """
        if not self.client:
            # LLM 客户端未初始化
            reason = "大模型客户端未配置或初始化失败"
            self.last_run_meta["llm_reason"] = reason
            return self._fallback_response(
                role_type,
                user_message,
                context,
                reason,
                role_name=role_name,
                role_description=role_description,
            )

        try:
            # 调用 OpenAI 兼容 API
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[{"role": "user", "content": prompt}],
                temperature=self.temperature,
                top_p=self.top_p,
                max_tokens=self.max_new_tokens,
                extra_body={
                    "repetition_penalty": self.repetition_penalty,
                },
            )
            content = ""
            if response.choices:
                content = response.choices[0].message.content or ""
            # 规范化输出格式
            content = self._normalize_output_format(content.strip())
            if content:
                self.last_run_meta["llm_reason"] = None
                return content
            reason = "大模型返回了空内容"
        except Exception as exc:
            reason = f"大模型调用失败: {exc}"

        # LLM 调用失败，降级
        self.last_run_meta["llm_reason"] = reason
        return self._fallback_response(
            role_type,
            user_message,
            context if knowledge_context_used else "",
            reason,
            role_name=role_name,
            role_description=role_description,
        )

    def _stream_llm(
        self,
        prompt: str,
        role_type: str,
        user_message: str,
        context: str,
        knowledge_context_used: bool,
        role_name: Optional[str] = None,
        role_description: Optional[str] = None,
    ) -> Iterator[str]:
        """
        流式调用 LLM，逐段产出文本。
        如果流式调用失败，则回退为一次性降级回复。
        """
        if not self.client:
            reason = "大模型客户端未配置或初始化失败"
            self.last_run_meta["llm_reason"] = reason
            yield self._fallback_response(
                role_type,
                user_message,
                context,
                reason,
                role_name=role_name,
                role_description=role_description,
            )
            return

        try:
            stream = self.client.chat.completions.create(
                model=self.model_name,
                messages=[{"role": "user", "content": prompt}],
                temperature=self.temperature,
                top_p=self.top_p,
                max_tokens=self.max_new_tokens,
                stream=True,
                extra_body={
                    "repetition_penalty": self.repetition_penalty,
                },
            )
            has_content = False
            for chunk in stream:
                choices = getattr(chunk, "choices", None) or []
                if not choices:
                    continue
                delta = getattr(choices[0], "delta", None)
                content = getattr(delta, "content", None) if delta is not None else None
                if not content:
                    continue
                has_content = True
                yield content

            if has_content:
                self.last_run_meta["llm_reason"] = None
                return
            reason = "大模型流式返回了空内容"
        except Exception as exc:
            reason = f"大模型流式调用失败: {exc}"

        self.last_run_meta["llm_reason"] = reason
        yield self._fallback_response(
            role_type,
            user_message,
            context if knowledge_context_used else "",
            reason,
            role_name=role_name,
            role_description=role_description,
        )

    def _fallback_response(
        self,
        role_type: str,
        user_message: str,
        context: str,
        reason: str,
        role_name: Optional[str] = None,
        role_description: Optional[str] = None,
    ) -> str:
        """
        构建降级回复（LLM 不可用时）。
        
        如果有检索到的知识上下文，基于知识回答。
        如果没有，提示用户补充信息。
        
        Args:
            role_type: 角色类型
            user_message: 用户消息
            context: 检索上下文
            reason: 降级原因
            role_name: 角色名称（可选）
            role_description: 角色描述（可选）
            
        Returns:
            str: 降级回复
        """
        # 各角色的降级显示名称
        role_names = {
            "lawyer": "法律助手",
            "stock_analyst": "财务分析助手",
            "teacher": "学习辅导助手",
            "psychological_counselor": "心理支持助手",
            "doctor": "健康科普助手",
            "scientist": "科研方法助手",
            "custom_persona": "智能助手",
        }
        display_name = (role_name or "").strip() or role_names.get(role_type, "智能助手")

        if context and context != NO_KNOWLEDGE_CONTEXT:
            # 有知识上下文：基于知识给出保守回答
            reply = (
                f"结论\n{display_name}当前无法连接到大模型服务，我先依据已检索到的内容给出保守回答。\n\n"
                f"知识依据\n{context}\n\n"
                "说明\n"
                f"本次为降级回答，原因：{reason}"
            )
            return self._normalize_output_format(reply)

        # 无知识上下文：提示用户补充信息
        reply = (
            f"结论\n{display_name}当前无法连接到大模型服务，而且知识库里没有检索到直接依据。\n\n"
            f"用户问题\n{user_message}\n\n"
            "建议\n请补充更具体的场景、目标、限制条件或背景后重试。"
            "如果问题涉及法律、医疗、心理或投资风险，请优先联系线下专业人士。\n\n"
            f"说明\n本次为降级回答，原因：{reason}"
        )
        return self._normalize_output_format(reply)

    def generate_response(
        self,
        conversation_id: int,
        user_message: str,
        role_type: str,
        role_name: Optional[str] = None,
        role_description: Optional[str] = None,
        user_id: Optional[int] = None,
        history_messages: Optional[List[Dict]] = None,
    ) -> str:
        """
        生成回复（核心入口方法）。
        
        按优先级依次尝试以下回答模式：
        1. 社交开场白（打招呼、咨询开场）
        2. 轻量聊天（谢谢、你是谁、在吗）
        3. 短期记忆（我叫什么、你还记得我吗）
        4. 知识库回答（RAG 检索 + LLM 生成）
        5. 在线模型降级（本地知识未命中时）
        
        Args:
            conversation_id: 会话 ID
            user_message: 用户消息
            role_type: 角色类型
            role_name: 角色名称（可选）
            role_description: 角色描述（可选）
            user_id: 用户 ID（可选）
            history_messages: 历史消息列表（可选）
            
        Returns:
            str: 生成的回复
        """
        # ============================================================
        # 第 1 步：尝试社交开场白
        # ============================================================
        social_reply = self._build_social_opening_reply(role_type, user_message)
        if social_reply is not None:
            # 如果用户提供了角色名称，在开场白中自我介绍
            resolved_role_name = (role_name or "").strip()
            if resolved_role_name and social_reply.startswith("你好。"):
                social_reply = social_reply.replace("你好。", f"你好，我是{resolved_role_name}。", 1)
            elif resolved_role_name and social_reply.startswith("你好，"):
                social_reply = social_reply.replace("。", f"。我是{resolved_role_name}。", 1)
            # 保存到短期记忆
            self.memory.add_message(conversation_id, "user", user_message)
            self.memory.add_message(conversation_id, "assistant", social_reply)
            # 记录元数据
            self.last_run_meta = {
                "pdf_context_used": False,
                "user_file_context_used": False,
                "public_context_used": False,
                "knowledge_context_used": False,
                "uploaded_file_mode": False,
                "answer_mode": "social_opening",
                "history_used": bool(history_messages),
                "history_message_count": len(history_messages or []),
                "llm_reason": None,
            }
            return social_reply

        # ============================================================
        # 第 2 步：尝试轻量聊天
        # ============================================================
        lightweight_reply = self._build_lightweight_chat_reply(
            role_type=role_type,
            user_message=user_message,
            role_name=role_name,
        )
        if lightweight_reply is not None:
            self.memory.add_message(conversation_id, "user", user_message)
            self.memory.add_message(conversation_id, "assistant", lightweight_reply)
            self.last_run_meta = {
                "pdf_context_used": False,
                "user_file_context_used": False,
                "public_context_used": False,
                "knowledge_context_used": False,
                "uploaded_file_mode": False,
                "answer_mode": "lightweight_chat",
                "history_used": bool(history_messages),
                "history_message_count": len(history_messages or []),
                "llm_reason": None,
            }
            return lightweight_reply

        # ============================================================
        # 第 3 步：尝试短期记忆
        # ============================================================
        memory_reply = self._build_memory_reply(
            conversation_id=conversation_id,
            user_message=user_message,
            history_messages=history_messages,
        )
        if memory_reply is not None:
            self.memory.add_message(conversation_id, "user", user_message)
            self.memory.add_message(conversation_id, "assistant", memory_reply)
            self.last_run_meta = {
                "pdf_context_used": False,
                "user_file_context_used": False,
                "public_context_used": False,
                "knowledge_context_used": False,
                "uploaded_file_mode": False,
                "answer_mode": "short_term_memory",
                "history_used": bool(history_messages),
                "history_message_count": len(history_messages or []),
                "llm_reason": None,
            }
            return memory_reply

        # ============================================================
        # 第 4 步：知识库回答（RAG 检索 + LLM 生成）
        # ============================================================
        runtime = self._collect_runtime_retrieval_state(
            user_message=user_message,
            history_messages=history_messages,
            user_id=user_id,
            conversation_id=conversation_id,
        )
        retrieval_query = str(runtime["retrieval_query"])
        history = str(runtime["history"])
        uploaded_file_mode = bool(runtime["uploaded_file_mode"])
        request_mode = str(runtime["request_mode"])
        history_priority_prefix = str(runtime["history_priority_prefix"])
        private_context = str(runtime["private_context"] or "")
        context = NO_KNOWLEDGE_CONTEXT  # 默认无知识上下文
        answer_mode = "online_model"  # 默认回答模式
        is_document_overview_request = request_mode == "overview"
        # 构建角色身份指令
        persona_prefix = self._build_persona_prefix(
            role_type=role_type,
            role_name=role_name,
            role_description=role_description,
        )

        if uploaded_file_mode and request_mode == "full_output":
            reply = self._build_uploaded_file_full_output_reply(
                user_id=user_id,
                conversation_id=conversation_id,
            )
            if reply:
                answer_mode = "uploaded_file_full_output"
                self.memory.add_message(conversation_id, "user", user_message)
                self.memory.add_message(conversation_id, "assistant", reply)
                self.last_run_meta = self._build_last_run_meta(
                    context=reply,
                    private_context=reply,
                    uploaded_file_mode=True,
                    answer_mode=answer_mode,
                    history_messages=history_messages,
                    knowledge_context_used=True,
                    direct_return_blocked=False,
                    llm_reason=None,
                )
                return reply

        if uploaded_file_mode and private_context:
            direct_return_blocked = self._requires_direct_return_block(user_message, private_context)
            if direct_return_blocked:
                reply = self._build_direct_return_block_reply()
                answer_mode = "user_file_direct_return_blocked"
                self.memory.add_message(conversation_id, "user", user_message)
                self.memory.add_message(conversation_id, "assistant", reply)
                self.last_run_meta = self._build_last_run_meta(
                    context=reply,
                    private_context=private_context,
                    uploaded_file_mode=True,
                    answer_mode=answer_mode,
                    history_messages=history_messages,
                    knowledge_context_used=True,
                    direct_return_blocked=True,
                    llm_reason=None,
                )
                return reply

        # 根据角色类型选择不同的 Prompt 构建策略
        if role_type == "custom_persona":
            # 自定义人格：不依赖角色知识库
            context = self._prepare_uploaded_file_context(user_message, private_context) if private_context else NO_KNOWLEDGE_CONTEXT
            knowledge_context_used = self._has_knowledge_context(context)
            prompt = (
                f"{persona_prefix}\n\n{history_priority_prefix}\n"
                + PROMPT_TEMPLATES["custom_persona"].format(
                    context=context,
                    history=history,
                    question=user_message,
                )
            )
            answer_mode = "custom_persona_uploaded_file" if private_context else "custom_persona"
        else:
            # 固定角色：构建完整上下文
            context = self.build_context(
                query=retrieval_query,
                role_type=role_type,
                user_id=user_id,
                conversation_id=conversation_id,
                user_message=user_message,
            )
            knowledge_context_used = self._has_knowledge_context(context)
            if knowledge_context_used:
                # 有知识上下文：使用角色 Prompt 模板
                template = PROMPT_TEMPLATES.get(role_type, PROMPT_TEMPLATES["teacher"])
                prompt = (
                    f"{persona_prefix}\n\n{history_priority_prefix}\n"
                    + template.format(context=context, history=history, question=user_message)
                )
                if private_context and is_document_overview_request:
                    answer_mode = "uploaded_file_overview"
                else:
                    answer_mode = "uploaded_file_analysis" if private_context else "local_knowledge"
            else:
                # 无知识上下文：使用在线模型降级
                prompt = (
                    f"{history_priority_prefix}\n"
                    + self._build_online_fallback_prompt(
                        role_type=role_type,
                        history=history,
                        user_message=user_message,
                        role_name=role_name,
                        role_description=role_description,
                    )
                )
                answer_mode = "online_model"

        # 调用 LLM 生成回复
        reply = self._call_llm(
            prompt=prompt,
            role_type=role_type,
            user_message=user_message,
            context=context,
            knowledge_context_used=knowledge_context_used,
            role_name=role_name,
            role_description=role_description,
        )
        # 保存到短期记忆
        self.memory.add_message(conversation_id, "user", user_message)
        self.memory.add_message(conversation_id, "assistant", reply)
        # 记录元数据
        self.last_run_meta = self._build_last_run_meta(
            context=context,
            private_context=private_context,
            uploaded_file_mode=uploaded_file_mode,
            answer_mode=answer_mode,
            history_messages=history_messages,
            knowledge_context_used=knowledge_context_used,
            direct_return_blocked=False,
            llm_reason=self.last_run_meta.get("llm_reason"),
        )
        return reply

    def stream_response(
        self,
        conversation_id: int,
        user_message: str,
        role_type: str,
        role_name: Optional[str] = None,
        role_description: Optional[str] = None,
        user_id: Optional[int] = None,
        history_messages: Optional[List[Dict]] = None,
    ) -> Iterator[str]:
        """
        流式生成回复。
        非 LLM 分支一次性产出完整文本；LLM 分支逐段产出。
        """
        social_reply = self._build_social_opening_reply(role_type, user_message)
        if social_reply is not None:
            resolved_role_name = (role_name or "").strip()
            if resolved_role_name and social_reply.startswith("你好。"):
                social_reply = social_reply.replace("你好。", f"你好，我是{resolved_role_name}。", 1)
            elif resolved_role_name and social_reply.startswith("你好，"):
                social_reply = social_reply.replace("。", f"。我是{resolved_role_name}。", 1)
            self.last_run_meta = {
                "pdf_context_used": False,
                "user_file_context_used": False,
                "public_context_used": False,
                "knowledge_context_used": False,
                "uploaded_file_mode": False,
                "answer_mode": "social_opening",
                "history_used": bool(history_messages),
                "history_message_count": len(history_messages or []),
                "llm_reason": None,
            }
            yield social_reply
            return

        lightweight_reply = self._build_lightweight_chat_reply(
            role_type=role_type,
            user_message=user_message,
            role_name=role_name,
        )
        if lightweight_reply is not None:
            self.last_run_meta = {
                "pdf_context_used": False,
                "user_file_context_used": False,
                "public_context_used": False,
                "knowledge_context_used": False,
                "uploaded_file_mode": False,
                "answer_mode": "lightweight_chat",
                "history_used": bool(history_messages),
                "history_message_count": len(history_messages or []),
                "llm_reason": None,
            }
            yield lightweight_reply
            return

        memory_reply = self._build_memory_reply(
            conversation_id=conversation_id,
            user_message=user_message,
            history_messages=history_messages,
        )
        if memory_reply is not None:
            self.last_run_meta = {
                "pdf_context_used": False,
                "user_file_context_used": False,
                "public_context_used": False,
                "knowledge_context_used": False,
                "uploaded_file_mode": False,
                "answer_mode": "short_term_memory",
                "history_used": bool(history_messages),
                "history_message_count": len(history_messages or []),
                "llm_reason": None,
            }
            yield memory_reply
            return

        runtime = self._collect_runtime_retrieval_state(
            user_message=user_message,
            history_messages=history_messages,
            user_id=user_id,
            conversation_id=conversation_id,
        )
        retrieval_query = str(runtime["retrieval_query"])
        history = str(runtime["history"])
        uploaded_file_mode = bool(runtime["uploaded_file_mode"])
        request_mode = str(runtime["request_mode"])
        history_priority_prefix = str(runtime["history_priority_prefix"])
        private_context = str(runtime["private_context"] or "")
        context = NO_KNOWLEDGE_CONTEXT
        answer_mode = "online_model"
        is_document_overview_request = request_mode == "overview"
        persona_prefix = self._build_persona_prefix(
            role_type=role_type,
            role_name=role_name,
            role_description=role_description,
        )

        if uploaded_file_mode and request_mode == "full_output":
            reply = self._build_uploaded_file_full_output_reply(
                user_id=user_id,
                conversation_id=conversation_id,
            )
            if reply:
                self.last_run_meta = self._build_last_run_meta(
                    context=reply,
                    private_context=reply,
                    uploaded_file_mode=True,
                    answer_mode="uploaded_file_full_output",
                    history_messages=history_messages,
                    knowledge_context_used=True,
                    direct_return_blocked=False,
                    llm_reason=None,
                )
                yield reply
                return

        if uploaded_file_mode and private_context:
            direct_return_blocked = self._requires_direct_return_block(user_message, private_context)
            if direct_return_blocked:
                reply = self._build_direct_return_block_reply()
                self.last_run_meta = self._build_last_run_meta(
                    context=reply,
                    private_context=private_context,
                    uploaded_file_mode=True,
                    answer_mode="user_file_direct_return_blocked",
                    history_messages=history_messages,
                    knowledge_context_used=True,
                    direct_return_blocked=True,
                    llm_reason=None,
                )
                yield reply
                return

        if role_type == "custom_persona":
            context = self._prepare_uploaded_file_context(user_message, private_context) if private_context else NO_KNOWLEDGE_CONTEXT
            knowledge_context_used = self._has_knowledge_context(context)
            prompt = (
                f"{persona_prefix}\n\n{history_priority_prefix}\n"
                + PROMPT_TEMPLATES["custom_persona"].format(
                    context=context,
                    history=history,
                    question=user_message,
                )
            )
            answer_mode = "custom_persona_uploaded_file" if private_context else "custom_persona"
        else:
            yield {
                "type": "status",
                "stage": "retrieving",
                "message": "正在检索知识库...",
            }
            context = self.build_context(
                query=retrieval_query,
                role_type=role_type,
                user_id=user_id,
                conversation_id=conversation_id,
                user_message=user_message,
            )
            knowledge_context_used = self._has_knowledge_context(context)
            if knowledge_context_used:
                template = PROMPT_TEMPLATES.get(role_type, PROMPT_TEMPLATES["teacher"])
                prompt = (
                    f"{persona_prefix}\n\n{history_priority_prefix}\n"
                    + template.format(context=context, history=history, question=user_message)
                )
                if private_context and is_document_overview_request:
                    answer_mode = "uploaded_file_overview"
                else:
                    answer_mode = "uploaded_file_analysis" if private_context else "local_knowledge"
            else:
                prompt = (
                    f"{history_priority_prefix}\n"
                    + self._build_online_fallback_prompt(
                        role_type=role_type,
                        history=history,
                        user_message=user_message,
                        role_name=role_name,
                        role_description=role_description,
                    )
                )
                answer_mode = "online_model"

        yield {
            "type": "status",
            "stage": "generating",
            "message": "正在生成回答...",
        }
        self.last_run_meta = self._build_last_run_meta(
            context=context,
            private_context=private_context,
            uploaded_file_mode=uploaded_file_mode,
            answer_mode=answer_mode,
            history_messages=history_messages,
            knowledge_context_used=knowledge_context_used,
            direct_return_blocked=False,
            llm_reason=None,
        )

        for chunk in self._stream_llm(
            prompt=prompt,
            role_type=role_type,
            user_message=user_message,
            context=context,
            knowledge_context_used=knowledge_context_used,
            role_name=role_name,
            role_description=role_description,
        ):
            yield chunk

    def update_knowledge_base(self, documents: List[Dict]) -> None:
        """
        更新知识库（向量化并插入文档）。
        
        Args:
            documents: 文档列表 [{title, content, source, role_type}]
        """
        self.vector_store.insert_documents(documents)
