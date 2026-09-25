"""Tool registry: every deterministic tool is registered with a name, side-effect flag,
and the list of agents allowed to call it (design doc §6.3). Agents never call tool
functions directly -- they go through ToolRegistry.invoke, which enforces the allowlist.
This is the one place that would need to change to add auth/quota/tracing around tool use.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Literal


@dataclass
class ToolSpec:
    name: str
    func: Callable
    side_effects: Literal["none", "writes_artifact", "writes_db"] = "none"
    allowed_agents: list[str] = field(default_factory=list)  # empty list = allowed for all
    timeout_s: int = 60


class ToolError(Exception):
    pass


class ToolNotAllowedError(ToolError):
    pass


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec:
        if name not in self._tools:
            raise ToolError(f"Unknown tool: {name}")
        return self._tools[name]

    def invoke(self, agent_name: str, tool_name: str, **kwargs):
        spec = self.get(tool_name)
        if spec.allowed_agents and agent_name not in spec.allowed_agents:
            raise ToolNotAllowedError(f"Agent '{agent_name}' is not allowed to call tool '{tool_name}'")
        started = time.monotonic()
        result = spec.func(**kwargs)
        elapsed = time.monotonic() - started
        return result, elapsed


registry = ToolRegistry()


def tool(name: str, side_effects: str = "none", allowed_agents: list[str] | None = None, timeout_s: int = 60):
    """Decorator: registers a plain function as a tool. Keeps registration next to the
    implementation instead of a separate wiring file that drifts out of sync."""

    def decorator(func: Callable) -> Callable:
        registry.register(ToolSpec(
            name=name, func=func, side_effects=side_effects,
            allowed_agents=allowed_agents or [], timeout_s=timeout_s,
        ))
        return func

    return decorator
