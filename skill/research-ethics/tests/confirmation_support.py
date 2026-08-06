"""Synthetic, fully confirmed V1 intakes for regression tests only."""

from __future__ import annotations

from typing import Any

from validate_atomic_schema import AtomicSchemaValidator
from confirmation_workflow import pending_completion_items
from validate_v1_intake import active_structural_paths


PREFERRED_OPTIONS = (
    "private",
    "no",
    "否",
    "unlimited",
    "cross-sectional",
    "1005.14",
    "surgery-operation",
    "therapeutic",
    "chictr",
    "do-not-share",
    "academic-publication",
)


def choose_safe_option(control: Any) -> str:
    option_ids = [str(option.option_id) for option in control.options]
    for option_id in PREFERRED_OPTIONS:
        if option_id in option_ids:
            return option_id
    if not option_ids:
        raise ValueError(f"{control.path} has no selectable option")
    return option_ids[0]


def confirmed_intake(
    canonical: dict[str, Any], *, diagnostic: str = "no", platform: str = "private", operating_mode: str = "test_public"
) -> dict[str, Any]:
    """Choose deterministic synthetic values until no structural control remains open."""
    validator = AtomicSchemaValidator(canonical)
    errors = validator.validate()
    if errors:
        raise ValueError("invalid canonical: " + "; ".join(errors[:3]))
    selections: dict[str, Any] = {
        "research-category.route-leaf": "investigator-observational",
        "research-category.diagnostic-trial": diagnostic,
        "basic-information.sync-platform": platform,
    }
    for _ in range(64):
        missing = [path for path in active_structural_paths(validator, canonical, selections) if path not in selections]
        if not missing:
            break
        for path in missing:
            selections[path] = choose_safe_option(validator.controls[path])
    else:
        raise AssertionError("structural confirmation choices did not reach a fixed point")
    return {
        "metadata": {
            "operating_mode": operating_mode,
            "structural_confirmation": {
                "status": "explicitly_confirmed",
                "method": "user_explicit",
                "confirmed_selections": dict(selections),
            },
            # Regression tests use explicit synthetic deferrals for ordinary
            # content.  Production use must collect real values or a user
            # chosen resolution during the second confirmation stage.
            "proposal_confirmation": {
                "status": "explicitly_confirmed",
                "method": "user_explicit",
                "confirmed_values": {},
            },
            "completion_confirmation": {
                "status": "explicitly_confirmed",
                "method": "user_explicit",
                "resolutions": {
                    item["key"]: "user_deferred"
                    for item in pending_completion_items(
                        canonical,
                        {
                            "selections": selections,
                            "values": {},
                            "repeat_groups": {},
                        },
                    )
                },
            },
        },
        "selections": selections,
        "values": {},
        "repeat_groups": {},
    }
