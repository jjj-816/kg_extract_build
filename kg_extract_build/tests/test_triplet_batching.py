import json
import tempfile
import unittest
from pathlib import Path

from kg_extract_build.llm_thinking import build_thinking_options
from kg_extract_build.triplets import TripletGenerator


class Schema:
    def render_allowed_relation_schema(self, head_type):
        return "- 安装于 -> 设施"

    def render_allowed_tail_types(self, head_type):
        return "设施, 未分类"

    def normalize_relation(self, relation):
        return relation

    def normalize_entity_type(self, entity_type):
        return entity_type

    def is_relation_allowed(self, relation, head_type=None, tail_type=None):
        return relation == "安装于"


class Recorder:
    def __init__(self):
        self.llm_calls = []
        self.triplet_calls = []

    def record_llm_call(self, **kwargs):
        self.llm_calls.append(kwargs)
        return 77

    def record_triplets(self, *args, **kwargs):
        self.triplet_calls.append((args, kwargs))


class Completions:
    def __init__(self, content=None, error=None):
        self.content = content
        self.error = error
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        message = type("Message", (), {"content": self.content})()
        choice = type("Choice", (), {"message": message})()
        return type("Response", (), {"choices": [choice]})()


def make_generator(tmp, completions):
    generator = TripletGenerator.__new__(TripletGenerator)
    generator.client = type(
        "Client",
        (),
        {"chat": type("Chat", (), {"completions": completions})()},
    )()
    generator.model = "model"
    generator.schema = Schema()
    generator.known_entities = {
        "井口": {"name": "井口", "type": "设施"},
        "防喷器": {"name": "防喷器", "type": "设施"},
        "井场": {"name": "井场", "type": "设施"},
    }
    generator.recorder = Recorder()
    generator.debug_dir = Path(tmp)
    generator._secret_values = ("top-secret",)
    generator._thinking_options = build_thinking_options(
        "qwen",
        False,
    )
    return generator


class TripletBatchingTests(unittest.TestCase):
    def test_generate_batch_uses_one_request_and_splits_results_by_entity(self):
        response = json.dumps(
            [
                {
                    "head": "井口",
                    "head_type": "设施",
                    "relation": "安装于",
                    "tail": "井场",
                    "tail_type": "设施",
                },
                {
                    "head": "防喷器",
                    "head_type": "设施",
                    "relation": "安装于",
                    "tail": "井口",
                    "tail_type": "设施",
                },
            ],
            ensure_ascii=False,
        )
        completions = Completions(response)
        with tempfile.TemporaryDirectory() as tmp:
            generator = make_generator(tmp, completions)
            result = generator.generate_batch(
                entities=[
                    {"name": "井口", "type": "设施"},
                    {"name": "防喷器", "type": "设施"},
                ],
                evidence=[
                    {
                        "sentence_index": 1,
                        "sentence": "井口安装于井场，防喷器安装于井口。",
                    },
                    {
                        "sentence_index": 2,
                        "sentence": "防喷器需要定期检查。",
                    },
                ],
                entity_evidence_ids={
                    "井口": (1,),
                    "防喷器": (1, 2),
                },
                batch_metadata={"strategy": "shared_context_batch"},
            )

            prompt = completions.calls[0]["messages"][0]["content"]
            self.assertEqual(prompt.count("[S1]"), 1)
            self.assertEqual(prompt.count("[S2]"), 1)
            self.assertEqual(len(completions.calls), 1)
            self.assertEqual(result["井口"][0]["tail"], "井场")
            self.assertEqual(result["防喷器"][0]["tail"], "井口")
            self.assertEqual(len(generator.recorder.llm_calls), 1)
            self.assertEqual(
                {
                    kwargs["source_llm_call_id"]
                    for _, kwargs in generator.recorder.triplet_calls
                },
                {77},
            )
            self.assertTrue((Path(tmp) / "井口.json").exists())
            self.assertTrue((Path(tmp) / "防喷器.json").exists())

    def test_generate_batch_raises_after_recording_redacted_failure(self):
        completions = Completions(
            error=RuntimeError("Authorization: Bearer top-secret")
        )
        with tempfile.TemporaryDirectory() as tmp:
            generator = make_generator(tmp, completions)
            with self.assertRaisesRegex(RuntimeError, "批量三元组抽取失败"):
                generator.generate_batch(
                    entities=[{"name": "井口", "type": "设施"}],
                    evidence=[
                        {
                            "sentence_index": 1,
                            "sentence": "井口安装于井场。",
                        }
                    ],
                    entity_evidence_ids={"井口": (1,)},
                )

        call = generator.recorder.llm_calls[0]
        self.assertFalse(call["success"])
        self.assertNotIn("top-secret", call["error_message"])


if __name__ == "__main__":
    unittest.main()
