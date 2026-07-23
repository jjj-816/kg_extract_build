import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).with_name(".env"), override=False)
except ImportError:
    pass

def env_path(name, default):
    configured = os.getenv(name, "").strip()
    return Path(configured or default).expanduser().resolve()


DOCUMENT_FOLDER = env_path(
    "KG_DOCUMENT_FOLDER",
    BASE_DIR / "shale_gas_docs" / "guifan",
)
PROCESSED_RECORD = env_path(
    "KG_PROCESSED_RECORD",
    BASE_DIR / "processed_docs.json",
)
SCHEMA_PATH = env_path("KG_SCHEMA_PATH", BASE_DIR / "kg_schema.json")
SCHEMA_EXAMPLE_PATH = env_path(
    "KG_SCHEMA_EXAMPLE_PATH",
    BASE_DIR / "kg_schema.example.json",
)
DEBUG_DIR = env_path(
    "KG_TRIPLET_DEBUG_DIR",
    BASE_DIR / "shale_gas_triplets_debug",
)
ENTITY_DEBUG_DIR = env_path(
    "KG_ENTITY_DEBUG_DIR",
    BASE_DIR / "shale_gas_entity_debug",
)
VECTOR_MODEL_PATH = env_path(
    "KG_VECTOR_MODEL_PATH",
    BASE_DIR / "models" / "paraphrase-multilingual-MiniLM-L12-v2",
)

LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4/")
LLM_MODEL = os.getenv("LLM_MODEL", "glm-4.5-air")

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "")
NEO4J_DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")

EXPERT_ENTITIES = []
RETRIEVE_SENTENCE_NUM = 10
FREQ_THRESHOLD = 3
UNKNOWN_TYPE = "未分类"


def env_bool(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


MYSQL_ENABLED = env_bool("KG_MYSQL_ENABLED", False)
MILVUS_ENABLED = env_bool("KG_MILVUS_ENABLED", False)
RESPECT_LEGACY_BREAKPOINT = env_bool("KG_RESPECT_LEGACY_BREAKPOINT", False)
REUSE_ENTITY_CACHE = env_bool("KG_REUSE_ENTITY_CACHE", False)
REUSE_TRIPLET_CACHE = env_bool("KG_REUSE_TRIPLET_CACHE", False)
EXPERIMENT_RUN_NAME = os.getenv("KG_RUN_NAME", "")


def resolve_schema_path():
    if SCHEMA_PATH.exists():
        return SCHEMA_PATH
    return SCHEMA_EXAMPLE_PATH
