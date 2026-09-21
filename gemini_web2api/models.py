"""Model definitions and mapping from Gemini frontend JS source."""

# MODE_CATEGORY enum from 028-6eb337387583.js:
#   1=FAST, 2=THINKING, 3=PRO, 4=AUTO, 5=FAST_DYNAMIC_THINKING, 6=FLASH_LITE

MODELS = {
    # ─── Google Gemini Active Models ───────────────────────────────────────
    "gemini-3.8-flash": {
        "mode": 1, "think": 4,
        "desc": "Latest Google model (Gemini 3.8 Flash with native reasoning)",
    },
    "gemini-3.7-flash": {
        "mode": 1, "think": 4,
        "desc": "Gemini 3.7 Flash model",
    },
    "gemini-3.6-flash": {
        "mode": 1, "think": 4,
        "desc": "Gemini 3.6 Flash model",
    },
    "gemini-3.1-pro": {
        "mode": 3, "think": 4,
        "desc": "Gemini 3.1 Pro (Gemini Advanced Pro model)",
    },
    "gemini-3.1-pro-enhanced": {
        "mode": 3, "think": 4, "extra": {31: 2, 80: 3},
        "desc": "Gemini 3.1 Pro Enhanced (expanded response buffers)",
    },
    "gemini-auto": {
        "mode": 4, "think": 4,
        "desc": "Auto model selection",
    },
    "gemini-flash-lite": {
        "mode": 6, "think": 4,
        "desc": "Lightweight fast model",
    },
    # ─── Convenience Aliases ──────────────────────────────────────────────
    "gemini-flash": {
        "mode": 1, "think": 4,
        "desc": "Alias for gemini-3.8-flash",
    },
    "gemini-pro": {
        "mode": 3, "think": 4,
        "desc": "Alias for gemini-3.1-pro",
    },
    "gemini-advanced": {
        "mode": 3, "think": 4,
        "desc": "Alias for gemini-3.1-pro (Paid Tier)",
    },
    "gemini-2.5-flash": {
        "mode": 1, "think": 4,
        "desc": "Legacy alias for Flash",
    },
    "gemini-2.5-pro": {
        "mode": 3, "think": 4,
        "desc": "Legacy alias for Pro",
    },
}


def resolve_model(model_name: str, default: str = "gemini-3.8-flash"):
    """Resolve model name to (name, mode_id, think_mode, error, extra_fields).

    Unknown or empty model names fall back intelligently based on keywords:
    - 'pro' / 'advanced' -> gemini-3.1-pro (mode: 3)
    - '3.7' -> gemini-3.7-flash (mode: 1)
    - '3.6' -> gemini-3.6-flash (mode: 1)
    - 'lite' -> gemini-flash-lite (mode: 6)
    - other / default -> gemini-3.8-flash (mode: 1)
    """
    if not model_name or not str(model_name).strip():
        model_name = default
    think_override = None
    if "@think=" in model_name:
        model_name, think_str = model_name.rsplit("@think=", 1)
        try:
            think_override = int(think_str)
        except ValueError:
            return None, None, None, f"Invalid think level: {think_str}", None
    cfg = MODELS.get(model_name)
    if not cfg:
        clean_name = model_name.lower().split("/")[-1]
        if clean_name in MODELS:
            cfg = MODELS[clean_name]
            model_name = clean_name
        elif "advanc" in clean_name or "pro" in clean_name:
            model_name = "gemini-3.1-pro"
            cfg = MODELS["gemini-3.1-pro"]
        elif "3.7" in clean_name:
            model_name = "gemini-3.7-flash"
            cfg = MODELS["gemini-3.7-flash"]
        elif "3.6" in clean_name:
            model_name = "gemini-3.6-flash"
            cfg = MODELS["gemini-3.6-flash"]
        elif "lite" in clean_name:
            model_name = "gemini-flash-lite"
            cfg = MODELS["gemini-flash-lite"]
        else:
            from .gemini import log
            log(f"Unknown model '{model_name}', falling back to '{default}'")
            model_name = default
            cfg = MODELS.get(default) or MODELS["gemini-3.8-flash"]
    mode_id = cfg["mode"]
    think_mode = think_override if think_override is not None else cfg["think"]
    extra = cfg.get("extra")
    return model_name, mode_id, think_mode, None, extra
