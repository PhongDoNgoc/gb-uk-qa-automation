"""Requirement-driven review pipeline for the Azure DevOps QA Test Case Generator.

Provides:
- Section-aware HTML parsing (parse_sections)
- Atomic statement decomposition (extract_atomic_statements)
- Deterministic statement classification (classify_statement)
- 1:1 atomic-statement -> effective REQ mapping (build_effective_requirements)
- REQ-driven test case generation (generate_test_cases)
- Overmerge detection (detect_overmerge)
- Explicit-assertion coverage matrix (build_coverage_matrix)
- Review-status gate (compute_review_status)
- Apply-safety validator (validate_apply_readiness)
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass, asdict, field
from typing import Any


# ---------------------------------------------------------------------------
# 1. HTML normalization + section-aware parsing
# ---------------------------------------------------------------------------


_LIST_ITEM_OPEN = re.compile(r"<li[^>]*>", re.IGNORECASE)
_BLOCK_CLOSE = re.compile(
    r"<(br|/p|/div|/li|/h[1-6]|/tr|/td|/th|/table|/thead|/tbody|/ol|/ul|/section)[^>]*>",
    re.IGNORECASE,
)
_ANY_TAG = re.compile(r"<[^>]+>")


def normalize_html(raw: str | None) -> str:
    if not raw:
        return ""
    text = _LIST_ITEM_OPEN.sub("\n- ", raw)
    text = _BLOCK_CLOSE.sub("\n", text)
    text = _ANY_TAG.sub("", text)
    text = html.unescape(text).replace("\u00a0", " ")
    lines: list[str] = []
    for raw_line in text.splitlines():
        cleaned = re.sub(r"[ \t]+", " ", raw_line).strip()
        if cleaned:
            lines.append(cleaned)
    return "\n".join(lines)


# Known section headings (case-insensitive, matched against a normalized line).
_KNOWN_SECTIONS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^context$", re.I), "Context"),
    (re.compile(r"^item$", re.I), "Item Description"),
    (re.compile(r"^where to implement$", re.I), "Where To Implement"),
    (re.compile(r"^preconditions?$", re.I), "Preconditions"),
    (re.compile(r"^postconditions?$", re.I), "Postconditions"),
    (re.compile(r"^primary flow$", re.I), "Primary Flow"),
    (re.compile(r"^alternate flow(?:\s*\d*)?$", re.I), "Alternate Flow"),
    (re.compile(r"^alternate\s*\d+.*", re.I), "Alternate Flow"),
    (re.compile(r"^what a user needs to be able to do$", re.I), "What A User Needs To Be Able To Do"),
    (re.compile(r"^business rules$", re.I), "Business Rules"),
    (re.compile(r"^open questions$", re.I), "Open Questions"),
]

_NUMBERED_SUBSECTION = re.compile(r"^(\d+\.\d+)\s+(?!-)([A-Za-z].*)$")
_FIGURE_LINE = re.compile(r"^figure\s+\d+\.\d+", re.I)
_INTERACTIVE_PROTOTYPE = re.compile(r"interactive prototype", re.I)


@dataclass
class SourceBlock:
    section: str
    subsection: str
    order: int
    text: str
    kind: str  # "heading" | "paragraph" | "list_item"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _detect_section(line: str) -> tuple[str | None, str | None]:
    for pattern, name in _KNOWN_SECTIONS:
        if pattern.match(line):
            return name, ""
    m = _NUMBERED_SUBSECTION.match(line)
    if m:
        return None, f"{m.group(1)} {m.group(2).strip()}"
    return None, None


def _iter_desc_blocks(text: str) -> list[SourceBlock]:
    blocks: list[SourceBlock] = []
    current_section = "Description/Background"
    current_subsection = ""
    order = 0
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        sec, sub = _detect_section(line)
        if sec is not None:
            current_section = sec
            current_subsection = ""
            blocks.append(SourceBlock(current_section, current_subsection, order, line, "heading"))
            order += 1
            continue
        if sub is not None:
            current_subsection = sub
            blocks.append(SourceBlock(current_section, current_subsection, order, line, "heading"))
            order += 1
            continue
        if _FIGURE_LINE.match(line) or _INTERACTIVE_PROTOTYPE.search(line):
            blocks.append(SourceBlock(current_section, current_subsection, order, line, "paragraph"))
            order += 1
            continue
        kind = "list_item" if line.startswith("- ") else "paragraph"
        cleaned = line[2:].strip() if line.startswith("- ") else line
        blocks.append(SourceBlock(current_section, current_subsection, order, cleaned, kind))
        order += 1
    return blocks


_AC_TODAY_MARKER = re.compile(r"^if viewing[^\n]*today['\u2019]s delivery date", re.I)
_AC_PAST_MARKER = re.compile(r"^if viewing[^\n]*past deli+very date", re.I)


def _iter_ac_blocks(text: str) -> list[SourceBlock]:
    blocks: list[SourceBlock] = []
    subsection = "AC-today"
    order = 0
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    current_bullet: list[str] = []

    def _flush() -> None:
        nonlocal order
        if current_bullet:
            merged = " ".join(current_bullet).strip()
            merged = re.sub(r"\s+", " ", merged)
            blocks.append(SourceBlock("Acceptance Criteria", subsection, order, merged, "list_item"))
            order += 1
            current_bullet.clear()

    for line in lines:
        if _AC_TODAY_MARKER.search(line):
            _flush()
            subsection = "AC-today"
            blocks.append(SourceBlock("Acceptance Criteria", subsection, order, line, "heading"))
            order += 1
            continue
        if _AC_PAST_MARKER.search(line):
            _flush()
            subsection = "AC-past"
            blocks.append(SourceBlock("Acceptance Criteria", subsection, order, line, "heading"))
            order += 1
            continue
        if line.startswith("- "):
            _flush()
            current_bullet.append(line[2:].strip())
        else:
            # GIVEN/WHEN/THEN or other continuation of the current AC bullet
            if current_bullet:
                current_bullet.append(line)
            else:
                blocks.append(SourceBlock("Acceptance Criteria", subsection, order, line, "paragraph"))
                order += 1
    _flush()
    return blocks


def parse_sections(work_item: dict[str, Any], comments: list[dict[str, Any]] | None = None) -> list[SourceBlock]:
    blocks: list[SourceBlock] = []
    desc = normalize_html(work_item.get("description"))
    if desc:
        blocks.extend(_iter_desc_blocks(desc))
    ac = normalize_html(work_item.get("acceptance_criteria"))
    if ac:
        blocks.extend(_iter_ac_blocks(ac))
    br = normalize_html(work_item.get("business_rules"))
    if br:
        blocks.append(SourceBlock("Business Rules", "", len(blocks), br, "paragraph"))
    if comments:
        for c in comments:
            date = c.get("createdDate") or c.get("created_date") or ""
            body = normalize_html(c.get("text") or "")
            if not body:
                continue
            sub = f"Comment {date[:10]}" if date else "Comment"
            for ln in body.splitlines():
                cleaned = ln.strip()
                if not cleaned:
                    continue
                kind = "list_item" if cleaned.startswith("- ") else "paragraph"
                cleaned_text = cleaned[2:].strip() if cleaned.startswith("- ") else cleaned
                blocks.append(SourceBlock("Comments", sub, len(blocks), cleaned_text, kind))
    return blocks


# ---------------------------------------------------------------------------
# 2. Atomic decomposition
# ---------------------------------------------------------------------------


@dataclass
class AtomicStatement:
    statement_id: str
    source: str  # "Description" | "Acceptance Criteria" | "Business Rules" | "Comments"
    source_section: str
    source_subsection: str
    original_text: str
    classification: str
    testable: bool
    reason: str
    priority_hint: str = "P1"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


# Categories used by classify_statement / classify_comment_v2.
CAT_PRODUCT_REQUIREMENT = "PRODUCT_REQUIREMENT"
CAT_BUSINESS_RULE = "BUSINESS_RULE"
CAT_UI_REQUIREMENT = "UI_REQUIREMENT"
CAT_DATA_REQUIREMENT = "DATA_REQUIREMENT"
CAT_BOUNDARY_RULE = "BOUNDARY_RULE"
CAT_ALTERNATE_FLOW = "ALTERNATE_FLOW"
CAT_PRECONDITION = "PRECONDITION"
CAT_POSTCONDITION = "POSTCONDITION"
CAT_ENVIRONMENT_NOTE = "ENVIRONMENT_NOTE"
CAT_DATA_AVAILABILITY_GAP = "DATA_AVAILABILITY_GAP"
CAT_DEV_IMPLEMENTATION_NOTE = "DEV_IMPLEMENTATION_NOTE"
CAT_QA_REVIEW_REQUEST = "QA_REVIEW_REQUEST"
CAT_UI_REVIEW_REQUEST = "UI_REVIEW_REQUEST"
CAT_BUSINESS_CONTEXT = "BUSINESS_CONTEXT"
CAT_OPEN_QUESTION_RESOLVED = "OPEN_QUESTION_RESOLVED"
CAT_OPEN_QUESTION_UNRESOLVED = "OPEN_QUESTION_UNRESOLVED"
CAT_DEFERRED_OUT_OF_SCOPE = "DEFERRED_OUT_OF_SCOPE"
CAT_IRRELEVANT = "IRRELEVANT"


_TESTABLE_CATEGORIES = {
    CAT_PRODUCT_REQUIREMENT,
    CAT_BUSINESS_RULE,
    CAT_UI_REQUIREMENT,
    CAT_DATA_REQUIREMENT,
    CAT_BOUNDARY_RULE,
    CAT_ALTERNATE_FLOW,
    CAT_QA_REVIEW_REQUEST,
    CAT_UI_REVIEW_REQUEST,
    CAT_OPEN_QUESTION_RESOLVED,
}


def _split_compound_statements(text: str, section: str, subsection: str) -> list[str]:
    """Split a bullet that packs multiple atomic rules into separate strings."""
    t = text.strip()
    # Gate-closure BMU/Non-BMU: three distinct rules.
    if re.search(r"BMU", t) and re.search(r"Non-?BMU", t) and re.search(r"gate closure", t, re.I):
        parts: list[str] = []
        m_shift = re.search(r"shift[^.]*?next upcoming[^.]*?settlement period", t, re.I)
        if m_shift:
            parts.append(
                "The current time (gate closure) line on the graph shifts to the next upcoming gate-closure settlement period."
            )
        parts.append(
            "For a BMU asset, the gate closure line is placed at the settlement period start time minus 1 hour."
        )
        parts.append(
            "For a Non-BMU asset, the gate closure line is placed at the settlement period start time minus 15 minutes."
        )
        return parts
    # "- The recommended volume for a bid in MW - The recommended price for a bid in £/MWh" merged bullet.
    if re.search(r"\bMW\b.*-\s*The\s+recommended\s+price", t):
        parts = [p.strip() for p in re.split(r"\s+-\s+(?=The\s+recommended)", t) if p.strip()]
        if len(parts) > 1:
            return parts
    return [t]


def _classify_open_question(text: str) -> tuple[str, str]:
    """Return (classification, extracted_answer_or_original)."""
    t = text.strip()
    q_starter = re.compile(r"^(when|how|do|does|are|is|should|can|what|which|where|who)\s", re.I)
    deferred_patterns = [
        r"to be (discussed|decided|determined|confirmed|agreed|resolved)",
        r"separate user story",
        r"separate story",
        r"another (user )?story",
        r"defer(red)? to",
        r"out of scope",
    ]

    def _is_deferred(answer: str) -> bool:
        return any(re.search(p, answer, re.I) for p in deferred_patterns)

    def _is_unresolved(answer: str) -> bool:
        return answer.lower() in {"", "tbd", "tbc", "tba", "?", "n/a"}

    # Case 1: "Question? Answer"
    m = re.search(r"^(.+?\?)\s*(.+)$", t)
    if m:
        answer = m.group(2).strip()
        if _is_deferred(answer):
            return CAT_DEFERRED_OUT_OF_SCOPE, t
        if _is_unresolved(answer):
            return CAT_OPEN_QUESTION_UNRESOLVED, t
        return CAT_OPEN_QUESTION_RESOLVED, t
    # Case 2: "When do we ... - answer" (embedded via dash, no ?)
    if q_starter.match(t) and " - " in t:
        answer = t.split(" - ", 1)[1].strip()
        if _is_deferred(answer):
            return CAT_DEFERRED_OUT_OF_SCOPE, t
        if _is_unresolved(answer):
            return CAT_OPEN_QUESTION_UNRESOLVED, t
        return CAT_OPEN_QUESTION_RESOLVED, t
    return CAT_OPEN_QUESTION_UNRESOLVED, t


def classify_statement(text: str, source: str, section: str, subsection: str) -> str:
    t = (text or "").lower()
    section_lower = section.lower()

    if source == "Description":
        if section_lower.startswith("preconditions"):
            return CAT_PRECONDITION
        if section_lower.startswith("postconditions"):
            return CAT_POSTCONDITION
        if section_lower.startswith("context") or section_lower.startswith("item"):
            return CAT_BUSINESS_CONTEXT
        if section_lower.startswith("alternate flow"):
            return CAT_ALTERNATE_FLOW
        if section_lower.startswith("open questions"):
            return CAT_OPEN_QUESTION_RESOLVED if re.search(r"\?\s*\S", text) else CAT_OPEN_QUESTION_UNRESOLVED
        if subsection.startswith("2.1") or "graph" in subsection.lower():
            return CAT_UI_REQUIREMENT
        if subsection.startswith("2.2") or "table" in subsection.lower():
            if re.search(r"status.*volue.*active|active.*submitted", t):
                return CAT_DATA_REQUIREMENT
            return CAT_UI_REQUIREMENT
        if section_lower.startswith("primary flow") or section_lower.startswith("what a user"):
            return CAT_PRODUCT_REQUIREMENT
        return CAT_BUSINESS_CONTEXT

    if source == "Acceptance Criteria":
        if "given" in t and "when" in t and "then" in t:
            return CAT_PRODUCT_REQUIREMENT
        return CAT_PRODUCT_REQUIREMENT

    if source == "Business Rules":
        return CAT_BUSINESS_RULE

    if source == "Comments":
        return classify_comment_v2(text)

    return CAT_BUSINESS_CONTEXT


_ENV_PATTERNS = [
    r"\bdev(elopment)?\s+environment\b",
    r"\bin\s+dev\b",
    r"\bmissing records\b",
    r"\bno data flowing\b",
    r"gaps?\s*(are|,)?\s*expected",
    r"third[- ]party",
    r"auto[- ]submission[^.\n]*\b(on|enabled|is on)\b",
]
_DATA_GAP_PATTERNS = [
    r"doesn'?t (yet )?provide",
    r"not (yet )?available",
    r"still (doesn'?t|no|can'?t)",
    r"still no",
    r"missing data",
    r"no data(?! flowing)",
]
_QA_REVIEW_PATTERNS = [
    r"review wording", r"writing/wording", r"^wording$",
    r"naming convention", r"^conciseness$",
    r"graph colours?", r"graph colors?",
    r"^ui review$", r"colour clarity", r"clarity and consistency of graph",
]
_DEV_IMPL_PATTERNS = [
    r"\brefactored\b", r"\bdeployed\b", r"implementation note", r"pr merged", r"pull request",
]
_REQUIREMENT_CHANGE_PATTERNS = [
    r"\bnow should\b", r"\binstead of\b", r"\breplaced by\b", r"\bnew behavior\b", r"\bchanged to\b",
]
_BUSINESS_RULE_PATTERNS = [
    r"\bonly when\b", r"\bnot allowed\b", r"\bbusiness rule\b",
]


def classify_comment_v2(text: str) -> str:
    t = (text or "").lower()
    if not t:
        return CAT_IRRELEVANT
    if any(re.search(p, t) for p in _REQUIREMENT_CHANGE_PATTERNS):
        return CAT_PRODUCT_REQUIREMENT
    if any(re.search(p, t) for p in _ENV_PATTERNS):
        return CAT_ENVIRONMENT_NOTE
    if any(re.search(p, t) for p in _DATA_GAP_PATTERNS):
        return CAT_DATA_AVAILABILITY_GAP
    if any(re.search(p, t) for p in _DEV_IMPL_PATTERNS):
        return CAT_DEV_IMPLEMENTATION_NOTE
    if any(re.search(p, t) for p in _QA_REVIEW_PATTERNS):
        return CAT_QA_REVIEW_REQUEST
    if any(re.search(p, t) for p in _BUSINESS_RULE_PATTERNS):
        return CAT_BUSINESS_RULE
    return CAT_IRRELEVANT


def _is_context_line(text: str) -> bool:
    """Filter noisy Context / Item Description paragraphs from the atomic set."""
    tl = text.lower().strip()
    if not tl:
        return True
    if len(tl) < 4:
        return True
    return False


def extract_atomic_statements(source_blocks: list[SourceBlock], work_item_id: int) -> list[AtomicStatement]:
    statements: list[AtomicStatement] = []
    counters: dict[str, int] = {}

    def _next_id(prefix: str) -> str:
        counters[prefix] = counters.get(prefix, 0) + 1
        return f"{work_item_id}-{prefix}-{counters[prefix]:03d}"

    for block in source_blocks:
        section = block.section
        subsection = block.subsection
        original = block.text
        if block.kind == "heading":
            continue
        if section.startswith("Description"):
            source = "Description"
            prefix = "DESC"
        elif section == "Acceptance Criteria":
            source = "Acceptance Criteria"
            prefix = "AC-PAST" if subsection == "AC-past" else "AC-TODAY"
        elif section == "Business Rules":
            source = "Business Rules"
            prefix = "BR"
        elif section == "Comments":
            source = "Comments"
            prefix = "COM"
        else:
            source = "Description"
            prefix = "DESC"

        # Context/business background — capture as BUSINESS_CONTEXT (non-testable), but only
        # for lines under the Context / Item Description umbrella, to keep the atomic set
        # focused. Preconditions / Primary Flow / Alternate Flow / 2.x list items are always
        # decomposed below.
        if section in {"Context", "Item Description", "Where To Implement"} and block.kind != "list_item":
            statements.append(AtomicStatement(
                statement_id=_next_id(prefix),
                source=source,
                source_section=section,
                source_subsection=subsection,
                original_text=original,
                classification=CAT_BUSINESS_CONTEXT,
                testable=False,
                reason="Business/domain context; not a testable rule.",
            ))
            continue

        pieces = _split_compound_statements(original, section, subsection)
        for piece in pieces:
            piece_text = piece.strip()
            if _is_context_line(piece_text):
                continue
            cls = classify_statement(piece_text, source, section, subsection)
            if source == "Description" and section == "Open Questions":
                cls, piece_text = _classify_open_question(piece_text)
            testable = cls in _TESTABLE_CATEGORIES
            reason_map = {
                CAT_PRECONDITION: "Setup condition; not a positive product rule.",
                CAT_POSTCONDITION: "Outcome envelope; not a distinct testable rule.",
                CAT_BUSINESS_CONTEXT: "Business/domain context; not testable.",
                CAT_ENVIRONMENT_NOTE: "DEV environment note; must not become a product requirement.",
                CAT_DATA_AVAILABILITY_GAP: "Data gap in DEV; informs environment scoping, not product spec.",
                CAT_DEV_IMPLEMENTATION_NOTE: "Implementation note; may drive regression scope but is not a new product rule.",
                CAT_OPEN_QUESTION_UNRESOLVED: "Unresolved question; requires clarification before generating tests.",
                CAT_IRRELEVANT: "No QA impact detected.",
            }
            reason = reason_map.get(cls, "Testable rule extracted from source.")
            statements.append(AtomicStatement(
                statement_id=_next_id(prefix),
                source=source,
                source_section=section,
                source_subsection=subsection,
                original_text=piece_text,
                classification=cls,
                testable=testable,
                reason=reason,
                priority_hint=_priority_for(cls, section, subsection),
            ))
    return statements


def _priority_for(cls: str, section: str, subsection: str) -> str:
    if cls in {CAT_PRODUCT_REQUIREMENT, CAT_BUSINESS_RULE, CAT_DATA_REQUIREMENT, CAT_BOUNDARY_RULE, CAT_ALTERNATE_FLOW}:
        return "P0"
    if cls == CAT_UI_REQUIREMENT and (subsection.startswith("2.2") or "table" in subsection.lower()):
        return "P0"
    if cls in {CAT_UI_REQUIREMENT, CAT_UI_REVIEW_REQUEST, CAT_QA_REVIEW_REQUEST}:
        return "P1"
    if cls == CAT_OPEN_QUESTION_RESOLVED:
        return "P1"
    return "P2"


# ---------------------------------------------------------------------------
# 3. Effective REQ mapping
# ---------------------------------------------------------------------------


@dataclass
class EffectiveRequirement:
    req_id: str
    statement_id: str
    requirement_text: str
    source_section: str
    source_subsection: str
    source_text: str
    classification: str
    priority_hint: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_effective_requirements(
    atomic_statements: list[AtomicStatement],
    work_item_id: int,
) -> list[EffectiveRequirement]:
    reqs: list[EffectiveRequirement] = []
    counter = 0
    for stmt in atomic_statements:
        if not stmt.testable:
            continue
        counter += 1
        req_id = f"REQ-{work_item_id}-{counter:02d}"
        reqs.append(EffectiveRequirement(
            req_id=req_id,
            statement_id=stmt.statement_id,
            requirement_text=stmt.original_text,
            source_section=stmt.source_section,
            source_subsection=stmt.source_subsection,
            source_text=stmt.original_text,
            classification=stmt.classification,
            priority_hint=stmt.priority_hint,
        ))
    return reqs


def check_decomposition_completeness(
    atomic_statements: list[AtomicStatement],
    effective_reqs: list[EffectiveRequirement],
) -> dict[str, Any]:
    testable = [s for s in atomic_statements if s.testable]
    mapped_statement_ids = {r.statement_id for r in effective_reqs}
    unmapped = [s.statement_id for s in testable if s.statement_id not in mapped_statement_ids]
    return {
        "testable_statement_count": len(testable),
        "mapped_req_count": len(effective_reqs),
        "unmapped_testable_statement_ids": unmapped,
        "status": "OK" if not unmapped else "DECOMPOSITION_INCOMPLETE",
    }


# ---------------------------------------------------------------------------
# 4. Requirement-driven test case generation
# ---------------------------------------------------------------------------


@dataclass
class TestStep:
    action: str
    expected_result: str
    covers: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TestCase:
    id: str
    title: str
    preconditions: list[str]
    steps: list[TestStep]
    priority: str
    test_type: str
    layer: str
    source_requirements: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "preconditions": self.preconditions,
            "steps": [s.as_dict() for s in self.steps],
            "priority": self.priority,
            "test_type": self.test_type,
            "layer": self.layer,
            "source_requirements": self.source_requirements,
        }


def _infer_test_type_layer(req: EffectiveRequirement) -> tuple[str, str]:
    cls = req.classification
    subsection = (req.source_subsection or "").lower()
    if cls == CAT_BOUNDARY_RULE:
        return "Boundary", "End-to-End"
    if cls in {CAT_UI_REQUIREMENT, CAT_UI_REVIEW_REQUEST, CAT_QA_REVIEW_REQUEST}:
        return "UI", "Frontend"
    if cls == CAT_DATA_REQUIREMENT:
        return "Functional", "End-to-End"
    if cls == CAT_ALTERNATE_FLOW:
        return "Functional", "End-to-End"
    if "graph" in subsection:
        return "UI", "Frontend"
    if "table" in subsection:
        return "Functional", "End-to-End"
    return "Functional", "End-to-End"


def _short_title(text: str, limit: int = 110) -> str:
    t = re.sub(r"\s+", " ", text).strip()
    if len(t) <= limit:
        return t
    return t[: limit - 1].rstrip() + "\u2026"


def _global_preconditions(atomic_statements: list[AtomicStatement]) -> list[str]:
    return [
        s.original_text
        for s in atomic_statements
        if s.classification == CAT_PRECONDITION
    ]


def generate_test_cases(
    effective_reqs: list[EffectiveRequirement],
    atomic_statements: list[AtomicStatement],
    work_item_id: int,
) -> list[TestCase]:
    """Generate one Test Case per effective REQ with an explicit assertion step per REQ.

    Grouping is deliberately conservative here: 1 REQ -> 1 TC. Higher-level grouping
    can be layered on later, but each REQ must always retain an explicit assertion
    step to prevent OVERMERGED_SCENARIO issues.
    """
    global_pre = _global_preconditions(atomic_statements)
    cases: list[TestCase] = []
    for idx, req in enumerate(effective_reqs, start=1):
        test_type, layer = _infer_test_type_layer(req)
        title = _short_title(f"Verify: {req.requirement_text}")
        action = _infer_action(req)
        expected = _infer_expected(req)
        step = TestStep(action=action, expected_result=expected, covers=[req.req_id])
        pre_note = f"Section: {req.source_section}"
        if req.source_subsection:
            pre_note += f" / {req.source_subsection}"
        preconditions = [pre_note] + global_pre
        cases.append(TestCase(
            id=f"TC-{work_item_id}-{idx:02d}",
            title=title,
            preconditions=preconditions,
            steps=[step],
            priority=req.priority_hint,
            test_type=test_type,
            layer=layer,
            source_requirements=[req.req_id],
        ))
    return cases


def _infer_action(req: EffectiveRequirement) -> str:
    subsection = req.source_subsection.lower()
    if "graph" in subsection or "2.1" in subsection:
        return "Open the Submitted IDC Recommendations graph for the selected delivery date and inspect the behavior described in the requirement."
    if "table" in subsection or "2.2" in subsection:
        return "Open the Submitted IDC Recommendations table for the selected delivery date and inspect the column/row behavior described in the requirement."
    if req.source_section == "Acceptance Criteria" and req.source_subsection == "AC-past":
        return "Select a past delivery date for IDC and load the Submitted IDC Recommendations view."
    if req.source_section == "Acceptance Criteria":
        return "Select today's delivery date for IDC and load the Submitted IDC Recommendations view."
    if req.source_section == "Alternate Flow":
        return "Trigger the alternate flow described in the requirement and load the resulting view."
    if req.source_section == "Primary Flow":
        return "Execute the primary flow step described in the requirement."
    if req.source_section == "Open Questions":
        return "Execute the workflow implied by the resolved open question."
    if req.source_section == "Comments":
        return "Open the affected view and inspect the aspect referenced in the requirement."
    return "Load the Submitted IDC Recommendations view and inspect the aspect referenced in the requirement."


def _infer_expected(req: EffectiveRequirement) -> str:
    return f"Observed behavior matches the requirement: {req.requirement_text}"


# ---------------------------------------------------------------------------
# 5. Overmerge detection
# ---------------------------------------------------------------------------


def detect_overmerge(
    test_cases: list[TestCase],
    effective_reqs: list[EffectiveRequirement],
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for tc in test_cases:
        asserted: set[str] = set()
        for step in tc.steps:
            for r in step.covers:
                asserted.add(r)
        unasserted = [r for r in tc.source_requirements if r not in asserted]
        if unasserted:
            findings.append({
                "test_case_id": tc.id,
                "assigned_req_ids": list(tc.source_requirements),
                "unasserted_req_ids": unasserted,
                "flag": "OVERMERGED_SCENARIO",
                "recommendation": "Split into per-REQ test cases OR add explicit assertion steps for the unasserted REQs.",
            })
    return findings


# ---------------------------------------------------------------------------
# 6. Coverage matrix
# ---------------------------------------------------------------------------


def build_coverage_matrix(
    effective_reqs: list[EffectiveRequirement],
    test_cases: list[TestCase],
) -> list[dict[str, Any]]:
    matrix: list[dict[str, Any]] = []
    for req in effective_reqs:
        covering: list[dict[str, Any]] = []
        for tc in test_cases:
            for idx, step in enumerate(tc.steps, start=1):
                if req.req_id not in step.covers:
                    continue
                if not step.action.strip() or not step.expected_result.strip():
                    continue
                covering.append({"test_case_id": tc.id, "step_index": idx})
        if covering:
            status = "COVERED"
            reason = None
        elif any(req.req_id in tc.source_requirements for tc in test_cases):
            status = "PARTIAL"
            reason = "Referenced by a test case but no step explicitly asserts this REQ."
        else:
            status = "UNCOVERED"
            reason = "No test case references this REQ."
        matrix.append({
            "req_id": req.req_id,
            "requirement_text": req.requirement_text,
            "coverage_status": status,
            "covering_steps": covering,
            "reason": reason,
        })
    return matrix


# ---------------------------------------------------------------------------
# 7. Review status + apply-safety gate
# ---------------------------------------------------------------------------


def compute_review_status(
    atomic_statements: list[AtomicStatement],
    effective_reqs: list[EffectiveRequirement],
    coverage_matrix: list[dict[str, Any]],
    overmerge_findings: list[dict[str, Any]],
) -> tuple[str, list[str]]:
    reasons: list[str] = []
    decomp = check_decomposition_completeness(atomic_statements, effective_reqs)
    if decomp["status"] != "OK":
        reasons.append("DECOMPOSITION_INCOMPLETE: " + ", ".join(decomp["unmapped_testable_statement_ids"][:5]))
    uncovered = [c for c in coverage_matrix if c["coverage_status"] == "UNCOVERED"]
    partial = [c for c in coverage_matrix if c["coverage_status"] == "PARTIAL"]
    if uncovered:
        reasons.append(f"COVERAGE_INCOMPLETE: {len(uncovered)} uncovered REQ(s)")
    if partial:
        reasons.append(f"COVERAGE_INCOMPLETE: {len(partial)} partial REQ(s)")
    if overmerge_findings:
        reasons.append(f"OVERMERGED_SCENARIO: {len(overmerge_findings)} scenario(s)")
    # Only UNRESOLVED (not DEFERRED) blocks the gate.
    unresolved = [s for s in atomic_statements if s.classification == CAT_OPEN_QUESTION_UNRESOLVED]
    if unresolved:
        reasons.append(f"REQUIREMENT_CLARIFICATION_REQUIRED: {len(unresolved)} open question(s)")

    if not reasons:
        return "READY_FOR_QA_APPROVAL", []
    if any("DECOMPOSITION_INCOMPLETE" in r for r in reasons):
        return "DECOMPOSITION_INCOMPLETE", reasons
    if any("REQUIREMENT_CLARIFICATION_REQUIRED" in r for r in reasons):
        return "REQUIREMENT_CLARIFICATION_REQUIRED", reasons
    return "COVERAGE_INCOMPLETE", reasons


def validate_apply_readiness(review_v2: dict[str, Any], approved_for_apply: bool) -> tuple[bool, str]:
    if not approved_for_apply:
        return False, "review not manually approved (approved_for_apply=false)"
    status = review_v2.get("review_status")
    if status != "READY_FOR_QA_APPROVAL":
        return False, f"review_status={status}; must be READY_FOR_QA_APPROVAL"
    coverage = review_v2.get("coverage_matrix") or []
    for entry in coverage:
        if entry.get("coverage_status") != "COVERED":
            return False, f"REQ {entry.get('req_id')} coverage_status={entry.get('coverage_status')}"
    if review_v2.get("overmerge_findings"):
        return False, "OVERMERGED_SCENARIO present"
    decomp = review_v2.get("decomposition") or {}
    if decomp.get("status") != "OK":
        return False, "DECOMPOSITION_INCOMPLETE"
    return True, "OK"


# ---------------------------------------------------------------------------
# 8. Top-level entry point
# ---------------------------------------------------------------------------


def run_review_v2(
    work_item: dict[str, Any],
    comments: list[dict[str, Any]],
    work_item_id: int,
) -> dict[str, Any]:
    blocks = parse_sections(work_item, comments)
    atomic = extract_atomic_statements(blocks, work_item_id)
    effective_reqs = build_effective_requirements(atomic, work_item_id)
    test_cases = generate_test_cases(effective_reqs, atomic, work_item_id)
    overmerge = detect_overmerge(test_cases, effective_reqs)
    coverage = build_coverage_matrix(effective_reqs, test_cases)
    decomp = check_decomposition_completeness(atomic, effective_reqs)
    status, reasons = compute_review_status(atomic, effective_reqs, coverage, overmerge)

    return {
        "work_item_id": work_item_id,
        "source_blocks": [b.as_dict() for b in blocks],
        "atomic_statements": [s.as_dict() for s in atomic],
        "effective_requirements": [r.as_dict() for r in effective_reqs],
        "test_cases": [t.as_dict() for t in test_cases],
        "overmerge_findings": overmerge,
        "coverage_matrix": coverage,
        "decomposition": decomp,
        "review_status": status,
        "review_status_reasons": reasons,
        "counts": {
            "atomic_statements": len(atomic),
            "testable_statements": sum(1 for s in atomic if s.testable),
            "effective_requirements": len(effective_reqs),
            "test_cases": len(test_cases),
            "covered_reqs": sum(1 for c in coverage if c["coverage_status"] == "COVERED"),
            "partial_reqs": sum(1 for c in coverage if c["coverage_status"] == "PARTIAL"),
            "uncovered_reqs": sum(1 for c in coverage if c["coverage_status"] == "UNCOVERED"),
            "overmerged_scenarios": len(overmerge),
            "environment_notes": sum(1 for s in atomic if s.classification in {CAT_ENVIRONMENT_NOTE, CAT_DATA_AVAILABILITY_GAP}),
        },
    }


# ---------------------------------------------------------------------------
# 9. Business scenarios (v3) + REQ-driven multi-step test cases
# ---------------------------------------------------------------------------


@dataclass
class BusinessScenario:
    id: str
    title: str
    workflow_context: str
    source_setup: str
    screen: str
    priority_hint: str
    req_ids: list[str]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


# Ordered rules. First rule that matches wins. Each rule returns
# (scenario_id, title, workflow_context, source_setup, screen).
def _scenario_key_for_req(req: EffectiveRequirement) -> tuple[str, str, str, str, str]:
    text = req.requirement_text.lower()
    subsection = (req.source_subsection or "").lower()
    section = req.source_section.lower()

    def _has(*keys: str) -> bool:
        return any(k in text for k in keys)

    # 1. UI review (P2) — from comments or explicit UI review REQ text
    if req.classification in {CAT_QA_REVIEW_REQUEST, CAT_UI_REVIEW_REQUEST} or _has(
        "wording", "naming convention", "conciseness", "graph colour", "graph color",
        "clarity and consistency of graph", "colour clarity",
    ):
        return ("SCEN-UI-REVIEW", "UI review: wording, naming, and graph colour consistency",
                "Latest UI build for Submitted IDC Recommendations", "N/A",
                "Submitted IDC Recommendations view")

    # 2. Gate closure (BMU / Non-BMU / shift)
    if "gate closure" in text or (("bmu" in text or "non-bmu" in text) and ("1 hour" in text or "15 minutes" in text or "15 min" in text)):
        return ("SCEN-GATE-CLOSURE", "Gate closure line: BMU / Non-BMU / shift to next upcoming SP",
                "Data with BMU and Non-BMU assets across upcoming SPs", "Volue send + EPEX submit data",
                "Submitted IDC Recommendations graph")

    # 3. Status refresh polling
    if _has("every minute", "retrieved every minute"):
        return ("SCEN-STATUS-POLLING", "Status refresh cadence: every 1 minute",
                "Active view with at least one submitted record", "Live status feed",
                "Submitted IDC Recommendations view")

    # 4. Send-to-Volue cadence (Open Question resolved answer)
    if section == "open questions" and _has("24/7", "every 5 mins", "5 mins for the next 2 hours"):
        return ("SCEN-SEND-CADENCE", "Send-to-Volue cadence: 24/7, every 5 minutes for the next 2 hours (next 4 SPs)",
                "Recommendation generator active", "Optimiser + Volue integration",
                "Submitted IDC Recommendations view")

    # 5. Historical date-range support (Open Question)
    if section == "open questions" and _has("historical", "date range"):
        return ("SCEN-HISTORICAL-RANGE", "Historical date-range support (resolved: Yes)",
                "Historical data available across multiple dates", "Volue-submitted historical records",
                "Submitted IDC Recommendations view (historical range)")

    # 6. Past delivery date branch
    if req.source_subsection == "AC-past" or section == "alternate flow" or _has("past delivery date", "past-date"):
        return ("SCEN-PAST-DATE", "Past delivery date flow (Alternate Flow)",
                "Historical past-date data for IDC", "Volue-submitted historical records",
                "Submitted IDC Recommendations view (past date)")

    # 7-10. AC-today value/status scenarios (bid vs offer, value vs status kept separate)
    if req.source_subsection == "AC-today":
        if "status" in text and "bid" in text:
            return ("SCEN-TODAY-BID-STATUS", "Today: submitted IDC bid status",
                    "Today delivery date with submitted bid records", "Volue-submitted bids",
                    "Submitted IDC Recommendations view")
        if "status" in text and "offer" in text:
            return ("SCEN-TODAY-OFFER-STATUS", "Today: submitted IDC offer status",
                    "Today delivery date with submitted offer records", "Volue-submitted offers",
                    "Submitted IDC Recommendations view")
        if "bid" in text:
            return ("SCEN-TODAY-BID", "Today: submitted IDC bid data (price and volume per in-horizon SP)",
                    "Today delivery date with in-horizon submitted bid records", "Volue-submitted bid prices and volumes",
                    "Submitted IDC Recommendations view")
        if "offer" in text:
            return ("SCEN-TODAY-OFFER", "Today: submitted IDC offer data (price and volume per in-horizon SP)",
                    "Today delivery date with in-horizon submitted offer records", "Volue-submitted offer prices and volumes",
                    "Submitted IDC Recommendations view")

    # 11. "What a user needs" mirrors the AC-today classifications
    if "what a user" in section:
        if _has("status of the submitted idc recommended bids", "status of the sent bid"):
            return ("SCEN-TODAY-BID-STATUS", "Today: submitted IDC bid status",
                    "Today delivery date with submitted bid records", "Volue-submitted bids",
                    "Submitted IDC Recommendations view")
        if _has("status of the submitted idc recommended offers", "status of the sent offer"):
            return ("SCEN-TODAY-OFFER-STATUS", "Today: submitted IDC offer status",
                    "Today delivery date with submitted offer records", "Volue-submitted offers",
                    "Submitted IDC Recommendations view")
        if _has("bid price", "bid volume"):
            return ("SCEN-TODAY-BID", "Today: submitted IDC bid data (price and volume per in-horizon SP)",
                    "Today delivery date with in-horizon submitted bid records", "Volue-submitted bid prices and volumes",
                    "Submitted IDC Recommendations view")
        if _has("offer price", "offer volume"):
            return ("SCEN-TODAY-OFFER", "Today: submitted IDC offer data (price and volume per in-horizon SP)",
                    "Today delivery date with in-horizon submitted offer records", "Volue-submitted offer prices and volumes",
                    "Submitted IDC Recommendations view")

    # 12. Primary flow: delivery date defaults to today
    if section == "primary flow" and "today" in text and "delivery date" in text:
        return ("SCEN-TODAY-DEFAULT", "Primary flow: delivery date defaults to today",
                "Fresh session opening the Submitted IDC Recommendations view", "Any live data",
                "Submitted IDC Recommendations view")

    # 13. In-horizon boundary — only for REQs whose main assertion IS the horizon boundary
    if _has("next 4 upcoming settlement", "next 4 sps", "2 hour horizon", "2-hour horizon", "within the upcoming 2-hour", "within a 2 hour horizon"):
        return ("SCEN-HORIZON", "In-horizon boundary: next 4 SPs / 2-hour horizon",
                "Data spanning in-horizon and out-of-horizon SPs", "Volue-sent + EPEX-submitted data",
                "Submitted IDC Recommendations view")

    # 14. 2.2 Table row details
    if "2.2" in subsection or "table" in subsection or _has("start time of the sp", "pn initial"):
        return ("SCEN-TABLE-ROW", "Submitted IDC table row details: SP Start Time, PN Initial, values, Volue Active \u2192 UI Submitted",
                "Table view populated with at least one in-horizon submitted record",
                "Volue-submitted records with status = Active",
                "Submitted IDC Recommendations table")

    # 15. 2.1 Graph submission states + graph MW + real-time + hover-price
    if "2.1" in subsection or ("graph" in subsection and "table" not in subsection) or _has("graph mw", "graph \u00a3/mwh", "graph time period", "real-time"):
        return ("SCEN-GRAPH-STATES", "Graph submission states: Sent-to-Volue / Submitted-to-EPEX, MW, price on hover, real-time",
                "Graph loaded for the selected delivery date with mixed sent/submitted records",
                "Volue-sent + EPEX-submitted graph traces",
                "Submitted IDC Recommendations graph")

    # 16. Primary flow catch-all
    if section == "primary flow":
        return ("SCEN-PRIMARY-FLOW", "Primary submission viewing flow",
                "Trader logged in with IDC market selected", "Volue-sent + EPEX-submitted data",
                "Submitted IDC Recommendations view")

    # 17. Comments catch-all -> UI review
    if section == "comments":
        return ("SCEN-UI-REVIEW", "UI review: wording, naming, and graph colour consistency",
                "Latest UI build for Submitted IDC Recommendations", "N/A",
                "Submitted IDC Recommendations view")

    return ("SCEN-OTHER", "Other supporting requirements",
            "Standard IDC setup", "Live data",
            "Submitted IDC Recommendations view")


def build_business_scenarios(
    effective_reqs: list[EffectiveRequirement],
    atomic_statements: list[AtomicStatement],
    work_item_id: int,
) -> list[BusinessScenario]:
    grouped: dict[str, dict[str, Any]] = {}
    for req in effective_reqs:
        sid, title, workflow, setup, screen = _scenario_key_for_req(req)
        entry = grouped.setdefault(sid, {
            "id": sid,
            "title": title,
            "workflow_context": workflow,
            "source_setup": setup,
            "screen": screen,
            "reqs": [],
        })
        entry["reqs"].append(req)

    scenarios: list[BusinessScenario] = []
    for entry in grouped.values():
        pris = [r.priority_hint for r in entry["reqs"]]
        priority = "P0" if "P0" in pris else ("P1" if "P1" in pris else "P2")
        scenarios.append(BusinessScenario(
            id=entry["id"],
            title=entry["title"],
            workflow_context=entry["workflow_context"],
            source_setup=entry["source_setup"],
            screen=entry["screen"],
            priority_hint=priority,
            req_ids=[r.req_id for r in entry["reqs"]],
        ))
    priority_order = {"P0": 0, "P1": 1, "P2": 2}
    scenarios.sort(key=lambda s: (priority_order.get(s.priority_hint, 3), s.id))
    return scenarios


def _majority_test_type_layer(reqs: list[EffectiveRequirement]) -> tuple[str, str]:
    counts_tt: dict[str, int] = {}
    counts_layer: dict[str, int] = {}
    for r in reqs:
        tt, layer = _infer_test_type_layer(r)
        counts_tt[tt] = counts_tt.get(tt, 0) + 1
        counts_layer[layer] = counts_layer.get(layer, 0) + 1
    tt = max(counts_tt.items(), key=lambda x: x[1])[0] if counts_tt else "Functional"
    layer = max(counts_layer.items(), key=lambda x: x[1])[0] if counts_layer else "End-to-End"
    return tt, layer


def generate_test_cases_v3(
    scenarios: list[BusinessScenario],
    effective_reqs: list[EffectiveRequirement],
    atomic_statements: list[AtomicStatement],
    work_item_id: int,
) -> list[TestCase]:
    req_by_id = {r.req_id: r for r in effective_reqs}
    global_pre = _global_preconditions(atomic_statements)
    cases: list[TestCase] = []
    for idx, scenario in enumerate(scenarios, start=1):
        scenario_reqs = [req_by_id[rid] for rid in scenario.req_ids if rid in req_by_id]
        # Deduplicate steps whose (action, expected) are identical -> merge covers lists.
        step_bucket: dict[tuple[str, str], list[str]] = {}
        order: list[tuple[str, str]] = []
        for req in scenario_reqs:
            action = _infer_action_scenario(scenario, req)
            expected = _infer_expected(req)
            key = (action, expected)
            if key not in step_bucket:
                step_bucket[key] = []
                order.append(key)
            if req.req_id not in step_bucket[key]:
                step_bucket[key].append(req.req_id)
        steps = [TestStep(action=k[0], expected_result=k[1], covers=step_bucket[k]) for k in order]
        test_type, layer = _majority_test_type_layer(scenario_reqs)
        preconditions = [
            f"Scenario: {scenario.id}",
            f"Workflow: {scenario.workflow_context}",
            f"Screen: {scenario.screen}",
            f"Source setup: {scenario.source_setup}",
        ] + global_pre
        cases.append(TestCase(
            id=f"TC-{work_item_id}-{idx:02d}",
            title=scenario.title,
            preconditions=preconditions,
            steps=steps,
            priority=scenario.priority_hint,
            test_type=test_type,
            layer=layer,
            source_requirements=list(scenario.req_ids),
        ))
    return cases


def _infer_action_scenario(scenario: BusinessScenario, req: EffectiveRequirement) -> str:
    subsection = req.source_subsection.lower()
    section = req.source_section.lower()
    if scenario.id == "SCEN-UI-REVIEW":
        return "Compare the visible wording, naming, and graph colour of the Submitted IDC Recommendations view against the approved design for the aspect below."
    if scenario.id == "SCEN-GATE-CLOSURE":
        return "Load the graph for a delivery date containing BMU and Non-BMU SPs and inspect the gate closure line placement for the aspect below."
    if scenario.id == "SCEN-STATUS-POLLING":
        return "Keep the Submitted IDC Recommendations view open for several minutes while a submission status changes at the source."
    if scenario.id == "SCEN-HORIZON":
        return "Load the Submitted IDC Recommendations view and inspect which settlement periods are included for the aspect below."
    if scenario.id == "SCEN-PAST-DATE":
        return "Select a past delivery date for IDC and load the Submitted IDC Recommendations view."
    if scenario.id == "SCEN-TABLE-ROW":
        return "Open the Submitted IDC Recommendations table and inspect the column/row content for the aspect below."
    if scenario.id == "SCEN-GRAPH-STATES":
        return "Open the Submitted IDC Recommendations graph for the selected delivery date and inspect the trace/label for the aspect below."
    if scenario.id in {"SCEN-TODAY-BID", "SCEN-TODAY-OFFER"}:
        return "Select today as the delivery date, ensure Volue has submitted the required records, and open the Submitted IDC Recommendations view."
    if scenario.id in {"SCEN-TODAY-BID-STATUS", "SCEN-TODAY-OFFER-STATUS"}:
        return "Select today as the delivery date and inspect the status column/badge for the record type below."
    if scenario.id == "SCEN-TODAY-DEFAULT":
        return "Open the Trading Cockpit and navigate to the IDC market on a fresh session."
    if scenario.id == "SCEN-HISTORICAL-RANGE":
        return "Select a historical date range for IDC and load the Submitted IDC Recommendations view."
    if scenario.id == "SCEN-SEND-CADENCE":
        return "Observe the recommendation-to-Volue send stream over a 2-hour window."
    if scenario.id == "SCEN-PRIMARY-FLOW":
        return "Execute the primary flow step described in the requirement."
    return _infer_action(req)


# ---------------------------------------------------------------------------
# 10. Undermerge (advisory) detection
# ---------------------------------------------------------------------------


def detect_undermerge(test_cases: list[TestCase]) -> list[dict[str, Any]]:
    groups: dict[tuple[Any, ...], list[TestCase]] = {}
    for tc in test_cases:
        pre_key = tuple(sorted(p for p in tc.preconditions if not p.startswith("Scenario:")))
        key = (pre_key, tc.test_type, tc.layer)
        groups.setdefault(key, []).append(tc)
    findings: list[dict[str, Any]] = []
    for key, tcs in groups.items():
        if len(tcs) >= 3:
            findings.append({
                "flag": "UNDERMERGED_SCENARIO_SET",
                "shared_preconditions": list(key[0]),
                "shared_test_type": key[1],
                "shared_layer": key[2],
                "test_case_ids": [tc.id for tc in tcs],
                "recommendation": "Consider consolidating into one scenario with multiple step assertions.",
                "advisory": True,
            })
    return findings


# ---------------------------------------------------------------------------
# 11. Top-level v3 entry point
# ---------------------------------------------------------------------------


def run_review_v3(
    work_item: dict[str, Any],
    comments: list[dict[str, Any]],
    work_item_id: int,
) -> dict[str, Any]:
    blocks = parse_sections(work_item, comments)
    atomic = extract_atomic_statements(blocks, work_item_id)
    effective_reqs = build_effective_requirements(atomic, work_item_id)
    scenarios = build_business_scenarios(effective_reqs, atomic, work_item_id)
    test_cases = generate_test_cases_v3(scenarios, effective_reqs, atomic, work_item_id)
    overmerge = detect_overmerge(test_cases, effective_reqs)
    undermerge = detect_undermerge(test_cases)
    coverage = build_coverage_matrix(effective_reqs, test_cases)
    decomp = check_decomposition_completeness(atomic, effective_reqs)
    status, reasons = compute_review_status(atomic, effective_reqs, coverage, overmerge)

    resolved_qs = [s.as_dict() for s in atomic if s.classification == CAT_OPEN_QUESTION_RESOLVED]
    deferred_qs = [s.as_dict() for s in atomic if s.classification == CAT_DEFERRED_OUT_OF_SCOPE]
    unresolved_qs = [s.as_dict() for s in atomic if s.classification == CAT_OPEN_QUESTION_UNRESOLVED]

    return {
        "work_item_id": work_item_id,
        "atomic_statements": [s.as_dict() for s in atomic],
        "effective_requirements": [r.as_dict() for r in effective_reqs],
        "business_scenarios": [s.as_dict() for s in scenarios],
        "test_cases": [t.as_dict() for t in test_cases],
        "overmerge_findings": overmerge,
        "undermerge_findings": undermerge,
        "coverage_matrix": coverage,
        "decomposition": decomp,
        "review_status": status,
        "review_status_reasons": reasons,
        "resolved_open_questions": resolved_qs,
        "deferred_open_questions": deferred_qs,
        "unresolved_open_questions": unresolved_qs,
        "counts": {
            "atomic_statements": len(atomic),
            "testable_statements": sum(1 for s in atomic if s.testable),
            "effective_requirements": len(effective_reqs),
            "business_scenarios": len(scenarios),
            "test_cases": len(test_cases),
            "covered_reqs": sum(1 for c in coverage if c["coverage_status"] == "COVERED"),
            "partial_reqs": sum(1 for c in coverage if c["coverage_status"] == "PARTIAL"),
            "uncovered_reqs": sum(1 for c in coverage if c["coverage_status"] == "UNCOVERED"),
            "overmerged_scenarios": len(overmerge),
            "undermerged_sets": len(undermerge),
            "environment_notes": sum(1 for s in atomic if s.classification in {CAT_ENVIRONMENT_NOTE, CAT_DATA_AVAILABILITY_GAP}),
            "resolved_open_questions": len(resolved_qs),
            "deferred_open_questions": len(deferred_qs),
            "unresolved_open_questions": len(unresolved_qs),
        },
    }
