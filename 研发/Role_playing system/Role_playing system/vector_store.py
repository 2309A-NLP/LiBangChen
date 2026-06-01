# -*- coding: utf-8 -*-
"""
向量检索与混合检索模块
====================
功能：提供稠密向量检索、基于词项重合的词法检索、BM25 检索和混合检索（RRF 融合 + 重排序）。
支持系统知识库（公共）和用户上传文件（私有）两种检索范围。
当 Milvus 不可用时，自动降级到本地 SQLite + 内存向量检索。

主要类：MilvusStore
  - 公共知识检索：search(), search_pdf_documents(), search_non_pdf_documents()
  - 用户文件检索：search_user_document_chunks()
  - 知识库管理：insert_documents(), replace_documents()
  - 用户文件管理：insert_user_document_chunks(), delete_user_file_chunks()
  - 状态查询：get_status()
"""

import json  # JSON 序列化/反序列化
import hashlib  # 哈希计算，用于生成唯一 ID
import math  # 数学函数，用于 BM25 评分
import os  # 操作系统接口
import subprocess  # 子进程管理，用于运行 rerank worker
import time  # 时间相关，用于重连间隔控制
from collections import Counter  # 计数器，用于词频统计
from threading import Lock  # 线程锁，用于模型共享
from typing import Dict, Iterable, List, Optional, Sequence  # 类型注解

from config import HYBRID_RETRIEVAL_CONFIG, LOW_MEMORY_MODE_CONFIG, MILVUS_CONFIG, RERANK_CONFIG  # 配置
from data_processor import DataProcessor  # 数据处理器
from models import KnowledgeDocument, SessionLocal, UserDocumentChunk  # 数据库模型

try:
    from sentence_transformers import CrossEncoder, SentenceTransformer
except ImportError:  # pragma: no cover - 可选依赖
    CrossEncoder = SentenceTransformer = None

try:
    from pymilvus import Collection, CollectionSchema, DataType, FieldSchema, connections, utility
except ImportError:  # pragma: no cover - 可选依赖
    Collection = CollectionSchema = DataType = FieldSchema = connections = utility = None


DEFAULT_EMBEDDING_DIM = 1024  # 默认向量维度
SUPPORTED_RETRIEVAL_MODES = {"dense", "bm25", "hybrid", "hybrid_rerank"}



class MilvusStore:
    # 统一封装公共知识库和用户文件分块的检索、写入、降级逻辑。
    # dense 优先走 Milvus；sparse/bm25 目前仍在本地数据库文档上计算词法分数；
    # hybrid / hybrid_rerank 会组合多路召回结果。
    """
    混合检索存储类。
    
    提供稠密向量检索、基于词项重合的词法检索、BM25 检索和混合检索（RRF 融合 + 重排序）。
    支持系统知识库（公共）和用户上传文件（私有）两种检索范围。
    当 Milvus 不可用时，自动降级到本地 SQLite + 内存向量检索。
    """

    # 共享模型锁和缓存，避免重复加载模型
    _shared_model_lock = Lock()  # 模型加载线程锁
    _shared_embedding_model = None  # 共享的 embedding 模型实例
    _shared_embedding_path = ""  # 共享的 embedding 模型路径
    _shared_embedding_error = ""  # 共享的 embedding 加载错误信息
    _shared_reranker = None  # 共享的 reranker 模型实例
    _shared_reranker_path = ""  # 共享的 reranker 模型路径
    _shared_rerank_error = ""  # 共享的 reranker 加载错误信息
    _shared_public_documents_cache: Dict[tuple, List[Dict]] = {}
    _shared_user_chunks_cache: Dict[tuple, List[Dict]] = {}
    _shared_token_cache: Dict[str, List[str]] = {}
    _shared_instance = None

    def __new__(cls, *args, **kwargs):
        if cls._shared_instance is None:
            with cls._shared_model_lock:
                if cls._shared_instance is None:
                    cls._shared_instance = super().__new__(cls)
        return cls._shared_instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return
        self._initialized = True
        """初始化 MilvusStore 实例。"""
        self.collection_name = MILVUS_CONFIG["collection_name"]  # 公共知识库集合名
        self.user_collection_name = MILVUS_CONFIG["user_collection_name"]  # 用户文件集合名
        self.processor = DataProcessor()  # 数据处理器实例
        self._local_embedding_cache: Dict[str, List[float]] = {}  # 本地 embedding 缓存
        self._public_documents_cache = type(self)._shared_public_documents_cache
        self._user_chunks_cache = type(self)._shared_user_chunks_cache
        self._token_cache = type(self)._shared_token_cache

        self.collection = None  # 公共知识库 Milvus 集合
        self.user_collection = None  # 用户文件 Milvus 集合
        self.available = False  # Milvus 是否可用
        self.degraded_reason = ""  # 降级原因
        self.last_connect_attempt = 0.0  # 上次连接尝试时间

        self.embedding_model = None  # embedding 模型
        self.embedding_available = False  # embedding 是否可用
        self.embedding_error = ""  # embedding 加载错误
        self.embedding_model_path = os.getenv(  # embedding 模型路径
            "EMBEDDING_MODEL_PATH",
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "models", "bge-m3"),
        )
        self.embedding_dim = DEFAULT_EMBEDDING_DIM  # 向量维度

        self.reranker = None  # reranker 模型
        self.rerank_available = False  # reranker 是否可用
        self.rerank_error = ""  # reranker 加载错误
        self.rerank_model_path = RERANK_CONFIG["model_path"]  # reranker 模型路径，当前默认由 config/.env 指向 bge-reranker-base
        self.rerank_worker_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rerank_worker.py")  # rerank worker 脚本路径
        self.rerank_candidate_limit = max(int(RERANK_CONFIG["candidate_limit"]), 1)

        self.hybrid_enabled = HYBRID_RETRIEVAL_CONFIG["enabled"]  # 是否启用混合检索
        self.hybrid_rrf_k = HYBRID_RETRIEVAL_CONFIG["rrf_k"]  # RRF 融合参数 k
        self.candidate_multiplier = HYBRID_RETRIEVAL_CONFIG["candidate_multiplier"]  # 候选集倍数
        self.reconnect_interval = HYBRID_RETRIEVAL_CONFIG["milvus_reconnect_interval_seconds"]  # 重连间隔（秒）
        self.bm25_k1 = HYBRID_RETRIEVAL_CONFIG["bm25_k1"]  # BM25 参数 k1
        self.bm25_b = HYBRID_RETRIEVAL_CONFIG["bm25_b"]  # BM25 参数 b
        self.retrieval_mode = self._normalize_retrieval_mode(HYBRID_RETRIEVAL_CONFIG["mode"])  # 检索模式
        self.compare_mode_enabled = False
        self.compare_modes = []
        self.auto_mode_enabled = False
        self.milvus_first_enabled = False
        self.milvus_first_min_score = 0.0
        self.milvus_first_min_hits = 0
        self.last_search_meta: Dict[str, object] = {}  # 上次搜索元数据
        self._load_local_models()  # 加载本地模型
        self._setup_backend()  # 初始化后端

    def _load_local_models(self) -> None:
        """加载本地模型（embedding + reranker）。"""
        self._load_embedding_model()
        self._load_reranker()

    def _load_embedding_model(self) -> None:
        """加载 embedding 模型（BGE-M3）。"""
        if SentenceTransformer is None:
            self.embedding_error = "sentence-transformers is not installed"
            return
        if not os.path.exists(self.embedding_model_path):
            self.embedding_error = f"embedding model missing: {self.embedding_model_path}"
            return

        cls = type(self)
        # 如果共享缓存中有相同路径的模型，直接复用
        if cls._shared_embedding_model is not None and cls._shared_embedding_path == self.embedding_model_path:
            self.embedding_model = cls._shared_embedding_model
            self.embedding_available = True
            self.embedding_error = ""
            return
        if cls._shared_embedding_error and cls._shared_embedding_path == self.embedding_model_path:
            self.embedding_error = cls._shared_embedding_error
            return

        with cls._shared_model_lock:
            # 双重检查锁定
            if cls._shared_embedding_model is not None and cls._shared_embedding_path == self.embedding_model_path:
                self.embedding_model = cls._shared_embedding_model
                self.embedding_available = True
                self.embedding_error = ""
                return
            try:
                model = SentenceTransformer(self.embedding_model_path, trust_remote_code=True)
                model.max_seq_length = 8192  # 设置最大序列长度
                inferred_dim = getattr(model, "get_sentence_embedding_dimension", lambda: None)()
                cls._shared_embedding_model = model
                cls._shared_embedding_path = self.embedding_model_path
                cls._shared_embedding_error = ""
                self.embedding_model = model
                self.embedding_dim = int(inferred_dim or DEFAULT_EMBEDDING_DIM)
                self.embedding_available = True
                self.embedding_error = ""
            except Exception as exc:  # pragma: no cover - 依赖本地模型文件
                cls._shared_embedding_model = None
                cls._shared_embedding_path = self.embedding_model_path
                cls._shared_embedding_error = f"embedding load failed: {exc}"
                self.embedding_model = None
                self.embedding_dim = DEFAULT_EMBEDDING_DIM
                self.embedding_available = False
                self.embedding_error = cls._shared_embedding_error

    def _load_reranker(self) -> None:
        """加载 reranker 模型（BGE-Reranker）。"""
        if not RERANK_CONFIG["enabled"]:
            self.rerank_error = "rerank disabled by config"
            return
        if not self.rerank_model_path or not os.path.exists(self.rerank_model_path):
            self.rerank_error = f"rerank model missing: {self.rerank_model_path}"
            return
        if not os.path.exists(self.rerank_worker_path):
            self.rerank_error = f"rerank worker missing: {self.rerank_worker_path}"
            return

        self.reranker = None  # 使用子进程方式，不直接加载模型
        self.rerank_available = True
        self.rerank_error = ""

    def _setup_backend(self) -> None:
        """初始化后端（连接 Milvus 或降级到本地检索）。"""
        if not MILVUS_CONFIG["enabled"]:
            self.available = False
            self.degraded_reason = "Milvus disabled; using local hybrid retrieval"
            return

        if not all([connections, Collection, CollectionSchema, FieldSchema, DataType, utility]):
            self.available = False
            self.degraded_reason = "pymilvus is unavailable; using local hybrid retrieval"
            return

        if not self.embedding_available:
            self.available = False
            self.degraded_reason = f"embedding unavailable; using local hybrid retrieval: {self.embedding_error}"
            return

        self._connect_backend(force=True)

    def _connect_backend(self, force: bool = False) -> bool:
        """
        连接 Milvus 后端。
        
        Args:
            force: 是否强制连接（忽略重连间隔）
            
        Returns:
            bool: 连接是否成功
        """
        if not MILVUS_CONFIG["enabled"]:
            return False

        now = time.monotonic()
        if not force and (now - self.last_connect_attempt) < self.reconnect_interval:
            return self.available
        self.last_connect_attempt = now

        try:
            connections.connect(alias="default", **self._build_connection_args())
            self._create_collection()  # 创建公共知识库集合
            self._create_user_collection()  # 创建用户文件集合
            self.available = True
            self.degraded_reason = ""
            return True
        except Exception as exc:  # pragma: no cover - 依赖外部服务
            self.available = False
            self.collection = None
            self.user_collection = None
            self.degraded_reason = f"Milvus init failed: {exc}"
            return False

    def _maybe_reconnect(self) -> None:
        """如果 Milvus 不可用，尝试重新连接。"""
        if MILVUS_CONFIG["enabled"] and not self.available:
            self._connect_backend(force=False)

    def _build_connection_args(self) -> Dict:
        """
        构建 Milvus 连接参数。
        
        Returns:
            Dict: 连接参数字典
        """
        args: Dict[str, object] = {
            "timeout": MILVUS_CONFIG["timeout"],
        }
        if MILVUS_CONFIG["uri"]:
            args["uri"] = MILVUS_CONFIG["uri"]
        else:
            args["host"] = MILVUS_CONFIG["host"]
            args["port"] = MILVUS_CONFIG["port"]

        if MILVUS_CONFIG["token"]:
            args["token"] = MILVUS_CONFIG["token"]
        else:
            if MILVUS_CONFIG["user"]:
                args["user"] = MILVUS_CONFIG["user"]
            if MILVUS_CONFIG["password"]:
                args["password"] = MILVUS_CONFIG["password"]

        if MILVUS_CONFIG["db_name"]:
            args["db_name"] = MILVUS_CONFIG["db_name"]
        if MILVUS_CONFIG["secure"]:
            args["secure"] = True
        return args

    def _create_collection(self) -> None:
        """创建公共知识库 Milvus 集合。"""
        if utility.has_collection(self.collection_name):
            collection = Collection(self.collection_name)
            vector_field = next((field for field in collection.schema.fields if field.name == "embedding"), None)
            current_dim = vector_field.params.get("dim", 0) if vector_field else 0
            if current_dim != self.embedding_dim:
                utility.drop_collection(self.collection_name)

        if not utility.has_collection(self.collection_name):
            fields = [
                FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
                FieldSchema(name="doc_id", dtype=DataType.VARCHAR, max_length=255),
                FieldSchema(name="title", dtype=DataType.VARCHAR, max_length=500),
                FieldSchema(name="content", dtype=DataType.VARCHAR, max_length=5000),
                FieldSchema(name="role_type", dtype=DataType.VARCHAR, max_length=50),
                FieldSchema(name="source", dtype=DataType.VARCHAR, max_length=500),
                FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=self.embedding_dim),
            ]
            schema = CollectionSchema(fields, description="Knowledge base collection")
            self.collection = Collection(self.collection_name, schema)
            index_params = {
                "metric_type": "IP",
                "index_type": "IVF_FLAT",
                "params": {"nlist": 1024},
            }
            self.collection.create_index("embedding", index_params)
        else:
            self.collection = Collection(self.collection_name)

        self.collection.load()

    def _create_user_collection(self) -> None:
        """创建用户文件 Milvus 集合。"""
        required_fields = {
            "chunk_id",
            "file_id",
            "user_id",
            "conversation_id",
            "title",
            "content",
            "source",
            "embedding",
        }
        if utility.has_collection(self.user_collection_name):
            collection = Collection(self.user_collection_name)
            field_names = {field.name for field in collection.schema.fields}
            vector_field = next((field for field in collection.schema.fields if field.name == "embedding"), None)
            current_dim = vector_field.params.get("dim", 0) if vector_field else 0
            if current_dim != self.embedding_dim or not required_fields.issubset(field_names):
                utility.drop_collection(self.user_collection_name)

        if not utility.has_collection(self.user_collection_name):
            fields = [
                FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
                FieldSchema(name="chunk_id", dtype=DataType.VARCHAR, max_length=255),
                FieldSchema(name="file_id", dtype=DataType.INT64),
                FieldSchema(name="user_id", dtype=DataType.INT64),
                FieldSchema(name="conversation_id", dtype=DataType.INT64),
                FieldSchema(name="title", dtype=DataType.VARCHAR, max_length=500),
                FieldSchema(name="content", dtype=DataType.VARCHAR, max_length=5000),
                FieldSchema(name="source", dtype=DataType.VARCHAR, max_length=500),
                FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=self.embedding_dim),
            ]
            schema = CollectionSchema(fields, description="User uploaded document chunks")
            self.user_collection = Collection(self.user_collection_name, schema)
            index_params = {
                "metric_type": "IP",
                "index_type": "IVF_FLAT",
                "params": {"nlist": 1024},
            }
            self.user_collection.create_index("embedding", index_params)
        else:
            self.user_collection = Collection(self.user_collection_name)

        self.user_collection.load()

    def _generate_embedding(self, text: str) -> List[float]:
        """
        生成单个文本的向量。
        
        Args:
            text: 输入文本
            
        Returns:
            List[float]: 向量
        """
        if not self.embedding_model:
            raise RuntimeError("Embedding model is unavailable")
        embedding = self.embedding_model.encode(
            text,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return embedding.tolist()

    def _generate_embeddings_batch(self, texts: Sequence[str]) -> List[List[float]]:
        """
        批量生成文本向量。
        
        Args:
            texts: 文本列表
            
        Returns:
            List[List[float]]: 向量列表
        """
        if not self.embedding_model:
            raise RuntimeError("Embedding model is unavailable")
        if not texts:
            return []
        embeddings = self.embedding_model.encode(
            list(texts),
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return embeddings.tolist()

    def insert_documents(self, documents: List[Dict]) -> None:
        """
        向公共知识库插入文档。
        
        Args:
            documents: 文档列表，每项包含 doc_id、title、content、role_type、source
        """
        if not documents:
            return

        self._maybe_reconnect()
        if not self.available or self.collection is None:
            return

        try:
            contents = [doc["content"] for doc in documents]
            embeddings = self._generate_embeddings_batch(contents)
            payload = [
                [doc["doc_id"] for doc in documents],
                [doc["title"][:500] for doc in documents],
                [doc["content"][:5000] for doc in documents],
                [doc["role_type"][:50] for doc in documents],
                [doc["source"][:500] for doc in documents],
                embeddings,
            ]
            self.collection.insert(payload)
            self.collection.flush()
            self._invalidate_public_caches()
        except Exception as exc:  # pragma: no cover - 依赖外部服务
            self.available = False
            self.degraded_reason = f"Milvus insert failed: {exc}"

    def replace_documents(self, documents: List[Dict]) -> None:
        """
        替换公共知识库的所有文档（重建集合）。
        
        Args:
            documents: 新文档列表
        """
        if not documents:
            return

        self._maybe_reconnect()
        if not self.available:
            return

        try:
            if utility.has_collection(self.collection_name):
                utility.drop_collection(self.collection_name)
            self.collection = None
            self._invalidate_public_caches()
            self._create_collection()
            self.insert_documents(documents)
        except Exception as exc:  # pragma: no cover - 依赖外部服务
            self.available = False
            self.collection = None
            self.degraded_reason = f"Milvus rebuild failed: {exc}"

    def insert_user_document_chunks(
        self,
        file_id: int,
        user_id: int,
        conversation_id: int,
        chunks: List[Dict],
    ) -> None:
        """
        向用户文件集合插入文档分块。
        
        Args:
            file_id: 文件 ID
            user_id: 用户 ID
            conversation_id: 会话 ID
            chunks: 分块列表，每项包含 title、content、source、chunk_index
        """
        if not chunks:
            return

        self._maybe_reconnect()
        if not self.available or self.user_collection is None:
            return

        try:
            prepared = []
            for chunk in chunks:
                content = self.processor.clean_text(chunk.get("content", ""))
                if not content:
                    continue
                title = self.processor.clean_text(chunk.get("title", ""))[:500]
                source = self.processor.clean_text(chunk.get("source", ""))[:500]
                chunk_index = int(chunk.get("chunk_index", 0))
                stable_key = f"{user_id}:{conversation_id}:{file_id}:{chunk_index}:{content}"
                prepared.append(
                    {
                        "chunk_id": hashlib.sha1(stable_key.encode("utf-8")).hexdigest(),
                        "file_id": int(file_id),
                        "user_id": int(user_id),
                        "conversation_id": int(conversation_id),
                        "title": title,
                        "content": content[:5000],
                        "source": source,
                    }
                )

            if not prepared:
                return

            embeddings = self._generate_embeddings_batch([item["content"] for item in prepared])
            for item, embedding in zip(prepared, embeddings):
                item["embedding"] = embedding

            payload = [
                [item["chunk_id"] for item in prepared],
                [item["file_id"] for item in prepared],
                [item["user_id"] for item in prepared],
                [item["conversation_id"] for item in prepared],
                [item["title"] for item in prepared],
                [item["content"] for item in prepared],
                [item["source"] for item in prepared],
                [item["embedding"] for item in prepared],
            ]
            self.user_collection.insert(payload)
            self.user_collection.flush()
            self._invalidate_user_chunk_caches()
        except Exception as exc:  # pragma: no cover - 依赖外部服务
            self.available = False
            self.degraded_reason = f"Milvus user chunk insert failed: {exc}"

    def delete_user_file_chunks(self, file_id: int) -> None:
        """
        删除指定文件的所有分块向量。
        
        Args:
            file_id: 文件 ID
        """
        self._delete_user_chunks(f"file_id == {int(file_id)}")

    def delete_user_conversation_chunks(self, conversation_id: int) -> None:
        """
        删除指定会话的所有分块向量。
        
        Args:
            conversation_id: 会话 ID
        """
        self._delete_user_chunks(f"conversation_id == {int(conversation_id)}")

    def _delete_user_chunks(self, expr: str) -> None:
        """
        根据表达式删除用户分块向量。
        
        Args:
            expr: Milvus 删除表达式
        """
        self._maybe_reconnect()
        if not self.available or self.user_collection is None:
            return
        try:
            self.user_collection.delete(expr)
            self.user_collection.flush()
            self._invalidate_user_chunk_caches()
        except Exception as exc:  # pragma: no cover - 依赖外部服务
            self.available = False
            self.degraded_reason = f"Milvus user chunk delete failed: {exc}"

    def search(self, query: str, role_type: str, top_k: int = 3) -> List[Dict]:
        # 公共知识库主入口：根据当前 retrieval_mode 决定走哪种检索策略。
        """
        公共知识库搜索（所有文档）。
        
        Args:
            query: 查询文本
            role_type: 角色类型
            top_k: 返回结果数
            
        Returns:
            List[Dict]: 搜索结果列表
        """
        return self._public_search_by_mode(query=query, role_type=role_type, top_k=top_k)

    def search_pdf_documents(self, query: str, role_type: str, top_k: int = 3) -> List[Dict]:
        """
        公共知识库搜索（仅 PDF 文档）。
        
        Args:
            query: 查询文本
            role_type: 角色类型
            top_k: 返回结果数
            
        Returns:
            List[Dict]: 搜索结果列表
        """
        return self._public_search_by_mode(query=query, role_type=role_type, top_k=top_k, pdf_only=True)

    def search_non_pdf_documents(self, query: str, role_type: str, top_k: int = 3) -> List[Dict]:
        """
        公共知识库搜索（排除 PDF 文档）。
        
        Args:
            query: 查询文本
            role_type: 角色类型
            top_k: 返回结果数
            
        Returns:
            List[Dict]: 搜索结果列表
        """
        return self._public_search_by_mode(query=query, role_type=role_type, top_k=top_k, exclude_pdf=True)

    def search_user_document_chunks(
        self,
        query: str,
        user_id: int,
        conversation_id: int = None,
        top_k: int = 4,
        include_other_conversations: bool = True,
    ) -> List[Dict]:
        """
        用户文件分块搜索。
        
        优先搜索当前会话，如果结果不足则扩展到其他会话。
        
        Args:
            query: 查询文本
            user_id: 用户 ID
            conversation_id: 会话 ID
            top_k: 返回结果数
            include_other_conversations: 是否包含其他会话的结果
            
        Returns:
            List[Dict]: 搜索结果列表
        """
        primary_hits = self._search_user_document_scope(
            query=query,
            user_id=user_id,
            conversation_id=conversation_id,
            top_k=top_k,
            current_conversation_only=True,
        )
        if len(primary_hits) >= top_k or not user_id or not include_other_conversations:
            return primary_hits[:top_k]

        fallback_hits = self._search_user_document_scope(
            query=query,
            user_id=user_id,
            conversation_id=conversation_id,
            top_k=top_k * 2,
            current_conversation_only=False,
        )
        merged = self._dedupe_by_key(primary_hits + fallback_hits, "id")
        return merged[:top_k]

    def _hybrid_public_search(
        self,
        query: str,
        role_type: str,
        top_k: int,
        pdf_only: bool = False,
        exclude_pdf: bool = False,
    ) -> List[Dict]:
        # 历史兼容入口：执行公共知识库混合检索。
        # 这里会并行取回 dense、sparse、bm25 三路结果，再做融合和重排。
        """
        公共知识库混合检索（稠密 + 稀疏 + RRF 融合 + 重排序）。
        
        Args:
            query: 查询文本
            role_type: 角色类型
            top_k: 返回结果数
            pdf_only: 仅搜索 PDF 文档
            exclude_pdf: 排除 PDF 文档
            
        Returns:
            List[Dict]: 搜索结果列表
        """
        query_text = self.processor.clean_text(query or "")
        if not query_text:
            return []
        return self._run_public_mode(
            mode="hybrid_rerank",
            query=query_text,
            role_type=role_type,
            top_k=top_k,
            pdf_only=pdf_only,
            exclude_pdf=exclude_pdf,
        )

    def _public_search_by_mode(self, query: str, role_type: str, top_k: int, pdf_only: bool = False, exclude_pdf: bool = False) -> List[Dict]:
        hits = self._run_public_mode(mode=self.retrieval_mode, query=query, role_type=role_type, top_k=top_k, pdf_only=pdf_only, exclude_pdf=exclude_pdf)
        self.last_search_meta = {"scope": "public", "requested_mode": self.retrieval_mode, "effective_mode": self.retrieval_mode, "compare_mode_enabled": False, "compare": None, "auto_selection": None}
        return hits

    def _run_public_mode(
        self,
        mode: str,
        query: str,
        role_type: str,
        top_k: int,
        pdf_only: bool = False,
        exclude_pdf: bool = False,
    ) -> List[Dict]:
        # 执行单次公共检索。
        # 默认链路：dense + bm25 + RRF + rerank。
        """
        执行指定模式的公共知识库搜索。
        
        Args:
            mode: 检索模式（dense/sparse/bm25/hybrid/hybrid_rerank）
            query: 查询文本
            role_type: 角色类型
            top_k: 返回结果数
            pdf_only: 仅搜索 PDF 文档
            exclude_pdf: 排除 PDF 文档
            
        Returns:
            List[Dict]: 搜索结果列表
        """
        normalized_mode = self._normalize_retrieval_mode(mode)
        query_text = self.processor.clean_text(query or "")
        if not query_text:
            return []

        candidate_limit = max(top_k * self.candidate_multiplier, top_k)
        if normalized_mode == "bm25":
            return self._search_database_bm25(
                query=query_text,
                role_type=role_type,
                top_k=top_k,
                pdf_only=pdf_only,
                exclude_pdf=exclude_pdf,
            )

        dense_hits = self._search_public_dense(
            query=query_text,
            role_type=role_type,
            top_k=candidate_limit,
            pdf_only=pdf_only,
            exclude_pdf=exclude_pdf,
        )
        bm25_hits = self._search_database_bm25(
            query=query_text,
            role_type=role_type,
            top_k=candidate_limit,
            pdf_only=pdf_only,
            exclude_pdf=exclude_pdf,
        )
        merged = self._merge_hits([dense_hits, bm25_hits], key_field="doc_id")
        if normalized_mode == "hybrid":
            return merged[:top_k]
        return self._rerank_hits(query_text, merged, top_k=top_k)

    def _search_public_dense(
        self,
        query: str,
        role_type: str,
        top_k: int,
        pdf_only: bool = False,
        exclude_pdf: bool = False,
    ) -> List[Dict]:
        # 公共知识库 dense 检索。
        # 优先使用 Milvus；Milvus 不可用时回退到本地 embedding 相似度计算。
        """
        公共知识库稠密向量检索。
        
        优先使用 Milvus，降级到本地内存向量检索。
        
        Args:
            query: 查询文本
            role_type: 角色类型
            top_k: 返回结果数
            pdf_only: 仅搜索 PDF 文档
            exclude_pdf: 排除 PDF 文档
            
        Returns:
            List[Dict]: 搜索结果列表
        """
        self._maybe_reconnect()
        if self.available and self.collection is not None:
            hits = self._search_public_from_milvus(query, role_type, top_k * 2)
            return self._filter_public_hits(hits, pdf_only=pdf_only, exclude_pdf=exclude_pdf)[:top_k]
        return []

    def _search_public_from_milvus(self, query: str, role_type: str, top_k: int) -> List[Dict]:
        """
        从 Milvus 搜索公共知识库。
        
        Args:
            query: 查询文本
            role_type: 角色类型
            top_k: 返回结果数
            
        Returns:
            List[Dict]: 搜索结果列表
        """
        try:
            query_vector = self._generate_embedding(query)
            results = self.collection.search(
                data=[query_vector],
                anns_field="embedding",
                param={"metric_type": "IP", "params": {"nprobe": 10}},
                limit=top_k,
                expr=f'role_type == "{role_type}"',
                output_fields=["doc_id", "title", "content", "role_type", "source"],
            )
            hits = []
            for hit in results[0]:
                entity = hit.entity
                hits.append(
                    {
                        "doc_id": entity.get("doc_id"),
                        "title": entity.get("title"),
                        "content": entity.get("content"),
                        "role_type": entity.get("role_type"),
                        "source": entity.get("source"),
                        "score": float(hit.distance),
                        "retrieval_sources": ["milvus_dense"],
                    }
                )
            return hits
        except Exception as exc:  # pragma: no cover - 依赖外部服务
            self.available = False
            self.degraded_reason = f"Milvus search failed: {exc}"
            return []

    def _search_public_from_db_embeddings(
        self,
        query: str,
        role_type: str,
        top_k: int,
        pdf_only: bool = False,
        exclude_pdf: bool = False,
    ) -> List[Dict]:
        """
        从数据库加载文档并在内存中计算向量相似度。
        
        Args:
            query: 查询文本
            role_type: 角色类型
            top_k: 返回结果数
            pdf_only: 仅搜索 PDF 文档
            exclude_pdf: 排除 PDF 文档
            
        Returns:
            List[Dict]: 搜索结果列表
        """
        query_vector = self._generate_embedding(query)
        documents = self._load_public_documents(role_type, pdf_only=pdf_only, exclude_pdf=exclude_pdf)
        if not documents:
            return []

        scored = []
        for doc in documents:
            doc_id = doc.get("doc_id", "")
            cached = self._cached_embedding(doc_id)
            if cached is None:
                cached = self._generate_embedding(doc.get("content", ""))
                self._local_embedding_cache[doc_id] = cached
            score = self._dot(query_vector, cached)
            scored.append(
                {
                    "doc_id": doc_id,
                    "title": doc.get("title", ""),
                    "content": doc.get("content", ""),
                    "role_type": doc.get("role_type", ""),
                    "source": doc.get("source", ""),
                    "score": score,
                    "retrieval_sources": ["db_dense"],
                }
            )

        scored.sort(key=lambda item: item["score"], reverse=True)
        return scored[:top_k]

    def _search_database_bm25(
        self,
        query: str,
        role_type: str,
        top_k: int,
        pdf_only: bool = False,
        exclude_pdf: bool = False,
    ) -> List[Dict]:
        """
        使用 BM25 分数执行公共知识库词法检索。
        """
        documents = self._load_public_documents(role_type, pdf_only=pdf_only, exclude_pdf=exclude_pdf)
        if not documents:
            return []

        query_tokens = self.processor.segment_chinese(query)
        if not query_tokens:
            return []

        scored: List[Dict] = []
        for doc in documents:
            title = doc.get("title", "")
            content = doc.get("content", "")
            text = f"{title} {content}"
            score = float(self._bm25_score(query_tokens, text, doc_tokens=self._tokenize_text_cached(text)))
            scored.append(
                {
                    "doc_id": doc.get("doc_id", ""),
                    "title": title,
                    "content": content,
                    "role_type": doc.get("role_type", ""),
                    "source": doc.get("source", ""),
                    "score": score,
                    "retrieval_sources": ["db_bm25"],
                }
            )

        scored.sort(key=lambda item: item["score"], reverse=True)
        return scored[:top_k]

    def _search_user_document_scope(
        self,
        query: str,
        user_id: int,
        conversation_id: int = None,
        top_k: int = 4,
        current_conversation_only: bool = True,
    ) -> List[Dict]:
        """
        搜索用户文件分块。
        
        Args:
            query: 查询文本
            user_id: 用户 ID
            conversation_id: 会话 ID
            top_k: 返回结果数
            current_conversation_only: 是否仅搜索当前会话
            
        Returns:
            List[Dict]: 搜索结果列表
        """
        query_text = self.processor.clean_text(query or "")
        if not query_text:
            return []

        self._maybe_reconnect()
        if self.available and self.user_collection is not None:
            hits = self._search_user_document_chunks_from_milvus(
                query=query_text,
                user_id=user_id,
                conversation_id=conversation_id,
                top_k=top_k,
                current_conversation_only=current_conversation_only,
            )
            if hits:
                return hits

        return self._search_user_document_chunks_from_db(
            query=query_text,
            user_id=user_id,
            conversation_id=conversation_id,
            top_k=top_k,
            current_conversation_only=current_conversation_only,
        )

    def _search_user_document_chunks_from_milvus(
        self,
        query: str,
        user_id: int,
        conversation_id: int = None,
        top_k: int = 4,
        current_conversation_only: bool = True,
    ) -> List[Dict]:
        """
        从 Milvus 搜索用户文件分块。
        
        Args:
            query: 查询文本
            user_id: 用户 ID
            conversation_id: 会话 ID
            top_k: 返回结果数
            current_conversation_only: 是否仅搜索当前会话
            
        Returns:
            List[Dict]: 搜索结果列表
        """
        try:
            query_vector = self._generate_embedding(query)
            if current_conversation_only and conversation_id is not None:
                expr = f"user_id == {int(user_id)} and conversation_id == {int(conversation_id)}"
            else:
                expr = f"user_id == {int(user_id)}"

            results = self.user_collection.search(
                data=[query_vector],
                anns_field="embedding",
                param={"metric_type": "IP", "params": {"nprobe": 10}},
                limit=top_k,
                expr=expr,
                output_fields=["chunk_id", "file_id", "user_id", "conversation_id", "title", "content", "source"],
            )
            hits = []
            for hit in results[0]:
                entity = hit.entity
                hits.append(
                    {
                        "id": entity.get("chunk_id"),
                        "file_id": entity.get("file_id"),
                        "user_id": entity.get("user_id"),
                        "conversation_id": entity.get("conversation_id"),
                        "title": entity.get("title"),
                        "content": entity.get("content"),
                        "source": entity.get("source"),
                        "score": float(hit.distance),
                        "retrieval_sources": ["milvus_user_dense"],
                    }
                )
            return hits
        except Exception as exc:  # pragma: no cover - 依赖外部服务
            self.available = False
            self.degraded_reason = f"Milvus user chunk search failed: {exc}"
            return []

    def _search_user_document_chunks_from_db_embeddings(
        self,
        query: str,
        user_id: int,
        conversation_id: int = None,
        top_k: int = 4,
        current_conversation_only: bool = True,
    ) -> List[Dict]:
        """
        从数据库加载用户分块并在内存中计算向量相似度。
        
        Args:
            query: 查询文本
            user_id: 用户 ID
            conversation_id: 会话 ID
            top_k: 返回结果数
            current_conversation_only: 是否仅搜索当前会话
            
        Returns:
            List[Dict]: 搜索结果列表
        """
        query_vector = self._generate_embedding(query)
        chunks = self._load_user_chunks(
            user_id=user_id,
            conversation_id=conversation_id,
            current_conversation_only=current_conversation_only,
        )
        if not chunks:
            return []

        scored = []
        for chunk in chunks:
            chunk_id = chunk.get("id", "")
            cached = self._cached_embedding(chunk_id)
            if cached is None:
                cached = self._generate_embedding(chunk.get("content", ""))
                self._local_embedding_cache[chunk_id] = cached
            score = self._dot(query_vector, cached)
            scored.append(
                {
                    "id": chunk_id,
                    "file_id": chunk.get("file_id"),
                    "user_id": chunk.get("user_id"),
                    "conversation_id": chunk.get("conversation_id"),
                    "title": chunk.get("title", ""),
                    "content": chunk.get("content", ""),
                    "source": chunk.get("source", ""),
                    "score": score,
                    "retrieval_sources": ["db_user_dense"],
                }
            )

        scored.sort(key=lambda item: item["score"], reverse=True)
        return scored[:top_k]

    def _is_pdf_source(self, source: str) -> bool:
        """
        判断来源是否为 PDF 文档。
        
        Args:
            source: 来源字符串
            
        Returns:
            bool: 是否为 PDF 来源
        """
        if not source:
            return False
        return source.lower().endswith(".pdf")

    def _search_user_document_chunks_from_db(
        self,
        query: str,
        user_id: int,
        conversation_id: int = None,
        top_k: int = 4,
        current_conversation_only: bool = True,
    ) -> List[Dict]:
        """
        从数据库搜索用户文件分块（基于 BM25 评分）。
        
        Args:
            query: 查询文本
            user_id: 用户 ID
            conversation_id: 会话 ID
            top_k: 返回结果数
            current_conversation_only: 是否仅搜索当前会话
            
        Returns:
            List[Dict]: 搜索结果列表
        """
        chunks = self._load_user_chunks(
            user_id=user_id,
            conversation_id=conversation_id,
            current_conversation_only=current_conversation_only,
        )
        if not chunks:
            return []

        query_tokens = self.processor.segment_chinese(query)
        if not query_tokens:
            return []

        scored = []
        for chunk in chunks:
            content = chunk.get("content", "")
            title = chunk.get("title", "")
            text = f"{title} {content}"
            score = self._bm25_score(query_tokens, text)
            scored.append(
                {
                    "id": chunk.get("id"),
                    "file_id": chunk.get("file_id"),
                    "user_id": chunk.get("user_id"),
                    "conversation_id": chunk.get("conversation_id"),
                    "title": title,
                    "content": content,
                    "source": chunk.get("source", ""),
                    "score": score,
                    "retrieval_sources": ["db_user_bm25"],
                }
            )

        scored.sort(key=lambda item: item["score"], reverse=True)
        return scored[:top_k]

    def _search_user_document_chunks_sparse(
        self,
        query: str,
        user_id: int,
        conversation_id: int = None,
        top_k: int = 4,
        current_conversation_only: bool = True,
    ) -> List[Dict]:
        """
        从数据库搜索用户文件分块（基于词项重合评分）。
        
        Args:
            query: 查询文本
            user_id: 用户 ID
            conversation_id: 会话 ID
            top_k: 返回结果数
            current_conversation_only: 是否仅搜索当前会话
            
        Returns:
            List[Dict]: 搜索结果列表
        """
        chunks = self._load_user_chunks(
            user_id=user_id,
            conversation_id=conversation_id,
            current_conversation_only=current_conversation_only,
        )
        if not chunks:
            return []

        query_tokens = self.processor.segment_chinese(query)
        if not query_tokens:
            return []

        query_counter = Counter(query_tokens)
        scored = []
        for chunk in chunks:
            content = chunk.get("content", "")
            title = chunk.get("title", "")
            text = f"{title} {content}"
            doc_tokens = self._tokenize_text_cached(text)
            doc_counter = Counter(doc_tokens)
            common = query_counter & doc_counter
            score = sum(common.values())
            scored.append(
                {
                    "id": chunk.get("id"),
                    "file_id": chunk.get("file_id"),
                    "user_id": chunk.get("user_id"),
                    "conversation_id": chunk.get("conversation_id"),
                    "title": title,
                    "content": content,
                    "source": chunk.get("source", ""),
                    "score": score,
                    "retrieval_sources": ["db_user_sparse"],
                }
            )

        scored.sort(key=lambda item: item["score"], reverse=True)
        return scored[:top_k]

    def _load_user_chunks(
        self,
        user_id: int,
        conversation_id: int = None,
        current_conversation_only: bool = True,
    ) -> List[Dict]:
        """
        从数据库加载用户文件分块。
        
        Args:
            user_id: 用户 ID
            conversation_id: 会话 ID
            current_conversation_only: 是否仅加载当前会话的分块
            
        Returns:
            List[Dict]: 分块列表
        """
        cache_key = (int(user_id), int(conversation_id) if conversation_id is not None else None, bool(current_conversation_only))
        cached = self._user_chunks_cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            session = SessionLocal()
            try:
                query = session.query(UserDocumentChunk).filter(UserDocumentChunk.user_id == user_id)
                if current_conversation_only and conversation_id is not None:
                    query = query.filter(UserDocumentChunk.conversation_id == conversation_id)
                chunks = query.order_by(UserDocumentChunk.chunk_index).all()
                loaded_chunks = [
                    {
                        "id": chunk.id,
                        "file_id": chunk.file_id,
                        "user_id": chunk.user_id,
                        "conversation_id": chunk.conversation_id,
                        "title": chunk.title or "",
                        "content": chunk.content or "",
                        "source": chunk.source or "",
                    }
                    for chunk in chunks
                ]
                self._user_chunks_cache[cache_key] = loaded_chunks
                return loaded_chunks
            finally:
                session.close()
        except Exception as exc:  # pragma: no cover - 依赖数据库
            return []

    def _load_public_documents(
        self,
        role_type: str,
        pdf_only: bool = False,
        exclude_pdf: bool = False,
    ) -> List[Dict]:
        """
        从数据库加载公共知识文档。

        Args:
            role_type: 角色类型
            pdf_only: 仅保留 PDF 来源文档
            exclude_pdf: 排除 PDF 来源文档

        Returns:
            List[Dict]: 文档列表
        """
        cache_key = (role_type, bool(pdf_only), bool(exclude_pdf))
        cached = self._public_documents_cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            session = SessionLocal()
            try:
                rows = (
                    session.query(KnowledgeDocument)
                    .filter(KnowledgeDocument.role_type == role_type)
                    .order_by(KnowledgeDocument.id.asc())
                    .all()
                )

                documents: List[Dict] = []
                for row in rows:
                    source = row.source or ""
                    is_pdf = self._is_pdf_source(source)
                    if pdf_only and not is_pdf:
                        continue
                    if exclude_pdf and is_pdf:
                        continue
                    documents.append(
                        {
                            "doc_id": f"db_{row.id}",
                            "title": row.title or "",
                            "content": row.content or "",
                            "role_type": row.role_type or "",
                            "source": source,
                        }
                    )
                self._public_documents_cache[cache_key] = documents
                return documents
            finally:
                session.close()
        except Exception:  # pragma: no cover - 依赖数据库
            return []

    def _filter_public_hits(
        self,
        hits: List[Dict],
        pdf_only: bool = False,
        exclude_pdf: bool = False,
    ) -> List[Dict]:
        """
        过滤公共知识库搜索结果。
        
        Args:
            hits: 搜索结果列表
            pdf_only: 仅保留 PDF 来源的结果
            exclude_pdf: 排除 PDF 来源的结果
            
        Returns:
            List[Dict]: 过滤后的结果列表
        """
        if not pdf_only and not exclude_pdf:
            return hits
        filtered = []
        for hit in hits:
            source = hit.get("source", "")
            is_pdf = self._is_pdf_source(source)
            if pdf_only and not is_pdf:
                continue
            if exclude_pdf and is_pdf:
                continue
            filtered.append(hit)
        return filtered

    def _can_short_circuit_with_milvus(self, dense_hits: List[Dict]) -> bool:
        """
        判断是否可以使用 Milvus 结果短路（跳过本地检索）。
        
        Args:
            dense_hits: 稠密检索结果列表
            
        Returns:
            bool: 是否可以短路
        """
        if not self.milvus_first_enabled:
            return False
        if not dense_hits:
            return False
        if len(dense_hits) < self.milvus_first_min_hits:
            return False
        avg_score = sum(hit.get("score", 0.0) for hit in dense_hits) / len(dense_hits)
        return avg_score >= self.milvus_first_min_score

    def _merge_hits(
        self,
        hit_lists: List[List[Dict]],
        key_field: str = "doc_id",
    ) -> List[Dict]:
        """
        使用 RRF 融合多个检索结果列表。
        
        Args:
            hit_lists: 多个检索结果列表
            key_field: 用于去重的字段名
            
        Returns:
            List[Dict]: 融合后的结果列表
        """
        rrf_scores: Dict[str, float] = {}
        seen: Dict[str, Dict] = {}

        for rank_list in hit_lists:
            for rank, hit in enumerate(rank_list):
                key = str(hit.get(key_field, ""))
                if not key:
                    continue
                rrf_scores[key] = rrf_scores.get(key, 0.0) + 1.0 / (self.hybrid_rrf_k + rank + 1)
                if key not in seen:
                    seen[key] = dict(hit)

        merged = []
        for key, score in sorted(rrf_scores.items(), key=lambda item: item[1], reverse=True):
            entry = seen.get(key, {})
            entry["rrf_score"] = score
            merged.append(entry)

        return merged

    def _rerank_hits(self, query: str, hits: List[Dict], top_k: int) -> List[Dict]:
        """
        使用 reranker 模型对搜索结果进行重排序。
        
        Args:
            query: 查询文本
            hits: 搜索结果列表
            top_k: 返回结果数
            
        Returns:
            List[Dict]: 重排序后的结果列表
        """
        if not hits:
            return []

        if not self.rerank_available:
            return hits[:top_k]

        try:
            candidate_count = min(len(hits), max(top_k, self.rerank_candidate_limit))
            rerank_hits = [dict(hit) for hit in hits[:candidate_count]]
            scores = self._predict_rerank_scores(query, rerank_hits)
            for hit, score in zip(rerank_hits, scores):
                hit["rerank_score"] = score
            rerank_hits.sort(key=lambda item: item.get("rerank_score", 0.0), reverse=True)
            return rerank_hits[:top_k]
        except Exception as exc:  # pragma: no cover - 依赖子进程
            return hits[:top_k]

    def _predict_rerank_scores(self, query: str, hits: List[Dict]) -> List[float]:
        """
        使用 rerank worker 子进程预测重排序分数。
        
        Args:
            query: 查询文本
            hits: 搜索结果列表
            
        Returns:
            List[float]: 重排序分数列表
        """
        pairs = [[query, hit.get("content", "")] for hit in hits]
        input_data = json.dumps({"pairs": pairs, "model_path": self.rerank_model_path})
        completed = subprocess.run(
            [sys.executable, self.rerank_worker_path],
            input=input_data,
            capture_output=True,
            check=False,
            timeout=30,
        )
        if completed.returncode != 0:
            stderr = (completed.stderr or b"").decode("utf-8", errors="replace").strip()
            raise RuntimeError(stderr or f"rerank worker exit code: {completed.returncode}")

        output = (completed.stdout or b"").decode("utf-8", errors="replace").strip()
        if not output:
            raise RuntimeError("rerank worker returned empty output")

        result = json.loads(output)
        return result.get("scores", [])

    def _bm25_score(self, query_tokens: List[str], text: str, doc_tokens: Optional[List[str]] = None) -> float:
        """
        计算 BM25 评分。
        
        Args:
            query_tokens: 查询词列表
            text: 文档文本
            
        Returns:
            float: BM25 评分
        """
        doc_tokens = doc_tokens if doc_tokens is not None else self._tokenize_text_cached(text)
        doc_len = len(doc_tokens)
        if doc_len == 0:
            return 0.0

        doc_counter = Counter(doc_tokens)
        score = 0.0
        for token in query_tokens:
            tf = doc_counter.get(token, 0)
            if tf == 0:
                continue
            idf = 1.0  # 简化 IDF，假设所有词都有相同的 IDF
            score += idf * (tf * (self.bm25_k1 + 1)) / (tf + self.bm25_k1 * (1 - self.bm25_b + self.bm25_b * doc_len / 100.0))
        return score

    def _exact_match_bonus(self, query: str, text: str) -> float:
        """
        计算精确匹配加分。
        
        Args:
            query: 查询文本
            text: 文档文本
            
        Returns:
            float: 匹配加分
        """
        if not query or not text:
            return 0.0
        count = text.lower().count(query.lower())
        return count * 0.1

    def _tokenize_list(self, texts: List[str]) -> List[List[str]]:
        """
        批量分词。
        
        Args:
            texts: 文本列表
            
        Returns:
            List[List[str]]: 分词结果列表
        """
        return [self.processor.segment_chinese(text) for text in texts]

    def _cached_embedding(self, key: str) -> Optional[List[float]]:
        """
        从缓存中获取向量。
        
        Args:
            key: 缓存键
            
        Returns:
            Optional[List[float]]: 向量，如果缓存未命中则返回 None
        """
        return self._local_embedding_cache.get(key)

    def _tokenize_text_cached(self, text: str) -> List[str]:
        normalized = text or ""
        if not normalized:
            return []

        cache_key = hashlib.sha1(normalized.encode("utf-8")).hexdigest()
        cached = self._token_cache.get(cache_key)
        if cached is not None:
            return cached

        tokens = self.processor.segment_chinese(normalized)
        self._token_cache[cache_key] = tokens
        return tokens

    def _invalidate_public_caches(self) -> None:
        self._public_documents_cache.clear()

    def _invalidate_user_chunk_caches(self) -> None:
        self._user_chunks_cache.clear()

    def _dot(self, a: List[float], b: List[float]) -> float:
        """
        计算两个向量的点积。
        
        Args:
            a: 向量 a
            b: 向量 b
            
        Returns:
            float: 点积结果
        """
        return sum(x * y for x, y in zip(a, b))

    def _dedupe_by_key(self, items: List[Dict], key: str) -> List[Dict]:
        """
        按指定键去重。
        
        Args:
            items: 字典列表
            key: 去重键
            
        Returns:
            List[Dict]: 去重后的列表
        """
        seen: set = set()
        result: List[Dict] = []
        for item in items:
            value = item.get(key)
            if value is not None and value not in seen:
                seen.add(value)
                result.append(item)
        return result

    def _normalize_retrieval_mode(self, mode: str) -> str:
        """
        规范化检索模式字符串。
        
        Args:
            mode: 原始模式字符串
            
        Returns:
            str: 规范化后的模式
        """
        normalized = (mode or "hybrid").strip().lower().replace("-", "_")
        if normalized not in SUPPORTED_RETRIEVAL_MODES:
            normalized = "hybrid"
        return normalized

    def get_status(self) -> Dict:
        """
        获取 MilvusStore 的状态信息。
        
        Returns:
            Dict: 状态信息字典
        """
        return {
            "milvus_available": self.available,
            "degraded_reason": self.degraded_reason,
            "embedding_available": self.embedding_available,
            "embedding_error": self.embedding_error,
            "rerank_available": self.rerank_available,
            "rerank_error": self.rerank_error,
            "retrieval_mode": self.retrieval_mode,
            "hybrid_enabled": self.hybrid_enabled,
            "collection_name": self.collection_name,
            "user_collection_name": self.user_collection_name,
            "embedding_dim": self.embedding_dim,
            "embedding_model_path": self.embedding_model_path,
            "rerank_model_path": self.rerank_model_path,
            "last_search_meta": self.last_search_meta,
        }
