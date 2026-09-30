"""Chart rendering: matplotlib PNG (Agg backend, no display) plus the JSON spec the frontend
and Q&A agent read. Swapped in for vl-convert/Plotly+kaleido per the plan's
Windows-friendliness decision -- matplotlib has prebuilt wheels and no external binary.

The renderer is unit-aware so every chart reads like a finance chart rather than a raw plot:
- values are formatted by unit on axes and data labels: % (0.417 -> 41.7%), x (1.82x),
  days (67 d), INR in Indian scale (Rs 1.2 Cr / Rs 45.0 L);
- series of different scales go on separate panels or a secondary axis, never one axis;
- benchmark/threshold lines, forecast uncertainty bands and a one-line takeaway subtitle
  give each chart its "so what".

Chart types: line, bar (grouped), stacked_bar (handles negatives), stacked_bar_100, hbar,
waterfall, band_line (actual + forecast with a shaded range), and `panels` (small multiples,
each panel its own type/unit/reference lines). Any chart can add a secondary-axis line.
"""
from __future__ import annotations

import base64
import io
import math
import textwrap

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import FuncFormatter, MaxNLocator  # noqa: E402

from app.tools.registry import tool  # noqa: E402
from app.utils import storage  # noqa: E402
from app.utils.money import format_money, thread_scale  # noqa: E402

PALETTE = ["#2563eb", "#16a34a", "#f59e0b", "#dc2626", "#7c3aed", "#0891b2", "#db2777", "#64748b",
           "#65a30d", "#ea580c", "#0f766e", "#9333ea"]
POSITIVE, NEGATIVE, TOTAL, NEUTRAL = "#16a34a", "#dc2626", "#1e3a8a", "#64748b"
TEXT, MUTED, GRID = "#0f172a", "#64748b", "#e2e8f0"


# --------------------------------------------------------------------------- formatting

def _nan(v) -> bool:
    return v is None or (isinstance(v, float) and math.isnan(v))


def fmt_value(v, unit: str | None, precise: bool = False) -> str:
    """Human formatting for axis ticks and labels. INR uses the Indian scale (lakh/crore)."""
    if _nan(v):
        return ""
    if unit == "%":
        return f"{v * 100:.{2 if precise else 1}f}%"
    if unit == "x":
        return f"{v:.2f}x"
    if unit == "days":
        return f"{v:.0f} d"
    if unit == "pts":
        return f"{v:.0f}"
    if unit in ("INR", None):
        scale = thread_scale()
        if scale:
            # the job's document unit (set by the chart agent) -- same unit as tables and narrative
            scaled = abs(v / scale)
            return format_money(v, scale, decimals=0 if scaled >= 1000 else 1 if scaled >= 10 else 2)
        a, sign = abs(v), "-" if v < 0 else ""
        if a >= 1e7:
            return f"{sign}Rs {a / 1e7:.2f} Cr"
        if a >= 1e5:
            return f"{sign}Rs {a / 1e5:.1f} L"
        if a >= 1e3:
            return f"{sign}Rs {a / 1e3:.1f} K"
        return f"{sign}Rs {a:.0f}"
    return f"{v:,.2f}"


def _formatter(unit):
    return FuncFormatter(lambda v, _pos: fmt_value(v, unit))


def _style_axis(ax, unit):
    ax.yaxis.set_major_formatter(_formatter(unit))
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color("#cbd5e1")
    ax.tick_params(colors=MUTED, labelsize=8)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def _color(i: int, name: str, colors: dict | None) -> str:
    return (colors or {}).get(name) or PALETTE[i % len(PALETTE)]


def _clean(values) -> list[float]:
    return [float("nan") if _nan(v) else float(v) for v in values]


# --------------------------------------------------------------------------- drawers

def _reference_lines(ax, refs, unit):
    for ref in refs or []:
        color = ref.get("color", "#94a3b8")
        ax.axhline(ref["value"], color=color, linestyle="--", linewidth=1.1, zorder=1)
        ax.annotate(f"{ref.get('label', '')} ({fmt_value(ref['value'], unit)})".strip(), xy=(1.0, ref["value"]),
                    xycoords=("axes fraction", "data"), xytext=(-2, 3), textcoords="offset points",
                    ha="right", va="bottom", fontsize=7, color=color, zorder=5,
                    bbox={"boxstyle": "round,pad=0.2", "fc": "white", "ec": "none", "alpha": 0.85})


def _label_points(ax, x, values, unit, color, offset=6):
    for xi, v in zip(x, values):
        if not _nan(v):
            ax.annotate(fmt_value(v, unit), (xi, v), xytext=(0, offset), textcoords="offset points",
                        ha="center", fontsize=7, color=color, fontweight="bold", zorder=7,
                        bbox={"boxstyle": "round,pad=0.12", "fc": "white", "ec": "none", "alpha": 0.85})


def _draw_line(ax, labels, series, unit, opts):
    x = list(range(len(labels)))
    dashed = set(opts.get("dashed", []))
    label_points = opts.get("data_labels", True) and len(labels) <= 8
    for i, (name, values) in enumerate(series.items()):
        vals = _clean(values)
        color = _color(i, name, opts.get("colors"))
        ax.plot(x, vals, marker="o", markersize=5, linewidth=2.2, color=color, label=name,
                linestyle="--" if name in dashed else "-")
        if label_points:
            _label_points(ax, x, vals, unit, color)
    _xticks(ax, labels)


def _draw_bars(ax, labels, series, unit, opts):
    x = list(range(len(labels)))
    n = max(len(series), 1)
    width = min(0.8 / n, 0.32)
    for i, (name, values) in enumerate(series.items()):
        vals = _clean(values)
        offs = [xi + (i - (n - 1) / 2) * width for xi in x]
        colors = opts.get("bar_colors", {}).get(name)
        if opts.get("sign_colors"):
            colors = [POSITIVE if not _nan(v) and v >= 0 else NEGATIVE for v in vals]
        bars = ax.bar(offs, vals, width=width * 0.92, label=name, color=colors or _color(i, name, opts.get("colors")))
        if opts.get("data_labels", True) and len(labels) * n <= 24:
            ax.bar_label(bars, labels=[fmt_value(v, unit) for v in vals], padding=2, fontsize=7, color=TEXT)
    if any(not _nan(v) and v < 0 for vals in series.values() for v in vals):
        ax.axhline(0, color="#94a3b8", linewidth=0.9)
    _xticks(ax, labels)


def _draw_stacked(ax, labels, series, unit, opts, normalize=False):
    x = list(range(len(labels)))
    data = {k: _clean(v) for k, v in series.items()}
    if normalize:
        totals = [sum(abs(v[i]) for v in data.values() if not _nan(v[i])) or 1.0 for i in range(len(labels))]
        data = {k: [(v[i] / totals[i]) if not _nan(v[i]) else float("nan") for i in range(len(labels))]
                for k, v in data.items()}
        unit = "%"
    pos, neg = [0.0] * len(labels), [0.0] * len(labels)
    width = 0.55
    # label only segments that are big relative to the whole stack (not the running total)
    span = (max(sum(v[j] for v in data.values() if not _nan(v[j]) and v[j] > 0) for j in range(len(labels)))
            - min(sum(v[j] for v in data.values() if not _nan(v[j]) and v[j] < 0) for j in range(len(labels)))) or 1.0
    for i, (name, vals) in enumerate(data.items()):
        vals0 = [0.0 if _nan(v) else v for v in vals]
        bottoms = [pos[j] if v >= 0 else neg[j] for j, v in enumerate(vals0)]
        bars = ax.bar(x, vals0, bottom=bottoms, width=width, label=name, color=_color(i, name, opts.get("colors")),
                      edgecolor="white", linewidth=0.6)
        seg_labels = [fmt_value(v, unit) if abs(v) >= 0.06 * span else "" for v in vals0]
        if opts.get("data_labels", True):
            ax.bar_label(bars, labels=seg_labels, label_type="center", fontsize=7, color="white", fontweight="bold")
        for j, v in enumerate(vals0):
            if v >= 0:
                pos[j] += v
            else:
                neg[j] += v
    if any(n < 0 for n in neg):
        ax.axhline(0, color="#94a3b8", linewidth=0.9)
    _xticks(ax, labels)
    return unit


def _draw_hbar(ax, labels, series, unit, opts):
    name, values = next(iter(series.items()))
    vals = _clean(values)
    y = list(range(len(labels)))[::-1]
    colors = opts.get("hbar_colors") or [_color(0, name, opts.get("colors"))] * len(vals)
    bars = ax.barh(y, vals, color=colors, height=0.6, label=name)
    if opts.get("max_values"):
        ax.barh(y, _clean(opts["max_values"]), color="none", edgecolor="#94a3b8", height=0.6, linestyle="--")
    ax.bar_label(bars, labels=[fmt_value(v, unit) for v in vals], padding=3, fontsize=7, color=TEXT)
    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=8)
    ax.xaxis.set_major_formatter(_formatter(unit))
    if unit == "pts":
        ax.xaxis.set_major_locator(MaxNLocator(integer=True))
    ax.grid(axis="x", color=GRID)
    ax.grid(axis="y", visible=False)


def _draw_waterfall(ax, labels, series, unit, opts):
    steps = _clean(next(iter(series.values())))
    running, bottoms, heights, colors = 0.0, [], [], []
    for i, v in enumerate(steps):
        if i == 0:
            bottoms.append(0.0)
            heights.append(v)
            colors.append(NEUTRAL)
            running = v
            continue
        bottoms.append(running if v >= 0 else running + v)
        heights.append(abs(v))
        colors.append(POSITIVE if v >= 0 else NEGATIVE)
        running += v
    bottoms.append(0.0)
    heights.append(running)
    colors.append(TOTAL)
    x = list(range(len(heights)))
    bars = ax.bar(x, heights, bottom=bottoms, color=colors, width=0.62)
    tops = [b + h for b, h in zip(bottoms, heights)]
    level = steps[0]
    for i in range(len(heights) - 1):  # connectors between consecutive bars
        if i > 0:
            level += steps[i]
        ax.plot([i + 0.31, i + 0.69], [level, level], color="#94a3b8", linewidth=0.8, linestyle=":")
    shown = [steps[0]] + steps[1:] + [running]
    last = len(shown) - 1
    texts = [fmt_value(v, unit) if i in (0, last) else ("+" if v >= 0 else "") + fmt_value(v, unit)
             for i, v in enumerate(shown)]
    # Increases and totals are labelled above their bar, decreases below theirs, so a label
    # never sits on the neighbouring bar; labels at similar heights alternate between two
    # offsets so a dense bridge (12+ steps) stays readable.
    y_span = (max(tops + [0]) - min(bottoms + [0])) or 1.0
    prev_y, stagger = None, False
    for i, (xi, t) in enumerate(zip(x, texts)):
        above = i in (0, last) or shown[i] >= 0
        y = tops[i] if above else bottoms[i]
        stagger = (not stagger) if prev_y is not None and abs(y - prev_y) < 0.06 * y_span else False
        prev_y = y
        offset = (11 if stagger else 3) * (1 if above else -1)
        ax.annotate(t, (xi, y), xytext=(0, offset), textcoords="offset points", ha="center",
                    va="bottom" if above else "top", fontsize=7, color=TEXT, zorder=6,
                    bbox={"boxstyle": "round,pad=0.12", "fc": "white", "ec": "none", "alpha": 0.8})
    ax.margins(y=0.12)
    ax.bar_label(bars, labels=[""] * len(bars))
    _xticks(ax, list(labels) + [opts.get("closing_label", "Closing")], rotate=35)


def _draw_band_line(ax, labels, series, unit, opts):
    _draw_line(ax, labels, series, unit, {**opts, "data_labels": opts.get("data_labels", True)})
    x = list(range(len(labels)))
    for i, (name, band) in enumerate((opts.get("bands") or {}).items()):
        lo, hi = _clean(band["lower"]), _clean(band["upper"])
        color = _color(list(series).index(name) if name in series else i, name, opts.get("colors"))
        ax.fill_between(x, lo, hi, color=color, alpha=0.12, linewidth=0, label=f"{name} range")
    if opts.get("split_at") is not None:
        ax.axvline(opts["split_at"], color="#cbd5e1", linestyle=":", linewidth=1)
        ax.annotate("forecast →", (opts["split_at"], 1.0), xycoords=("data", "axes fraction"), xytext=(4, -10),
                    textcoords="offset points", fontsize=7, color=MUTED)


def _xticks(ax, labels, rotate=0):
    ax.set_xticks(list(range(len(labels))))
    rotate = rotate or (30 if len(labels) > 6 or max((len(str(l)) for l in labels), default=0) > 12 else 0)
    ax.set_xticklabels(labels, rotation=rotate, ha="right" if rotate else "center", fontsize=8)


_DRAWERS = {"line": _draw_line, "bar": _draw_bars, "hbar": _draw_hbar, "waterfall": _draw_waterfall,
            "band_line": _draw_band_line}


def _draw(ax, kind, labels, series, unit, opts):
    if kind in ("stacked_bar", "stacked_bar_100"):
        unit = _draw_stacked(ax, labels, series, unit, opts, normalize=kind == "stacked_bar_100")
    elif kind == "pie":  # legacy callers
        values = next(iter(series.values())) if series else []
        ax.pie(values, labels=labels, autopct="%1.1f%%", colors=PALETTE, wedgeprops={"width": 0.45})
        return
    else:
        _DRAWERS.get(kind, _draw_line)(ax, labels, series, unit, opts)
    if kind != "hbar":
        _style_axis(ax, unit)
    else:
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        ax.tick_params(colors=MUTED, labelsize=8)
    _reference_lines(ax, opts.get("reference_lines"), unit)
    # Lines in the SAME unit as the bars go on the primary axis (e.g. the cash conversion
    # cycle over its DSO/DIO/DPO components) -- a second axis would imply a different scale.
    for i, (name, values) in enumerate((opts.get("overlay") or {}).items()):
        vals = _clean(values)
        x = list(range(len(vals)))
        ax.plot(x, vals, marker="D", markersize=6, linewidth=2.2, color="#111827" if i == 0 else PALETTE[i + 6],
                label=name, zorder=6)
        _label_points(ax, x, vals, unit, "#111827", offset=8)
    secondary = opts.get("secondary")
    if secondary:
        ax2 = ax.twinx()
        x = list(range(len(labels)))
        for i, (name, values) in enumerate(secondary["series"].items()):
            vals = _clean(values)
            color = secondary.get("colors", {}).get(name, "#111827" if i == 0 else PALETTE[(i + 5) % len(PALETTE)])
            ax2.plot(x, vals, marker="D", markersize=5, linewidth=2, color=color, label=name)
            if secondary.get("data_labels", True):
                _label_points(ax2, x, vals, secondary.get("unit"), color, offset=7)
        ax2.yaxis.set_major_formatter(_formatter(secondary.get("unit")))
        ax2.tick_params(colors=MUTED, labelsize=8)
        for side in ("top",):
            ax2.spines[side].set_visible(False)
        ax2.spines["right"].set_color("#cbd5e1")
        lo, hi = ax2.get_ylim()
        ax2.set_ylim(min(lo, 0), hi * 1.15 if hi > 0 else hi)
        return ax2
    return None


def _legend(fig, axes):
    handles, names = [], []
    for ax in axes:
        for h, n in zip(*ax.get_legend_handles_labels()):
            if n not in names and not n.startswith("_"):
                handles.append(h)
                names.append(n)
    if len(names) > 1 or (names and len(axes) > 1):
        ncol = min(len(names), 5)
        fig.legend(handles, names, loc="lower center", ncol=ncol, frameon=False, fontsize=8,
                   bbox_to_anchor=(0.5, 0.0))
        return math.ceil(len(names) / ncol)
    return 0


def _header(fig, title: str, subtitle: str | None) -> float:
    """Title and takeaway, wrapped to the figure width (a long takeaway used to run off the
    right edge). Returns the top of the plotting area as a figure fraction, leaving exactly
    the room the wrapped lines need."""
    w_in, h_in = fig.get_size_inches()
    title_lines = textwrap.wrap(title, width=max(30, int(w_in * 8.2))) or [""]
    sub_lines = textwrap.wrap(subtitle, width=max(40, int(w_in * 14))) if subtitle else []
    y = 1 - 0.1 / h_in
    fig.text(0.012, y, "\n".join(title_lines), ha="left", va="top", fontsize=13, fontweight="bold", color=TEXT)
    y -= (0.24 * len(title_lines) + 0.04) / h_in
    if sub_lines:
        fig.text(0.012, y, "\n".join(sub_lines), ha="left", va="top", fontsize=9, color=MUTED)
        y -= (0.17 * len(sub_lines) + 0.06) / h_in
    return y - 0.08 / h_in


# --------------------------------------------------------------------------- entry point

def render_chart(job_id: str, chart_id: str, title: str, chart_type: str, labels: list[str],
                 series: dict[str, list[float]], unit: str | None = None, subtitle: str | None = None,
                 options: dict | None = None) -> dict:
    opts = options or {}
    panels = opts.get("panels") if chart_type == "panels" else None
    if panels:
        n = len(panels)
        rows, cols = (2, 2) if n == 4 else (1, n)
        fig, axes = plt.subplots(rows, cols, figsize=(9.5, 6.2 if rows == 2 else 4.4))
        axes = list(axes.flat) if n > 1 else [axes]
        all_axes = []
        for ax, panel in zip(axes, panels):
            p_opts = {**panel.get("options", {}), "reference_lines": panel.get("reference_lines")}
            ax2 = _draw(ax, panel.get("chart_type", "bar"), panel.get("labels", labels), panel["series"],
                        panel.get("unit"), p_opts)
            ax.set_title(panel.get("title", ""), fontsize=9, color=TEXT, loc="left", fontweight="bold")
            ax.margins(y=0.18)
            all_axes += [ax] + ([ax2] if ax2 else [])
    else:
        # a dense waterfall gets wider rather than squeezing its labels together
        width = max(9.5, 0.62 * (len(labels) + 1) + 2.5) if chart_type == "waterfall" else 9.5
        fig, ax = plt.subplots(figsize=(width, 4.8 if chart_type != "hbar" else 0.45 * max(len(labels), 4) + 1.6))
        ax2 = _draw(ax, chart_type, labels, series, unit, opts)
        if chart_type not in ("pie", "hbar"):
            ax.margins(y=0.15)
        all_axes = [ax] + ([ax2] if ax2 else [])

    legend_rows = _legend(fig, all_axes) if chart_type not in ("pie", "waterfall") else 0
    top = _header(fig, title, subtitle)
    # reserve ~0.2in per legend row so multi-row legends never overlap the axis labels
    bottom = (0.12 + 0.2 * legend_rows) / fig.get_size_inches()[1] if legend_rows else 0
    fig.tight_layout(rect=(0, bottom, 1, top))

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130, facecolor="white")
    plt.close(fig)
    png_bytes = buf.getvalue()

    # Saved to storage for anyone who wants the raw file, but the HTML/PDF report embeds the
    # base64 data URI directly -- png_uri uses our internal "file://" scheme, which isn't
    # reachable over HTTP, so a report that referenced it by URL would show a broken image
    # both in-browser and when xhtml2pdf tries to fetch it for the PDF.
    png_uri = storage.write_bytes(f"{job_id}/charts/{chart_id}.png", png_bytes)
    png_base64 = "data:image/png;base64," + base64.b64encode(png_bytes).decode("ascii")
    spec = {"title": title, "subtitle": subtitle, "chart_type": chart_type, "unit": unit, "labels": labels,
            "series": series}
    if panels:
        spec["panels"] = [{"title": p.get("title"), "chart_type": p.get("chart_type"), "unit": p.get("unit"),
                           "series": p["series"]} for p in panels]
    if opts.get("secondary"):
        spec["secondary"] = opts["secondary"]
    return {"png_uri": png_uri, "png_base64": png_base64, "spec": spec}


tool("chart.render", allowed_agents=["chart_spec"])(render_chart)
