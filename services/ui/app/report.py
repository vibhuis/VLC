"""Regulator-addressable compliance report (PDF). [spec §5.6, §8, DECISIONS D6]

Builds a PDF from a trace that maps each decision step to EU AI Act Articles and NIST AI
RMF functions. Pure ReportLab (no system libraries).
"""
from __future__ import annotations

import io
from datetime import datetime, timezone

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle)

# Human-readable obligation labels for the report's mapping section.
ARTICLE_LABELS = {
    "9": "EU AI Act Art. 9 — Risk management system",
    "10": "EU AI Act Art. 10 — Data and data governance",
    "12": "EU AI Act Art. 12 — Record-keeping / logging",
    "13": "EU AI Act Art. 13 — Transparency & provision of information",
}
NIST_LABELS = {
    "GOVERN-1.2": "NIST AI RMF GOVERN-1.2 — Accountability structures",
    "MAP-2.3": "NIST AI RMF MAP-2.3 — Data provenance documented",
    "MAP-3.4": "NIST AI RMF MAP-3.4 — Capabilities & context understood",
    "MEASURE-2.7": "NIST AI RMF MEASURE-2.7 — Security & resilience evaluated",
    "MANAGE-2.2": "NIST AI RMF MANAGE-2.2 — Mechanisms to sustain value",
}
OUTCOME_COLOR = {"deny": colors.HexColor("#b00020"), "mask": colors.HexColor("#b36b00"),
                 "allow": colors.HexColor("#1b6b1b")}


def build_report(trace_id: str, answer: str, events: list[dict], principal: dict) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, title=f"VCL Compliance Report {trace_id}",
                            leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=16 * mm, bottomMargin=16 * mm)
    styles = getSampleStyleSheet()
    h1 = styles["Title"]
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], spaceBefore=10, spaceAfter=4)
    body = styles["BodyText"]
    small = ParagraphStyle("small", parent=body, fontSize=8, textColor=colors.grey)
    story = []

    story.append(Paragraph("VCL Compliance Report", h1))
    story.append(Paragraph(
        "Verifiable Context Layer — regulator-addressable audit trail<br/>"
        "Companion paper: Zenodo DOI 10.5281/zenodo.20599942", small))
    story.append(Spacer(1, 6))

    meta = [
        ["Trace ID", trace_id],
        ["Generated", datetime.now(timezone.utc).isoformat()],
        ["Principal", f"{principal.get('user', '?')} (purpose: {principal.get('purpose', '?')})"],
        ["Decision steps", str(len(events))],
    ]
    t = Table(meta, colWidths=[35 * mm, 140 * mm])
    t.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, -1), "Helvetica", 9),
        ("FONT", (0, 0), (0, -1), "Helvetica-Bold", 9),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.lightgrey),
    ]))
    story.append(t)

    # --- Answer ---
    story.append(Paragraph("Answer returned to the user", h2))
    for line in answer.splitlines() or [""]:
        story.append(Paragraph(line.replace("&", "&amp;").replace("<", "&lt;") or "&nbsp;", body))

    # --- Decision path ---
    story.append(Paragraph("Decision path (ordered)", h2))
    rows = [["#", "Component", "Action", "Policy outcomes"]]
    for i, e in enumerate(events, 1):
        outs = []
        for d in e.get("policy_decisions", []):
            o = d.get("outcome")
            if o:
                outs_label = f"{d.get('policy', '?')}={o}"
                outs_color = OUTCOME_COLOR.get(o, colors.black)
                outs.append(f'<font color="{outs_color.hexval()}">{outs_label}</font>')
            elif "audit_required" in d:
                outs.append(f"{d.get('policy', '?')}=audit:{d.get('audit_required')}")
        rows.append([str(i), e["component"], e["action"],
                     Paragraph("<br/>".join(outs) if outs else "—", small)])
    dt = Table(rows, colWidths=[8 * mm, 32 * mm, 55 * mm, 80 * mm], repeatRows=1)
    dt.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, -1), "Helvetica", 8),
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2a44")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f6fb")]),
    ]))
    story.append(dt)

    # --- Regulatory mapping ---
    story.append(Paragraph("Regulatory mapping", h2))
    story.append(Paragraph(
        "Each obligation below is evidenced by the trace steps listed. This is the "
        "regulator-addressable mapping required for EU AI Act conformity records and "
        "NIST AI RMF documentation.", small))

    art_steps: dict[str, list[int]] = {}
    nist_steps: dict[str, list[int]] = {}
    for i, e in enumerate(events, 1):
        for a in e["regulatory_mapping"]["eu_ai_act_articles"]:
            art_steps.setdefault(a, []).append(i)
        for n in e["regulatory_mapping"]["nist_rmf_functions"]:
            nist_steps.setdefault(n, []).append(i)

    map_rows = [["Obligation", "Evidenced by steps"]]
    for a in sorted(art_steps, key=lambda x: int(x)):
        map_rows.append([ARTICLE_LABELS.get(a, f"EU AI Act Art. {a}"),
                         ", ".join(map(str, art_steps[a]))])
    for n in sorted(nist_steps):
        map_rows.append([NIST_LABELS.get(n, n), ", ".join(map(str, nist_steps[n]))])
    mt = Table(map_rows, colWidths=[130 * mm, 45 * mm], repeatRows=1)
    mt.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, -1), "Helvetica", 8),
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2a44")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
    ]))
    story.append(mt)
    story.append(Spacer(1, 8))
    story.append(Paragraph(
        "Generated by the VCL reference implementation. Not legal advice; a demonstration "
        "of how a verifiable context layer produces conformity evidence.", small))

    doc.build(story)
    return buf.getvalue()
