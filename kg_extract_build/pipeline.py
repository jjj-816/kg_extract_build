import json
import os
import subprocess
from datetime import datetime

from .documents import BreakpointManager, DocumentLoader
from .entity_aligner import EntityAligner
from .extractor import LongDocLLMEntityExtractor
from .persistence import ExperimentRecorder, build_experiment_store, content_hash
# from .neo4j_builder import ShaleGasNeo4jBuilder
from .retriever import CorpusRetriever
from .schema import KGSchema
from .settings import (
    DEBUG_DIR,
    DOCUMENT_FOLDER,
    ENTITY_DEBUG_DIR,
    EXPERIMENT_RUN_NAME,
    EXPERT_ENTITIES,
    LLM_API_KEY,
    LLM_BASE_URL,
    LLM_MODEL,
    MILVUS_ENABLED,
    MYSQL_ENABLED,
    # NEO4J_PWD,
    # NEO4J_URI,
    # NEO4J_USER,
    PROCESSED_RECORD,
    RESPECT_LEGACY_BREAKPOINT,
    REUSE_ENTITY_CACHE,
    REUSE_TRIPLET_CACHE,
    RETRIEVE_SENTENCE_NUM,
    VECTOR_MODEL_PATH,
    resolve_schema_path,
)
from .triplets import TripletCorrector, TripletGenerator
from .vector_store import build_vector_store


def infer_source_type(file_name):
    if "规范" in file_name or "标准" in file_name:
        return "spec"
    return "case"


def build_known_entities(aligned_entities):
    known_entities = {}
    for entity in aligned_entities:
        standard_item = {"name": entity["name"], "type": entity.get("type"), "aliases": entity.get("aliases", [])}
        known_entities[entity["name"]] = standard_item
        for alias in entity.get("aliases", []):
            known_entities[alias] = standard_item
    return known_entities


def clean_filename(text):
    for char in ['/', '\\', ':', '*', '?', '"', '<', '>', '|']:
        text = text.replace(char, "_")
    return text.strip()


def get_entity_debug_dir(file_name, debug_dir):
    doc_stem = clean_filename(file_name.rsplit(".", 1)[0])
    save_dir = debug_dir / doc_stem
    save_dir.mkdir(parents=True, exist_ok=True)
    return save_dir


def save_raw_entities(file_name, entities, debug_dir):
    save_dir = get_entity_debug_dir(file_name, debug_dir)
    save_path = save_dir / "raw_entities_debug.json"
    payload = {
        "file_name": file_name,
        "entity_count": len(entities),
        "entities": entities,
    }
    with save_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return save_path


def save_aligned_entities(file_name, entities, alias_to_standard, debug_dir):
    save_dir = get_entity_debug_dir(file_name, debug_dir)
    save_path = save_dir / "aligned_entities.json"
    payload = {
        "file_name": file_name,
        "entity_count": len(entities),
        "alias_mapping_count": len(alias_to_standard),
        "entities": entities,
        "alias_to_standard": alias_to_standard,
    }
    with save_path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    return save_path


def load_aligned_entities(file_name, debug_dir):
    doc_stem = clean_filename(file_name.rsplit(".", 1)[0])
    save_path = debug_dir / doc_stem / "aligned_entities.json"
    if not save_path.exists():
        return None
    try:
        with save_path.open("r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception as exc:
        print(f"读取实体对齐断点失败，将重新抽取和对齐：{save_path}，原因：{exc}")
        return None

    entities = payload.get("entities")
    if not isinstance(entities, list):
        print(f"实体对齐断点格式异常，将重新抽取和对齐：{save_path}")
        return None
    return entities


def retrieve_entity_context(retriever, entity, recorder=None):
    contexts = []
    for alias in entity.get("aliases", []) or [entity["name"]]:
        hits = retriever.retrieve_with_details(alias)
        if recorder is not None:
            recorder.record_retrieval(entity["name"], alias, hits)
        if hits:
            contexts.extend(hit["sentence"] for hit in hits)
    lines = list(dict.fromkeys(contexts))
    return "\n".join(lines[:retriever.top_n])


def current_code_commit():
    configured = os.getenv("KG_CODE_COMMIT", "").strip()
    if configured:
        return configured
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(DOCUMENT_FOLDER.parent.parent),
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
        return result.stdout.strip()
    except Exception:
        return ""


def schema_snapshot(schema):
    return {
        "path": str(schema.schema_path),
        "entity_types": schema.entity_types,
        "relation_types": schema.relation_types,
    }


def config_snapshot():
    return {
        "document_folder": str(DOCUMENT_FOLDER),
        "schema_path": str(resolve_schema_path()),
        "vector_model_path": str(VECTOR_MODEL_PATH),
        "llm_base_url": LLM_BASE_URL,
        "llm_model": LLM_MODEL,
        "retrieve_sentence_num": RETRIEVE_SENTENCE_NUM,
        "mysql_enabled": MYSQL_ENABLED,
        "milvus_enabled": MILVUS_ENABLED,
        "respect_legacy_breakpoint": RESPECT_LEGACY_BREAKPOINT,
        "reuse_entity_cache": REUSE_ENTITY_CACHE,
        "reuse_triplet_cache": REUSE_TRIPLET_CACHE,
    }


def default_run_name():
    if EXPERIMENT_RUN_NAME:
        return EXPERIMENT_RUN_NAME
    return datetime.now().strftime("kg-run-%Y%m%d-%H%M%S")


def run_pipeline():
    schema = KGSchema(resolve_schema_path())
    breakpoint_manager = BreakpointManager(PROCESSED_RECORD)
    doc_loader = DocumentLoader(
        DOCUMENT_FOLDER,
        breakpoint_manager,
        respect_breakpoint=RESPECT_LEGACY_BREAKPOINT,
    )
    extractor = LongDocLLMEntityExtractor(EXPERT_ENTITIES, LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, schema)
    aligner = EntityAligner(LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, VECTOR_MODEL_PATH)
    corrector = TripletCorrector(schema)
    store = build_experiment_store()
    vector_store = build_vector_store()
    run_id = None
    failed_documents = 0

    if MILVUS_ENABLED and not MYSQL_ENABLED:
        print("[实验存储] Milvus 依赖 MySQL chunk_id；请同时启用 KG_MYSQL_ENABLED。")

    try:
        run_id = store.start_run(
            default_run_name(),
            config_snapshot(),
            schema_snapshot(schema),
            current_code_commit(),
        )
        print(f"[实验存储] run_id={run_id}")

        docs = doc_loader.load_all_unprocessed_docs()
        if not docs:
            print("没有符合条件的待处理文档。")
            store.finish_run(run_id, "completed")
            return run_id

        for file_name, content in docs.items():
            print("\n" + "=" * 60)
            print(f"正在处理文档：{file_name}")
            print("=" * 60)

            source_type = infer_source_type(file_name)
            document_id = store.start_document(
                run_id,
                file_name,
                source_type,
                content_hash(content),
                content,
            )
            recorder = ExperimentRecorder(
                store,
                vector_store,
                run_id,
                document_id,
                model_name=LLM_MODEL,
            )

            try:
                entities = None
                if REUSE_ENTITY_CACHE:
                    entities = load_aligned_entities(file_name, ENTITY_DEBUG_DIR)
                if entities is not None:
                    for entity in entities:
                        entity.setdefault("source_type", source_type)
                    print(f"复用已保存实体对齐结果：{len(entities)} 个实体")
                    recorder.record_entities("aligned", entities)
                else:
                    entities = extractor.extract(content, recorder=recorder)
                    recorder.record_entities("raw", entities)
                    raw_entity_debug_path = save_raw_entities(file_name, entities, ENTITY_DEBUG_DIR)
                    print(f"原始实体抽取结果已保存至：{raw_entity_debug_path}")
                    if not entities:
                        print("无有效实体，跳过")
                        store.finish_document(document_id, "completed_empty")
                        breakpoint_manager.mark_processed(file_name)
                        continue

                    for entity in entities:
                        entity["source_type"] = source_type
                    entities, alias_to_standard = aligner.align(
                        entities,
                        source_type=source_type,
                        recorder=recorder,
                    )
                    recorder.record_entities("aligned", entities)
                    if alias_to_standard:
                        print(f"实体对齐映射数：{len(alias_to_standard)}")
                    entity_debug_path = save_aligned_entities(file_name, entities, alias_to_standard, ENTITY_DEBUG_DIR)
                    print(f"实体对齐结果已保存至：{entity_debug_path}")

                if not entities:
                    print("无有效对齐实体，跳过")
                    store.finish_document(document_id, "completed_empty")
                    breakpoint_manager.mark_processed(file_name)
                    continue

                retriever = CorpusRetriever(content, VECTOR_MODEL_PATH, top_n=RETRIEVE_SENTENCE_NUM)
                recorder.record_chunks(
                    "retrieval_sentence",
                    retriever.export_segments(),
                    embeddings=retriever.sent_embeddings,
                )
                known_entities = build_known_entities(entities)
                generator = TripletGenerator(
                    LLM_API_KEY,
                    LLM_BASE_URL,
                    LLM_MODEL,
                    doc_name=file_name,
                    debug_dir=DEBUG_DIR,
                    schema=schema,
                    known_entities=known_entities,
                    recorder=recorder,
                )

                raw_triplets = {}
                for entity in entities:
                    saved_triplets = None
                    if REUSE_TRIPLET_CACHE:
                        saved_triplets = generator.load_saved_triplets(entity["name"])
                    if saved_triplets is not None:
                        print(f"复用已保存三元组：{entity['name']}，数量：{len(saved_triplets)}")
                        raw_triplets[entity["name"]] = saved_triplets
                        recorder.record_triplets(
                            "raw",
                            saved_triplets,
                            entity_name=entity["name"],
                            source_kind="cache",
                        )
                        continue

                    context = retrieve_entity_context(
                        retriever,
                        entity,
                        recorder=recorder,
                    )
                    if not context:
                        print(f"跳过三元组抽取，缺乏可靠上下文：{entity['name']}")
                        raw_triplets[entity["name"]] = []
                        continue
                    raw_triplets[entity["name"]] = generator.generate(entity, context)
                print("完成三元组生成")

                clean_triplets = corrector.correct(raw_triplets)
                recorder.record_triplets("final", clean_triplets)
                print(f"有效三元组总数：{len(clean_triplets)}")

                store.finish_document(document_id, "completed")
                breakpoint_manager.mark_processed(file_name)
                print(f"文档 {file_name} 处理完成")
                print(f"调试文件已保存至：{generator.debug_dir}")
            except Exception as exc:
                failed_documents += 1
                store.finish_document(document_id, "failed", str(exc))
                print(f"处理失败：{exc}")
        run_status = "completed_with_errors" if failed_documents else "completed"
        store.finish_run(run_id, run_status)
        return run_id
    except Exception as exc:
        if run_id is not None:
            store.finish_run(run_id, "failed", str(exc))
        raise
    finally:
        vector_store.close()
        store.close()
        print("\n全部运行结束。")
