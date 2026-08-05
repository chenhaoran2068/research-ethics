#!/usr/bin/env python3
"""Extract a privacy-safe control inventory from a saved registration page.

This is a maintenance aid, not evidence of visibility. It never emits control
values or free text entered by a user. Hidden templates still require live UI
verification before their controls are added to the canonical field map.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup, Tag


FORM_PAGES = {
    "research_typeInfo_form": "研究类别",
    "research_baseInfo_form": "基本信息",
    "research_implementInfo_form": "实施信息",
    "research_contentInfo_form": "研究内容",
    "research_designInfo_form": "研究设计",
    "research_recruitInfo_form": "招募信息",
    "research_otherInfo_form": "其他信息",
    "research_dataInfo_form": "数据共享与信息公开",
    "research_docInfo_form": "相关附件",
}

INDEX_RE = re.compile(r"\[\d+\]")
SPACE_RE = re.compile(r"\s+")


def clean_text(value: str) -> str:
    value = value.replace("*", "").replace("：", "").replace(":", "")
    return SPACE_RE.sub(" ", value).strip()


def normalized_name(value: str) -> str:
    return INDEX_RE.sub("[]", value)


def has_hidden_ancestor(control: Tag, form: Tag) -> bool:
    current: Tag | None = control
    while current is not None and current is not form:
        style = str(current.get("style", "")).replace(" ", "").lower()
        classes = {str(item).lower() for item in current.get("class", [])}
        if "display:none" in style or "hidden" in classes or "hide" in classes:
            return True
        current = current.parent if isinstance(current.parent, Tag) else None
    return False


def nearest_group(control: Tag, form: Tag) -> Tag:
    current: Tag | None = control
    while current is not None and current is not form:
        classes = {str(item).lower() for item in current.get("class", [])}
        if "form-group" in classes or "input-group" in classes:
            return current
        current = current.parent if isinstance(current.parent, Tag) else None
    return control.parent if isinstance(control.parent, Tag) else form


def label_metadata(control: Tag, form: Tag) -> tuple[str, bool]:
    group = nearest_group(control, form)
    labels = group.find_all("label")
    label = clean_text(" ".join(item.get_text(" ", strip=True) for item in labels))
    required = any(item.select_one("sup.check-tag") is not None for item in labels)
    if not label:
        label = clean_text(str(control.get("placeholder", "")))
    return label, required or control.has_attr("required")


def option_labels(control: Tag) -> list[str]:
    if control.name != "select":
        return []
    result: list[str] = []
    for option in control.find_all("option"):
        text = clean_text(option.get_text(" ", strip=True))
        if text and text not in result:
            result.append(text)
    return result


def extract(html_path: Path) -> dict[str, Any]:
    soup = BeautifulSoup(html_path.read_text(encoding="utf-8"), "html.parser")
    pages: list[dict[str, Any]] = []
    for form_id, page_label in FORM_PAGES.items():
        form = soup.find("form", id=form_id)
        if not isinstance(form, Tag):
            raise ValueError(f"Missing expected form: {form_id}")
        controls: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str, bool]] = set()
        for control in form.find_all(["input", "select", "textarea"]):
            name = str(control.get("name", "")).strip()
            control_type = (
                str(control.get("type", "text")).lower()
                if control.name == "input"
                else control.name
            )
            if not name or control_type in {"hidden", "submit", "button", "reset"}:
                continue
            label, required = label_metadata(control, form)
            placeholder = clean_text(str(control.get("placeholder", "")))
            hidden = has_hidden_ancestor(control, form)
            key = (normalized_name(name), control_type, placeholder, hidden)
            if key in seen:
                continue
            seen.add(key)
            controls.append(
                {
                    "name": normalized_name(name),
                    "type": control_type,
                    "label_hint": label,
                    "required_marker": required,
                    "placeholder": placeholder,
                    "hidden_in_saved_source": hidden,
                    "options": option_labels(control),
                }
            )
        pages.append(
            {
                "page": page_label,
                "form_id": form_id,
                "control_count": len(controls),
                "controls": controls,
            }
        )
    return {"source_role": "candidate inventory; live verification required", "pages": pages}


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("html_path", type=Path)
    args = parser.parse_args()
    print(json.dumps(extract(args.html_path), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
