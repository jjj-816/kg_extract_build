import threading
import unittest

from kg_extract_build.runtime import (
    CancellationToken,
    PipelineCancelled,
    PipelineEvent,
    PipelineRunRegistry,
    reduce_events,
)


class RuntimeTests(unittest.TestCase):
    def test_cancel_token_raises_pipeline_cancelled(self):
        token = CancellationToken()
        token.cancel()
        with self.assertRaises(PipelineCancelled):
            token.raise_if_cancelled()

    def test_reducer_accumulates_metrics_and_latest_stage(self):
        state = reduce_events(
            {},
            [
                PipelineEvent(
                    "document_started", "document", "开始", document_name="a.md"
                ),
                PipelineEvent(
                    "chunks_created",
                    "chunking",
                    "切片完成",
                    metrics={"chunks": 3},
                ),
                PipelineEvent(
                    "chunks_created",
                    "chunking",
                    "继续切片",
                    metrics={"chunks": 2},
                ),
                PipelineEvent(
                    "document_completed",
                    "document",
                    "完成",
                    completed=1,
                    total=2,
                ),
            ],
        )
        self.assertEqual(state["stage"], "document")
        self.assertEqual(state["document_name"], "a.md")
        self.assertEqual(state["metrics"]["chunks"], 5)
        self.assertEqual(
            (state["document_completed"], state["document_total"]),
            (1, 2),
        )
        self.assertEqual(state["seen_stages"], ["document", "chunking"])

    def test_registry_rejects_second_active_run_and_can_cancel(self):
        entered = threading.Event()
        release = threading.Event()

        def runner(config, emit, token):
            entered.set()
            release.wait(timeout=2)
            token.raise_if_cancelled()

        registry = PipelineRunRegistry(runner)
        registry.start(object())
        self.assertTrue(entered.wait(timeout=1))
        with self.assertRaisesRegex(RuntimeError, "正在运行"):
            registry.start(object())
        registry.request_cancel()
        release.set()
        registry.join(timeout=2)
        self.assertFalse(registry.is_running)
        self.assertEqual(registry.snapshot()["running"], False)


if __name__ == "__main__":
    unittest.main()
