"""End-to-end smoke: register normative version, index it, and search it."""

from kg_extract_build import settings
from kg_extract_build.normative_encoder import EncoderProfile, NormativeEncoder, model_revision
from kg_extract_build.normative_indexer import NormativeIndexer
from kg_extract_build.normative_persistence import NormativeStore
from kg_extract_build.normative_registry import register_version
from kg_extract_build.normative_search import NormativeSearcher, SearchRequest
from kg_extract_build.normative_vector_store import build_normative_vector_store
from kg_extract_build.persistence import MySQLExperimentStore


SMOKE_TEXT = (
    "# 有限空间作业安全规范\n\n"
    "第二十条 作业前应通风。\n\n"
    "5.1.2 应记录检测结果。\n"
)


def main() -> None:
    if not settings.NORM_MILVUS_ENABLED:
        raise SystemExit("请先设置 KG_NORM_MILVUS_ENABLED=1 并启动 Milvus 服务。")
    backend = MySQLExperimentStore.from_env()
    store = NormativeStore(backend)
    store._backend.initialize_schema()
    documents = store._read(
        "SELECT document_id, file_name FROM kg_document ORDER BY document_id DESC LIMIT 1"
    )
    if not documents:
        raise SystemExit("规范 smoke 需要至少一条已解析的 kg_document 记录")
    document_id = int(documents[0]["document_id"])
    document_name = str(documents[0]["file_name"])
    result = register_version(
        store,
        document_id=document_id,
        file_name=document_name,
        content=SMOKE_TEXT,
        display_name="有限空间作业安全规范 2020",
        effective_year=2020,
        status="effective",
    )
    profile = EncoderProfile(
        embedding_model_key="paraphrase-multilingual-MiniLM-L12-v2",
        embedding_model_revision=model_revision(settings.NORM_VECTOR_MODEL_PATH),
        embedding_dimension=384,
        max_input_tokens=128,
    )
    encoder = NormativeEncoder(settings.NORM_VECTOR_MODEL_PATH, profile)
    vector_store = build_normative_vector_store()
    try:
        indexer = NormativeIndexer(store, vector_store, encoder, profile)
        build = indexer.build_index(result["version_id"])
        print("build_index:", build)
        if build["status"] != "ready":
            raise SystemExit(f"索引构建失败：{build}")
        release_id = indexer.build_release("smoke-release", [build["index_id"]])
        searcher = NormativeSearcher(store, vector_store, encoder, profile)
        outcome = searcher.search(SearchRequest("通风", 2025, release_id, {"scope_type": "all"}, top_k=5))
        print("evidence count:", len(outcome["evidence"]))
        for item in outcome["evidence"]:
            print(item["clause_number"], item["text"][:40])
    finally:
        encoder.close()
        vector_store.close()
        backend.close()


if __name__ == "__main__":
    main()
