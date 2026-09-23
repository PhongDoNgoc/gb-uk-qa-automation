import base64
import os
from dataclasses import dataclass
from typing import Any
import re
import time
import uuid

import requests


class AzureDevOpsError(Exception):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


@dataclass
class AzureConfig:
    org: str
    project: str
    pat: str


class AzureDevOpsClient:
    """Azure DevOps client for reading Azure Test Plans cases and managing automated test associations."""

    def __init__(self, config: AzureConfig, timeout: int = 30):
        self.config = config
        self.timeout = timeout
        token = base64.b64encode(f":{self.config.pat}".encode("ascii")).decode("ascii")
        self.headers = {
            "Authorization": f"Basic {token}",
            "Content-Type": "application/json",
        }
        self.base_url = f"https://dev.azure.com/{self.config.org}/{self.config.project}"

    @classmethod
    def from_env(cls) -> "AzureDevOpsClient":
        org = (os.getenv("AZDO_ORG") or "").strip()
        project = (os.getenv("AZDO_PROJECT") or "").strip()
        pat = (os.getenv("AZDO_PAT") or "").strip()
        return cls(AzureConfig(org=org, project=project, pat=pat))

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        response = None
        for attempt in range(3):
            try:
                response = requests.get(url, headers=self.headers, params=params, timeout=self.timeout)
            except requests.exceptions.RequestException as exc:
                if attempt < 2:
                    time.sleep(0.4 * (attempt + 1))
                    continue
                raise AzureDevOpsError(f"Network/DNS failure: {exc.__class__.__name__}") from None

            if response.status_code in {502, 503, 504} and attempt < 2:
                time.sleep(0.4 * (attempt + 1))
                continue
            break

        if response is None:
            raise AzureDevOpsError("Network/DNS failure: Unknown")

        if response.status_code == 401:
            raise AzureDevOpsError("401 Unauthorized", status_code=401)
        if response.status_code == 403:
            raise AzureDevOpsError("403 Forbidden", status_code=403)
        if response.status_code == 404:
            raise AzureDevOpsError("404 Not Found", status_code=404)
        if response.status_code >= 400:
            raise AzureDevOpsError(f"HTTP {response.status_code} error", status_code=response.status_code)

        data = response.json()
        if not isinstance(data, dict):
            raise AzureDevOpsError("Unexpected response format")
        return data

    def _get_with_headers(
        self,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], requests.structures.CaseInsensitiveDict[str]]:
        url = f"{self.base_url}{path}"
        response = None
        for attempt in range(3):
            try:
                response = requests.get(url, headers=self.headers, params=params, timeout=self.timeout)
            except requests.exceptions.RequestException as exc:
                if attempt < 2:
                    time.sleep(0.4 * (attempt + 1))
                    continue
                raise AzureDevOpsError(f"Network/DNS failure: {exc.__class__.__name__}") from None

            if response.status_code in {502, 503, 504} and attempt < 2:
                time.sleep(0.4 * (attempt + 1))
                continue
            break

        if response is None:
            raise AzureDevOpsError("Network/DNS failure: Unknown")

        if response.status_code == 401:
            raise AzureDevOpsError("401 Unauthorized", status_code=401)
        if response.status_code == 403:
            raise AzureDevOpsError("403 Forbidden", status_code=403)
        if response.status_code == 404:
            raise AzureDevOpsError("404 Not Found", status_code=404)
        if response.status_code >= 400:
            raise AzureDevOpsError(f"HTTP {response.status_code} error", status_code=response.status_code)

        data = response.json()
        if not isinstance(data, dict):
            raise AzureDevOpsError("Unexpected response format")
        return data, response.headers

    @staticmethod
    def _assigned_to_text(value: Any) -> str:
        if isinstance(value, dict):
            display = (value.get("displayName") or "").strip()
            unique = (value.get("uniqueName") or "").strip()
            if display and unique:
                return f"{display} <{unique}>"
            return display or unique
        return str(value or "").strip()

    @staticmethod
    def _normalize_token(value: str) -> str:
        return re.sub(r"[^a-z0-9]", "", value.strip().lower())

    @staticmethod
    def _extract_email(value: str) -> str:
        value = value.strip().lower()
        match = re.search(r"[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}", value)
        return match.group(0) if match else ""

    @staticmethod
    def _extract_username(value: str) -> str:
        text = value.strip()
        if "<" in text and ">" in text:
            text = text.split("<", 1)[0].strip()
        if "@" in text:
            text = text.split("@", 1)[0]
        return text.strip().lower()

    @staticmethod
    def _normalize_iteration_text(value: str) -> str:
        clean = value.strip().lower().replace("\\", "/").replace(" ", "")
        return re.sub(r"[^a-z0-9/]+", "", clean)

    @staticmethod
    def _iteration_matches(target: str, node_path: str, node_name: str) -> bool:
        target_norm = AzureDevOpsClient._normalize_iteration_text(target)
        path_norm = AzureDevOpsClient._normalize_iteration_text(node_path)
        name_norm = AzureDevOpsClient._normalize_iteration_text(node_name)
        if not target_norm:
            return False
        if target_norm in {path_norm, name_norm}:
            return True
        if path_norm.endswith("/" + target_norm):
            return True
        # Handles both spaced and unspaced sprint naming plus full path inputs.
        if target_norm.replace("/", "") == name_norm.replace("/", ""):
            return True
        return False

    @staticmethod
    def _identity_dict(value: Any) -> dict[str, str]:
        if not isinstance(value, dict):
            return {
                "display_name": str(value or "").strip(),
                "unique_name": "",
                "id": "",
                "descriptor": "",
            }
        return {
            "display_name": str(value.get("displayName") or "").strip(),
            "unique_name": str(value.get("uniqueName") or "").strip(),
            "id": str(value.get("id") or "").strip(),
            "descriptor": str(value.get("descriptor") or "").strip(),
        }

    @staticmethod
    def _identity_matches(
        candidate: dict[str, str],
        requested_text: str,
        requested_identity: dict[str, str] | None,
    ) -> bool:
        if requested_identity is None:
            requested_identity = {}

        candidate_id = candidate.get("id", "").lower()
        candidate_descriptor = candidate.get("descriptor", "").lower()
        candidate_unique = candidate.get("unique_name", "").lower()
        candidate_display = candidate.get("display_name", "")
        candidate_display_norm = AzureDevOpsClient._normalize_token(candidate_display)
        candidate_email = AzureDevOpsClient._extract_email(candidate_unique or candidate_display)
        candidate_user = AzureDevOpsClient._extract_username(candidate_unique or candidate_display)

        req_id = str(requested_identity.get("id") or "").lower()
        req_descriptor = str(requested_identity.get("descriptor") or "").lower()
        req_unique = str(requested_identity.get("unique_name") or "").lower()
        req_display = str(requested_identity.get("display_name") or "")
        req_display_norm = AzureDevOpsClient._normalize_token(req_display)
        req_email = AzureDevOpsClient._extract_email(req_unique or req_display)

        raw = requested_text.strip()
        raw_norm = AzureDevOpsClient._normalize_token(raw)
        raw_email = AzureDevOpsClient._extract_email(raw)

        # 1) Preferred identity ID/descriptor exact match.
        if req_id and candidate_id and req_id == candidate_id:
            return True
        if req_descriptor and candidate_descriptor and req_descriptor == candidate_descriptor:
            return True

        # 2) exact uniqueName/email.
        if req_unique and candidate_unique and req_unique == candidate_unique:
            return True
        if req_email and candidate_email and req_email == candidate_email:
            return True
        if raw_email and candidate_email and raw_email == candidate_email:
            return True

        # 3) normalized display name exact equivalence.
        if req_display_norm and candidate_display_norm and req_display_norm == candidate_display_norm:
            return True
        if raw_norm and candidate_display_norm and raw_norm == candidate_display_norm:
            return True

        return False

    @staticmethod
    def _extract_iteration_id(node: dict[str, Any], target_path: str) -> str | None:
        node_path = str(node.get("path") or "").strip().lower()
        node_name = str(node.get("name") or "").strip().lower()
        if AzureDevOpsClient._iteration_matches(target_path, node_path, node_name):
            return str(node.get("identifier") or node.get("id") or "") or None
        for child in node.get("children", []) or []:
            if isinstance(child, dict):
                result = AzureDevOpsClient._extract_iteration_id(child, target_path)
                if result:
                    return result
        return None

    @staticmethod
    def _find_iteration_node(node: dict[str, Any], target_path: str) -> dict[str, Any] | None:
        node_path = str(node.get("path") or "").strip().lower()
        node_name = str(node.get("name") or "").strip().lower()
        if AzureDevOpsClient._iteration_matches(target_path, node_path, node_name):
            return node
        for child in node.get("children", []) or []:
            if isinstance(child, dict):
                found = AzureDevOpsClient._find_iteration_node(child, target_path)
                if found is not None:
                    return found
        return None

    @staticmethod
    def _collect_iteration_nodes(node: dict[str, Any], target_path: str) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        node_path = str(node.get("path") or "").strip().lower()
        node_name = str(node.get("name") or "").strip().lower()
        if AzureDevOpsClient._iteration_matches(target_path, node_path, node_name):
            results.append(node)
        for child in node.get("children", []) or []:
            if isinstance(child, dict):
                results.extend(AzureDevOpsClient._collect_iteration_nodes(child, target_path))
        return results

    @staticmethod
    def _flatten_suites(suites: list[dict[str, Any]]) -> list[dict[str, Any]]:
        flat: list[dict[str, Any]] = []
        stack: list[dict[str, Any]] = list(suites)
        while stack:
            suite = stack.pop(0)
            if not isinstance(suite, dict):
                continue
            flat.append(suite)
            for child in suite.get("children", []) or []:
                if isinstance(child, dict):
                    stack.append(child)
        return flat

    def get_work_item(self, work_item_id: int) -> dict[str, Any]:
        data = self._get(
            f"/_apis/wit/workitems/{work_item_id}",
            params={"$expand": "all", "api-version": "7.1"},
        )
        fields = data.get("fields", {}) or {}
        return {
            "id": data.get("id"),
            "title": fields.get("System.Title"),
            "work_item_type": fields.get("System.WorkItemType"),
            "state": fields.get("System.State"),
            "description": fields.get("System.Description"),
            "acceptance_criteria": fields.get("Microsoft.VSTS.Common.AcceptanceCriteria"),
            "tags": fields.get("System.Tags"),
            "raw": data,
        }

    def get_work_item_full(self, work_item_id: int) -> dict[str, Any]:
        data = self._get(
            f"/_apis/wit/workitems/{work_item_id}",
            params={"$expand": "relations", "api-version": "7.1"},
        )
        fields = data.get("fields", {}) or {}
        return {
            "id": data.get("id"),
            "title": fields.get("System.Title"),
            "work_item_type": fields.get("System.WorkItemType"),
            "state": fields.get("System.State"),
            "assigned_to": self._assigned_to_text(fields.get("System.AssignedTo")),
            "assigned_identity": self._identity_dict(fields.get("System.AssignedTo")),
            "iteration_path": fields.get("System.IterationPath"),
            "description": fields.get("System.Description"),
            "acceptance_criteria": fields.get("Microsoft.VSTS.Common.AcceptanceCriteria"),
            "business_rules": fields.get("Custom.BusinessRules") or fields.get("Microsoft.VSTS.Common.BusinessValue"),
            "tags": fields.get("System.Tags"),
            "relations": data.get("relations", []) or [],
        }

    def get_work_item_comments(self, work_item_id: int) -> list[dict[str, Any]]:
        all_comments: list[dict[str, Any]] = []
        continuation_token: str | None = None
        seen_tokens: set[str] = set()
        page_count = 0
        while True:
            page_count += 1
            if page_count > 50:
                break
            params: dict[str, Any] = {
                "api-version": "7.1-preview.3",
                "$top": 200,
                "order": "asc",
            }
            if continuation_token:
                if continuation_token in seen_tokens:
                    break
                seen_tokens.add(continuation_token)
                params["continuationToken"] = continuation_token

            payload, headers = self._get_with_headers(
                f"/_apis/wit/workItems/{work_item_id}/comments",
                params=params,
            )
            comments = payload.get("comments", []) or []
            for comment in comments:
                if isinstance(comment, dict):
                    all_comments.append(
                        {
                            "id": comment.get("id"),
                            "text": comment.get("text") or "",
                            "createdDate": comment.get("createdDate"),
                            "modifiedDate": comment.get("modifiedDate"),
                            "createdBy": self._assigned_to_text(comment.get("createdBy")),
                        }
                    )

            continuation_token = (
                headers.get("x-ms-continuationtoken")
                or headers.get("x-ms-continuation-token")
                or payload.get("continuationToken")
            )
            if not continuation_token:
                break

        return all_comments

    def get_work_item_comment_count(self, work_item_id: int) -> int:
        comments = self.get_work_item_comments(work_item_id)
        return len(comments)

    def get_work_items_brief(self, ids: list[int], fields: list[str] | None = None) -> list[dict[str, Any]]:
        if not ids:
            return []
        field_list = fields or [
            "System.Title",
            "System.WorkItemType",
            "System.State",
            "System.AssignedTo",
            "System.IterationPath",
        ]

        unique_ids = sorted({int(v) for v in ids if isinstance(v, int) or str(v).isdigit()})
        results: list[dict[str, Any]] = []

        for i in range(0, len(unique_ids), 200):
            chunk = unique_ids[i : i + 200]
            payload = self._get(
                "/_apis/wit/workitems",
                params={
                    "ids": ",".join(str(v) for v in chunk),
                    "fields": ",".join(field_list),
                    "api-version": "7.1",
                },
            )

            for item in payload.get("value", []) or []:
                if not isinstance(item, dict):
                    continue
                fields_map = item.get("fields", {}) or {}
                results.append(
                    {
                        "id": item.get("id"),
                        "title": fields_map.get("System.Title") or "",
                        "type": fields_map.get("System.WorkItemType") or "",
                        "state": fields_map.get("System.State") or "",
                        "assigned_to": self._assigned_to_text(fields_map.get("System.AssignedTo")),
                        "assigned_identity": self._identity_dict(fields_map.get("System.AssignedTo")),
                        "iteration_path": fields_map.get("System.IterationPath") or "",
                    }
                )

        return results

    def resolve_iteration(self, iteration_path: str) -> dict[str, Any]:
        tree = self._get(
            "/_apis/wit/classificationnodes/iterations",
            params={"$depth": 10, "api-version": "7.1"},
        )
        matches = self._collect_iteration_nodes(tree, iteration_path)
        if not matches:
            return {
                "status": "NOT_FOUND",
                "identifier": None,
                "id": None,
                "name": "",
                "path": "",
                "candidates": [],
            }

        target_norm = self._normalize_iteration_text(iteration_path)
        ranked: list[tuple[int, dict[str, Any]]] = []
        for node in matches:
            path_norm = self._normalize_iteration_text(str(node.get("path") or ""))
            name_norm = self._normalize_iteration_text(str(node.get("name") or ""))
            rank = 3
            if path_norm == target_norm:
                rank = 0
            elif name_norm == target_norm:
                rank = 1
            elif path_norm.endswith("/" + target_norm):
                rank = 2
            ranked.append((rank, node))
        ranked.sort(key=lambda x: (x[0], str(x[1].get("path") or "")))
        node = ranked[0][1]

        candidates = [
            {
                "identifier": str(n.get("identifier") or "") or None,
                "id": n.get("id"),
                "name": str(n.get("name") or ""),
                "path": str(n.get("path") or ""),
            }
            for _, n in ranked
        ]

        return {
            "status": "FOUND",
            "identifier": str(node.get("identifier") or "") or None,
            "id": node.get("id"),
            "name": str(node.get("name") or ""),
            "path": str(node.get("path") or ""),
            "candidates": candidates,
        }

    def get_iteration_work_items(self, iteration_path: str, team: str | None = None) -> dict[str, Any]:
        iteration = self.resolve_iteration(iteration_path)
        if iteration.get("status") != "FOUND" or not iteration.get("identifier"):
            return {
                "status": "ITERATION_NOT_FOUND",
                "iteration": iteration,
                "work_items": [],
            }

        iteration_ids: list[str] = []
        first_identifier = str(iteration.get("identifier") or "")
        if first_identifier:
            iteration_ids.append(first_identifier)
        for cand in iteration.get("candidates") or []:
            cid = str((cand or {}).get("identifier") or "")
            if cid and cid not in iteration_ids:
                iteration_ids.append(cid)
        team_candidates: list[str] = []
        explicit_team = (team or "").strip()
        env_team = (os.getenv("AZDO_TEAM") or "").strip()
        if explicit_team:
            team_candidates.append(explicit_team)
        if env_team and env_team.lower() not in {x.lower() for x in team_candidates}:
            team_candidates.append(env_team)
        if self.config.project and self.config.project.lower() not in {x.lower() for x in team_candidates}:
            team_candidates.append(self.config.project)

        all_ids: set[int] = set()
        teams_used: list[str] = []
        last_error: AzureDevOpsError | None = None

        def collect_from_team(team_name: str, current_iteration_id: str) -> None:
            nonlocal last_error
            payload: dict[str, Any] | None = None
            paths = [
                f"/_apis/work/teamsettings/iterations/{current_iteration_id}/workitems",
                f"/{team_name}/_apis/work/teamsettings/iterations/{current_iteration_id}/workitems",
            ]
            for endpoint in paths:
                try:
                    payload = self._get(endpoint, params={"api-version": "7.1"})
                    break
                except AzureDevOpsError as exc:
                    last_error = exc
                    if "404" in str(exc) or "401" in str(exc) or "403" in str(exc):
                        continue
                    raise

            if payload is None:
                return

            teams_used.append(team_name)
            for rel in payload.get("workItemRelations", []) or []:
                target = rel.get("target") if isinstance(rel, dict) else None
                if isinstance(target, dict) and target.get("id"):
                    try:
                        all_ids.add(int(target.get("id")))
                    except (TypeError, ValueError):
                        continue

        for current_iteration_id in iteration_ids:
            before = len(all_ids)
            for team_name in team_candidates:
                collect_from_team(team_name, current_iteration_id)
            if len(all_ids) > before:
                break

        if not all_ids:
            try:
                discovered_teams = self._list_project_teams()
            except AzureDevOpsError:
                discovered_teams = []
            for current_iteration_id in iteration_ids:
                before = len(all_ids)
                for team_name in discovered_teams:
                    if team_name.lower() in {x.lower() for x in team_candidates}:
                        continue
                    collect_from_team(team_name, current_iteration_id)
                if len(all_ids) > before:
                    break

        if not all_ids and last_error is not None and "404" not in str(last_error):
            raise last_error

        items = self.get_work_items_brief(sorted(all_ids))
        return {
            "status": "FOUND",
            "iteration": iteration,
            "team_candidates": team_candidates,
            "teams_used": teams_used,
            "total_ids": len(all_ids),
            "work_items": sorted(items, key=lambda x: int(x.get("id") or 0)),
        }

    def get_assigned_work_items(
        self,
        iteration_path: str,
        assigned_to: str,
        work_item_types: list[str] | None = None,
        team: str | None = None,
        assigned_identity: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        iteration_data = self.get_iteration_work_items(iteration_path, team=team)
        batch_items = iteration_data.get("work_items") or []

        assigned_hint = assigned_to.strip()
        types = {t.strip().lower() for t in (work_item_types or ["Product Backlog Item", "User Story", "Bug"])}
        result: list[dict[str, Any]] = []

        for item in batch_items:
            if not isinstance(item, dict):
                continue
            item_type = str(item.get("type") or "")
            if item_type.strip().lower() not in types:
                continue

            assigned_identity_map = self._identity_dict(item.get("assigned_identity"))
            assigned_text = self._assigned_to_text(item.get("assigned_to"))
            if assigned_hint and not self._identity_matches(assigned_identity_map, assigned_hint, assigned_identity):
                continue

            result.append(
                {
                    "id": item.get("id"),
                    "title": item.get("title") or "",
                    "type": item_type,
                    "state": item.get("state") or "",
                    "assigned_to": assigned_text,
                    "assigned_identity": assigned_identity_map,
                    "iteration_path": item.get("iteration_path") or "",
                }
            )

        return sorted(result, key=lambda x: int(x.get("id") or 0))

    def _list_project_teams(self) -> list[str]:
        endpoint = "/_apis/projects/{project}/teams".format(project=self.config.project)
        params: dict[str, Any] = {"api-version": "7.1", "$top": 200}
        teams: list[str] = []
        continuation_token: str | None = None
        seen_tokens: set[str] = set()
        page_count = 0

        while True:
            page_count += 1
            if page_count > 25:
                break
            paged = dict(params)
            if continuation_token:
                if continuation_token in seen_tokens:
                    break
                seen_tokens.add(continuation_token)
                paged["continuationToken"] = continuation_token
            payload, headers = self._get_with_headers(endpoint, params=paged)
            for item in payload.get("value", []) or []:
                if isinstance(item, dict):
                    name = str(item.get("name") or "").strip()
                    if name:
                        teams.append(name)
            continuation_token = (
                headers.get("x-ms-continuationtoken")
                or headers.get("x-ms-continuation-token")
                or payload.get("continuationToken")
            )
            if not continuation_token:
                break

        unique: list[str] = []
        seen: set[str] = set()
        for t in teams:
            key = t.lower()
            if key not in seen:
                seen.add(key)
                unique.append(t)
        return unique

    def get_test_plan(self, plan_id: int) -> dict[str, Any]:
        return self._get(f"/_apis/testplan/Plans/{plan_id}", params={"api-version": "7.1"})

    def list_test_plans(self) -> list[dict[str, Any]]:
        endpoint = "/_apis/testplan/Plans"
        params: dict[str, Any] = {"api-version": "7.1", "$top": 100}
        plans: list[dict[str, Any]] = []
        continuation_token: str | None = None

        while True:
            paged = dict(params)
            if continuation_token:
                paged["continuationToken"] = continuation_token

            payload, headers = self._get_with_headers(endpoint, params=paged)
            plans.extend(payload.get("value", []) or [])
            continuation_token = (
                headers.get("x-ms-continuationtoken")
                or headers.get("x-ms-continuation-token")
                or payload.get("continuationToken")
            )
            if not continuation_token:
                break

        return plans

    def discover_test_plan_for_sprint(self, sprint_name: str, configured_plan_id: int | None = None) -> dict[str, Any]:
        sprint_target = self._normalize_iteration_text(sprint_name)
        plans = self.list_test_plans()

        # Preferred strategy: match plan name to sprint.
        best_name_match: dict[str, Any] | None = None
        for plan in plans:
            name = str(plan.get("name") or "").strip()
            norm_name = self._normalize_iteration_text(name)
            if not sprint_target or not norm_name:
                continue
            exact = norm_name == sprint_target or norm_name.endswith(sprint_target)
            contains = sprint_target in norm_name
            if exact:
                best_name_match = {
                    "status": "FOUND",
                    "plan_id": plan.get("id"),
                    "plan_name": name,
                    "source": "NAME_MATCH_EXACT",
                }
                break
            if contains and best_name_match is None:
                best_name_match = {
                    "status": "FOUND",
                    "plan_id": plan.get("id"),
                    "plan_name": name,
                    "source": "NAME_MATCH_PARTIAL",
                }

        if best_name_match is not None:
            return best_name_match

        # Fallback: configured plan id.
        if configured_plan_id:
            try:
                plan = self.get_test_plan(configured_plan_id)
                return {
                    "status": "FOUND",
                    "plan_id": plan.get("id"),
                    "plan_name": plan.get("name") or "",
                    "source": "CONFIGURED_PLAN_ID_FALLBACK",
                }
            except AzureDevOpsError:
                pass

        return {"status": "NOT_FOUND", "plan_id": None, "plan_name": "", "source": "NONE"}

    def list_plan_suites(self, plan_id: int) -> list[dict[str, Any]]:
        payload = self._get(
            f"/_apis/testplan/Plans/{plan_id}/Suites",
            params={"api-version": "7.1", "asTreeView": "true"},
        )
        suites = payload.get("value", []) or []
        return self._flatten_suites([s for s in suites if isinstance(s, dict)])

    def discover_requirement_suite(self, plan_id: int, work_item_id: int) -> dict[str, Any]:
        suites = self.list_plan_suites(plan_id)
        return self.resolve_requirement_suite_from_suites(suites, work_item_id)

    def resolve_requirement_suite_from_suites(self, suites: list[dict[str, Any]], work_item_id: int) -> dict[str, Any]:
        work_item_str = str(work_item_id)
        candidates: list[dict[str, Any]] = []

        for suite in suites:
            if not isinstance(suite, dict):
                continue

            suite_id = suite.get("id")
            suite_name = str(suite.get("name") or "")
            suite_type = str(suite.get("suiteType") or suite.get("type") or "")

            requirement_raw = suite.get("requirementId")
            if isinstance(requirement_raw, dict):
                requirement_raw = requirement_raw.get("id")
            requirement_text = str(requirement_raw or "").strip()

            linked_req_id = ""
            req_obj = suite.get("requirement")
            if isinstance(req_obj, dict):
                linked_req_id = str(req_obj.get("id") or "").strip()

            rule = ""
            rank = 99

            # Rule 1: suite.requirementId == work item id.
            if requirement_text and requirement_text == work_item_str:
                rule = "REQUIREMENT_ID_EXACT"
                rank = 1
            # Rule 2: linked requirement object id == work item id.
            elif linked_req_id and linked_req_id == work_item_str:
                rule = "LINKED_REQUIREMENT_ID_EXACT"
                rank = 2
            # Rule 3: fallback by suite name containing work item id.
            elif work_item_str and work_item_str in suite_name:
                rule = "SUITE_NAME_CONTAINS_ID"
                rank = 3

            if rule:
                candidates.append(
                    {
                        "suite_id": suite_id,
                        "suite_name": suite_name,
                        "suite_type": suite_type,
                        "requirement_id": requirement_text or linked_req_id or None,
                        "rule": rule,
                        "rank": rank,
                    }
                )

        if not candidates:
            return {
                "status": "NOT_FOUND",
                "suite_id": None,
                "suite_name": "",
                "suite_type": "",
                "requirement_id": None,
                "resolution_rule": "NONE",
                "ambiguity": False,
                "candidates": [],
            }

        ordered = sorted(candidates, key=lambda x: (int(x.get("rank") or 99), str(x.get("suite_id") or "")))
        best = ordered[0]
        same_rank = [c for c in ordered if int(c.get("rank") or 99) == int(best.get("rank") or 99)]

        ambiguity = len(same_rank) > 1
        status = "AMBIGUOUS" if ambiguity else "FOUND"

        return {
            "status": status,
            "suite_id": best.get("suite_id"),
            "suite_name": best.get("suite_name") or "",
            "suite_type": best.get("suite_type") or "",
            "requirement_id": best.get("requirement_id"),
            "resolution_rule": best.get("rule") or "NONE",
            "ambiguity": ambiguity,
            "candidates": ordered,
        }

    def get_suite_test_cases(self, plan_id: int, suite_id: int) -> list[dict[str, Any]]:
        # Test Plan endpoint returns work item metadata per test case.
        endpoint = f"/_apis/testplan/Plans/{plan_id}/Suites/{suite_id}/TestCase"
        params: dict[str, Any] = {"api-version": "7.1", "isRecursive": "true"}

        raw_cases: list[dict[str, Any]] = []
        continuation_token: str | None = None
        seen_tokens: set[str] = set()
        page_count = 0

        while True:
            page_count += 1
            if page_count > 50:
                break
            paged_params = dict(params)
            if continuation_token:
                if continuation_token in seen_tokens:
                    break
                seen_tokens.add(continuation_token)
                paged_params["continuationToken"] = continuation_token

            payload, headers = self._get_with_headers(endpoint, params=paged_params)
            raw_cases.extend(payload.get("value", []) or [])

            continuation_token = (
                headers.get("x-ms-continuationtoken")
                or headers.get("x-ms-continuation-token")
                or payload.get("continuationToken")
            )
            if not continuation_token:
                break

        normalized: list[dict[str, Any]] = []
        seen_ids: set[int] = set()

        for item in raw_cases:
            if not isinstance(item, dict):
                continue

            case_id: Any = None
            title: str | None = None

            work_item = item.get("workItem")
            test_case = item.get("testCase")

            if isinstance(work_item, dict):
                case_id = work_item.get("id")
                title = work_item.get("name") or work_item.get("title")
            if case_id is None and isinstance(test_case, dict):
                case_id = test_case.get("id")
                title = test_case.get("name") or test_case.get("title")
            if case_id is None:
                case_id = item.get("id")
                if title is None:
                    title = item.get("name") or item.get("title")

            try:
                normalized_id = int(case_id)
            except (TypeError, ValueError):
                continue

            if normalized_id in seen_ids:
                continue
            seen_ids.add(normalized_id)

            details = self.get_test_case(normalized_id)
            normalized.append(
                {
                    "id": str(normalized_id),
                    "title": details.get("title") or title or "",
                    "state": details.get("state") or "",
                    "steps": details.get("steps"),
                }
            )

        return normalized

    def get_suite_test_case_count(self, plan_id: int, suite_id: int) -> int:
        endpoint = f"/_apis/testplan/Plans/{plan_id}/Suites/{suite_id}/TestCase"
        params: dict[str, Any] = {"api-version": "7.1", "isRecursive": "true"}

        count = 0
        continuation_token: str | None = None
        seen_tokens: set[str] = set()
        page_count = 0
        seen_ids: set[int] = set()

        while True:
            page_count += 1
            if page_count > 50:
                break
            paged = dict(params)
            if continuation_token:
                if continuation_token in seen_tokens:
                    break
                seen_tokens.add(continuation_token)
                paged["continuationToken"] = continuation_token

            payload, headers = self._get_with_headers(endpoint, params=paged)
            for item in payload.get("value", []) or []:
                if not isinstance(item, dict):
                    continue
                case_id: Any = None
                wi = item.get("workItem")
                tc = item.get("testCase")
                if isinstance(wi, dict):
                    case_id = wi.get("id")
                if case_id is None and isinstance(tc, dict):
                    case_id = tc.get("id")
                if case_id is None:
                    case_id = item.get("id")
                try:
                    normalized_id = int(case_id)
                except (TypeError, ValueError):
                    continue
                if normalized_id in seen_ids:
                    continue
                seen_ids.add(normalized_id)
                count += 1

            continuation_token = (
                headers.get("x-ms-continuationtoken")
                or headers.get("x-ms-continuation-token")
                or payload.get("continuationToken")
            )
            if not continuation_token:
                break

        return count

    def get_test_case(self, test_case_id: int) -> dict[str, Any]:
        fields = [
            "System.Title",
            "System.State",
            "System.Description",
            "Microsoft.VSTS.TCM.Steps",
            "Microsoft.VSTS.Common.Priority",
            "Microsoft.VSTS.TCM.AutomatedTestId",
            "Microsoft.VSTS.TCM.AutomatedTestName",
            "Microsoft.VSTS.TCM.AutomatedTestStorage",
            "Microsoft.VSTS.TCM.AutomatedTestType",
            "Microsoft.VSTS.TCM.AutomationStatus",
        ]
        data = self._get(
            f"/_apis/wit/workitems/{test_case_id}",
            params={"fields": ",".join(fields), "api-version": "7.1"},
        )
        f = data.get("fields", {}) or {}
        return {
            "id": data.get("id"),
            "rev": data.get("rev"),
            "title": f.get("System.Title"),
            "state": f.get("System.State"),
            "description": f.get("System.Description"),
            "steps": f.get("Microsoft.VSTS.TCM.Steps"),
            "priority": f.get("Microsoft.VSTS.Common.Priority"),
            "automated_test_id": f.get("Microsoft.VSTS.TCM.AutomatedTestId"),
            "automated_test_name": f.get("Microsoft.VSTS.TCM.AutomatedTestName"),
            "automated_test_storage": f.get("Microsoft.VSTS.TCM.AutomatedTestStorage"),
            "automated_test_type": f.get("Microsoft.VSTS.TCM.AutomatedTestType"),
            "automation_status": f.get("Microsoft.VSTS.TCM.AutomationStatus"),
        }

    def associate_automated_test(
        self,
        test_case_id: int,
        *,
        automated_test_name: str,
        automated_test_storage: str,
        automated_test_type: str = "NUnit",
        automated_test_id: str | None = None,
    ) -> dict[str, Any]:
        normalized_name = automated_test_name.strip()
        normalized_storage = automated_test_storage.strip()
        normalized_type = automated_test_type.strip() or "NUnit"

        if not normalized_name:
            raise ValueError("Automated test name is required.")
        if not normalized_storage:
            raise ValueError("Automated test storage is required.")

        test_id = (automated_test_id or "").strip().upper()
        if not test_id:
            identity = f"{normalized_storage}|{normalized_type}|{normalized_name}"
            test_id = str(uuid.uuid5(uuid.NAMESPACE_URL, identity)).upper()

        patch_document = [
            {"op": "add", "path": "/fields/Microsoft.VSTS.TCM.AutomatedTestName", "value": normalized_name},
            {"op": "add", "path": "/fields/Microsoft.VSTS.TCM.AutomatedTestStorage", "value": normalized_storage},
            {"op": "add", "path": "/fields/Microsoft.VSTS.TCM.AutomatedTestType", "value": normalized_type},
            {"op": "add", "path": "/fields/Microsoft.VSTS.TCM.AutomatedTestId", "value": test_id},
            {"op": "add", "path": "/fields/Microsoft.VSTS.TCM.AutomationStatus", "value": "Automated"},
        ]
        return self.update_work_item(test_case_id, patch_document)

    def update_work_item(
        self,
        work_item_id: int,
        patch_document: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return self._send(
            "PATCH",
            f"/_apis/wit/workitems/{int(work_item_id)}",
            params={"api-version": "7.1"},
            json_body=patch_document,
            content_type="application/json-patch+json",
        )

    def _send(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any = None,
        content_type: str = "application/json",
    ) -> Any:
        url = f"{self.base_url}{path}"
        headers = dict(self.headers)
        headers["Content-Type"] = content_type
        response = None
        for attempt in range(3):
            try:
                response = requests.request(
                    method,
                    url,
                    headers=headers,
                    params=params,
                    json=json_body,
                    timeout=self.timeout,
                )
            except requests.exceptions.RequestException as exc:
                if attempt < 2:
                    time.sleep(0.4 * (attempt + 1))
                    continue
                raise AzureDevOpsError(f"Network/DNS failure: {exc.__class__.__name__}") from None

            if response.status_code in {502, 503, 504} and attempt < 2:
                time.sleep(0.4 * (attempt + 1))
                continue
            break

        if response is None:
            raise AzureDevOpsError("Network/DNS failure: Unknown")

        if response.status_code == 401:
            raise AzureDevOpsError("401 Unauthorized", status_code=401)
        if response.status_code == 403:
            raise AzureDevOpsError("403 Forbidden", status_code=403)
        if response.status_code == 404:
            raise AzureDevOpsError("404 Not Found", status_code=404)
        if response.status_code >= 400:
            snippet = (response.text or "")[:400]
            raise AzureDevOpsError(
                f"HTTP {response.status_code} error: {snippet}",
                status_code=response.status_code,
            )

        if not response.content:
            return None
        try:
            return response.json()
        except ValueError as exc:
            raise AzureDevOpsError(f"Unexpected response format: {exc}") from None

    def create_test_case_work_item(
        self,
        *,
        title: str,
        steps_xml: str,
        description_html: str | None = None,
        priority: int | None = None,
        assigned_to: str | None = None,
        area_path: str | None = None,
        iteration_path: str | None = None,
    ) -> dict[str, Any]:
        patch: list[dict[str, Any]] = [
            {"op": "add", "path": "/fields/System.Title", "value": title},
            {"op": "add", "path": "/fields/Microsoft.VSTS.TCM.Steps", "value": steps_xml},
        ]
        if description_html:
            patch.append({"op": "add", "path": "/fields/System.Description", "value": description_html})
        if priority is not None:
            patch.append({"op": "add", "path": "/fields/Microsoft.VSTS.Common.Priority", "value": int(priority)})
        if assigned_to:
            patch.append({"op": "add", "path": "/fields/System.AssignedTo", "value": assigned_to})
        if area_path:
            patch.append({"op": "add", "path": "/fields/System.AreaPath", "value": area_path})
        if iteration_path:
            patch.append({"op": "add", "path": "/fields/System.IterationPath", "value": iteration_path})

        return self._send(
            "POST",
            "/_apis/wit/workitems/$Test%20Case",
            params={"api-version": "7.1"},
            json_body=patch,
            content_type="application/json-patch+json",
        )

    def add_test_case_to_suite(
        self,
        plan_id: int,
        suite_id: int,
        test_case_id: int,
        configuration_ids: list[int] | None = None,
    ) -> Any:
        body_item: dict[str, Any] = {"workItem": {"id": int(test_case_id)}}
        if configuration_ids:
            body_item["pointAssignments"] = [{"configurationId": int(cfg_id)} for cfg_id in configuration_ids]
        body = [body_item]
        return self._send(
            "POST",
            f"/_apis/testplan/Plans/{int(plan_id)}/Suites/{int(suite_id)}/TestCase",
            params={"api-version": "7.1"},
            json_body=body,
        )

    def get_suite_test_cases_test_api(self, plan_id: int, suite_id: int) -> list[dict[str, Any]]:
        payload = self._get(
            f"/_apis/test/Plans/{int(plan_id)}/suites/{int(suite_id)}/testcases",
            params={"api-version": "7.1"},
        )
        values = payload.get("value", []) or []
        normalized: list[dict[str, Any]] = []
        for item in values:
            if not isinstance(item, dict):
                continue
            tc = item.get("testCase") if isinstance(item.get("testCase"), dict) else {}
            tc_id = tc.get("id")
            try:
                norm_id = int(tc_id)
            except (TypeError, ValueError):
                continue

            point_assignments: list[dict[str, Any]] = []
            for pa in item.get("pointAssignments", []) or []:
                if not isinstance(pa, dict):
                    continue
                cfg = pa.get("configuration") if isinstance(pa.get("configuration"), dict) else {}
                tester = pa.get("tester") if isinstance(pa.get("tester"), dict) else {}
                point_assignments.append(
                    {
                        "configuration_id": int(cfg.get("id")) if str(cfg.get("id") or "").isdigit() else None,
                        "configuration_name": cfg.get("name"),
                        "tester_id": tester.get("id"),
                        "tester_display_name": tester.get("displayName"),
                        "tester_unique_name": tester.get("uniqueName"),
                    }
                )

            normalized.append(
                {
                    "id": norm_id,
                    "point_assignments": point_assignments,
                }
            )
        return normalized

    def get_suite_test_points(self, plan_id: int, suite_id: int) -> list[dict[str, Any]]:
        payload = self._get(
            f"/_apis/test/Plans/{int(plan_id)}/suites/{int(suite_id)}/points",
            params={"api-version": "7.1", "$top": 1000},
        )
        values = payload.get("value", []) or []
        normalized: list[dict[str, Any]] = []
        for item in values:
            if not isinstance(item, dict):
                continue
            point_id = item.get("id")
            tc = item.get("testCase") if isinstance(item.get("testCase"), dict) else {}
            cfg = item.get("configuration") if isinstance(item.get("configuration"), dict) else {}
            tester = item.get("tester") if isinstance(item.get("tester"), dict) else {}
            try:
                tc_id = int(tc.get("id"))
            except (TypeError, ValueError):
                tc_id = None
            normalized.append(
                {
                    "id": int(point_id) if str(point_id or "").isdigit() else None,
                    "test_case_id": tc_id,
                    "configuration_id": int(cfg.get("id")) if str(cfg.get("id") or "").isdigit() else None,
                    "configuration_name": cfg.get("name"),
                    "tester_id": tester.get("id"),
                    "tester_display_name": tester.get("displayName"),
                    "tester_unique_name": tester.get("uniqueName"),
                }
            )
        return normalized

    def resolve_effective_suite_configuration_ids(self, plan_id: int, suite_id: int) -> list[int]:
        suites = self.list_plan_suites(plan_id)
        by_id: dict[int, dict[str, Any]] = {}
        for s in suites:
            sid = s.get("id")
            try:
                by_id[int(sid)] = s
            except (TypeError, ValueError):
                continue

        visited: set[int] = set()
        current = int(suite_id)
        while current in by_id and current not in visited:
            visited.add(current)
            suite = by_id[current]
            cfgs = suite.get("defaultConfigurations") or []
            ids: list[int] = []
            for c in cfgs:
                if not isinstance(c, dict):
                    continue
                cid = c.get("id")
                if str(cid or "").isdigit():
                    ids.append(int(cid))
            if ids:
                # Keep order stable and unique.
                ordered: list[int] = []
                seen: set[int] = set()
                for cid in ids:
                    if cid not in seen:
                        seen.add(cid)
                        ordered.append(cid)
                return ordered

            parent = suite.get("parentSuite") if isinstance(suite.get("parentSuite"), dict) else {}
            parent_id = parent.get("id")
            if not str(parent_id or "").isdigit():
                break
            current = int(parent_id)

        return []

    def update_suite_test_case_configurations(
        self,
        plan_id: int,
        suite_id: int,
        test_case_ids: list[int],
        configuration_ids: list[int],
    ) -> Any:
        if not test_case_ids:
            return {"count": 0, "value": []}
        if not configuration_ids:
            raise AzureDevOpsError("No configuration IDs supplied for suite test case update")

        unique_case_ids: list[int] = []
        seen_case_ids: set[int] = set()
        for tc_id in test_case_ids:
            if tc_id not in seen_case_ids:
                seen_case_ids.add(tc_id)
                unique_case_ids.append(int(tc_id))

        unique_cfg_ids: list[int] = []
        seen_cfg_ids: set[int] = set()
        for cfg_id in configuration_ids:
            if cfg_id not in seen_cfg_ids:
                seen_cfg_ids.add(cfg_id)
                unique_cfg_ids.append(int(cfg_id))

        id_csv = ",".join(str(v) for v in unique_case_ids)
        body = {"configurations": [{"id": str(cfg_id)} for cfg_id in unique_cfg_ids]}
        return self._send(
            "PATCH",
            f"/_apis/test/Plans/{int(plan_id)}/suites/{int(suite_id)}/testcases/{id_csv}",
            params={"api-version": "7.1"},
            json_body=body,
        )
