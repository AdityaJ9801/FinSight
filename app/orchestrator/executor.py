"""Dependency-aware task executor for a stage's agent fan-out.

Each node is a callable plus the names of the nodes it depends on. Every node whose
dependencies have finished is started immediately on a thread pool, so independent agents
overlap while ordered ones (e.g. chart_spec -> report_writer) are sequenced -- replacing the
hand-written submit/result choreography each supervisor used to carry.

A node that raises doesn't take the stage down: its exception is captured as its result
(NodeFailure), and dependents still run and can inspect it -- matching the pipeline's
"degrade gracefully" rule (a chart failure must not sink the report). Each callable is run
inside its own Flask app context when `app` is given, since SQLAlchemy sessions aren't safe
to share across threads.
"""
from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class Node:
    name: str
    func: Callable[[dict[str, Any]], Any]  # receives {dep_name: dep_result}
    depends_on: tuple[str, ...] = field(default_factory=tuple)


@dataclass
class NodeFailure:
    name: str
    error: BaseException

    def __str__(self) -> str:
        return f"{self.name} failed: {self.error}"


class CycleError(ValueError):
    pass


def _validate(nodes: list[Node]) -> None:
    names = {n.name for n in nodes}
    if len(names) != len(nodes):
        raise ValueError("duplicate node names in DAG")
    for n in nodes:
        missing = set(n.depends_on) - names
        if missing:
            raise ValueError(f"node '{n.name}' depends on unknown node(s): {sorted(missing)}")
    # Kahn's algorithm purely as a cycle check -- execution order is decided dynamically.
    indegree = {n.name: len(n.depends_on) for n in nodes}
    children: dict[str, list[str]] = {n.name: [] for n in nodes}
    for n in nodes:
        for d in n.depends_on:
            children[d].append(n.name)
    ready = [k for k, v in indegree.items() if v == 0]
    seen = 0
    while ready:
        cur = ready.pop()
        seen += 1
        for c in children[cur]:
            indegree[c] -= 1
            if indegree[c] == 0:
                ready.append(c)
    if seen != len(nodes):
        raise CycleError("dependency cycle in DAG")


def run_dag(nodes: list[Node], app=None, max_workers: int = 4,
            on_complete: Callable[[str, Any], None] | None = None) -> dict[str, Any]:
    """Runs every node once, respecting dependencies. Returns {name: result | NodeFailure}.
    on_complete(name, result) is called from the coordinating thread as each node finishes
    (used by supervisors to advance job progress)."""
    _validate(nodes)
    by_name = {n.name: n for n in nodes}
    results: dict[str, Any] = {}
    pending = dict(by_name)
    running: dict[Future, str] = {}

    def invoke(node: Node, dep_results: dict[str, Any]):
        if app is None:
            return node.func(dep_results)
        with app.app_context():
            return node.func(dep_results)

    with ThreadPoolExecutor(max_workers=max(1, max_workers)) as pool:
        while pending or running:
            for name in [n for n, node in pending.items() if all(d in results for d in node.depends_on)]:
                node = pending.pop(name)
                deps = {d: results[d] for d in node.depends_on}
                running[pool.submit(invoke, node, deps)] = name
            if not running:  # unreachable after _validate, but never spin forever
                break
            done, _ = wait(list(running), return_when=FIRST_COMPLETED)
            for fut in done:
                name = running.pop(fut)
                try:
                    results[name] = fut.result()
                except Exception as exc:  # noqa: BLE001 -- captured, surfaced to dependents
                    results[name] = NodeFailure(name, exc)
                if on_complete:
                    on_complete(name, results[name])
    return results
