"""确定性规则处理器注册表。

处理器名称属于规则集契约；具体任务实现可以在后续模块中细分，但未经注册的
处理器绝不能在正式规则集中引用。
"""

from .handlers import HANDLERS, get_handler

REGISTERED_HANDLERS = frozenset(HANDLERS)

__all__ = ("HANDLERS", "REGISTERED_HANDLERS", "get_handler")
