# -*- coding: utf-8 -*-
"""
数据处理模块
功能：提供文本清洗、中文分词、关键词提取、文档分块等数据预处理工具。
用于知识库文档和用户上传文件的标准化处理。

主要类：DataProcessor
  - clean_text(): 文本清洗（去空白、去特殊字符）
  - segment_chinese(): 中文分词（基于 jieba）
  - extract_keywords(): 关键词提取（基于词频）
  - process_document(): 文档标准化（清洗 + 关键词 + doc_id）
  - process_batch(): 批量文档处理
  - chunk_text(): 文本分块（按句子/换行边界）
  - build_chunked_documents(): 构建向量库分块文档
"""

import hashlib  # 哈希库，用于生成文档唯一 ID
import re  # 正则表达式库，用于文本清洗和分割
from typing import Dict, List  # 类型注解

import jieba  # 中文分词库


class DataProcessor:
    """
    数据处理器类。
    
    提供文本清洗、中文分词、关键词提取、文档分块等数据预处理功能。
    用于知识库文档和用户上传文件的标准化处理，确保数据一致性。
    """

    # 停用词集合，过滤无意义的常见词
    STOPWORDS = {
        "的",
        "了",
        "和",
        "是",
        "在",
        "就",
        "也",
        "都",
        "而",
        "并且",
        "等",
        "一个",
        "一些",
        "这种",
        "这个",
        "那个",
        "需要",
        "可以",
        "应该",
        "如何",
        "什么",
        "哪些",
        "是否",
        "怎么",
        "怎样",
        "请问",
        "时候",
        "进行",
        "根据",
        "对于",
        "通过",
        "如果",
        "以及",
        "问题",
        "情况",
    }

    def clean_text(self, text: str) -> str:
        """
        清洗文本：规范化空白字符，保留中英文常用字符。
        
        Args:
            text: 原始文本
            
        Returns:
            str: 清洗后的文本
        """
        if not text:  # 空文本直接返回
            return ""

        cleaned = str(text).replace("\r", "\n")  # 统一换行符
        cleaned = re.sub(r"[ \t\f\v]+", " ", cleaned)  # 合并多个空白字符为单个空格
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)  # 合并多个换行为两个换行
        # 保留 Markdown/表格常用符号，避免 PDF/多模态结构化结果被清洗坏
        cleaned = re.sub(
            r"[^\u4e00-\u9fa5a-zA-Z0-9，。；：！？、（）《》“”‘’【】\[\]\-—/#\\\n\.%,:;!?+|*_`~=:<>()]",
            "",
            cleaned,
        )
        return cleaned.strip()  # 去除首尾空白

    def segment_chinese(self, text: str) -> List[str]:
        """
        中文分词：基于 jieba 分词，带轻量停用词过滤。
        
        Args:
            text: 待分词的文本
            
        Returns:
            List[str]: 分词后的词列表
        """
        cleaned = self.clean_text(text)  # 先清洗文本
        if not cleaned:  # 清洗后为空则返回空列表
            return []

        words = jieba.lcut(cleaned)  # 使用 jieba 精确模式分词
        tokens: List[str] = []
        for word in words:
            token = word.strip().lower()  # 去除空白并转小写
            if not token or token in self.STOPWORDS:  # 过滤空词和停用词
                continue
            if len(token) == 1 and not re.fullmatch(r"[a-z0-9]", token):  # 过滤单字符非字母数字
                continue
            tokens.append(token)
        return tokens

    def extract_keywords(self, text: str, top_k: int = 10) -> List[str]:
        """
        基于词频提取关键词。
        
        Args:
            text: 待提取文本
            top_k: 返回前 k 个关键词，默认 10
            
        Returns:
            List[str]: 关键词列表
        """
        words = self.segment_chinese(text)  # 先分词
        frequency: Dict[str, int] = {}
        for word in words:
            frequency[word] = frequency.get(word, 0) + 1  # 统计词频
        sorted_words = sorted(frequency.items(), key=lambda item: (-item[1], item[0]))  # 按词频降序排列
        return [word for word, _ in sorted_words[:top_k]]  # 返回前 top_k 个词

    def process_document(self, doc: Dict) -> Dict:
        """
        标准化一个知识文档，附加稳定的元数据。
        
        Args:
            doc: 原始文档字典，包含 title、content、source、role_type 等字段
            
        Returns:
            Dict: 标准化后的文档字典，附加 keywords 和 doc_id
        """
        processed = doc.copy()  # 复制原始文档
        processed["title"] = self.clean_text(doc.get("title", ""))  # 清洗标题
        processed["content"] = self.clean_text(doc.get("content", ""))  # 清洗内容
        processed["source"] = self.clean_text(doc.get("source", ""))  # 清洗来源
        # 提取关键词
        processed["keywords"] = self.extract_keywords(
            f"{processed['title']} {processed['content']}"
        )
        # 基于角色类型、标题、内容、来源生成稳定的文档 ID
        stable_key = (
            f"{doc.get('role_type', '')}::{processed['title']}::"
            f"{processed['content']}::{processed['source']}"
        )
        processed["doc_id"] = hashlib.sha1(stable_key.encode("utf-8")).hexdigest()
        return processed

    def process_batch(self, documents: List[Dict]) -> List[Dict]:
        """
        批量标准化文档。
        
        Args:
            documents: 原始文档列表
            
        Returns:
            List[Dict]: 标准化后的文档列表
        """
        return [self.process_document(doc) for doc in documents]

    def chunk_text(self, text: str, chunk_size: int = 900, chunk_overlap: int = 120) -> List[str]:
        """
        按句末标点和换行优先切分文本，再按长度生成重叠分块。
        对没有空格分隔的中文长句，超过阈值时也会强制切块。
        """
        cleaned = self.clean_text(text)
        if not cleaned:
            return []

        units = [
            segment.strip()
            for segment in re.split(r"(?<=[。！？；.!?])|[\r\n]+", cleaned)
            if segment.strip()
        ]
        if not units:
            units = [cleaned]

        chunks: List[str] = []
        current = ""
        step = max(1, chunk_size - max(0, chunk_overlap))

        for unit in units:
            if len(unit) > chunk_size:
                if current:
                    chunks.append(current)
                    current = ""
                for start in range(0, len(unit), step):
                    piece = unit[start : start + chunk_size].strip()
                    if piece:
                        chunks.append(piece)
                continue

            candidate = unit if not current else f"{current}\n{unit}"
            if current and len(candidate) > chunk_size:
                chunks.append(current)
                overlap_text = current[-chunk_overlap:] if chunk_overlap else ""
                current = f"{overlap_text}\n{unit}".strip()
            else:
                current = candidate

        if current:
            chunks.append(current)

        result: List[str] = []
        for chunk in chunks:
            normalized = self.clean_text(chunk)
            if normalized:
                result.append(normalized)
        return result

    def build_chunked_documents(
        self,
        document: Dict,
        chunk_size: int = 900,
        chunk_overlap: int = 120,
    ) -> List[Dict]:
        """
        将一个逻辑文档展开为向量库分块文档列表。
        
        Args:
            document: 原始文档字典
            chunk_size: 每块最大字符数，默认 900
            chunk_overlap: 块间重叠字符数，默认 120
            
        Returns:
            List[Dict]: 分块文档列表，每块包含 title、content、source、role_type、doc_id 等字段
        """
        processed = self.process_document(document)  # 先标准化文档
        chunks = self.chunk_text(
            processed.get("content", ""),
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
        if not chunks:  # 没有分块则返回空列表
            return []

        base_title = processed.get("title", "")  # 基础标题
        base_source = processed.get("source", "")  # 基础来源
        base_doc_id = processed.get("doc_id", "")  # 基础文档 ID
        base_role_type = processed.get("role_type", document.get("role_type", ""))  # 角色类型
        total_chunks = len(chunks)  # 总块数

        results: List[Dict] = []
        for index, chunk in enumerate(chunks):
            # 如果只有一块，标题不变；否则添加分块序号
            title = base_title if total_chunks == 1 else f"{base_title} [part {index + 1}/{total_chunks}]"
            # 来源添加分块序号
            source = base_source if not base_source else f"{base_source}#chunk={index + 1}"
            # 基于基础文档 ID 和分块序号生成唯一的分块文档 ID
            chunk_doc_id = hashlib.sha1(f"{base_doc_id}:{index}:{chunk}".encode("utf-8")).hexdigest()
            results.append(
                {
                    "title": title,
                    "content": chunk,
                    "source": source,
                    "role_type": base_role_type,
                    "doc_id": chunk_doc_id,
                    "keywords": self.extract_keywords(f"{title} {chunk}"),
                    "chunk_index": index,
                    "chunk_total": total_chunks,
                    "is_chunk": total_chunks > 1,
                }
            )
        return results
