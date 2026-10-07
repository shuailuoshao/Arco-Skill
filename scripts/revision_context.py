"""Serializable revision intent and caller-owned visual review (no image analysis)."""
from copy import deepcopy
from collections.abc import Mapping
import re
from typing import Any

VISUAL_STATUSES = frozenset({"unchecked", "passed", "degraded"})
SETTINGS = ("user_style_overrides", "external_references", "style_briefs",
            "composition_readability", "exposure_profile", "rendering_hygiene", "reference_analysis")


def is_previous_output(ref: Any) -> bool:
    return isinstance(ref, Mapping) and (
        "output_id" in ref or "generation_depth" in ref
        or bool(ref.get("generated_output_role"))
        or (isinstance(ref.get("provenance"), Mapping) and ref["provenance"].get("transport") == "previous_output")
    )


def first_context(request: Mapping[str, Any]) -> dict[str, Any]:
    return {"version": 1, "source_request": deepcopy(dict(request)),
            "revisions": [], "current_settings": {
                key: deepcopy(request[key]) for key in SETTINGS if key in request},
            "history_complete": True}


def advance_context(previous: Mapping[str, Any], source_request: Mapping[str, Any] | None,
                    request: Mapping[str, Any], supplied: Mapping[str, Any] | None = None) -> dict[str, Any]:
    raw = supplied if supplied is not None else previous.get("revision_context")
    if raw is None:
        context = first_context(source_request or {})
        context["history_complete"] = bool(source_request) and previous["generation_depth"] == 0 and previous.get("reset_triggered_from_output") is None
    else:
        context = deepcopy(raw)
        if (not isinstance(context, dict) or context.get("version") != 1
                or not isinstance(context.get("source_request"), dict)
                or not isinstance(context.get("revisions"), list)
                or not all(isinstance(x, str) and x.strip() for x in context["revisions"])
                or not isinstance(context.get("current_settings"), dict)
                or set(context["current_settings"]) - set(SETTINGS)
                or type(context.get("history_complete")) is not bool):
            raise ValueError("Malformed revision context")
    # Explicit source recovery is allowed; never fabricates missing revisions.
    if source_request is not None:
        context["source_request"] = deepcopy(dict(source_request))
    text = request.get("base_prompt")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Revision request must be non-empty")
    context["revisions"].append(text)
    for key in SETTINGS:
        if key in request:
            value = deepcopy(request[key])
            if key == "user_style_overrides" and isinstance(value, dict) and value:
                value = {**context["current_settings"].get(key, {}), **value}
            context["current_settings"][key] = value
    return context


def without_image_numbers(text: str) -> str:
    # Historical labels must not bind to newly selected input positions.
    return re.sub(r"(?i)\bimage\s*\d+\b|图\s*[一二三四五六七八九十\d]+",
                  "the previously referenced image (follow current reference duties)", text)


def cumulative_prompt(context: Mapping[str, Any]) -> str:
    return ("Apply the following user revisions in chronological order. Later explicit "
            "requests supersede conflicting earlier requests; retain all other changes. "
            "Historical image labels do not refer to current input numbers.\n"
            + "\n".join(f"{i}. {without_image_numbers(text)}" for i, text in enumerate(context["revisions"], 1)))
