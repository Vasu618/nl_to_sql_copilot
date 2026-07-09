"""
LLM provider layer.

Architecture intent (from docs/architecture.md §3.4): the LLM is a *swappable
layer* with a defined interface (system prompt + user prompt in; structured
output out). The non-negotiable safety properties live in the validator and
DB layers, NOT in the LLM — so swapping providers cannot weaken them.

Provider selection
------------------
    LLM_PROVIDER=claude  -> uses Anthropic API (architecture.md default)
    LLM_PROVIDER=glm     -> uses z-ai-web-dev-sdk via CLI subprocess
                             (fallback when no Anthropic key is available;
                              see README "LLM provider substitution")

The substitution is documented as a deliberate design choice, not a
workaround. The benchmark numbers in the README will be labeled with the
provider that produced them — both providers run the same safety pipeline.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from abc import ABC, abstractmethod
from typing import Any

from .config import get_settings


class LLMProvider(ABC):
    """Provider-agnostic LLM interface.

    The Week 2 SQL generator and Week 3 explanation layer both depend on this
    interface, not on a concrete provider — so swapping providers is a one-env-var change.
    """

    @abstractmethod
    def chat(self, system_prompt: str, user_prompt: str, *, max_tokens: int = 2048) -> str:
        """Single-turn chat completion. Returns the assistant's text response."""
        raise NotImplementedError

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Identifier used in the evaluation log."""
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Claude (primary, per architecture.md)
# ---------------------------------------------------------------------------

class ClaudeLLM(LLMProvider):
    """Anthropic Claude provider. Requires ANTHROPIC_API_KEY."""

    def __init__(self) -> None:
        from anthropic import Anthropic  # imported lazily so the package is optional
        key = get_settings().anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY not set. "
                "Either set it in the environment or switch LLM_PROVIDER=glm."
            )
        self._client = Anthropic(api_key=key)
        self._model = get_settings().anthropic_model

    @property
    def provider_name(self) -> str:
        return f"claude:{self._model}"

    def chat(self, system_prompt: str, user_prompt: str, *, max_tokens: int = 2048) -> str:
        resp = self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        # Anthropic returns a list of content blocks; concatenate text blocks.
        return "".join(
            block.text for block in resp.content if getattr(block, "type", None) == "text"
        )


# ---------------------------------------------------------------------------
# GLM via z-ai-web-dev-sdk CLI (fallback)
# ---------------------------------------------------------------------------

class GLMLLM(LLMProvider):
    """GLM provider via the z-ai-web-dev-sdk CLI.

    Used when no Anthropic key is available. Calls `z-ai chat` via subprocess
    and parses the JSON response. For production, a direct HTTP/SDK call would
    be cleaner — but subprocess is sufficient for the Week 1 checkpoint and
    keeps the codebase provider-agnostic.
    """

    @property
    def provider_name(self) -> str:
        return "glm:z-ai-web-dev-sdk"

    def chat(self, system_prompt: str, user_prompt: str, *, max_tokens: int = 2048) -> str:
        # The z-ai CLI writes JSON to -o <path>. We pass the prompts via CLI
        # flags and read the structured response.
        #
        # Rate-limit handling: GLM free-tier returns HTTP 429 on bursts.
        # We retry with exponential backoff + jitter up to 6 times.
        # Backoff schedule (with jitter): ~5, ~10, ~20, ~40, ~60, ~60 = ~195s max.
        # The jitter prevents thundering-herd when multiple calls retry
        # simultaneously. The 60s cap on later retries reflects the observed
        # rate-limit window (GLM free-tier seems to need ~60s to clear).
        #
        # We also retry on network errors and timeouts (not just 429s) since
        # the z-ai CLI can fail transiently for other reasons.
        import random
        import time as _time
        max_retries = 6
        base_backoff_s = 5.0
        last_err: Exception | None = None

        for attempt in range(max_retries + 1):
            with tempfile.NamedTemporaryFile(
                mode="w+", suffix=".json", delete=False
            ) as tmp:
                output_path = tmp.name

            try:
                cmd = [
                    "z-ai", "chat",
                    "--prompt", user_prompt,
                    "--system", system_prompt,
                    "--output", output_path,
                ]
                # Shorter per-call timeout (30s instead of 120s) so we fail
                # faster on hangs and get to the retry sooner.
                result = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=30, check=False,
                )
                if result.returncode != 0:
                    full_err = result.stderr or ""
                    err_text = full_err[:500]
                    # Detect HTTP 429 in the FULL stderr (not truncated).
                    # The 429 marker appears at the end of stderr, after a
                    # source-code dump, so truncating to 500 chars hides it.
                    is_rate_limit = "429" in full_err or "Too many requests" in full_err
                    # Also treat network/connection errors as retryable
                    is_network_err = any(
                        s in full_err.lower()
                        for s in ["econnrefused", "econnreset", "etimedout",
                                  "enotfound", "socket hang up", "fetch failed"]
                    )
                    should_retry = (is_rate_limit or is_network_err) and attempt < max_retries
                    if should_retry:
                        last_err = RuntimeError(
                            f"z-ai CLI {'rate-limited (429)' if is_rate_limit else 'network error'}: {err_text}"
                        )
                        # Exponential backoff with jitter, capped at 60s
                        backoff = min(base_backoff_s * (2 ** attempt), 60.0)
                        backoff += random.uniform(0, backoff * 0.3)  # 0-30% jitter
                        print(f"  [llm] retry {attempt+1}/{max_retries} after {backoff:.1f}s "
                              f"({'429' if is_rate_limit else 'network'})", flush=True)
                        _time.sleep(backoff)
                        continue
                    raise RuntimeError(
                        f"z-ai CLI failed (exit {result.returncode}): stderr={err_text}"
                    )
                with open(output_path, "r", encoding="utf-8") as f:
                    data: Any = json.load(f)
                # Response shape: {"choices": [{"message": {"content": "..."}}], ...}
                return data["choices"][0]["message"]["content"]
            except subprocess.TimeoutExpired:
                # The z-ai CLI hung — retry if budget remains
                if attempt < max_retries:
                    backoff = min(base_backoff_s * (2 ** attempt), 60.0)
                    backoff += random.uniform(0, backoff * 0.3)
                    print(f"  [llm] retry {attempt+1}/{max_retries} after {backoff:.1f}s "
                          f"(timeout)", flush=True)
                    last_err = RuntimeError("z-ai CLI timed out after 30s")
                    _time.sleep(backoff)
                    continue
                raise RuntimeError("z-ai CLI timed out after 30s (exhausted retries)")
            finally:
                if os.path.exists(output_path):
                    os.unlink(output_path)

        # Exhausted retries
        raise last_err or RuntimeError("z-ai CLI failed after multiple retries")


# ---------------------------------------------------------------------------
# Local / Mock provider (development convenience)
# ---------------------------------------------------------------------------


class MockLLM(LLMProvider):
    """A tiny synchronous mock LLM used for local development when the
    configured CLI-based provider isn't available. Returns a deterministic
   , human-readable echo so the front-end can show an answer without
    depending on external APIs or CLI configuration.
    """

    @property
    def provider_name(self) -> str:
        return "mock:local"

    def chat(self, system_prompt: str, user_prompt: str, *, max_tokens: int = 2048) -> str:
        # Return a minimal valid JSON object the pipeline expects so the
        # validator + executor can run. Use a harmless SELECT literal.
        import json
        payload = {
            "sql": "SELECT 1 AS mock",
            "rationale": f"mock reply for: {user_prompt}",
        }
        return json.dumps(payload)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

_provider: LLMProvider | None = None

# ---------------------------------------------------------------------------
# Gemini via Google's generativeai SDK (free tier, no credit card)
# ---------------------------------------------------------------------------

class GeminiLLM(LLMProvider):
    """Google Gemini provider — free tier, works on any server."""

    def __init__(self) -> None:
        import google.generativeai as genai
        key = get_settings().gemini_api_key or os.environ.get("GEMINI_API_KEY")
        if not key:
            raise RuntimeError(
                "GEMINI_API_KEY not set. "
                "Get a free key at https://aistudio.google.com/apikey"
            )
        genai.configure(api_key=key)
        self._model_name = get_settings().gemini_model
        self._model = genai.GenerativeModel(self._model_name)

    @property
    def provider_name(self) -> str:
        return f"gemini:{self._model_name}"

    def chat(self, system_prompt: str, user_prompt: str, *, max_tokens: int = 2048) -> str:
        # Gemini handles system prompts by prepending them to the user message.
        # This is the recommended approach per Google's docs.
        full_prompt = f"{system_prompt}\n\n---\n\n{user_prompt}"
        response = self._model.generate_content(
            full_prompt,
            generation_config={
                "max_output_tokens": max_tokens,
                "temperature": 0.7,
            },
        )
        return response.text