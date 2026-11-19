"""Current prototype cohort; historical registrations and backends stay intact."""

ACTIVE_MODELS = (
    "gpt-6.1-sol",
    "claude-opus-5-5",
    "deepseek/deepseek-v4.1-flash-1017",  # OpenRouter，固定 Cohere fp8（2026-11-12；pilot 为 Alibaba，2026-11-10）
    "gemini-3.8-flash",
    "qwen3.8-max",
)
PAUSED_MODELS = ("kimi-k3",)
GEMINI_THINKING_LEVEL = "MEDIUM"


def require_active(model):
    bare = model.lower().split("/")[-1].strip()
    if bare in PAUSED_MODELS:
        raise SystemExit("Kimi is temporarily paused for this study. Use gemini-3.8-flash instead.")


if __name__ == "__main__":
    print("\n".join(ACTIVE_MODELS))
