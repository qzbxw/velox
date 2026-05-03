from bot.config import settings


def is_agent_enabled() -> bool:
    return bool(getattr(settings, "AGENT_ENABLED", True))


def tool_timeout() -> int:
    return int(getattr(settings, "AGENT_TOOL_TIMEOUT_SEC", 15) or 15)


def pipeline_timeout() -> int:
    return int(getattr(settings, "AGENT_PIPELINE_TIMEOUT_SEC", 120) or 120)
