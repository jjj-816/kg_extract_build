import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]

DOCUMENT_FOLDER = BASE_DIR / "shale_gas_docs" / "guifan"
PROCESSED_RECORD = BASE_DIR / "processed_docs.json"
SCHEMA_PATH = BASE_DIR / "kg_schema.json"
SCHEMA_EXAMPLE_PATH = BASE_DIR / "kg_schema.example.json"
DEBUG_DIR = BASE_DIR / "shale_gas_triplets_debug"
ENTITY_DEBUG_DIR = BASE_DIR / "shale_gas_entity_debug"
VECTOR_MODEL_PATH = BASE_DIR / "models" / "paraphrase-multilingual-MiniLM-L12-v2"

LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4/")
LLM_MODEL = os.getenv("LLM_MODEL", "glm-4.5-air")

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PWD = os.getenv("NEO4J_PWD", "neo4j123")

EXPERT_ENTITIES = []
RETRIEVE_SENTENCE_NUM = 10
FREQ_THRESHOLD = 3
UNKNOWN_TYPE = "未分类"


def resolve_schema_path():
    if SCHEMA_PATH.exists():
        return SCHEMA_PATH
    return SCHEMA_EXAMPLE_PATH
