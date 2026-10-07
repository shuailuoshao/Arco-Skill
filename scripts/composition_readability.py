"""Deterministic, request-only planning of character scale and readability."""

from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata
from typing import Any, Mapping


PRIORITIES = frozenset({"atmosphere", "balanced", "character_readability"})
SCALES = frozenset({"unknown", "very_small", "small", "medium", "close"})
DETAIL_LEVELS = frozenset({"low", "normal", "high"})
INPUT_FIELDS = frozenset({"composition_priority", "subject_frame_height_ratio", "subject_scale", "character_detail_requirement"})
HEADER = "[Composition Readability]"


def _ratio(value: Any, name: str) -> float:
    if type(value) not in (int, float) or not 0 < value <= 1:
        raise ValueError(f"{name} must be a number in (0, 1].")
    return float(value)


@dataclass(frozen=True)
class ReadabilityPolicy:
    very_small_max_exclusive: float
    small_max_exclusive: float
    close_min_inclusive: float
    full_body_preferred_min_frame_height_ratio: float
    full_body_preferred_target_frame_height_ratio: float

    @classmethod
    def from_document(cls, document: Mapping[str, Any]) -> "ReadabilityPolicy":
        if not isinstance(document, Mapping) or document.get("schema_version") != 1:
            raise ValueError("Readability policy requires schema_version 1.")
        values = document.get("composition_readability")
        if not isinstance(values, Mapping) or set(values) != set(cls.__dataclass_fields__):
            raise ValueError("Readability policy fields are incomplete or unsupported.")
        policy = cls(**{key: _ratio(value, key) for key, value in values.items()})
        if not (policy.very_small_max_exclusive < policy.small_max_exclusive
                == policy.full_body_preferred_min_frame_height_ratio
                <= policy.full_body_preferred_target_frame_height_ratio
                < policy.close_min_inclusive):
            raise ValueError("Readability policy thresholds must be ordered.")
        return policy

    def scale_for_ratio(self, ratio: float) -> str:
        if ratio < self.very_small_max_exclusive:
            return "very_small"
        if ratio < self.small_max_exclusive:
            return "small"
        if ratio < self.close_min_inclusive:
            return "medium"
        return "close"


@dataclass(frozen=True)
class CompositionReadabilityPlan:
    composition_priority: str
    subject_scale: str
    requested_frame_ratio: float | None
    character_detail_requirement: str
    scale_readability_conflict: bool | None
    recommended_subject_scale: str
    recommended_frame_ratio: float | None
    readability_guidance_enabled: bool
    guidance: str

    def as_dict(self) -> dict[str, Any]:
        return {key: getattr(self, key) for key in self.__dataclass_fields__}


def _text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


_CHINESE_TENTHS = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
_PERCENT = re.compile(r"(?:人物|角色|阿尔可|character|subject).{0,28}?(?:占|occup(?:y|ies)).{0,12}?(\d+(?:\.\d+)?\s*%|[一二三四五六七八九十]成)", re.I)
_HIGH = re.compile(r"(?:脸|面部|眼睛|发型|头发|服装|衣服|身份|配饰|饰品|领结).{0,12}(?:清楚|清晰|看清|可辨|可识别|可见)|(?:face|eyes?|hair|outfit|identity|accessor(?:y|ies)).{0,24}(?:clear|readable|recogniz|visible|visibility|legible|distinguishable)", re.I)
_SILHOUETTE = re.compile(r"轮廓.{0,8}(?:清楚|清晰|可辨)|(?:clear|readable|recognizable).{0,12}silhouette", re.I)
_ATMOSPHERE = re.compile(r"氛围优先|氛围为主|人物.{0,12}(?:点缀|远景)|保留大面积天空|大面积天空负空间|large negative space|atmosphere first|small distant figure", re.I)
_READABILITY = re.compile(r"人物(?:清晰|可读|辨识)优先|角色(?:清晰|可读|辨识)优先|character readability first|prioriti[sz]e character readability", re.I)
_ENVIRONMENT = re.compile(r"大场景|大环境|大量天空|大面积天空|负空间|large (?:scene|environment|sky)|negative space", re.I)
_CLOSER = re.compile(r"往近|靠近|拉近|再大一点|closer|move (?:the )?(?:character|subject) closer|larger", re.I)


def _explicit_ratio(text: str) -> float | None:
    match = _PERCENT.search(text)
    if not match:
        return None
    raw = match.group(1).replace(" ", "")
    value = _CHINESE_TENTHS[raw[0]] / 10 if raw.endswith("成") else float(raw[:-1]) / 100
    return _ratio(value, "requested frame ratio")


def _discrete_scale(text: str) -> str:
    if re.search(r"极小|很小|小点|tiny figure|tiny character|speck", text):
        return "very_small"
    if re.search(r"小人物|人物.{0,8}很小|远景点缀|small (?:full.body )?(?:character|figure|subject)|distant figure", text):
        return "small"
    if re.search(r"中景人物|medium (?:shot|figure)|medium.scale character", text):
        return "medium"
    if re.search(r"人物特写|近景人物|close.up character|close shot", text):
        return "close"
    return "unknown"


def _options(value: Mapping[str, Any] | None) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping) or set(value) - INPUT_FIELDS:
        raise ValueError("composition_readability must contain only supported fields.")
    result = dict(value)
    for field, allowed in (("composition_priority", PRIORITIES), ("subject_scale", SCALES),
                           ("character_detail_requirement", DETAIL_LEVELS)):
        if field in result and (type(result[field]) is not str or result[field] not in allowed):
            raise ValueError(f"Invalid {field}.")
    if "subject_frame_height_ratio" in result:
        result["subject_frame_height_ratio"] = _ratio(result["subject_frame_height_ratio"], "subject_frame_height_ratio")
    return result


def plan_composition_readability(
    request_text: str, policy: ReadabilityPolicy, *,
    options: Mapping[str, Any] | None = None,
    source_text: str | None = None,
    source_options: Mapping[str, Any] | None = None,
    allow_scale_change: bool = True,
) -> CompositionReadabilityPlan:
    if not isinstance(request_text, str) or not isinstance(policy, ReadabilityPolicy):
        raise TypeError("Readability planning requires request text and policy.")
    current, source = _text(request_text), _text(source_text or "")
    explicit, original = _options(options), _options(source_options)
    if explicit.get("character_detail_requirement") in {"low", "normal"} and _HIGH.search(current):
        raise ValueError("Explicit detail requirement conflicts with a high-readability request.")
    ratio = explicit.get("subject_frame_height_ratio")
    if ratio is None:
        ratio = _explicit_ratio(current)
    if ratio is None and "subject_scale" not in explicit and _discrete_scale(current) == "unknown":
        ratio = original.get("subject_frame_height_ratio")
    if ratio is None and "subject_scale" not in explicit and _discrete_scale(current) == "unknown":
        ratio = _explicit_ratio(source)
    scale = policy.scale_for_ratio(ratio) if ratio is not None else explicit.get("subject_scale") or _discrete_scale(current)
    if scale == "unknown":
        scale = original.get("subject_scale") or _discrete_scale(source)
    if ratio is not None and "subject_scale" in explicit and explicit["subject_scale"] != scale:
        raise ValueError("Explicit subject scale conflicts with frame-height ratio.")

    detail = explicit.get("character_detail_requirement") or ("high" if _HIGH.search(current) else None)
    detail = detail or original.get("character_detail_requirement") or ("high" if _HIGH.search(source) else "normal")
    atmo = bool(_ATMOSPHERE.search(current))
    readable = bool(_READABILITY.search(current))
    if not atmo and not readable and source:
        source_atmo = bool(_ATMOSPHERE.search(source))
        source_readable = bool(_READABILITY.search(source))
        if (_HIGH.search(current) or _CLOSER.search(current)) and source_atmo:
            atmo, readable = True, True
        else:
            atmo, readable = source_atmo, source_readable
    if "composition_priority" in explicit:
        priority = explicit["composition_priority"]
    elif atmo and readable:
        priority = "balanced"
    elif readable:
        priority = "character_readability"
    elif atmo:
        priority = "atmosphere"
    elif original.get("composition_priority") == "atmosphere" and (_HIGH.search(current) or _CLOSER.search(current)):
        priority = "balanced"
    elif detail == "high" and not _ENVIRONMENT.search(current + " " + source):
        priority = "character_readability"
    else:
        priority = original.get("composition_priority", "balanced")

    if scale == "unknown":
        conflict = None
    elif ratio is not None:
        conflict = detail == "high" and ratio < policy.full_body_preferred_min_frame_height_ratio
    else:
        conflict = detail == "high" and scale in {"very_small", "small"}

    recommended_ratio = ratio
    recommended_scale = scale
    closer = bool(_CLOSER.search(current))
    if allow_scale_change and priority != "atmosphere" and detail == "high" and (conflict or closer):
        target = (policy.full_body_preferred_target_frame_height_ratio if priority == "character_readability"
                  else policy.full_body_preferred_min_frame_height_ratio)
        if ratio is None or ratio < target:
            recommended_ratio = target
            recommended_scale = policy.scale_for_ratio(target)
    explicit_goal = bool(_HIGH.search(current) or _SILHOUETTE.search(current))
    guidance_enabled = bool(conflict or explicit_goal or closer) or bool(source and _HIGH.search(source) and conflict)
    if not guidance_enabled:
        guidance = ""
    elif conflict and priority == "atmosphere":
        guidance = "Preserve the requested distant character scale and environmental negative space. Keep the main identity and outfit silhouette recognizable where that scale permits; detailed facial features may be limited."
    elif recommended_ratio is not None and recommended_ratio != ratio:
        guidance = f"Keep substantial environment visible while placing the character at about {recommended_ratio:.0%} of frame height so the face and primary outfit structure remain distinguishable."
    elif closer and not allow_scale_change:
        guidance = "Keep the existing composition scope; make main character cues as distinguishable as the permitted edit allows."
    elif _SILHOUETTE.search(current) and detail != "high":
        guidance = "At the requested composition scale, keep the character silhouette and main identity cues recognizable without enlarging the figure."
    else:
        guidance = "At the requested composition scale, keep main facial features, hair silhouette, and primary outfit structure distinguishable."
    return CompositionReadabilityPlan(priority, scale, ratio, detail, conflict, recommended_scale,
                                      recommended_ratio, guidance_enabled, guidance)


def compile_readability(plan: CompositionReadabilityPlan) -> str:
    if type(plan) is not CompositionReadabilityPlan:
        raise TypeError("Expected CompositionReadabilityPlan.")
    return f"{HEADER}\n{plan.guidance}\n[/Composition Readability]" if plan.readability_guidance_enabled else ""
