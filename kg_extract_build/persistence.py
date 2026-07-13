import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def content_hash(text):
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def json_text(value):
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, default=str)


def env_bool(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class BaseExperimentStore:
    def delete_run(self, run_id):
        return False

    def get_deletion_state(self, run_id):
        return None

    def mark_vectors_deleted_sql_pending(self, run_id):
        return False


class NullExperimentStore(BaseExperimentStore):
    enabled = False


    def initialize_schema(self):
        return None

    def start_run(self, run_name, config_snapshot, schema_snapshot, code_commit):
        return str(uuid.uuid4())

    def finish_run(self, run_id, status, error_message=None):
        return None

    def start_document(self, run_id, file_name, source_type, document_hash, content):
        return None

    def finish_document(self, document_id, status, error_message=None):
        return None

    def save_chunks(self, run_id, document_id, chunk_type, chunks):
        return [None for _ in chunks]

    def link_chunk_vector(self, chunk_id, milvus_id):
        return None

    def save_llm_call(self, **record):
        return None

    def save_entities(self, records):
        return None

    def save_retrieval_results(self, records):
        return None

    def save_triplets(self, records):
        return None

    def list_experiment_runs(self, limit=100):
        return []

    def load_evaluation_input(self, run_id):
        return {"documents": {}, "triplets": {}, "evidence": {}}

    def list_evaluations(self, run_id, gold_hash=None):
        return []

    def save_evaluation(self, run_id, gold_path, gold_hash, metric_config, result):
        return None

    def close(self):
        return None


class MemoryExperimentStore(NullExperimentStore):
    """Small in-memory implementation used by tests and local dry-runs."""

    enabled = True

    def __init__(self):
        self.runs = {}
        self.documents = {}
        self.chunks = []
        self.llm_calls = []
        self.entities = []
        self.retrieval_results = []
        self.triplets = []
        self.evaluation_runs = []
        self.evaluation_metrics = []
        self._document_id = 0
        self._chunk_id = 0
        self._llm_call_id = 0

    def start_run(self, run_name, config_snapshot, schema_snapshot, code_commit):
        run_id = str(uuid.uuid4())
        self.runs[run_id] = {
            "run_id": run_id,
            "run_name": run_name,
            "status": "running",
            "deletion_state": "active",
            "config_snapshot": config_snapshot,
            "schema_snapshot": schema_snapshot,
            "code_commit": code_commit,
            "started_at": utc_now(),
        }
        return run_id

    def finish_run(self, run_id, status, error_message=None):
        self.runs[run_id].update(status=status, error_message=error_message)

    def delete_run(self, run_id):
        if run_id not in self.runs:
            return False
        document_ids = {
            document_id
            for document_id, document in self.documents.items()
            if document["run_id"] == run_id
        }
        evaluation_ids = {
            evaluation["evaluation_id"]
            for evaluation in self.evaluation_runs
            if evaluation["run_id"] == run_id
        }
        self.runs.pop(run_id)
        self.documents = {
            document_id: document
            for document_id, document in self.documents.items()
            if document_id not in document_ids
        }
        self.chunks = [row for row in self.chunks if row["run_id"] != run_id]
        self.llm_calls = [row for row in self.llm_calls if row["run_id"] != run_id]
        self.entities = [row for row in self.entities if row["run_id"] != run_id]
        self.retrieval_results = [
            row for row in self.retrieval_results if row["run_id"] != run_id
        ]
        self.triplets = [row for row in self.triplets if row["run_id"] != run_id]
        self.evaluation_runs = [
            row for row in self.evaluation_runs if row["run_id"] != run_id
        ]
        self.evaluation_metrics = [
            row
            for row in self.evaluation_metrics
            if row["evaluation_id"] not in evaluation_ids
        ]
        return True

    def get_deletion_state(self, run_id):
        run = self.runs.get(run_id)
        return run and run.get("deletion_state", "active")

    def mark_vectors_deleted_sql_pending(self, run_id):
        if self.get_deletion_state(run_id) != "active":
            return False
        self.runs[run_id]["deletion_state"] = "vectors_deleted_sql_pending"
        return True

    def start_document(self, run_id, file_name, source_type, document_hash, content):
        self._document_id += 1
        self.documents[self._document_id] = {
            "document_id": self._document_id,
            "run_id": run_id,
            "file_name": file_name,
            "source_type": source_type,
            "content_hash": document_hash,
            "content": content,
            "status": "running",
        }
        return self._document_id

    def finish_document(self, document_id, status, error_message=None):
        self.documents[document_id].update(status=status, error_message=error_message)

    def save_chunks(self, run_id, document_id, chunk_type, chunks):
        ids = []
        for chunk in chunks:
            self._chunk_id += 1
            record = {
                "chunk_id": self._chunk_id,
                "run_id": run_id,
                "document_id": document_id,
                "chunk_type": chunk_type,
                **chunk,
            }
            self.chunks.append(record)
            ids.append(self._chunk_id)
        return ids

    def link_chunk_vector(self, chunk_id, milvus_id):
        for chunk in self.chunks:
            if chunk["chunk_id"] == chunk_id:
                chunk["milvus_id"] = milvus_id
                return

    def save_llm_call(self, **record):
        self._llm_call_id += 1
        record["llm_call_id"] = self._llm_call_id
        self.llm_calls.append(record)
        return self._llm_call_id

    def save_entities(self, records):
        self.entities.extend(records)

    def save_retrieval_results(self, records):
        self.retrieval_results.extend(records)

    def save_triplets(self, records):
        self.triplets.extend(records)

    def list_experiment_runs(self, limit=100):
        rows = list(self.runs.values())
        rows.sort(key=lambda row: row.get("started_at") or datetime.min, reverse=True)
        return rows[:limit]

    def load_evaluation_input(self, run_id):
        documents = {}
        document_keys = {}
        for document_id, doc in self.documents.items():
            if doc["run_id"] != run_id:
                continue
            doc_key = Path(doc["file_name"]).stem
            document_keys[document_id] = doc_key
            documents[doc_key] = {
                "document_id": document_id,
                "file_name": doc["file_name"],
                "content": doc["content"],
            }

        triplets = {}
        triplet_by_doc = {}
        for row in self.triplets:
            if row["run_id"] != run_id or row["stage"] != "final":
                continue
            doc_key = document_keys.get(row["document_id"])
            if not doc_key:
                continue
            item = (
                row["head"],
                row["head_type"],
                row["relation"],
                row["tail"],
                row["tail_type"],
            )
            triplets.setdefault(doc_key, []).append(item)
            triplet_by_doc.setdefault(doc_key, []).append(item)

        evidence = {doc_key: {} for doc_key in triplet_by_doc}
        for row in self.retrieval_results:
            if row["run_id"] != run_id:
                continue
            doc_key = document_keys.get(row["document_id"])
            if not doc_key:
                continue
            entity_name = row.get("entity_name")
            for triplet in triplet_by_doc.get(doc_key, []):
                if entity_name in {triplet[0], triplet[3]}:
                    evidence.setdefault(doc_key, {}).setdefault(triplet, []).append(
                        row.get("sentence", "")
                    )
        return {"documents": documents, "triplets": triplets, "evidence": evidence}

    def list_evaluations(self, run_id, gold_hash=None):
        rows = [row for row in self.evaluation_runs if row["run_id"] == run_id]
        if gold_hash is not None:
            rows = [row for row in rows if row["gold_hash"] == gold_hash]
        return list(rows)

    def save_evaluation(self, run_id, gold_path, gold_hash, metric_config, result):
        evaluation_id = str(uuid.uuid4())
        triplet_f1 = result.overall.get("triplet_f1")
        summary = {
            "matched_documents": result.matched_documents,
            "missing_gold_documents": result.missing_gold_documents,
            "extra_gold_documents": result.extra_gold_documents,
            "overall": {name: metric.value for name, metric in result.overall.items()},
        }
        self.evaluation_runs.append(
            {
                "evaluation_id": evaluation_id,
                "run_id": run_id,
                "gold_path": gold_path,
                "gold_hash": gold_hash,
                "metric_config_json": metric_config,
                "summary_json": summary,
                "triplet_f1": None if triplet_f1 is None else triplet_f1.value,
                "created_at": utc_now(),
            }
        )
        for name, metric in result.overall.items():
            self.evaluation_metrics.append(
                {
                    "evaluation_id": evaluation_id,
                    "scope_type": "overall",
                    "scope_name": "all",
                    "metric_name": name,
                    "metric_value": metric.value,
                    "numerator": metric.numerator,
                    "denominator": metric.denominator,
                    "details_json": metric.details,
                }
            )
        for doc_name, metrics in result.by_document.items():
            for name, metric in metrics.items():
                self.evaluation_metrics.append(
                    {
                        "evaluation_id": evaluation_id,
                        "scope_type": "document",
                        "scope_name": doc_name,
                        "metric_name": name,
                        "metric_value": metric.value,
                        "numerator": metric.numerator,
                        "denominator": metric.denominator,
                        "details_json": metric.details,
                    }
                )
        return evaluation_id


class MySQLExperimentStore(BaseExperimentStore):
    enabled = True

    def __init__(
        self,
        host,
        port,
        user,
        password,
        database,
        charset="utf8mb4",
        auto_initialize=True,
    ):
        self.connection_options = {
            "host": host,
            "port": int(port),
            "user": user,
            "password": password,
            "database": database,
            "charset": charset,
            "autocommit": False,
        }
        self.auto_initialize = auto_initialize
        self._connection_instance = None

    @classmethod
    def from_env(cls):
        return cls(
            host=os.getenv("KG_MYSQL_HOST", "127.0.0.1"),
            port=os.getenv("KG_MYSQL_PORT", "3306"),
            user=os.getenv("KG_MYSQL_USER", "root"),
            password=os.getenv("KG_MYSQL_PASSWORD", ""),
            database=os.getenv("KG_MYSQL_DATABASE", "kg_experiments"),
            charset=os.getenv("KG_MYSQL_CHARSET", "utf8mb4"),
            auto_initialize=env_bool("KG_MYSQL_AUTO_INIT", True),
        )

    def _connection(self):
        try:
            import pymysql
        except ImportError as exc:
            raise RuntimeError("启用 MySQL 存储需要安装 pymysql") from exc

        if self._connection_instance is None:
            self._connection_instance = pymysql.connect(**self.connection_options)
        else:
            self._connection_instance.ping(reconnect=True)
        return self._connection_instance

    def _write(self, sql, params=None, many=False, return_rowcount=False):
        connection = self._connection()
        try:
            with connection.cursor() as cursor:
                if many:
                    cursor.executemany(sql, params or [])
                else:
                    cursor.execute(sql, params or ())
                lastrowid = cursor.lastrowid
                rowcount = cursor.rowcount
            connection.commit()
            return rowcount if return_rowcount else lastrowid
        except Exception:
            connection.rollback()
            raise

    def _read(self, sql, params=None):
        connection = self._connection()
        with connection.cursor() as cursor:
            cursor.execute(sql, params or ())
            columns = [item[0] for item in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def initialize_schema(self):
        if not self.auto_initialize:
            return
        schema_path = Path(__file__).with_name("schema.sql")
        sql_text = schema_path.read_text(encoding="utf-8")
        connection = self._connection()
        try:
            with connection.cursor() as cursor:
                for statement in sql_text.split(";"):
                    statement = statement.strip()
                    if statement:
                        cursor.execute(statement)
                cursor.execute(
                    """
                    SELECT COUNT(*) FROM information_schema.columns
                    WHERE table_schema=DATABASE()
                      AND table_name='kg_experiment_run'
                      AND column_name='deletion_state'
                    """
                )
                if cursor.fetchone()[0] == 0:
                    cursor.execute(
                        "ALTER TABLE kg_experiment_run ADD COLUMN deletion_state "
                        "VARCHAR(32) NOT NULL DEFAULT 'active'"
                    )
            connection.commit()
        except Exception:
            connection.rollback()
            raise

    def start_run(self, run_name, config_snapshot, schema_snapshot, code_commit):
        run_id = str(uuid.uuid4())
        self._write(
            """
            INSERT INTO kg_experiment_run
                (run_id, run_name, status, code_commit, config_snapshot,
                 schema_snapshot, started_at)
            VALUES (%s, %s, 'running', %s, %s, %s, %s)
            """,
            (
                run_id,
                run_name,
                code_commit or None,
                json_text(config_snapshot),
                json_text(schema_snapshot),
                utc_now(),
            ),
        )
        return run_id

    def finish_run(self, run_id, status, error_message=None):
        self._write(
            """
            UPDATE kg_experiment_run
            SET status=%s, error_message=%s, finished_at=%s
            WHERE run_id=%s
            """,
            (status, error_message, utc_now(), run_id),
        )

    def delete_run(self, run_id):
        return self._write(
            "DELETE FROM kg_experiment_run WHERE run_id=%s",
            (run_id,),
            return_rowcount=True,
        ) > 0

    def get_deletion_state(self, run_id):
        rows = self._read(
            "SELECT deletion_state FROM kg_experiment_run WHERE run_id=%s", (run_id,)
        )
        return rows[0]["deletion_state"] if rows else None

    def mark_vectors_deleted_sql_pending(self, run_id):
        return self._write(
            """
            UPDATE kg_experiment_run
            SET deletion_state='vectors_deleted_sql_pending'
            WHERE run_id=%s AND deletion_state='active'
            """,
            (run_id,),
            return_rowcount=True,
        ) > 0

    def start_document(self, run_id, file_name, source_type, document_hash, content):
        return self._write(
            """
            INSERT INTO kg_document
                (run_id, file_name, source_type, content_hash, content,
                 status, started_at)
            VALUES (%s, %s, %s, %s, %s, 'running', %s)
            """,
            (run_id, file_name, source_type, document_hash, content, utc_now()),
        )

    def finish_document(self, document_id, status, error_message=None):
        if document_id is None:
            return
        self._write(
            """
            UPDATE kg_document
            SET status=%s, error_message=%s, finished_at=%s
            WHERE document_id=%s
            """,
            (status, error_message, utc_now(), document_id),
        )

    def save_chunks(self, run_id, document_id, chunk_type, chunks):
        ids = []
        for chunk in chunks:
            chunk_id = self._write(
                """
                INSERT INTO kg_document_chunk
                    (run_id, document_id, chunk_type, chunk_index, start_offset,
                     end_offset, content_hash, content, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    run_id,
                    document_id,
                    chunk_type,
                    int(chunk["index"]),
                    chunk.get("start_offset"),
                    chunk.get("end_offset"),
                    content_hash(chunk.get("content", "")),
                    chunk.get("content", ""),
                    utc_now(),
                ),
            )
            ids.append(chunk_id)
        return ids

    def link_chunk_vector(self, chunk_id, milvus_id):
        if chunk_id is None:
            return
        self._write(
            "UPDATE kg_document_chunk SET milvus_id=%s WHERE chunk_id=%s",
            (milvus_id, chunk_id),
        )

    def save_llm_call(self, **record):
        return self._write(
            """
            INSERT INTO kg_llm_call
                (run_id, document_id, chunk_id, stage, entity_name, model_name,
                 prompt, raw_response, parsed_result, metadata_json, latency_ms,
                 success, error_message, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                record["run_id"],
                record.get("document_id"),
                record.get("chunk_id"),
                record["stage"],
                record.get("entity_name"),
                record.get("model_name", ""),
                record.get("prompt", ""),
                record.get("raw_response"),
                json_text(record.get("parsed_result")),
                json_text(record.get("metadata")),
                record.get("latency_ms"),
                1 if record.get("success", True) else 0,
                record.get("error_message"),
                utc_now(),
            ),
        )

    def save_entities(self, records):
        if not records:
            return
        sql = """
            INSERT INTO kg_entity
                (run_id, document_id, stage, entity_name, entity_type,
                 standard_name, aliases, source_type, metadata_json, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        params = [
            (
                item["run_id"],
                item["document_id"],
                item["stage"],
                item["entity_name"],
                item["entity_type"],
                item.get("standard_name"),
                json_text(item.get("aliases")),
                item.get("source_type"),
                json_text(item.get("metadata")),
                utc_now(),
            )
            for item in records
        ]
        self._write(sql, params, many=True)

    def save_retrieval_results(self, records):
        if not records:
            return
        sql = """
            INSERT INTO kg_retrieval_result
                (run_id, document_id, entity_name, query_alias, chunk_id,
                 sentence, similarity_score, hit_rank, match_type, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        params = [
            (
                item["run_id"],
                item["document_id"],
                item["entity_name"],
                item["query_alias"],
                item.get("chunk_id"),
                item["sentence"],
                item.get("similarity_score"),
                item["hit_rank"],
                item["match_type"],
                utc_now(),
            )
            for item in records
        ]
        self._write(sql, params, many=True)

    def save_triplets(self, records):
        if not records:
            return
        sql = """
            INSERT INTO kg_triplet
                (run_id, document_id, source_llm_call_id, stage, source_kind,
                 entity_name, head, head_type, relation_name, tail, tail_type,
                 is_valid, validation_reason, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        params = [
            (
                item["run_id"],
                item["document_id"],
                item.get("source_llm_call_id"),
                item["stage"],
                item.get("source_kind", "model"),
                item.get("entity_name"),
                item["head"],
                item["head_type"],
                item["relation"],
                item["tail"],
                item["tail_type"],
                1 if item.get("is_valid", True) else 0,
                item.get("validation_reason"),
                utc_now(),
            )
            for item in records
        ]
        self._write(sql, params, many=True)

    def list_experiment_runs(self, limit=100):
        return self._read(
            """
            SELECT run_id, run_name, status, started_at, finished_at,
                   config_snapshot
            FROM kg_experiment_run
            ORDER BY started_at DESC
            LIMIT %s
            """,
            (int(limit),),
        )

    def load_evaluation_input(self, run_id):
        documents_raw = self._read(
            """
            SELECT document_id, file_name, content
            FROM kg_document
            WHERE run_id=%s
            """,
            (run_id,),
        )
        documents = {}
        document_keys = {}
        for doc in documents_raw:
            doc_key = Path(doc["file_name"]).stem
            document_keys[doc["document_id"]] = doc_key
            documents[doc_key] = {
                "document_id": doc["document_id"],
                "file_name": doc["file_name"],
                "content": doc["content"],
            }

        triplet_rows = self._read(
            """
            SELECT document_id, head, head_type, relation_name, tail, tail_type
            FROM kg_triplet
            WHERE run_id=%s AND stage='final'
            """,
            (run_id,),
        )
        triplets = {}
        triplet_by_doc = {}
        for row in triplet_rows:
            doc_key = document_keys.get(row["document_id"])
            if not doc_key:
                continue
            item = (
                row["head"],
                row["head_type"],
                row["relation_name"],
                row["tail"],
                row["tail_type"],
            )
            triplets.setdefault(doc_key, []).append(item)
            triplet_by_doc.setdefault(doc_key, []).append(item)

        retrieval_rows = self._read(
            """
            SELECT document_id, entity_name, sentence
            FROM kg_retrieval_result
            WHERE run_id=%s
            """,
            (run_id,),
        )
        evidence = {doc_key: {} for doc_key in triplet_by_doc}
        for row in retrieval_rows:
            doc_key = document_keys.get(row["document_id"])
            if not doc_key:
                continue
            entity_name = row.get("entity_name")
            for triplet in triplet_by_doc.get(doc_key, []):
                if entity_name in {triplet[0], triplet[3]}:
                    evidence.setdefault(doc_key, {}).setdefault(triplet, []).append(
                        row.get("sentence", "")
                    )
        return {"documents": documents, "triplets": triplets, "evidence": evidence}

    def list_evaluations(self, run_id, gold_hash=None):
        params = [run_id]
        where = "WHERE run_id=%s"
        if gold_hash is not None:
            where += " AND gold_hash=%s"
            params.append(gold_hash)
        rows = self._read(
            f"""
            SELECT evaluation_id, run_id, gold_path, gold_hash,
                   metric_config_json, summary_json, created_at
            FROM kg_evaluation_run
            {where}
            ORDER BY created_at DESC
            """,
            tuple(params),
        )
        for row in rows:
            summary = row.get("summary_json") or {}
            if isinstance(summary, str):
                try:
                    summary = json.loads(summary)
                except json.JSONDecodeError:
                    summary = {}
            row["triplet_f1"] = (summary.get("overall") or {}).get("triplet_f1")
        return rows

    def save_evaluation(self, run_id, gold_path, gold_hash, metric_config, result):
        evaluation_id = str(uuid.uuid4())
        summary = {
            "matched_documents": result.matched_documents,
            "missing_gold_documents": result.missing_gold_documents,
            "extra_gold_documents": result.extra_gold_documents,
            "overall": {name: metric.value for name, metric in result.overall.items()},
        }
        self._write(
            """
            INSERT INTO kg_evaluation_run
                (evaluation_id, run_id, gold_path, gold_hash,
                 metric_config_json, summary_json, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                evaluation_id,
                run_id,
                gold_path,
                gold_hash,
                json_text(metric_config),
                json_text(summary),
                utc_now(),
            ),
        )
        rows = []
        for name, metric in result.overall.items():
            rows.append(
                (
                    evaluation_id,
                    "overall",
                    "all",
                    name,
                    metric.value,
                    metric.numerator,
                    metric.denominator,
                    json_text(metric.details),
                    utc_now(),
                )
            )
        for doc_name, metrics in result.by_document.items():
            for name, metric in metrics.items():
                rows.append(
                    (
                        evaluation_id,
                        "document",
                        doc_name,
                        name,
                        metric.value,
                        metric.numerator,
                        metric.denominator,
                        json_text(metric.details),
                        utc_now(),
                    )
                )
        if rows:
            self._write(
                """
                INSERT INTO kg_evaluation_metric
                    (evaluation_id, scope_type, scope_name, metric_name,
                     metric_value, numerator, denominator, details_json,
                     created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                rows,
                many=True,
            )
        return evaluation_id

    def close(self):
        if self._connection_instance is not None:
            self._connection_instance.close()
            self._connection_instance = None


class ExperimentRecorder:
    def __init__(
        self,
        store,
        vector_store,
        run_id,
        document_id,
        model_name="",
        event_callback=None,
    ):
        self.store = store
        self.vector_store = vector_store
        self.run_id = run_id
        self.document_id = document_id
        self.model_name = model_name
        self.event_callback = event_callback
        self._chunk_ids = {}

    def record_chunks(self, chunk_type, chunks, embeddings=None):
        normalized = []
        for index, chunk in enumerate(chunks):
            if isinstance(chunk, str):
                normalized.append({"index": index, "content": chunk})
            else:
                item = dict(chunk)
                item.setdefault("index", index)
                normalized.append(item)

        ids = self.store.save_chunks(
            self.run_id,
            self.document_id,
            chunk_type,
            normalized,
        )
        for item, chunk_id in zip(normalized, ids):
            self._chunk_ids[(chunk_type, int(item["index"]))] = chunk_id

        if (
            embeddings is not None
            and ids
            and any(chunk_id is not None for chunk_id in ids)
            and getattr(self.vector_store, "enabled", False)
        ):
            vector_records = []
            vector_values = []
            for item, chunk_id, embedding in zip(normalized, ids, embeddings):
                if chunk_id is None:
                    continue
                vector_records.append(
                    {
                        "chunk_id": chunk_id,
                        "run_id": self.run_id,
                        "document_id": self.document_id,
                        "segment_type": chunk_type,
                        "text_hash": content_hash(item.get("content", "")),
                    }
                )
                vector_values.append(embedding)
            self.vector_store.upsert_segments(vector_records, vector_values)
            for record in vector_records:
                self.store.link_chunk_vector(record["chunk_id"], record["chunk_id"])
        return ids

    def chunk_id(self, chunk_type, chunk_index):
        return self._chunk_ids.get((chunk_type, int(chunk_index)))

    def record_llm_call(
        self,
        stage,
        prompt,
        raw_response="",
        parsed=None,
        latency_ms=None,
        success=True,
        error_message=None,
        entity_name=None,
        metadata=None,
    ):
        metadata = dict(metadata or {})
        chunk_id = None
        if "chunk_type" in metadata and "chunk_index" in metadata:
            chunk_id = self.chunk_id(metadata["chunk_type"], metadata["chunk_index"])
        call_id = self.store.save_llm_call(
            run_id=self.run_id,
            document_id=self.document_id,
            chunk_id=chunk_id,
            stage=stage,
            entity_name=entity_name,
            model_name=self.model_name,
            prompt=prompt,
            raw_response=raw_response,
            parsed_result=parsed,
            metadata=metadata,
            latency_ms=latency_ms,
            success=success,
            error_message=error_message,
        )
        if self.event_callback is not None:
            self.event_callback({"stage": stage, "success": success})
        return call_id

    def record_entities(self, stage, entities):
        records = []
        for entity in entities:
            records.append(
                {
                    "run_id": self.run_id,
                    "document_id": self.document_id,
                    "stage": stage,
                    "entity_name": entity.get("name", ""),
                    "entity_type": entity.get("type") or "未分类",
                    "standard_name": entity.get("name") if stage == "aligned" else None,
                    "aliases": entity.get("aliases"),
                    "source_type": entity.get("source_type"),
                    "metadata": {
                        key: value
                        for key, value in entity.items()
                        if key not in {"name", "type", "aliases", "source_type"}
                    },
                }
            )
        self.store.save_entities(records)

    def record_retrieval(self, entity_name, query_alias, hits):
        records = []
        for rank, hit in enumerate(hits, start=1):
            records.append(
                {
                    "run_id": self.run_id,
                    "document_id": self.document_id,
                    "entity_name": entity_name,
                    "query_alias": query_alias,
                    "chunk_id": self.chunk_id(
                        "retrieval_sentence",
                        hit.get("sentence_index", -1),
                    ),
                    "sentence": hit.get("sentence", ""),
                    "similarity_score": hit.get("score"),
                    "hit_rank": rank,
                    "match_type": hit.get("match_type", "semantic"),
                }
            )
        self.store.save_retrieval_results(records)

    def record_triplets(
        self,
        stage,
        triplets,
        entity_name=None,
        source_kind="model",
        source_llm_call_id=None,
    ):
        records = []
        for triplet in triplets:
            if isinstance(triplet, dict):
                item = triplet
            else:
                head, head_type, relation, tail, tail_type = triplet
                item = {
                    "head": head,
                    "head_type": head_type,
                    "relation": relation,
                    "tail": tail,
                    "tail_type": tail_type,
                }
            records.append(
                {
                    "run_id": self.run_id,
                    "document_id": self.document_id,
                    "source_llm_call_id": source_llm_call_id,
                    "stage": stage,
                    "source_kind": source_kind,
                    "entity_name": entity_name,
                    "head": item.get("head", ""),
                    "head_type": item.get("head_type") or "未分类",
                    "relation": item.get("relation", ""),
                    "tail": item.get("tail", ""),
                    "tail_type": item.get("tail_type") or "未分类",
                    "is_valid": stage == "final" or item.get("is_valid", True),
                    "validation_reason": item.get("validation_reason"),
                }
            )
        self.store.save_triplets(records)


def build_experiment_store():
    if not env_bool("KG_MYSQL_ENABLED", False):
        return NullExperimentStore()
    store = MySQLExperimentStore.from_env()
    store.initialize_schema()
    return store


