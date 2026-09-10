from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AtomicStatement:
    statement_id: str
    source: str
    source_section: str
    source_subsection: str
    original_text: str
    classification: str
    testable: bool
    reason: str
    priority_hint: str = "P1"


@dataclass
class Requirement:
    req_id: str
    statement_id: str
    requirement_text: str
    source_section: str
    source_subsection: str
    classification: str
    priority_hint: str


@dataclass
class BusinessScenario:
    scenario_id: str
    title: str
    workflow_context: str
    source_setup: str
    screen: str
    priority_hint: str
    req_ids: list[str] = field(default_factory=list)


@dataclass
class TestStep:
    action: str
    expected_result: str
    covers: list[str] = field(default_factory=list)


@dataclass
class TestCase:
    id: str
    title: str
    preconditions: list[str] = field(default_factory=list)
    steps: list[TestStep] = field(default_factory=list)
    priority: str = "P1"
    test_type: str = "Functional"
    layer: str = "End-to-End"
    source_requirements: list[str] = field(default_factory=list)


@dataclass
class ReconciliationItem:
    review_test_case_id: str
    title: str
    scenario_id: str
    req_ids: list[str]
    classification: str
    matched_azure_case_id: int | None
    matched_azure_title: str | None
    match_score: int
    note: str


@dataclass
class PointAssignment:
    test_case_id: int
    configuration_id: int
    tester_id: str | None = None


@dataclass
class SuiteState:
    work_item_id: int
    plan_id: int
    suite_id: int
    membership_count: int
    point_count: int
    missing_points: list[int] = field(default_factory=list)
    duplicate_cases: list[int] = field(default_factory=list)


@dataclass
class ApplyResult:
    work_item_id: int
    plan_id: int
    suite_id: int
    dry_run: bool
    status: str
    summary: dict[str, Any] = field(default_factory=dict)
    created_ids: list[int] = field(default_factory=list)
    updated_ids: list[int] = field(default_factory=list)
    skipped_ids: list[int] = field(default_factory=list)
    failures: list[dict[str, Any]] = field(default_factory=list)
