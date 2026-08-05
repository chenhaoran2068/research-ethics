#!/usr/bin/env python3
"""Generate deterministic model-derived verification scenarios.

The generated scenarios are *not* represented as live browser evidence.  They
are derived from the canonical condition DAG and use the evaluator in
``validate_atomic_schema.py`` as their executable semantics.

Default mode atomically replaces only ``verification.scenarios`` in the YAML
document.  ``--check`` performs the complete generation and validation in
memory and never writes the target file.
"""

from __future__ import annotations

import argparse
import copy
import itertools
import json
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import yaml

from validate_atomic_schema import AtomicSchemaValidator, ConditionUse, ControlSpec


VERIFICATION_KIND = "model_derived_condition_coverage"
DEFAULT_SCENARIO_CANDIDATES = 8
DEFAULT_ENUMERATION_LIMIT = 250_000
DEFAULT_PAIR_CANDIDATE_LIMIT = 6_000


class ScenarioGenerationError(RuntimeError):
    """Raised when the model cannot yield complete, internally valid coverage."""


@dataclass(frozen=True)
class DependencySpec:
    name: str
    node_ids: tuple[str, ...]
    minimum_options: int


# These are deliberately explicit.  They are high-risk branch drivers called
# out in the audit plan, including the six root leaves and all eight recruitment
# statuses.  Once found, all declared options (not just condition literals) are
# included in the coverage universe.
DEPENDENCY_SPECS = (
    DependencySpec("route_leaf", ("route-leaf",), 6),
    DependencySpec("sync_platform", ("sync-platform",), 3),
    DependencySpec("diagnostic_trial", ("diagnostic-test-classification", "diagnostic-trial"), 2),
    DependencySpec("material_donation", ("material-donation-flag",), 2),
    DependencySpec("multicenter", ("multicenter-flag",), 2),
    DependencySpec("randomization", ("random-group",), 2),
    DependencySpec("blinding", ("blinding-type",), 1),
    DependencySpec("biological_sample", ("biological-sample-collection",), 2),
    DependencySpec("recruitment_status", ("recruitment-status",), 8),
    DependencySpec("overseas_recruitment", ("overseas-recruitment-flag",), 2),
    DependencySpec("data_sharing", ("data-share-statement",), 2),
)


@dataclass(frozen=True)
class Goal:
    token: str
    kind: str
    condition_location: str | None = None
    condition: Any = None
    expected_outcome: bool | None = None
    page_id: str | None = None
    control_path: str | None = None
    option_id: str | None = None


@dataclass(frozen=True)
class Candidate:
    key: str
    selections: tuple[tuple[str, Any], ...]
    coverage: frozenset[str]

    def as_mapping(self) -> dict[str, Any]:
        return {path: _external_value(value) for path, value in self.selections}


@dataclass
class GenerationResult:
    scenarios: list[dict[str, Any]]
    universe: set[str]
    covered: set[str]
    coverage_counts: dict[str, int]
    dependency_counts: dict[str, int]
    runtime_evidence_matches: int


def _external_value(value: Any) -> Any:
    return list(value) if isinstance(value, tuple) else value


def _internal_value(value: Any) -> Any:
    if isinstance(value, list):
        return tuple(value)
    return value


def _selection_values(value: Any) -> tuple[str, ...]:
    if isinstance(value, tuple):
        return value
    if isinstance(value, list):
        return tuple(value)
    return (value,)


def _selection_key(selections: Mapping[str, Any]) -> str:
    external = {key: _external_value(selections[key]) for key in sorted(selections)}
    return json.dumps(external, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _candidate(selections: Mapping[str, Any], coverage: Iterable[str]) -> Candidate:
    normalized = tuple((key, _internal_value(selections[key])) for key in sorted(selections))
    return Candidate(_selection_key(dict(normalized)), normalized, frozenset(coverage))


def _condition_token(use: ConditionUse, outcome: bool) -> str:
    return f"condition::{use.location}::{str(outcome).lower()}"


def _option_token(control_path: str, option_id: str) -> str:
    return f"option::{control_path}::{option_id}"


def _page_token(page_id: str) -> str:
    return f"page::{page_id}"


def _control_token(control_path: str) -> str:
    return f"control::{control_path}"


def _prepare_validator(document: Any) -> AtomicSchemaValidator:
    """Collect the model without requiring scenarios to exist yet."""

    validator = AtomicSchemaValidator(document)
    if not isinstance(document, dict):
        raise ScenarioGenerationError("canonical document must be a mapping")
    version = str(document.get("schema_version", ""))
    if version not in {"0.3", "0.3-draft"}:
        raise ScenarioGenerationError(f"unsupported schema_version {version!r}")
    validator._reject_string_field_shorthands(document, "$")
    validator._collect_pages()
    validator._validate_all_conditions()
    if validator.errors.issues:
        rendered = "\n".join(f"- {issue}" for issue in validator.errors.issues[:80])
        remainder = len(validator.errors.issues) - 80
        suffix = f"\n- ... {remainder} more" if remainder > 0 else ""
        raise ScenarioGenerationError(
            "canonical structure/conditions must validate before scenario generation:\n"
            f"{rendered}{suffix}"
        )
    return validator


def _find_explicit_dependencies(
    validator: AtomicSchemaValidator,
) -> tuple[set[str], dict[str, int]]:
    by_node: dict[str, list[ControlSpec]] = {}
    for control in validator.controls.values():
        by_node.setdefault(control.node_id, []).append(control)

    driver_paths: set[str] = set()
    counts: dict[str, int] = {}
    gaps: list[str] = []
    for spec in DEPENDENCY_SPECS:
        matches: list[ControlSpec] = []
        for node_id in spec.node_ids:
            matches.extend(by_node.get(node_id, []))
        # A path-normalized diagnostic control can have node_id
        # diagnostic-test-classification but path diagnostic-trial.
        if not matches:
            matches = [
                control
                for control in validator.controls.values()
                if any(alias in control.path.rsplit(".", 1)[-1] for alias in spec.node_ids)
            ]
        unique = {control.path: control for control in matches}
        if len(unique) != 1:
            gaps.append(
                f"dependency {spec.name!r}: expected exactly one control matching "
                f"{list(spec.node_ids)!r}, found {sorted(unique)!r}"
            )
            continue
        control = next(iter(unique.values()))
        option_count = len(control.options)
        counts[spec.name] = option_count
        if option_count < spec.minimum_options:
            gaps.append(
                f"dependency {spec.name!r} at {control.path!r}: found {option_count} "
                f"options, expected at least {spec.minimum_options}"
            )
        driver_paths.add(control.path)
    if gaps:
        raise ScenarioGenerationError(
            "explicit dependency audit failed:\n" + "\n".join(f"- {gap}" for gap in gaps)
        )
    return driver_paths, counts


def _build_goals(
    validator: AtomicSchemaValidator,
) -> tuple[list[Goal], set[str], set[str], dict[str, int]]:
    goals: list[Goal] = []
    universe: set[str] = set()
    driver_paths: set[str] = set()

    for use in validator.condition_uses:
        if isinstance(use.condition, bool):
            continue
        driver_paths.update(validator._condition_refs(use.condition))
        for outcome in (False, True):
            token = _condition_token(use, outcome)
            universe.add(token)
            goals.append(
                Goal(
                    token=token,
                    kind="condition",
                    condition_location=use.location,
                    condition=use.condition,
                    expected_outcome=outcome,
                )
            )

    explicit_paths, dependency_counts = _find_explicit_dependencies(validator)
    driver_paths.update(explicit_paths)

    for path in sorted(driver_paths):
        control = validator.controls.get(path)
        if control is None:
            raise ScenarioGenerationError(f"condition driver {path!r} does not exist")
        if not control.options:
            raise ScenarioGenerationError(
                f"condition/dependency driver {path!r} has no declared options"
            )
        for option in control.options:
            token = _option_token(path, option.option_id)
            universe.add(token)
            goals.append(
                Goal(
                    token=token,
                    kind="option",
                    control_path=path,
                    option_id=option.option_id,
                )
            )

    for page in validator.pages:
        token = _page_token(page.page_id)
        universe.add(token)
        goals.append(Goal(token=token, kind="page", page_id=page.page_id))

    for path, control in sorted(validator.controls.items()):
        if not control.observable:
            continue
        token = _control_token(path)
        universe.add(token)
        goals.append(Goal(token=token, kind="control", control_path=path))

    # One token should have one canonical goal.  Duplicate conditions may have
    # identical content but distinct locations and therefore remain distinct.
    by_token: dict[str, Goal] = {}
    for goal in goals:
        by_token.setdefault(goal.token, goal)
    return list(by_token.values()), universe, driver_paths, dependency_counts


def _multi_select(control: ControlSpec) -> bool:
    widget = control.widget.lower().replace("_", "-")
    return "multi" in widget or "checkbox" in widget


def _literal_sets(condition: Any, control_path: str) -> set[tuple[str, ...]]:
    """Collect useful multi-select combinations from a condition tree."""

    if not isinstance(condition, dict):
        return set()
    result: set[tuple[str, ...]] = set()
    control = condition.get("control")
    if control == control_path:
        for key in ("equals", "not_equals"):
            if isinstance(condition.get(key), str):
                result.add((condition[key],))
        for key in ("in", "not_in"):
            values = condition.get(key)
            if isinstance(values, list) and values and all(isinstance(value, str) for value in values):
                result.add(tuple(dict.fromkeys(values)))
    for key in ("all", "any"):
        children = condition.get(key)
        if isinstance(children, list):
            combined: list[str] = []
            for child in children:
                child_sets = _literal_sets(child, control_path)
                result.update(child_sets)
                if key == "all":
                    for value_set in child_sets:
                        combined.extend(value_set)
            if combined:
                result.add(tuple(dict.fromkeys(combined)))
    if "not" in condition:
        result.update(_literal_sets(condition["not"], control_path))
    return result


def _domain_for_control(
    validator: AtomicSchemaValidator,
    control: ControlSpec,
) -> list[Any]:
    option_ids = [option.option_id for option in control.options]
    if not option_ids:
        raise ScenarioGenerationError(
            f"control {control.path!r} is required for solving but has no options"
        )
    if not _multi_select(control):
        return option_ids

    combinations: set[tuple[str, ...]] = {(option_id,) for option_id in option_ids}
    combinations.add(tuple(option_ids))
    for use in validator.condition_uses:
        combinations.update(_literal_sets(use.condition, control.path))
    declared = set(option_ids)
    filtered = {
        tuple(value for value in option_ids if value in values)
        for values in combinations
        if values and set(values).issubset(declared)
    }
    return sorted(filtered, key=lambda values: (len(values), values))


def _goal_conditions(validator: AtomicSchemaValidator, goal: Goal) -> list[Any]:
    if goal.kind == "condition":
        return [goal.condition]
    if goal.kind == "page":
        page = next(page for page in validator.pages if page.page_id == goal.page_id)
        return [page.visible_if]
    if goal.kind in {"control", "option"}:
        control = validator.controls[goal.control_path or ""]
        conditions = list(control.visibility_chain)
        if goal.kind == "option" and goal.option_id is not None:
            option = next(option for option in control.options if option.option_id == goal.option_id)
            conditions.append(option.visible_if)
        return conditions
    raise ScenarioGenerationError(f"unknown goal kind {goal.kind!r}")


def _closure_for_goal(validator: AtomicSchemaValidator, goal: Goal) -> set[str]:
    pending_conditions = list(_goal_conditions(validator, goal))
    controls: set[str] = set()
    if goal.kind == "option" and goal.control_path:
        controls.add(goal.control_path)

    processed_conditions: set[str] = set()
    processed_controls: set[str] = set()
    while pending_conditions or processed_controls != controls:
        while pending_conditions:
            condition = pending_conditions.pop()
            marker = json.dumps(condition, ensure_ascii=False, sort_keys=True, default=str)
            if marker in processed_conditions:
                continue
            processed_conditions.add(marker)
            controls.update(validator._condition_refs(condition))

        for path in sorted(controls - processed_controls):
            processed_controls.add(path)
            control = validator.controls.get(path)
            if control is None:
                raise ScenarioGenerationError(f"solver closure reached unknown control {path!r}")
            if not control.options:
                raise ScenarioGenerationError(
                    f"solver closure reached optionless condition control {path!r}"
                )
            if control.observable:
                pending_conditions.extend(control.visibility_chain)
                pending_conditions.append(control.enabled_if)
            for option in control.options:
                pending_conditions.append(option.visible_if)
    return controls


def _expected_visible_sets(
    validator: AtomicSchemaValidator, selections: Mapping[str, Any]
) -> tuple[set[str], set[str]]:
    external = {key: _external_value(value) for key, value in selections.items()}
    pages = validator._expected_pages(external)
    page_ids = {page.page_id for page, _ in pages}
    controls = {path for _, signature in pages for path, _ in signature}
    return page_ids, controls


def _assignment_realizable(
    validator: AtomicSchemaValidator, selections: Mapping[str, Any]
) -> bool:
    external = {key: _external_value(value) for key, value in selections.items()}
    page_ids, visible_controls = _expected_visible_sets(validator, selections)
    for path, selected in selections.items():
        control = validator.controls.get(path)
        if control is None or not control.options:
            return False
        if control.page_id not in page_ids:
            return False
        if control.observable:
            if path not in visible_controls:
                return False
            if not validator._evaluate(control.enabled_if, external):
                return False
        declared = {option.option_id: option for option in control.options}
        for option_id in _selection_values(selected):
            option = declared.get(option_id)
            if option is None or not validator._evaluate(option.visible_if, external):
                return False
    return True


def _goal_satisfied(
    validator: AtomicSchemaValidator, goal: Goal, selections: Mapping[str, Any]
) -> bool:
    external = {key: _external_value(value) for key, value in selections.items()}
    if goal.kind == "condition":
        refs = validator._condition_refs(goal.condition)
        return refs.issubset(selections) and (
            validator._evaluate(goal.condition, external) is goal.expected_outcome
        )
    page_ids, visible_controls = _expected_visible_sets(validator, selections)
    if goal.kind == "page":
        return goal.page_id in page_ids
    if goal.kind == "control":
        return goal.control_path in visible_controls
    if goal.kind == "option":
        if goal.control_path not in selections:
            return False
        return goal.option_id in _selection_values(selections[goal.control_path])
    return False


def _coverage_for_assignment(
    validator: AtomicSchemaValidator,
    selections: Mapping[str, Any],
    driver_paths: set[str],
) -> set[str]:
    external = {key: _external_value(value) for key, value in selections.items()}
    coverage: set[str] = set()
    for use in validator.condition_uses:
        if isinstance(use.condition, bool):
            continue
        refs = validator._condition_refs(use.condition)
        if refs and refs.issubset(selections):
            coverage.add(_condition_token(use, validator._evaluate(use.condition, external)))
    for path in driver_paths:
        if path not in selections:
            continue
        for option_id in _selection_values(selections[path]):
            coverage.add(_option_token(path, option_id))
    for page, signature in validator._expected_pages(external):
        coverage.add(_page_token(page.page_id))
        coverage.update(_control_token(path) for path, _ in signature)
    return coverage


def _ordered_domains(
    validator: AtomicSchemaValidator,
    closure: Sequence[str],
    goal: Goal,
) -> list[list[Any]]:
    domains: list[list[Any]] = []
    for path in closure:
        domain = _domain_for_control(validator, validator.controls[path])
        if goal.kind == "option" and goal.control_path == path and goal.option_id is not None:
            domain.sort(
                key=lambda value: (
                    goal.option_id not in _selection_values(value),
                    len(_selection_values(value)),
                    str(value),
                )
            )
        domains.append(domain)
    return domains


def _solve_goal(
    validator: AtomicSchemaValidator,
    goal: Goal,
    driver_paths: set[str],
    *,
    candidate_limit: int,
    enumeration_limit: int,
) -> list[Candidate]:
    closure = sorted(_closure_for_goal(validator, goal))
    domains = _ordered_domains(validator, closure, goal)
    theoretical = 1
    for domain in domains:
        theoretical *= len(domain)
    if theoretical > enumeration_limit:
        raise ScenarioGenerationError(
            f"goal {goal.token!r} requires {theoretical:,} assignments across "
            f"{closure!r}, exceeding enumeration limit {enumeration_limit:,}"
        )

    solved: list[Candidate] = []
    products: Iterable[tuple[Any, ...]]
    products = itertools.product(*domains) if domains else [tuple()]
    for values in products:
        selections = dict(zip(closure, values))
        if not _assignment_realizable(validator, selections):
            continue
        if not _goal_satisfied(validator, goal, selections):
            continue
        coverage = _coverage_for_assignment(validator, selections, driver_paths)
        solved.append(_candidate(selections, coverage))
        if len(solved) >= candidate_limit:
            break
    if not solved:
        raise ScenarioGenerationError(
            f"uncoverable goal {goal.token!r}; closure={closure!r}, "
            f"candidate assignments checked={theoretical:,}"
        )
    return solved


def _merge_selections(left: Candidate, right: Candidate) -> dict[str, Any] | None:
    merged = {path: value for path, value in left.selections}
    for path, value in right.selections:
        if path in merged and merged[path] != value:
            return None
        merged[path] = value
    return merged


def _augment_pair_candidates(
    validator: AtomicSchemaValidator,
    base: dict[str, Candidate],
    driver_paths: set[str],
    *,
    limit: int,
) -> None:
    seeds = sorted(base.values(), key=lambda candidate: (len(candidate.selections), candidate.key))
    for left_index, left in enumerate(seeds):
        for right in seeds[left_index + 1 :]:
            if len(base) >= limit:
                return
            merged = _merge_selections(left, right)
            if merged is None:
                continue
            key = _selection_key(merged)
            if key in base or not _assignment_realizable(validator, merged):
                continue
            coverage = _coverage_for_assignment(validator, merged, driver_paths)
            base[key] = _candidate(merged, coverage)


def _greedy_cover(universe: set[str], candidates: Iterable[Candidate]) -> list[Candidate]:
    remaining = set(universe)
    pool = list(candidates)
    selected: list[Candidate] = []
    while remaining:
        best = min(
            pool,
            key=lambda candidate: (
                -len(candidate.coverage & remaining),
                len(candidate.selections),
                candidate.key,
            ),
        )
        gain = best.coverage & remaining
        if not gain:
            missing = "\n".join(f"- {token}" for token in sorted(remaining))
            raise ScenarioGenerationError(f"set-cover gap after candidate generation:\n{missing}")
        selected.append(best)
        remaining.difference_update(gain)
        pool.remove(best)
    return selected


def _merge_selected(
    validator: AtomicSchemaValidator,
    selected: list[Candidate],
    driver_paths: set[str],
) -> list[Candidate]:
    """Safely collapse compatible scenarios when the merge loses no coverage."""

    changed = True
    while changed:
        changed = False
        for left_index in range(len(selected)):
            for right_index in range(left_index + 1, len(selected)):
                left, right = selected[left_index], selected[right_index]
                merged = _merge_selections(left, right)
                if merged is None or not _assignment_realizable(validator, merged):
                    continue
                coverage = _coverage_for_assignment(validator, merged, driver_paths)
                if not (left.coverage | right.coverage).issubset(coverage):
                    continue
                replacement = _candidate(merged, coverage)
                selected = [
                    candidate
                    for index, candidate in enumerate(selected)
                    if index not in {left_index, right_index}
                ] + [replacement]
                selected.sort(key=lambda candidate: (len(candidate.selections), candidate.key))
                changed = True
                break
            if changed:
                break
    return selected


def _remove_redundant(universe: set[str], selected: list[Candidate]) -> list[Candidate]:
    result = list(selected)
    for candidate in sorted(result, key=lambda item: (-len(item.selections), item.key)):
        others = [item for item in result if item is not candidate]
        covered = set().union(*(item.coverage for item in others)) if others else set()
        if universe.issubset(covered):
            result.remove(candidate)
    return sorted(result, key=lambda candidate: (len(candidate.selections), candidate.key))


def _load_runtime_index(path: Path | None) -> dict[str, dict[str, Any]]:
    """Load only a scenario index; caller never copies values/options from it."""

    if path is None or not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    scenarios: Any
    if isinstance(raw, dict) and isinstance(raw.get("scenarios"), list):
        scenarios = raw["scenarios"]
    elif isinstance(raw, list):
        scenarios = raw
    elif isinstance(raw, dict):
        scenarios = [
            dict(value, id=key) if isinstance(value, dict) and "id" not in value else value
            for key, value in raw.items()
        ]
    else:
        return {}
    index: dict[str, dict[str, Any]] = {}
    for item in scenarios:
        if isinstance(item, dict) and isinstance(item.get("id"), str):
            index[item["id"]] = item
    return index


def _runtime_key_status(
    runtime: Mapping[str, Any], expected_pages: Sequence[Mapping[str, Any]]
) -> str:
    runtime_pages = runtime.get("observed_pages")
    if not isinstance(runtime_pages, list):
        return "runtime_record_has_no_observed_pages"
    expected_by_page = {
        page["page_id"]: [item["observed_key"] for item in page["observed_signature"]]
        for page in expected_pages
    }
    actual_by_page: dict[str, list[str]] = {}
    for page in runtime_pages:
        if not isinstance(page, dict) or not isinstance(page.get("page_id"), str):
            continue
        signature = page.get("observed_signature")
        if isinstance(signature, list):
            keys = [
                item.get("observed_key")
                for item in signature
                if isinstance(item, dict) and isinstance(item.get("observed_key"), str)
            ]
        elif isinstance(page.get("observed_keys"), list):
            keys = [key for key in page["observed_keys"] if isinstance(key, str)]
        else:
            keys = []
        actual_by_page[page["page_id"]] = keys
    return (
        "exact_observed_key_sequence_match"
        if actual_by_page == expected_by_page
        else "observed_key_sequence_mismatch"
    )


def _scenario_from_candidate(
    validator: AtomicSchemaValidator,
    candidate: Candidate,
    scenario_id: str,
    runtime_index: Mapping[str, Mapping[str, Any]],
    runtime_source: str | None,
) -> tuple[dict[str, Any], bool]:
    selections = candidate.as_mapping()
    expected_pages = validator._expected_pages(selections)
    observed_pages: list[dict[str, Any]] = []
    for page, signature_pairs in expected_pages:
        signature = [item for _, item in signature_pairs]
        observed_pages.append(
            {
                "page_id": page.page_id,
                "observed_signature": signature,
                "signature_hash": f"sha256:{validator._signature_hash(signature)}",
            }
        )
    scenario: dict[str, Any] = {
        "id": scenario_id,
        "verification_kind": VERIFICATION_KIND,
        "selections": selections,
        "page_sequence": [page.page_id for page, _ in expected_pages],
        "observed_pages": observed_pages,
    }
    matched = scenario_id in runtime_index
    if matched:
        # Attach only source/status and structural counts.  No runtime values,
        # labels, option lists, account data, or other source payload is copied.
        scenario["runtime_key_evidence"] = {
            "source": runtime_source,
            "status": _runtime_key_status(runtime_index[scenario_id], observed_pages),
            "expected_page_count": len(observed_pages),
        }
    return scenario, matched


def _coverage_counts(universe: set[str]) -> dict[str, int]:
    counts = {"condition_outcomes": 0, "driver_options": 0, "pages": 0, "controls": 0}
    prefixes = {
        "condition::": "condition_outcomes",
        "option::": "driver_options",
        "page::": "pages",
        "control::": "controls",
    }
    for token in universe:
        for prefix, key in prefixes.items():
            if token.startswith(prefix):
                counts[key] += 1
                break
    return counts


def generate_scenarios(
    document: dict[str, Any],
    *,
    runtime_path: Path | None = None,
    scenario_candidate_limit: int = DEFAULT_SCENARIO_CANDIDATES,
    enumeration_limit: int = DEFAULT_ENUMERATION_LIMIT,
    pair_candidate_limit: int = DEFAULT_PAIR_CANDIDATE_LIMIT,
) -> GenerationResult:
    validator = _prepare_validator(document)
    goals, universe, driver_paths, dependency_counts = _build_goals(validator)

    pool: dict[str, Candidate] = {}
    for goal in goals:
        for candidate in _solve_goal(
            validator,
            goal,
            driver_paths,
            candidate_limit=scenario_candidate_limit,
            enumeration_limit=enumeration_limit,
        ):
            if candidate.key not in pool or len(candidate.coverage) > len(pool[candidate.key].coverage):
                pool[candidate.key] = candidate

    _augment_pair_candidates(
        validator,
        pool,
        driver_paths,
        limit=max(pair_candidate_limit, len(pool)),
    )
    selected = _greedy_cover(universe, pool.values())
    selected = _merge_selected(validator, selected, driver_paths)
    selected = _remove_redundant(universe, selected)
    covered = set().union(*(candidate.coverage for candidate in selected)) if selected else set()
    gaps = universe - covered
    if gaps:
        rendered = "\n".join(f"- {token}" for token in sorted(gaps))
        raise ScenarioGenerationError(f"coverage gaps remain after minimization:\n{rendered}")

    runtime_index = _load_runtime_index(runtime_path)
    runtime_source = runtime_path.as_posix() if runtime_path else None
    scenarios: list[dict[str, Any]] = []
    runtime_matches = 0
    for index, candidate in enumerate(selected, start=1):
        scenario, matched = _scenario_from_candidate(
            validator,
            candidate,
            f"model-coverage-{index:03d}",
            runtime_index,
            runtime_source,
        )
        scenarios.append(scenario)
        runtime_matches += int(matched)

    return GenerationResult(
        scenarios=scenarios,
        universe=universe,
        covered=covered,
        coverage_counts=_coverage_counts(universe),
        dependency_counts=dependency_counts,
        runtime_evidence_matches=runtime_matches,
    )


def _install_generated_scenarios(
    document: dict[str, Any], scenarios: list[dict[str, Any]]
) -> dict[str, Any]:
    output = copy.deepcopy(document)
    verification = output.get("verification")
    if verification is None:
        verification = {}
        output["verification"] = verification
    if not isinstance(verification, dict):
        raise ScenarioGenerationError("$.verification must be a mapping")
    verification["scenarios"] = scenarios
    return output


def _validate_generated_document(
    original: dict[str, Any], generated: dict[str, Any]
) -> None:
    original_pages = original.get("workflow", {}).get("pages")
    generated_pages = generated.get("workflow", {}).get("pages")
    if generated_pages != original_pages:
        raise ScenarioGenerationError(
            "generator invariant failed: workflow.pages changed while replacing scenarios"
        )
    issues = AtomicSchemaValidator(generated).validate()
    if issues:
        rendered = "\n".join(f"- {issue}" for issue in issues[:100])
        remainder = len(issues) - 100
        suffix = f"\n- ... {remainder} more" if remainder > 0 else ""
        raise ScenarioGenerationError(
            f"generated document failed atomic validation ({len(issues)} issue(s)):\n"
            f"{rendered}{suffix}"
        )


def _atomic_write_yaml(path: Path, document: dict[str, Any], original_pages: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(document, allow_unicode=True, sort_keys=False, width=120)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        reread = yaml.safe_load(temporary.read_text(encoding="utf-8"))
        if not isinstance(reread, dict):
            raise ScenarioGenerationError("serialized YAML did not reload as a mapping")
        if reread.get("workflow", {}).get("pages") != original_pages:
            raise ScenarioGenerationError(
                "serialized YAML changed workflow.pages; refusing atomic replacement"
            )
        issues = AtomicSchemaValidator(reread).validate()
        if issues:
            raise ScenarioGenerationError(
                "serialized YAML failed final validation:\n"
                + "\n".join(f"- {issue}" for issue in issues[:100])
            )
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _print_report(result: GenerationResult, *, mode: str, target: Path) -> None:
    counts = result.coverage_counts
    print(
        f"Verification scenario generation {mode}: target={_console_safe_path(target)}, "
        f"scenarios={len(result.scenarios)}, coverage={len(result.covered)}/{len(result.universe)}, "
        f"condition_outcomes={counts['condition_outcomes']}, "
        f"driver_options={counts['driver_options']}, pages={counts['pages']}, "
        f"controls={counts['controls']}, runtime_matches={result.runtime_evidence_matches}"
    )
    print(
        "Explicit dependency option counts: "
        + ", ".join(f"{key}={value}" for key, value in sorted(result.dependency_counts.items()))
    )


def _console_safe_path(path: Path, *, stream: Any = sys.stdout) -> str:
    encoding = getattr(stream, "encoding", None) or "utf-8"
    return str(path).encode(encoding, errors="backslashreplace").decode(encoding)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "target",
        type=Path,
        help="project root or references/registration-tree.yaml path",
    )
    parser.add_argument(
        "--runtime-signatures",
        type=Path,
        default=None,
        help="optional runtime-signatures.json; only same-id key evidence is attached",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="generate and validate in memory without modifying the YAML file",
    )
    parser.add_argument("--candidate-limit", type=int, default=DEFAULT_SCENARIO_CANDIDATES)
    parser.add_argument("--enumeration-limit", type=int, default=DEFAULT_ENUMERATION_LIMIT)
    parser.add_argument("--pair-candidate-limit", type=int, default=DEFAULT_PAIR_CANDIDATE_LIMIT)
    args = parser.parse_args(argv)

    target = args.target.resolve()
    yaml_path = target if target.is_file() else target / "references" / "registration-tree.yaml"
    runtime_path = args.runtime_signatures
    if runtime_path is None:
        candidate = yaml_path.parent / "drafts" / "runtime-signatures.json"
        runtime_path = candidate if candidate.exists() else None
    elif not runtime_path.is_absolute():
        runtime_path = (Path.cwd() / runtime_path).resolve()

    try:
        document = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            raise ScenarioGenerationError("canonical YAML must contain a mapping")
        original_pages = copy.deepcopy(document.get("workflow", {}).get("pages"))
        result = generate_scenarios(
            document,
            runtime_path=runtime_path,
            scenario_candidate_limit=max(args.candidate_limit, 1),
            enumeration_limit=max(args.enumeration_limit, 1),
            pair_candidate_limit=max(args.pair_candidate_limit, 1),
        )
        generated = _install_generated_scenarios(document, result.scenarios)
        _validate_generated_document(document, generated)
        if args.check:
            _print_report(result, mode="check passed (no write)", target=yaml_path)
            return 0
        _atomic_write_yaml(yaml_path, generated, original_pages)
        _print_report(result, mode="written atomically", target=yaml_path)
        return 0
    except (OSError, UnicodeError, yaml.YAMLError, ScenarioGenerationError) as exc:
        print(f"Verification scenario generation failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
