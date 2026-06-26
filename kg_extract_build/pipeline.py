import json

from .documents import BreakpointManager, DocumentLoader
from .entity_aligner import EntityAligner
from .extractor import LongDocLLMEntityExtractor
# from .neo4j_builder import ShaleGasNeo4jBuilder
from .retriever import CorpusRetriever
from .schema import KGSchema
from .settings import (
    DEBUG_DIR,
    DOCUMENT_FOLDER,
    ENTITY_DEBUG_DIR,
    EXPERT_ENTITIES,
    LLM_API_KEY,
    LLM_BASE_URL,
    LLM_MODEL,
    # NEO4J_PWD,
    # NEO4J_URI,
    # NEO4J_USER,
    PROCESSED_RECORD,
    RETRIEVE_SENTENCE_NUM,
    VECTOR_MODEL_PATH,
    resolve_schema_path,
)
from .triplets import TripletCorrector, TripletGenerator


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


def retrieve_entity_context(retriever, entity):
    contexts = []
    for alias in entity.get("aliases", []) or [entity["name"]]:
        context = retriever.retrieve(alias)
        if context:
            contexts.append(context)
    lines = list(dict.fromkeys("\n".join(contexts).splitlines()))
    return "\n".join(lines[:retriever.top_n])


def run_pipeline():
    schema = KGSchema(resolve_schema_path())
    breakpoint_manager = BreakpointManager(PROCESSED_RECORD)
    doc_loader = DocumentLoader(DOCUMENT_FOLDER, breakpoint_manager)
    extractor = LongDocLLMEntityExtractor(EXPERT_ENTITIES, LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, schema)
    aligner = EntityAligner(LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, VECTOR_MODEL_PATH)
    corrector = TripletCorrector(schema)
    # neo4j_builder = ShaleGasNeo4jBuilder(NEO4J_URI, NEO4J_USER, NEO4J_PWD)

    docs = doc_loader.load_all_unprocessed_docs()
    if not docs:
        print("所有文档已处理完毕。")
        # neo4j_builder.close()
        return

    try:
        for file_name, content in docs.items():
            print("\n" + "=" * 60)
            print(f"正在处理文档：{file_name}")
            print("=" * 60)

            try:
                source_type = infer_source_type(file_name)
                entities = load_aligned_entities(file_name, ENTITY_DEBUG_DIR)
                if entities is not None:
                    for entity in entities:
                        entity.setdefault("source_type", source_type)
                    print(f"复用已保存实体对齐结果：{len(entities)} 个实体")
                else:
                    entities = extractor.extract(content)
                    raw_entity_debug_path = save_raw_entities(file_name, entities, ENTITY_DEBUG_DIR)
                    print(f"原始实体抽取结果已保存至：{raw_entity_debug_path}")
                    if not entities:
                        print("无有效实体，跳过")
                        breakpoint_manager.mark_processed(file_name)
                        continue

                    for entity in entities:
                        entity["source_type"] = source_type
                    entities, alias_to_standard = aligner.align(entities, source_type=source_type)
                    if alias_to_standard:
                        print(f"实体对齐映射数{len(alias_to_standard)}")
                    entity_debug_path = save_aligned_entities(file_name, entities, alias_to_standard, ENTITY_DEBUG_DIR)
                    print(f"实体对齐结果已保存至：{entity_debug_path}")

                if not entities:
                    print("无有效对齐实体，跳过")
                    breakpoint_manager.mark_processed(file_name)
                    continue

                retriever = CorpusRetriever(content, VECTOR_MODEL_PATH, top_n=RETRIEVE_SENTENCE_NUM)
                known_entities = build_known_entities(entities)
                generator = TripletGenerator(
                    LLM_API_KEY,
                    LLM_BASE_URL,
                    LLM_MODEL,
                    doc_name=file_name,
                    debug_dir=DEBUG_DIR,
                    schema=schema,
                    known_entities=known_entities,
                )

                raw_triplets = {}
                for entity in entities:
                    saved_triplets = generator.load_saved_triplets(entity["name"])
                    if saved_triplets is not None:
                        print(f"复用已保存三元组：{entity['name']}，数量：{len(saved_triplets)}")
                        raw_triplets[entity["name"]] = saved_triplets
                        continue

                    context = retrieve_entity_context(retriever, entity)
                    if not context:
                        print(f"跳过三元组抽取，缺乏可靠上下文：{entity['name']}")
                        raw_triplets[entity["name"]] = []
                        continue
                    raw_triplets[entity["name"]] = generator.generate(entity, context)
                print("完成三元组生成")

                clean_triplets = corrector.correct(raw_triplets)
                print(f"有效三元组总数：{len(clean_triplets)}")
                # neo4j_builder.import_triplets(clean_triplets, source_type=source_type)

                breakpoint_manager.mark_processed(file_name)
                print(f"文档 {file_name} 处理完成")
                print(f"调试文件已保存至：{generator.debug_dir}")
            except Exception as exc:
                print(f"处理失败：{exc}")
    finally:
        # neo4j_builder.close()
        print("\n全部运行结束。")
