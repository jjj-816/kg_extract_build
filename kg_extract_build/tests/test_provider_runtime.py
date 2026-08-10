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


if __name__ == "__main__":
    unittest.main()
