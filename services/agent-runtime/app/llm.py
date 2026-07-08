"""LLM gateway — provider-agnostic via LiteLLM. [spec §3, DECISIONS D5/D9]

Shared helpers used by the scenario plugins (see app/scenarios/): a provider-agnostic
completion call, a readiness check, money formatting, the redaction markers, and an
optional LLM-based field parser for free-form questions. Scenario-specific synthesis lives
in each Scenario class; this module stays domain-agnostic.

Model is chosen with VCL_LLM_MODEL; the matching provider key (ANTHROPIC_API_KEY,
OPENAI_API_KEY, GEMINI_API_KEY, …) selects the backend. With no key, scenarios fall back to
deterministic synthesis so the demo and tests run end-to-end.
"""
from __future__ import annotations

import json
import os
import re

from .config import settings

PII_MARKER = "[redacted: policy allow_pii_field_access]"
SECRET_MARKER = "[redacted: policy mask_secrets_in_response]"
COMMERCIAL_MARKER = "[redacted: policy redact_commercial_terms]"
CONTACT_MARKER = "[redacted: policy mask_supplier_contact_pii]"

# model-string prefix → required provider env var (None = local, no key needed)
_PROVIDER_ENV = {
    "anthropic": "ANTHROPIC_API_KEY",
    "gpt": "OPENAI_API_KEY", "o1": "OPENAI_API_KEY", "o3": "OPENAI_API_KEY", "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY", "groq": "GROQ_API_KEY", "mistral": "MISTRAL_API_KEY",
    "cohere": "COHERE_API_KEY", "deepseek": "DEEPSEEK_API_KEY",
    "ollama": None, "ollama_chat": None,
}


def llm_ready() -> bool:
    """True if the configured model's provider key is available (or it's a local model)."""
    model = settings.llm_model.lower()
    prefix = model.split("/", 1)[0]
    for key, env in _PROVIDER_ENV.items():
        if prefix == key or model.startswith(key):
            return True if env is None else bool(os.environ.get(env))
    return any(os.environ.get(v) for v in {e for e in _PROVIDER_ENV.values() if e})


def _complete(system: str, user: str, max_tokens: int = 1024) -> str:
    from litellm import completion  # heavy import, kept lazy
    resp = completion(
        model=settings.llm_model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        max_tokens=max_tokens,
    )
    return (resp.choices[0].message.content or "").strip()


def _money(v: int) -> str:
    return f"${v / 1_000_000:.1f}M" if v >= 1_000_000 else f"${v:,}"


# --------------------------------------------------------- optional LLM field parser
_PARSE_SYSTEM = (
    "You translate a business question into a JSON query over a supplier / contract / "
    "consent / delivery dataset. Output ONLY a JSON object with any of these keys that apply:\n"
    "  geo: \"EMEA\" | \"AMER\" | \"APAC\" | null\n"
    "  end_before: ISO date \"YYYY-MM-DD\" upper bound on contract end date | null\n"
    "  contains_pii / contains_secrets / require_valid_consent: true | false | null\n"
    "  residency_scope: \"EU\" | null\n"
    "  quarter: \"FY26-Q3\"-style string | null\n"
    "  penalty_exposure_min: integer dollars | null\n"
    "  delivery_at_risk: true | false | null\n"
    "  limit: integer | null\n"
    "No prose, no code fences.")

_FIELD_KEYS = ("geo", "end_before", "contains_pii", "contains_secrets", "require_valid_consent",
               "residency_scope", "quarter", "penalty_exposure_min", "delivery_at_risk", "limit")


def llm_parse_fields(query: str) -> dict | None:
    """LLM-extracted intent fields for free-form questions (or None if unavailable)."""
    if not llm_ready():
        return None
    try:
        raw = _complete(_PARSE_SYSTEM, f"Question: {query}", max_tokens=300)
        m = re.search(r"\{.*\}", raw, re.S)
        data = json.loads(m.group(0) if m else raw)
    except Exception:
        return None
    fields = {k: data[k] for k in _FIELD_KEYS if data.get(k) is not None}
    if isinstance(fields.get("geo"), str):
        fields["geo"] = fields["geo"].upper()
    return fields
