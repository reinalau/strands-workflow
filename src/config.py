"""
Global model configuration for the workflow.

Design choice: ONE provider is used for the entire workflow run, selected via
env var. This keeps the educational focus on the orchestration pattern itself
(dependencies, parallelism, join points) rather than on multi-provider setup.
A real per-role/per-provider setup is left as a follow-up (e.g. moving to AWS
Bedrock) once the pattern itself is understood.

Swap providers freely between runs to compare behavior/cost/latency without
touching src/workflow/builder.py:

    MODEL_PROVIDER=gemini python -m src.main
    MODEL_PROVIDER=ollama python -m src.main
"""

import os

# "gemini" -> Google AI Studio free tier (API key required), routed via LiteLLM
# "ollama" -> fully local, no API key, no cost
MODEL_PROVIDER = os.getenv("MODEL_PROVIDER", "ollama").lower()

SUPPORTED_PROVIDERS = {"gemini", "ollama"}

if MODEL_PROVIDER not in SUPPORTED_PROVIDERS:
    raise ValueError(
        f"Unsupported MODEL_PROVIDER='{MODEL_PROVIDER}'. "
        f"Choose one of: {sorted(SUPPORTED_PROVIDERS)}"
    )

# --- Gemini (free tier via Google AI Studio) ---
GEMINI_MODEL_ID = os.getenv("GEMINI_MODEL_ID", "gemini-2.0-flash")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")  # required only if MODEL_PROVIDER=gemini

# --- Ollama (fully local) ---
# --- Ollama (fully local) ---
# gemma4:e2b-it-qat confirmed available on Ollama's official library
# (https://ollama.com/library/gemma4:e2b-it-qat) — released June 2026.
OLLAMA_MODEL_ID = os.getenv("OLLAMA_MODEL_ID", "gemma4:e2b-it-qat")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")


def get_model_config() -> dict:
    """Return the model_provider + model_settings pair to use for EVERY task
    in the workflow. src/workflow/builder.py pulls from here for each task
    dict, so switching providers is a one-env-var change, not a code change.

    NOTE: strands_tools.create_model (used internally by the `workflow` tool)
    has no native "gemini" provider — verified empirically, it only supports
    bedrock/anthropic/litellm/llamaapi/ollama/openai/writer/cohere/github.
    LiteLLM DOES support Gemini natively via the "gemini/<model>" prefix, so
    Gemini is routed through model_provider="litellm" here.
    """
    if MODEL_PROVIDER == "gemini":
        if not GEMINI_API_KEY:
            raise EnvironmentError(
                "GEMINI_API_KEY is not set. Get a free key at "
                "https://aistudio.google.com/apikey and export it, "
                "or switch MODEL_PROVIDER=ollama."
            )
        os.environ.setdefault("GEMINI_API_KEY", GEMINI_API_KEY)
        return {
            "model_provider": "litellm",
            "model_settings": {
                "model_id": f"gemini/{GEMINI_MODEL_ID}",
                # NOTE: LiteLLMConfig's own validation only lists
                # context_window_limit, model_id, params, stream as valid —
                # passing temperature/max_tokens flat like this triggers a
                # UserWarning (params silently ignored, Gemini falls back to
                # its own defaults). Nesting them under "params" avoids the
                # warning and does apply them, but that combination is what
                # coincided with a Windows-only aiohttp/asyncio crash under
                # real concurrent execution (unconfirmed whether it was the
                # actual cause, or an unrelated network flake). Kept flat
                # deliberately: simpler, matches what was verified stable
                # across multiple real runs, at the cost of temperature/
                # max_tokens not being enforced for Gemini (Ollama is
                # unaffected either way — see branch below).
                "temperature": 0.4,
                "max_tokens": 4096,
            },
        }

    # ollama
    return {
        "model_provider": "ollama",
        "model_settings": {
            "model_id": OLLAMA_MODEL_ID,
            "host": OLLAMA_HOST,
            # NOTE: OllamaModel does NOT accept a nested "params" dict.
            # Verified empirically — passing {"params": {"temperature": ...}}
            # raises: UserWarning: Invalid configuration parameters: ['params'].
            # Valid parameters are flat: temperature, max_tokens, options, etc.
            "temperature": 0.4,
            # max_tokens: without this, generation can be cut off mid-answer
            # (verified empirically on discovery_questions, whose prompt
            # concatenates the full outputs of two upstream tasks — a long
            # context). When a task's output is truncated, workflow.py marks
            # it "error" internally, which permanently blocks any dependent
            # task from becoming "ready" (see get_ready_tasks) and hangs the
            # whole run forever instead of failing explicitly.
            # Bumped from 2048 -> 4096: still not enough for follow_up_actions
            # (heaviest task — synthesizes discovery_questions + meeting_summary,
            # each already long). Verified empirically it got cut mid-table.
            "max_tokens": 4096,
            # options.num_ctx: Ollama's default context window (often 2048)
            # can be too small once dependency context is concatenated into
            # the prompt AND we need room for a longer max_tokens output.
            # Widened to fit both.
            "options": {"num_ctx": 12288},
        },
    }