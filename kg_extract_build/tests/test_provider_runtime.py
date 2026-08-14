import unittest
from types import SimpleNamespace

from kg_extract_build.audit.provider_runtime import build_structured_model
from kg_extract_build.audit.semantic_runtime import EvidencePackage


class FakeCompletions:
    def create(self, **kwargs):
        self.kwargs = kwargs
        package_id = __import__("json").loads(kwargs["messages"][1]["content"])["evidence_package_id"]
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=__import__("json").dumps({"result_status": "no_issue", "issues": [], "package_id": package_id})))])


class FakeClient:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.chat = SimpleNamespace(completions=FakeCompletions())


class SemanticRouteCompletions:
    def create(self, **kwargs):
        self.kwargs = kwargs
        prompt = __import__("json").loads(kwargs["messages"][1]["content"])
        if prompt["route"] == "semantic_compliance":
            content = {
                "result_status": "no_issue",
                "document_evidence_ids": [],
                "normative_evidence_ids": [],
                "issues": [],
            }
        else:
            content = {"issues": []}
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=__import__("json").dumps(content)))])


class SemanticRouteClient:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.chat = SimpleNamespace(completions=SemanticRouteCompletions())


class ProviderRuntimeTests(unittest.TestCase):
    def test_graph_entity_extractor_corrects_contract_and_records_responses(self):
        responses = [
            '{"items":[{"name":"地下管线","type":"施工对象"}]}',
            '{"entities":[{"name":"地下管线","type":"施工对象","evidence_block_ids":["B1"]}]}',
        ]

        class Client:
            def __init__(self, **_kwargs):
                self.chat = SimpleNamespace(completions=self)
                self.calls = 0

            def create(self, **_kwargs):
                content = responses[self.calls]
                self.calls += 1
                return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])

        client = Client()
        model = build_structured_model(
            api_key="test-key", base_url="http://localhost:8000/v1", model="test-model",
            client_factory=lambda **_kwargs: client,
        )

        result = model.graph_entity_extractor(
            SimpleNamespace(task_id="T1", name="现场准备"),
            [{"block_id": "B1", "raw_text": "动土作业前确认地下管线"}],
            ("施工对象", "作业活动"),
        )

        self.assertEqual(client.calls, 2)
        self.assertEqual(result["entities"][0]["name"], "地下管线")
        self.assertEqual(result["entities"][0]["evidence_block_ids"], ["B1"])
        interaction = model.graph_entity_extractor.last_interaction
        self.assertEqual(interaction["raw_response"], responses[0])
        self.assertEqual(interaction["correction_raw_response"], responses[1])
    def test_retrieval_plan_preserves_invalid_json_compatibility_payload(self):
        class Completions:
            def create(self, **_kwargs):
                return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
                    content='{"search_queries":["pressure test","pressure relief"]}'
                ))])

        class Client:
            def __init__(self, **_kwargs):
                self.chat = SimpleNamespace(completions=Completions())

        model = build_structured_model(api_key="key", base_url="http://localhost:8000/v1", model="audit", client_factory=Client)
        result = model.retrieval_planner(SimpleNamespace(task_id="T1", name="task"), [{"block_id": "B1"}])

        self.assertEqual(result, {"search_queries": ["pressure test", "pressure relief"]})
        self.assertIn("validation_error", model.retrieval_planner.last_interaction["parsed_response"])
    def test_structured_model_uses_selected_provider_and_package_id(self):
        client = None

        def factory(**kwargs):
            nonlocal client
            client = FakeClient(**kwargs)
            return client

        model = build_structured_model(
            api_key="key",
            base_url="https://provider.test/v1",
            model="audit-model",
            client_factory=factory,
        )
        task = SimpleNamespace(task_id="T1", name="任务", route="semantic_compliance")
        package = EvidencePackage.from_task(task, [{"block_id": "b1", "raw_text": "证据"}], "run-1")
        output = model(task, package)
        self.assertEqual(output["package_id"], package.package_id)
        self.assertEqual(client.kwargs["base_url"], "https://provider.test/v1")
        self.assertEqual(client.chat.completions.kwargs["model"], "audit-model")

    def test_online_provider_requires_key(self):
        with self.assertRaises(ValueError):
            build_structured_model(api_key="", base_url="https://provider.test/v1", model="audit-model")

    def test_structured_model_accepts_compliance_evidence_mapping(self):
        model = build_structured_model(
            api_key="key",
            base_url="https://provider.test/v1",
            model="audit-model",
            client_factory=SemanticRouteClient,
        )
        task = SimpleNamespace(task_id="C-1", name="合规", route="semantic_compliance")

        output = model(task, {
            "run_id": "run-1",
            "task_id": "C-1",
            "document_evidence": [{"block_id": "d1", "raw_text": "方案证据"}],
            "normative_evidence": [{"clause_id": "c1", "text": "规范条款"}],
        })

        self.assertEqual(output["result_status"], "no_issue")
        self.assertNotIn("package_id", output)

    def test_structured_model_accepts_reasonableness_graph_arguments(self):
        model = build_structured_model(
            api_key="key",
            base_url="https://provider.test/v1",
            model="audit-model",
            client_factory=SemanticRouteClient,
        )
        task = SimpleNamespace(task_id="R-1", name="合理性", route="semantic_reasonableness")

        output = model(task, [{"block_id": "d1", "raw_text": "方案证据"}], SimpleNamespace(clues=()), run_id="run-1")

        self.assertEqual(output, {"issues": []})

    def test_reasonableness_contract_corrects_risk_to_summary(self):
        class Completions:
            def __init__(self):
                self.calls = []

            def create(self, **kwargs):
                self.calls.append(kwargs)
                content = (
                    '{"issues":[{"risk":"unsafe sequence","evidence":["a1"]}]}'
                    if len(self.calls) == 1 else
                    '{"issues":[{"summary":"unsafe sequence","suggestion":"fix it","evidence":["a1"]}]}'
                )
                return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])

        class Client:
            def __init__(self, **_kwargs):
                self.chat = SimpleNamespace(completions=Completions())

        client = Client()
        model = build_structured_model(api_key="key", base_url="https://provider.test/v1", model="audit-model", client_factory=lambda **_kwargs: client)
        task = SimpleNamespace(task_id="R-1", name="reasonableness", route="semantic_reasonableness")

        result = model(task, [{"block_id": "d1", "raw_text": "evidence"}], SimpleNamespace(clues=()), run_id="run-1")

        self.assertEqual(result["issues"][0]["summary"], "unsafe sequence")
        self.assertEqual(len(client.chat.completions.calls), 2)
        correction = client.chat.completions.calls[1]["messages"][-1]["content"]
        self.assertIn("summary", correction)

    def test_compliance_correction_prompt_requires_controlled_conclusion_fields(self):
        client = None
        def factory(**kwargs):
            nonlocal client
            client = SemanticRouteClient(**kwargs)
            return client
        model = build_structured_model(api_key="key", base_url="https://provider.test/v1", model="audit-model", client_factory=factory)
        task = SimpleNamespace(task_id="C-1", name="合规", route="semantic_compliance")

        model(task, {"run_id": "r", "document_evidence": [], "normative_evidence": []}, correction=True)

        prompt = __import__("json").loads(client.chat.completions.kwargs["messages"][1]["content"])
        self.assertIn("issue_found", prompt["instruction"])
        self.assertIn("document_evidence_ids", prompt["instruction"])


if __name__ == "__main__":
    unittest.main()
