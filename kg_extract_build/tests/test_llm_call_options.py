import json
import tempfile
import unittest
from pathlib import Path

from kg_extract_build.entity_aligner import EntityAligner
from kg_extract_build.extractor import LongDocLLMEntityExtractor
from kg_extract_build.triplets import TripletGenerator


class RecordingCompletions:
    def __init__(self, content):
        self.content = content
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        message = type("Message", (), {"content": self.content})()
        choice = type("Choice", (), {"message": message})()
        return type("Response", (), {"choices": [choice]})()


class Schema:
    schema_path = Path("schema.json")
    entity_types = {}
    relation_types = {}

    def normalize_entity_type(self, value):
        return value

    def render_entity_schema(self):
        return "设施"

    def render_allowed_relation_schema(self, head_type):
        return "- 安装于 -> 设施"

    def render_allowed_tail_types(self, head_type):
        return "设施, 未分类"

    def normalize_relation(self, relation):
        return relation

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


class LLMCallOptionsTests(unittest.TestCase):
    def test_extractor_includes_thinking_options(self):
        completions = RecordingCompletions(
            json.dumps(
                [{"name": "井口", "type": "设施"}],
                ensure_ascii=False,
            )
        )
        extractor = LongDocLLMEntityExtractor(
            expert_entities=[],
            api_key="sk-test",
            base_url="https://api.deepseek.com",
            model_name="deepseek-chat",
            schema=Schema(),
            max_chunk_size=2000,
            provider_id="deepseek",
            enable_thinking=False,
        )
        extractor.client = type(
            "Client",
            (),
            {"chat": type("Chat", (), {"completions": completions})()},
        )()
        extractor._extract_from_chunk("井口装置是页岩气开采的关键设备。")
        self.assertEqual(
            completions.calls[0]["extra_body"],
            {"thinking": {"type": "disabled"}},
        )

    def test_aligner_includes_thinking_options(self):
        completions = RecordingCompletions(
            json.dumps(
                {
                    "same_groups": [
                        {
                            "members": ["井口", "井口装置"],
                            "standard_name": "井口装置",
                        }
                    ],
                    "different": [],
                },
                ensure_ascii=False,
            )
        )
        aligner = EntityAligner(
            api_key="sk-test",
            base_url="https://api.deepseek.com",
            model_name="deepseek-chat",
            provider_id="deepseek",
            enable_thinking=False,
        )
        aligner.client = type(
            "Client",
            (),
            {"chat": type("Chat", (), {"completions": completions})()},
        )()
        aligner._judge_group(
            [
                {"name": "井口", "type": "设施"},
                {"name": "井口装置", "type": "设施"},
            ]
        )
        self.assertEqual(
            completions.calls[0]["extra_body"],
            {"thinking": {"type": "disabled"}},
        )

    def test_single_entity_triplet_includes_thinking_options(self):
        completions = RecordingCompletions(
            json.dumps(
                [
                    {
                        "head": "井口",
                        "head_type": "设施",
                        "relation": "安装于",
                        "tail": "井场",
                        "tail_type": "设施",
                    }
                ],
                ensure_ascii=False,
            )
        )
        with tempfile.TemporaryDirectory() as tmp:
            generator = TripletGenerator(
                api_key="sk-test",
                base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                model_name="qwen-plus",
                doc_name="test.md",
                debug_dir=Path(tmp),
                schema=Schema(),
                known_entities={
                    "井口": {"name": "井口", "type": "设施"},
                    "井场": {"name": "井场", "type": "设施"},
                },
                recorder=Recorder(),
                provider_id="qwen",
                enable_thinking=False,
            )
            generator.client = type(
                "Client",
                (),
                {"chat": type("Chat", (), {"completions": completions})()},
            )()
            generator.generate(
                {"name": "井口", "type": "设施"},
                "井口安装于井场。",
            )
        self.assertEqual(
            completions.calls[0]["extra_body"],
            {"enable_thinking": False},
        )

    def test_batch_triplet_includes_thinking_options(self):
        completions = RecordingCompletions(
            json.dumps(
                [
                    {
                        "head": "井口",
                        "head_type": "设施",
                        "relation": "安装于",
                        "tail": "井场",
                        "tail_type": "设施",
                    }
                ],
                ensure_ascii=False,
            )
        )
        with tempfile.TemporaryDirectory() as tmp:
            generator = TripletGenerator(
                api_key="sk-test",
                base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                model_name="qwen-plus",
                doc_name="test.md",
                debug_dir=Path(tmp),
                schema=Schema(),
                known_entities={
                    "井口": {"name": "井口", "type": "设施"},
                    "井场": {"name": "井场", "type": "设施"},
                },
                recorder=Recorder(),
                provider_id="qwen",
                enable_thinking=False,
            )
            generator.client = type(
                "Client",
                (),
                {"chat": type("Chat", (), {"completions": completions})()},
            )()
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
        self.assertEqual(
            completions.calls[0]["extra_body"],
            {"enable_thinking": False},
        )


if __name__ == "__main__":
    unittest.main()
