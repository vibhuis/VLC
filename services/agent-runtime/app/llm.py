"""LLM gateway — provider-agnostic via LiteLLM. [spec §3, DECISIONS D5/D9]

Users choose the model with VCL_LLM_MODEL and supply the matching provider key
(ANTHROPIC_API_KEY, OPENAI_API_KEY, GEMINI_API_KEY, …); LiteLLM routes by the model
string. Default is claude-sonnet-4-6. The LLM does two jobs:

  • understanding  — turn a free-form question into the governed structured intent
  • synthesis      — write the final analyst answer

Both fall back to deterministic logic when no provider key is configured, so the demo
and tests run with zero keys. The governance path (semantic → graph → policy → trace) is
identical in every mode.
"""
from __future__ import annotations

import json
import os
import re

from .config import settings

PII_MARKER = "[redacted: policy allow_pii_field_access]"
SECRET_MARKER = "[redacted: policy mask_secrets_in_response]"

# model-string prefix → required provider env var (None = local, no key needed)
_PROVIDER_ENV = {
    "claude": "ANTHROPIC_API_KEY", "anthropic": "ANTHROPIC_API_KEY",
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
    # Unknown model string → ready if any known provider key is set.
    return any(os.environ.get(v) for v in {e for e in _PROVIDER_ENV.values() if e})


def _complete(system: str, user: str, max_tokens: int = 1024) -> str:
    from litellm import completion  # heavy import, kept lazy
    resp = completion(
        model=settings.llm_model,
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": user}],
        max_tokens=max_tokens,
    )
    return (resp.choices[0].message.content or "").strip()


# --------------------------------------------------------------------- understanding
_PARSE_SYSTEM = (
    "You translate a business question into a JSON query over a supplier/contract/consent "
    "dataset. Output ONLY a JSON object with these keys:\n"
    "  geo: one of \"EMEA\", \"AMER\", \"APAC\", or null\n"
    "  end_before: ISO date \"YYYY-MM-DD\" upper bound on contract end date, or null "
    "(interpret 'before <Month> <Year>' as the last day of that period)\n"
    "  contains_pii: true, false, or null\n"
    "  contains_secrets: true, false, or null\n"
    "  require_valid_consent: true or false\n"
    "  residency_scope: \"EU\" or null (set \"EU\" for EU/EMEA/GDPR questions)\n"
    "  limit: integer or null (from 'top N')\n"
    "  in_domain: true if the question is about suppliers/contracts/consents/risk, else false\n"
    "No prose, no code fences."
)


def llm_parse_intent(query: str) -> dict | None:
    if not llm_ready():
        return None
    try:
        raw = _complete(_PARSE_SYSTEM, f"Question: {query}", max_tokens=300)
        m = re.search(r"\{.*\}", raw, re.S)
        data = json.loads(m.group(0) if m else raw)
    except Exception:
        return None
    intent: dict = {"raw": query, "rank_by": "value_usd", "source": "llm"}
    for k in ("geo", "end_before", "contains_pii", "contains_secrets",
              "require_valid_consent", "residency_scope", "limit", "in_domain"):
        if data.get(k) is not None:
            intent[k] = data[k]
    if isinstance(intent.get("geo"), str):
        intent["geo"] = intent["geo"].upper()
    return intent


# --------------------------------------------------------------------- synthesis
def _money(v: int) -> str:
    return f"${v / 1_000_000:.1f}M" if v >= 1_000_000 else f"${v:,}"


def describe(intent: dict) -> str:
    parts = []
    if intent.get("geo"):
        parts.append(intent["geo"])
    if intent.get("contains_pii"):
        parts.append("PII contracts")
    if intent.get("contains_secrets"):
        parts.append("secret clauses")
    if intent.get("end_before"):
        parts.append(f"expiring on/before {intent['end_before']}")
    if intent.get("require_valid_consent"):
        parts.append("valid GDPR consent")
    return " · ".join(parts) if parts else "all suppliers"


def _deterministic(intent: dict, allowed: list, masked: list, excluded: list, limit: int) -> str:
    shown = allowed[:limit] if limit else allowed
    lines = [f"Top {len(shown)} suppliers — {describe(intent)}:", ""]
    for i, r in enumerate(shown, 1):
        secret_note = f" {SECRET_MARKER}" if any(
            x["policy"] == "mask_secrets_in_response" for x in r.get("redactions", [])) else ""
        lines.append(f"{i}. {r['name']} ({r['region']}) — contract {r['contract_id']} "
                     f"expires {r['end_date']}, value {_money(r['value_usd'])} "
                     f"[risk: {r['risk_tier']}]{secret_note}")
    if masked:
        lines += ["", "Withheld — matched the query but failed a policy check:"]
        for r in masked:
            lines.append(f"  • {r['name']} ({r['region']}) — {PII_MARKER} "
                         "(GDPR consent expired or missing)")
    if excluded:
        lines += ["", "Excluded — outside the permitted data-residency scope:"]
        for r in excluded:
            lines.append(f"  • {r['name']} ({r['region']}) — excluded by policy "
                         "require_residency_match (data hosted outside the EU)")
    return "\n".join(lines)


def _llm(query: str, intent: dict, allowed: list, masked: list, excluded: list, limit: int) -> str:
    payload = {"allowed": allowed[:limit] if limit else allowed, "masked": masked, "excluded": excluded}
    system = (
        "You are the response-synthesis node of a governed enterprise AI system. Write a "
        "concise analyst answer to the user's question using ONLY the supplied data. Do not "
        "invent suppliers or values. List allowed suppliers as a ranked top-N. For each "
        f"masked supplier show the marker '{PII_MARKER}' and the reason. For each excluded "
        "supplier state it was excluded by policy require_residency_match. If an allowed "
        f"supplier's redactions include mask_secrets_in_response, append '{SECRET_MARKER}'. "
        "Keep it factual and regulator-readable."
    )
    return _complete(system,
                     f"Question: {query}\n\nGoverned data (JSON):\n{json.dumps(payload, indent=2)}",
                     max_tokens=1200)


def synthesize(query: str, intent: dict, allowed: list, masked: list,
               excluded: list, limit: int) -> tuple[str, str]:
    """Return (answer_text, mode) where mode is the model id or 'deterministic'."""
    if llm_ready():
        try:
            return _llm(query, intent, allowed, masked, excluded, limit), settings.llm_model
        except Exception:
            pass  # fall back so the demo never hard-fails on an LLM error
    return _deterministic(intent, allowed, masked, excluded, limit), "deterministic"
