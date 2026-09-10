from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from html import escape, unescape
from typing import Any


def text(raw: str | None) -> str:
    if not raw:
        return ""
    t = unescape(raw)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def extract_param_text(param_el: Any) -> str:
    if param_el is None:
        return ""
    if param_el.text and param_el.text.strip():
        return text(param_el.text)
    joined = "".join(param_el.itertext())
    return re.sub(r"\s+", " ", joined).strip()


def parse_existing_steps(steps_xml: str | None) -> list[dict[str, str]]:
    if not steps_xml:
        return []
    try:
        root = ET.fromstring(steps_xml)
    except ET.ParseError:
        return []

    out: list[dict[str, str]] = []
    for step_el in root.findall("step"):
        params = step_el.findall("parameterizedString")
        action = extract_param_text(params[0]) if len(params) > 0 else ""
        expected = extract_param_text(params[1]) if len(params) > 1 else ""
        out.append({"text_action": action, "text_expected": expected})
    return out


def assign_reqs_to_steps(existing_steps: list[dict[str, str]], requirements: list[dict[str, Any]]) -> list[list[str]]:
    covers_per_step: list[list[str]] = [[] for _ in existing_steps]
    stop = {
        "the", "and", "for", "with", "each", "view", "of", "in", "on", "to", "a", "an", "is", "are", "be",
        "at", "by", "as", "or", "which", "that", "from", "was", "were", "has", "have", "any", "all",
        "given", "when", "then", "delivery", "date",
    }

    def tokens(value: str) -> set[str]:
        return {w for w in re.findall(r"[a-z0-9\u00a3]+", value.lower()) if len(w) > 2 and w not in stop}

    step_tokens = [tokens(s.get("text_action", "") + " " + s.get("text_expected", "")) for s in existing_steps]

    for req in requirements:
        req_text = str(req.get("requirement_text") or "")
        req_id = str(req.get("req_id") or "")
        req_tokens = tokens(req_text)
        best_idx = -1
        best_overlap = 0
        for i, st in enumerate(step_tokens):
            overlap = len(req_tokens & st)
            if overlap > best_overlap:
                best_overlap = overlap
                best_idx = i
        if best_idx < 0:
            best_idx = len(existing_steps) - 1 if existing_steps else 0
        if 0 <= best_idx < len(covers_per_step) and req_id:
            covers_per_step[best_idx].append(req_id)

    return covers_per_step


def rebuild_existing_steps_xml(existing_steps: list[dict[str, str]], covers_per_step: list[list[str]]) -> str:
    parts: list[str] = []
    parts.append(f'<steps id="0" last="{len(existing_steps)}">')
    for i, (step, covers) in enumerate(zip(existing_steps, covers_per_step), 1):
        action_text = step.get("text_action") or ""
        expected_text = step.get("text_expected") or ""
        action_html = f"&lt;P&gt;{escape(action_text)}&lt;/P&gt;"
        expected_html = f"&lt;P&gt;{escape(expected_text)}&lt;/P&gt;"
        covers_text = ", ".join(covers)
        desc_html = f"&lt;P&gt;Covers: {escape(covers_text)}&lt;/P&gt;" if covers_text else ""
        parts.append(f'<step id="{i}" type="ActionStep">')
        parts.append(f'<parameterizedString isformatted="true">{action_html}</parameterizedString>')
        parts.append(f'<parameterizedString isformatted="true">{expected_html}</parameterizedString>')
        parts.append(f"<description>{desc_html}</description>")
        parts.append("</step>")
    parts.append("</steps>")
    return "".join(parts)
