"""Response synthesis. [spec §5.4 "Synthesise response"]

Claude (``claude-sonnet-4-6``) writes the natural-language answer when an API key is
present; otherwise a deterministic template produces the same governed result so the
demo and tests run without a key. Both paths emit the literal
``[redacted: policy <name>]`` markers the UI and acceptance test look for. [DECISIONS D5]
"""
from __future__ import annotations

from .config import settings

PII_MARKER = "[redacted: policy allow_pii_field_access]"
SECRET_MARKER = "[redacted: policy mask_secrets_in_response]"


def _money(v: int) -> str:
    return f"${v / 1_000_000:.1f}M" if v >= 1_000_000 else f"${v:,}"


def _deterministic(query: str, allowed: list, masked: list, excluded: list, limit: int) -> str:
    shown = allowed[:limit] if limit else allowed
    lines = [f"Top {len(shown)} suppliers matching your query "
             "(EMEA · PII contracts · expiring in range · valid GDPR consent):", ""]
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


def _claude(query: str, allowed: list, masked: list, excluded: list, limit: int) -> str:
    import json

    import anthropic

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    payload = {"allowed": allowed[:limit] if limit else allowed,
               "masked": masked, "excluded": excluded}
    system = (
        "You are the response-synthesis node of a governed enterprise AI system. "
        "Write a concise analyst answer to the user's question using ONLY the supplied data. "
        "Do not invent suppliers or values. List the allowed suppliers as a ranked top-N. "
        f"For each masked supplier, show the marker '{PII_MARKER}' and the reason. "
        f"For each excluded supplier, state it was excluded by policy require_residency_match. "
        f"If an allowed supplier's redactions include mask_secrets_in_response, append '{SECRET_MARKER}'. "
        "Keep it factual and regulator-readable."
    )
    msg = client.messages.create(
        model=settings.llm_model,
        max_tokens=1200,
        system=system,
        messages=[{"role": "user", "content":
                   f"Question: {query}\n\nGoverned data (JSON):\n{json.dumps(payload, indent=2)}"}],
    )
    return next((b.text for b in msg.content if b.type == "text"), "").strip()


def synthesize(query: str, allowed: list, masked: list, excluded: list, limit: int) -> tuple[str, str]:
    """Return (answer_text, mode) where mode is 'claude' or 'deterministic'."""
    if settings.llm_enabled:
        try:
            return _claude(query, allowed, masked, excluded, limit), "claude"
        except Exception:
            pass  # fall back so the demo never hard-fails on an LLM error
    return _deterministic(query, allowed, masked, excluded, limit), "deterministic"
