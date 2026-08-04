"""确定性规则处理器的正式注册表。

规则集只允许引用本模块登记的处理器。执行器从规则集取得处理器名后再路由，
因此不能通过修改任务库把未登记的实现带入正式审核。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RuleHandler:
    name: str
    description: str


HANDLERS = {
    item.name: item for item in (
        RuleHandler("directory", "目录覆盖检查"),
        RuleHandler("fields", "字段存在性与占位值检查"),
        RuleHandler("dates", "日期可解析性与时序检查"),
        RuleHandler("tables", "业务表头、业务行与必填值检查"),
        RuleHandler("cross_section", "跨章节字段一致性检查"),
        RuleHandler("appendices", "附录固定字段检查"),
        RuleHandler("organization", "组织与职责检查"),
        RuleHandler("qualification", "资格证明可读性检查"),
        RuleHandler("equipment", "设备台账检查"),
        RuleHandler("control_table", "风险控制表检查"),
        RuleHandler("risk_catalog", "风险作业目录编号检查"),
        RuleHandler("jsa_adapter", "JSA 只读适配器"),
    )
}


def get_handler(name: str) -> RuleHandler:
    try:
        return HANDLERS[name]
    except KeyError as exc:
        raise ValueError(f"未注册的确定性规则处理器：{name}") from exc
