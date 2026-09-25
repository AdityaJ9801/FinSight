"""Forecasting tool. statsmodels ARIMA/ETS instead of Prophet -- pure-Python/scipy, prebuilt
Windows wheels, no compiled Stan toolchain to install (design doc's Prophet is swapped per
the plan's scoping decisions). Falls back to a naive linear trend when there isn't enough
history for a seasonal/ARIMA model to fit meaningfully.
"""
from __future__ import annotations

import numpy as np

from app.tools.registry import tool


def _naive_trend_forecast(series: list[float], periods_ahead: int) -> dict:
    if len(series) == 1:
        forecast = [series[0]] * periods_ahead
    else:
        x = np.arange(len(series))
        slope, intercept = np.polyfit(x, series, 1)
        forecast = [float(slope * (len(series) + i) + intercept) for i in range(periods_ahead)]
    spread = (max(series) - min(series)) / 2 if len(series) > 1 else abs(series[0]) * 0.1
    return {
        "method": "naive_linear_trend",
        "forecast": forecast,
        "lower": [v - spread for v in forecast],
        "upper": [v + spread for v in forecast],
    }


def run_forecast(series: list[float], periods_ahead: int = 2) -> dict:
    if len(series) < 4:
        return _naive_trend_forecast(series, periods_ahead)

    try:
        from statsmodels.tsa.holtwinters import ExponentialSmoothing

        model = ExponentialSmoothing(np.array(series, dtype=float), trend="add", damped_trend=True)
        fit = model.fit(optimized=True)
        forecast = fit.forecast(periods_ahead).tolist()
        resid_std = float(np.std(fit.resid)) if len(fit.resid) else abs(series[-1]) * 0.1
        return {
            "method": "holt_winters_ets",
            "forecast": forecast,
            "lower": [v - 1.96 * resid_std for v in forecast],
            "upper": [v + 1.96 * resid_std for v in forecast],
        }
    except Exception:
        # Any model-fit failure (e.g. degenerate/constant series) -- fall back rather than
        # fail the whole analysis stage for one module.
        return _naive_trend_forecast(series, periods_ahead)


tool("forecast.run", allowed_agents=["forecast"])(run_forecast)
