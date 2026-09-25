"""Importing this package registers every tool with the global ToolRegistry (registry.py's
`tool()` decorator runs at module-import time). Agents look tools up by string name via
`self.call_tool(...)`, not by importing the function directly, so each tool module MUST be
imported somewhere for its registration to take effect -- this is that somewhere. Any new
tool module needs an import line added here, or it will silently never register (raising
"Unknown tool: ..." the first time an agent calls it, not at import time).
"""
from app.tools import (  # noqa: F401
    chart_render,
    report_render,
    sandbox,
    sql_tool,
    table_detect,
    vector_search,
    web_search,
)
from app.tools.calc import health_score, metrics  # noqa: F401
from app.tools.ml import anomaly, forecast, risk  # noqa: F401
from app.tools.parsers import csv_tool, excel, fingerprint, ocr, pdf  # noqa: F401
