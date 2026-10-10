"""Deterministic chat intent: does a message ask FinSight to recompute something (re-run an
agent), or ask a question about results that already exist?

This runs before any LLM routing. Treating every chat message as a possible re-run meant a
plain question like "Why did EBITDA margin change?" re-ran the ratio module and replied
with its run summary instead of an answer. Re-running is side-effecting and slow, so it
requires an explicit recompute/scenario phrase; everything else is a question, answered
from verified figures by the QA agent.
"""
from __future__ import annotations

import re

_ACTION = re.compile(
    r"\b(re-?do|re-?run|re-?compute|re-?calculate|re-?generate|re-?build|re-?draw|re-?write|re-?score|"
    r"refresh|update the (report|chart|charts|analysis|forecast|risk)|"
    r"exclud(e|ing)|without the|leave out|ignore the|treat .{1,60} as|normali[sz]e|"
    r"assum(e|ing)|what if|scenario|sensitivity|stress[- ]test|adjust(ing)? for)\b"
    # Imperative requests to produce an artifact: "make the report", "create a chart of margins".
    r"|^\s*(please\s+)?(can you\s+|could you\s+)?(make|create|generate|produce|prepare|build|draft|write|draw|"
    r"give me|do)\b.{0,40}\b(report|memo|chart|charts|graph|forecast|projection|analysis|summary|insights?)\b",
    re.IGNORECASE,
)

# Keyword hints for which agent a recompute request concerns. Used by the offline mock and
# as a tie-breaker hint; a real model makes the final call via prompts.ASSISTANT_ROUTER.
AGENT_HINTS: list[tuple[str, tuple[str, ...]]] = [
    ("report_writer", ("report", "write-up", "narrative", "summary")),
    ("chart_spec", ("chart", "graph", "visual", "plot")),
    ("forecast", ("forecast", "projection", "project", "next year", "what if", "scenario", "sensitivity")),
    ("risk", ("risk", "anomal", "red flag", "stress")),
    ("gst", ("gst", "gstr", "input tax", "itc")),
    ("cash_wc", ("cash", "working capital", "receivable", "payable", "inventory", "dso", "dio", "dpo",
                 "bank", "collection")),
    ("ratio", ("ratio", "margin", "ebitda", "liquidity", "leverage", "debt", "coverage", "return on",
               "roe", "roce", "growth", "profit")),
    ("insight_reasoner", ("insight", "conclusion", "takeaway")),
]


def is_action_request(message: str) -> bool:
    return bool(_ACTION.search(message or ""))


_CHART_INTENT = re.compile(
    r"\b(chart|plot|graph|visualiz|draw a chart|show a chart|create a chart|make a chart|bar chart|line chart|scatter|pie chart)\b",
    re.IGNORECASE,
)


def is_chart_request(message: str) -> bool:
    return bool(_CHART_INTENT.search(message or ""))


def hinted_agent(message: str, available: list[str]) -> str | None:
    low = (message or "").lower()
    for agent, words in AGENT_HINTS:
        if agent in available and any(w in low for w in words):
            return agent
    return None
