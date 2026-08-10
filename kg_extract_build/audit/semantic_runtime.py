"""Ports and safeguards for semantic audit execution."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from types import MappingProxyType
from typing import Any, Callable, Mapping

from .models import AuditTaskDefinition


class StructuredOutputError(ValueError):
    pass


def _freeze(value):
    if isinstance(value, dict):
        return MappingProxyType({str(k): _freeze(v) for k, v in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(v) for v in value)
    return value


@dataclass(frozen=True)
class EvidencePackage:
    package_id: str
    run_id: str
    task_id: str
    route: str
    evidence: tuple[Mapping[str, Any], ...]

    @classmethod
    def from_task(cls, task: AuditTaskDefinition, evidence, run_id: str):
        frozen = tuple(_freeze(dict(item)) for item in evidence)
        payload = {"run_id": run_id, "task_id": task.task_id, "route": task.route, "evidence": frozen}
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=list).encode()
        return cls(hashlib.sha256(encoded).hexdigest(), run_id, task.task_id, task.route, frozen)


def validate_output(value: Mapping[str, Any], package: EvidencePackage) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise StructuredOutputError("结构化模型输出必须是对象")
    if value.get("package_id") != package.package_id:
        raise StructuredOutputError("模型输出引用了错误的证据包 ID")
    status = value.get("result_status")
    if status not in {"no_issue", "issue_found", "manual_review"}:
        raise StructuredOutputError("模型输出缺少合法 result_status")
    if not isinstance(value.get("issues", []), list):
        raise StructuredOutputError("模型输出 issues 必须是列表")
    return dict(value)


class SemanticRuntime:
    def __init__(self, model: Callable[..., Mapping[str, Any]] | None = None):
        self.model = model or self._unconfigured_model

    @staticmethod
    def _unconfigured_model(*_args, **_kwargs):
        raise RuntimeError("语义审核模型未配置")

    def run(self, task: AuditTaskDefinition, evidence, run_id: str) -> TaskExecutionResult:
        from .executor import AuditIssueResult, TaskExecutionResult
        package = EvidencePackage.from_task(task, evidence, run_id)
        errors = []
        for correction in (False, True):
            try:
                output = validate_output(self.model(task, package, correction=correction), package)
                issues = tuple(AuditIssueResult(**item) for item in output.get("issues", []))
                return TaskExecutionResult(task.task_id, task.route, "completed", output["result_status"], tuple(dict(item) for item in package.evidence), issues=issues, diagnostics=(f"evidence_package_id={package.package_id}",))
            except (StructuredOutputError, RuntimeError, TypeError, KeyError, ValueError) as exc:
                errors.append(str(exc))
                if correction:
                    break
        return TaskExecutionResult(task.task_id, task.route, "failed", None, tuple(dict(item) for item in package.evidence), diagnostics=(f"结构化语义审核失败（已纠正一次）：{errors[-1]}", f"evidence_package_id={package.package_id}"))
