"""Chart rendering: matplotlib PNG (server-side, Agg backend, no display needed) plus a
small JSON spec a frontend could render natively. Swapped in for vl-convert/Plotly+kaleido
per the plan's Windows-friendliness scoping decision -- matplotlib has prebuilt wheels and
no external binary dependency.
"""
from __future__ import annotations

import base64
import io

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from app.tools.registry import tool
from app.utils import storage


def render_chart(job_id: str, chart_id: str, title: str, chart_type: str,
                  labels: list[str], series: dict[str, list[float]]) -> dict:
    fig, ax = plt.subplots(figsize=(6, 4))

    if chart_type == "pie":
        values = next(iter(series.values())) if series else []
        ax.pie(values, labels=labels, autopct="%1.1f%%")
    else:
        x = range(len(labels))
        for name, values in series.items():
            if chart_type == "line":
                ax.plot(x, values, marker="o", label=name)
            else:
                ax.bar(x, values, label=name)
        ax.set_xticks(list(x))
        ax.set_xticklabels(labels, rotation=30, ha="right")
        if len(series) > 1:
            ax.legend()

    ax.set_title(title)
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=120)
    plt.close(fig)
    png_bytes = buf.getvalue()

    # Saved to storage for anyone who wants the raw file, but the HTML/PDF report embeds
    # the base64 data URI directly -- png_uri uses our internal "file://" scheme, which
    # isn't reachable over HTTP, so a report that referenced it by URL would show a broken
    # image both in-browser and when xhtml2pdf tries to fetch it for the PDF.
    png_uri = storage.write_bytes(f"{job_id}/charts/{chart_id}.png", png_bytes)
    png_base64 = "data:image/png;base64," + base64.b64encode(png_bytes).decode("ascii")
    spec = {
        "title": title, "chart_type": chart_type, "labels": labels, "series": series,
    }
    return {"png_uri": png_uri, "png_base64": png_base64, "spec": spec}


tool("chart.render", allowed_agents=["chart_spec"])(render_chart)
