"""Post-optimize LLM summaries for truck assignments and unassigned themes."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

from app.config import settings
from app.schemas import OptimizeResponse

logger = logging.getLogger(__name__)

_SYSTEM = """You write plain-language explanations for a freight dispatcher.
Return ONLY valid JSON:
{
  "trucks": { "<unit_number>": "<2-4 sentence paragraph>" },
  "unassigned_summary": "<2-4 sentence paragraph>"
}

Style rules (critical):
- Write complete sentences a non-technical person can skim. No jargon dumps.
- Do NOT paste or echo raw machine reject strings, truck:reason lists, or semicolon dumps.
- Translate constraints into everyday words, e.g. "delivery time window", "not enough cargo space",
  "missing heated equipment", "no liftgate", "driver not qualified for this freight".
- unassigned_summary is an OVERALL fleet briefing — not about any single truck.
  Speak of "the available trucks" / "the fleet". NEVER name a unit number, truck id, or driver
  in unassigned_summary (those belong only in the per-truck "trucks" map).
- Unassigned summary should start with how many orders could not be assigned, then explain the
  main constraint themes across the fleet (use unassigned_themes_hint), not one truck's rejects.
- Per-truck: explain why that truck got those stops (area/corridor, load fit, driver, timing)
  in narrative form — not a restatement of internal notes.
- Only use facts present in the input. If nothing is unassigned, say every considered order was assigned.

Example unassigned_summary tone:
"3 orders could not be assigned because the available trucks did not meet one or more delivery
requirements. The main constraints identified were delivery time window violations, insufficient
cargo capacity, and equipment incompatibility (such as missing heated equipment). These constraints
prevented the system from finding a feasible assignment for the affected orders."
"""


def _truncate_reason(reason: str, max_len: int = 120) -> str:
    text = (reason or "").strip()
    if not text:
        return ""
    # Prefer first truck clause before semicolon dump
    first = text.split(";")[0].strip()
    if len(first) > max_len:
        return first[: max_len - 1].rstrip() + "…"
    return first


def _strip_unit_prefix(clause: str) -> str:
    """Turn '202: requires heated' / '202: D01: …' into the constraint text only."""
    text = (clause or "").strip()
    if not text:
        return ""
    # unit: reason  OR  unit: driver: reason
    if ": " in text:
        parts = text.split(": ", 2)
        if len(parts) >= 2 and re.match(r"^[\w\-#]+$", parts[0].strip()):
            rest = parts[-1].strip() if len(parts) == 3 else parts[1].strip()
            return rest or text
    return text


def _anonymized_unassigned_themes(reason: str, *, max_themes: int = 4) -> list[str]:
    """Extract constraint phrases from a multi-truck reject string, without unit ids."""
    seen: list[str] = []
    for clause in (reason or "").split(";"):
        theme = _strip_unit_prefix(clause)
        if not theme:
            continue
        key = theme.lower()
        if any(key == s.lower() for s in seen):
            continue
        seen.append(theme)
        if len(seen) >= max_themes:
            break
    return seen


def _scrub_unit_mentions(text: str) -> str:
    """Rewrite accidental single-truck wording in the fleet unassigned summary."""
    cleaned = re.sub(
        r"\bTruck\s*#?\s*[\w\-]+\b",
        "the available trucks",
        text,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"\bunit\s*#?\s*[\w\-]+\b",
        "available units",
        cleaned,
        flags=re.IGNORECASE,
    )
    # Collapse awkward doubles from scrubbing
    cleaned = re.sub(
        r"(the available trucks)(\s+was\b)",
        r"\1 were",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"(the available trucks)(\s+does\b)",
        r"\1 do",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"(the available trucks)(\s+do not have\b)",
        r"\1 do not have",
        cleaned,
        flags=re.IGNORECASE,
    )
    # Capitalize after sentence boundaries
    cleaned = re.sub(
        r"([.!?]\s+)([a-z])",
        lambda m: m.group(1) + m.group(2).upper(),
        cleaned,
    )
    return cleaned


def _human_constraint_themes(reasons: list[str]) -> list[str]:
    """Map machine reject snippets to plain-language theme labels."""
    blob = " ".join(reasons).lower()
    themes: list[str] = []
    if any(
        k in blob
        for k in ("window", "outside delivery", "soft window", "due≤", "due<=")
    ):
        themes.append("delivery time window violations")
    if any(
        k in blob
        for k in (
            "capacity",
            "weight",
            "skid",
            "linear",
            "height",
            "oversize",
            "no floor",
            "placement",
        )
    ):
        themes.append("insufficient cargo capacity")
    if any(
        k in blob
        for k in ("heated", "liftgate", "equipment", "trailer type", "body type")
    ):
        themes.append(
            "equipment incompatibility (such as missing heated or liftgate equipment)"
        )
    if any(k in blob for k in ("driver", "qualified", "no driver")):
        themes.append("driver qualification or availability gaps")
    if any(k in blob for k in ("duty", "drive time", "shift", "hos")):
        themes.append("available driving/duty time")
    if not themes:
        themes.append("feasibility constraints across the available fleet")
    return themes


def _compact_payload(result: OptimizeResponse) -> dict[str, Any]:
    trucks: list[dict[str, Any]] = []
    for a in result.assignments:
        trucks.append(
            {
                "unit": a.unit_number,
                "driver": f"{a.driver_code or ''} {a.driver_name or ''}".strip(),
                "orders": a.order_ordnos,
                "destinations": a.destinations[:12],
                "duty_min": round(a.duty_minutes_used, 0),
                "usage": {
                    "weight": round(a.usage.weight_lbs, 0),
                    "skids": round(a.usage.skid_spots, 1),
                    "feet": round(a.usage.linear_feet, 1),
                },
                "notes": [r[:160] for r in (a.rationales or [])[:8]],
            }
        )
    unassigned = [
        {
            "ordno": u.ordno,
            # Fleet-level constraint phrases only — no unit numbers (avoids single-truck bias)
            "constraints": _anonymized_unassigned_themes(u.reason),
        }
        for u in result.unassigned
    ]
    return {
        "planning_date": str(result.planning_date),
        "routing_mode": result.routing_mode,
        "trucks": trucks,
        "unassigned": unassigned,
        "unassigned_themes_hint": _human_constraint_themes(
            [u.reason for u in result.unassigned]
        ),
    }


def _fallback_truck_summary(a) -> str:
    n = len(a.order_ordnos)
    dests = ", ".join(a.destinations[:3])
    more = len(a.destinations) - 3
    dest_bit = dests
    if more > 0:
        dest_bit = f"{dests}, and {more} other stop{'s' if more != 1 else ''}"
    driver = a.driver_name or a.driver_code or "an available driver"
    if n == 0:
        return (
            f"Truck {a.unit_number} was available with {driver} but did not receive "
            f"any orders in this plan."
        )
    order_word = "order" if n == 1 else "orders"
    base = (
        f"Truck {a.unit_number} ({driver}) was assigned {n} {order_word}"
        f"{f' toward {dest_bit}' if dest_bit else ''}."
    )
    # Prefer one short humanized note if present; avoid dumping raw lists.
    note = ""
    if a.rationales:
        raw = a.rationales[0].strip()
        if raw and not raw.lower().startswith("restored"):
            note = f" The plan favored this unit because {raw[0].lower()}{raw[1:]}"
            if not note.endswith("."):
                note += "."
    return base + note


def _fallback_unassigned_summary(result: OptimizeResponse) -> str:
    n = len(result.unassigned)
    if n == 0:
        return "Every order considered in this run was assigned to a truck."
    themes = _human_constraint_themes([u.reason for u in result.unassigned])
    if len(themes) == 1:
        theme_phrase = themes[0]
    elif len(themes) == 2:
        theme_phrase = f"{themes[0]} and {themes[1]}"
    else:
        theme_phrase = ", ".join(themes[:-1]) + f", and {themes[-1]}"
    order_word = "order" if n == 1 else "orders"
    return (
        f"{n} {order_word} could not be assigned because the available trucks did not "
        f"meet one or more delivery requirements. The main constraints identified were "
        f"{theme_phrase}. These constraints prevented the system from finding a feasible "
        f"assignment for the affected orders."
    )


def _fallback_summaries(result: OptimizeResponse) -> OptimizeResponse:
    for a in result.assignments:
        if not a.reasoning_summary:
            a.reasoning_summary = _fallback_truck_summary(a)
    if not result.unassigned_summary:
        result.unassigned_summary = _fallback_unassigned_summary(result)
    return result


def _parse_llm_json(content: str) -> dict[str, Any] | None:
    text = (content or "").strip()
    if not text:
        return None
    # Strip markdown fences if present
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                data = json.loads(text[start : end + 1])
                return data if isinstance(data, dict) else None
            except json.JSONDecodeError:
                return None
        return None


def summarize_optimize_result(result: OptimizeResponse) -> OptimizeResponse:
    """Enrich OptimizeResponse with LLM summaries; falls back if key missing/errors."""
    if not result.assignments and not result.unassigned:
        result.unassigned_summary = result.unassigned_summary or ""
        return result

    if not settings.llm_enabled:
        return _fallback_summaries(result)

    payload = _compact_payload(result)
    url = settings.openai_base_url.rstrip("/") + "/chat/completions"
    body = {
        "model": settings.openai_model,
        "temperature": 0.35,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {
                "role": "user",
                "content": (
                    "Write human-readable briefing paragraphs for this plan. "
                    "For unassigned_summary: write a fleet-wide overview using "
                    "unassigned_themes_hint — do not mention any truck unit number. "
                    "Phrase everything in plain English — never copy raw reject strings.\n"
                    + json.dumps(payload, ensure_ascii=False)
                ),
            },
        ],
    }
    headers = {
        "Authorization": f"Bearer {settings.openai_api_key.strip()}",
        "Content-Type": "application/json",
    }

    try:
        with httpx.Client(timeout=45.0) as client:
            resp = client.post(url, headers=headers, json=body)
            resp.raise_for_status()
            data = resp.json()
        content = (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
        )
        parsed = _parse_llm_json(content)
        if not parsed:
            logger.warning("LLM summarize: could not parse JSON response")
            return _fallback_summaries(result)

        trucks_map = parsed.get("trucks") or {}
        if isinstance(trucks_map, dict):
            by_unit = {str(k): str(v).strip() for k, v in trucks_map.items() if v}
            for a in result.assignments:
                summary = by_unit.get(a.unit_number) or by_unit.get(
                    a.unit_number.replace(" ", "")
                )
                if summary:
                    a.reasoning_summary = summary

        ua = parsed.get("unassigned_summary")
        if isinstance(ua, str) and ua.strip():
            result.unassigned_summary = _scrub_unit_mentions(ua.strip())

        return _fallback_summaries(result)
    except Exception:
        logger.exception("LLM summarize failed; using fallback text")
        return _fallback_summaries(result)


def short_unassigned_reason(reason: str, max_len: int = 80) -> str:
    """UI helper: first clause of a multi-truck reject string."""
    return _truncate_reason(reason, max_len)
