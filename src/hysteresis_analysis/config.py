"""Load and validate user-editable application settings."""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

PACKAGE_DIR = Path(__file__).resolve().parent

DEFAULT_SETTINGS: dict[str, Any] = {
    "application": {
        "title": "Perovskite Hysteresis — Ionic Relaxation Model",
        "window_size": "1460x900",
        "minimum_size": [1200, 760]
    },
    "fit": {
        "max_components": 4,
        "default_model": "auto",
        "default_weight_mode": "downweight",
        "cutoff_hz": 100.0,
        "weight_power": 2.0,
        "beta": 1.0,
        "fit_baseline": False
    },
    "display": {"show_smoothed_original": True},
    "input": {
        "preferred_sheet_name": "Analysis Results",
        "frequency_columns": ["Frequency", "Freq", "Frequency (Hz)"],
        "hysteresis_area_columns": ["Hyst_Area", "Hyst Area", "Hysteresis Area", "HystArea"],
        "device_columns": ["Device", "Cell", "Sample", "Element"]
    }
}

def _merge(base: dict, override: dict) -> dict:
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result

def load_settings(config_path: str | Path | None = None) -> dict[str, Any]:
    """Load defaults, then overlay a JSON config if a file is supplied/present."""
    if config_path is not None:
        path = Path(config_path).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Configuration file does not exist: {path}")
    else:
        local = PACKAGE_DIR / "config.json"
        example = PACKAGE_DIR / "config.example.json"
        path = local if local.exists() else example if example.exists() else None
    settings = copy.deepcopy(DEFAULT_SETTINGS)
    if path is not None:
        try:
            user_settings = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON in settings file {path}: {exc}") from exc
        if not isinstance(user_settings, dict):
            raise ValueError("The top level of the configuration file must be a JSON object.")
        settings = _merge(settings, user_settings)
    _validate(settings)
    return settings

def _validate(settings: dict[str, Any]) -> None:
    app = settings["application"]
    fit = settings["fit"]
    inp = settings["input"]
    if not isinstance(app["minimum_size"], list) or len(app["minimum_size"]) != 2:
        raise ValueError("application.minimum_size must contain [width, height].")
    components = int(fit["max_components"])
    if not 1 <= components <= 8:
        raise ValueError("fit.max_components must be between 1 and 8.")
    fit["max_components"] = components
    if str(fit["default_model"]).lower() != "auto":
        model_k = int(fit["default_model"])
        if not 1 <= model_k <= components:
            raise ValueError("fit.default_model must be 'auto' or an integer not exceeding max_components.")
    if fit["default_weight_mode"] not in {"all", "downweight", "exclude"}:
        raise ValueError("fit.default_weight_mode must be all, downweight, or exclude.")
    for name in ("cutoff_hz", "weight_power", "beta"):
        value = float(fit[name])
        if value <= 0:
            raise ValueError(f"fit.{name} must be greater than zero.")
        fit[name] = value
    for name in ("frequency_columns", "hysteresis_area_columns", "device_columns"):
        if not isinstance(inp.get(name), list) or not inp[name] or not all(str(x).strip() for x in inp[name]):
            raise ValueError(f"input.{name} must be a non-empty list of column names.")
