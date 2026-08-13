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
