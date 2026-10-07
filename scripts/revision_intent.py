"""Deterministic, non-executing planning for explicit image revisions.

The caller decides whether a request is a revision. This module neither reads
images nor changes reference selection, prompts, or generation behavior.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Sequence


class RevisionType(str, Enum):
    SCENE_ONLY = "scene_only"
    CHARACTER_DETAIL = "character_detail"
    COMPOSITION = "composition"
    STYLE = "style"
    ARTIFACT_REPAIR = "artifact_repair"
    MIXED = "mixed"


class SourceStrategy(str, Enum):
    EDIT_CURRENT = "edit_current"
    REANCHOR_AND_REGENERATE = "reanchor_and_regenerate"
    SOURCE_RESET = "source_reset"


class GeneratedOutputRole(str, Enum):
    PRIMARY_EDIT_SOURCE = "primary_edit_source"
    COMPOSITION_ANCHOR = "composition_anchor"
    EXCLUDED = "excluded"


@dataclass(frozen=True)
class RevisionPlan:
    revision_type: RevisionType
    source_strategy: SourceStrategy
    generated_output_role: GeneratedOutputRole
    requires_original_identity: bool
    requires_original_outfit: bool
    requires_external_refs: bool

    def __post_init__(self) -> None:
        for field, enum in (
            ("revision_type", RevisionType),
            ("source_strategy", SourceStrategy),
            ("generated_output_role", GeneratedOutputRole),
        ):
            if type(getattr(self, field)) is not enum:
                raise TypeError(f"{field} must be {enum.__name__}")
        for field in (
            "requires_original_identity",
            "requires_original_outfit",
            "requires_external_refs",
        ):
            if type(getattr(self, field)) is not bool:
                raise TypeError(f"{field} must be bool")

    def as_dict(self) -> dict[str, str | bool]:
        return {
            "revision_type": self.revision_type.value,
            "source_strategy": self.source_strategy.value,
            "generated_output_role": self.generated_output_role.value,
            "requires_original_identity": self.requires_original_identity,
            "requires_original_outfit": self.requires_original_outfit,
            "requires_external_refs": self.requires_external_refs,
        }


def normalize_revision_text(text: str) -> str:
    if not isinstance(text, str):
        raise TypeError("request_text must be str")
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


# These are intent phrases, not a general language model. More specific patterns
# precede broad nouns; unchanged/preservation clauses are filtered first.
_CONSTRAINT = re.compile(
    r"(?:背景|天空|场景|环境|人物|角色|脸|头发|衣服|服装|画风|风格)"
    r"(?:保持)?(?:不变|原样|不动|不修改|不改变)"
    r"|(?:保持|保留|维持|不要|别|无需)[^,，。;；!！\n]{0,35}"
    r"|(?:keep|preserve|leave)\s+[^,.;!\n]{0,45}",
    re.I,
)
_ARTIFACT = re.compile(
    r"波浪纹|涟漪|莫尔纹|摩尔纹|重复纹理|异常噪点|边缘扭曲|背景变脏|"
    r"背景(?:有|出现|产生|带有)?(?:脏|噪点|杂点)|moire|moiré|ripple|wave artifacts?|"
    r"repeated texture|noise artifacts?|warped edges?|重影|边缘(?:发糊|模糊|退化)|"
    r"发丝重复细纹|异常模糊|ghosting|blurred edges|edge degradation"
)
_IDENTITY = re.compile(
    r"阿尔可|身份|原来的样子|脸|面部|五官|眼睛|眼|虹膜|头发|发型|发色|发丝|"
    r"发梢|刘海|hair|hairstyle|face|eyes?|iris|identity|likeness"
)
_ANATOMY = re.compile(
    r"头太[大小]|头部比例|身体比例|身材比例|人体结构|手部|手指|双手|手臂|"
    r"四肢|解剖|画清楚|重画清楚|人物重新画|head proportion|body proportion|"
    r"anatomy|hands?|fingers?|limbs?"
)
_OUTFIT = re.compile(
    r"衣服|服装|服饰|穿着|领巾|裙裤|衬衫|肩带|原来的衣|outfit|clothing|"
    r"costume|garment|blouse|shirt structure"
)
_COMPOSITION = re.compile(
    r"构图|取景|裁切|镜头|画幅|人物.{0,6}(?:往[上下左右]|移|占画面|再大|再小|位置)|"
    r"位置.{0,6}(?:往[上下左右]|移动|调整)|画面.{0,8}(?:左|右|上|下)|"
    r"composition|framing|crop|placement|move (?:the )?(?:character|subject)|"
    r"(?:character|subject).{0,18}(?:larger|smaller|left|right|up|down)"
)
# Explicit subject distance and frame-scale edits. These stay inside the Phase 1
# composition domain; body/face proportions are deliberately not included.
_SUBJECT_SCALE_CHANGE = re.compile(
    r"(?:人物|角色|阿尔可).{0,8}(?:往近|靠近镜头|离镜头.{0,3}近|再大|再小|放大|小一点|太远|"
    r"在画面(?:中|里).{0,4}(?:太大|占比(?:更高|更多))|"
    r"占(?:画面|比).{0,4}(?:更多|再多|更高))|"
    r"镜头.{0,4}(?:靠近|拉近).{0,4}(?:人物|角色|阿尔可)"
)
# "不要这么远" requests a change, unlike a preservation clause. Detect it
# before the generic "不要..." constraint filter removes the phrase.
_CLOSER_NEGATIVE = re.compile(r"(?:人物|角色|阿尔可).{0,4}不要(?:这么|那么)?远")
_STYLE = re.compile(
    r"画风|风格|厚涂|线条|笔触|渲染|上色|赛璐璐|style|rendering|linework|"
    r"brushwork|shading|cel shading"
)
_SCENE = re.compile(
    r"背景|天空|环境|场景|灯光|光照|地面|建筑|便利店|树木|云层|"
    r"background|sky|environment|scene|lighting|light|ground|building"
)
_EXTERNAL_REQUEST = re.compile(
    r"(?:保留|沿用|继续用|使用|参考|按照|依照|遵照).{0,22}(?:外部|外来|提供的|上传的|参考图)|"
    r"(?:外部|外来|提供的|上传的|参考图).{0,22}(?:保留|沿用|继续用|使用|参考)|"
    r"(?:keep|use|follow|retain|preserve).{0,35}(?:external|supplied|uploaded|how reference)"
)


def _has_external_how(references: Sequence[Mapping[str, Any]]) -> bool:
    if isinstance(references, (str, bytes)) or not isinstance(references, Sequence):
        raise TypeError("external_references must be a sequence")
    for reference in references:
        if not isinstance(reference, Mapping):
            raise TypeError("external_references must contain mappings")
    return any(reference.get("source_scope") == "external_how" for reference in references)


def resolve_revision_intent(
    request_text: str, *, external_references: Sequence[Mapping[str, Any]] = ()
) -> RevisionPlan:
    """Classify an already-known revision; return metadata without executing it."""
    text = normalize_revision_text(request_text)
    has_external_how = _has_external_how(external_references)
    external_required = has_external_how and bool(_EXTERNAL_REQUEST.search(text))

    # A preservation clause can mention every visual domain; it is not an edit.
    retained_composition = bool(re.search(r"保留构图|保持构图|preserve composition", text))
    closer_negative = bool(_CLOSER_NEGATIVE.search(text))
    edits = _CONSTRAINT.sub(" ", text)
    artifact = bool(_ARTIFACT.search(edits))
    identity = bool(_IDENTITY.search(edits))
    anatomy = bool(_ANATOMY.search(edits))
    outfit = bool(_OUTFIT.search(edits))
    character = identity or anatomy or outfit
    composition = retained_composition or closer_negative or bool(
        _COMPOSITION.search(edits) or _SUBJECT_SCALE_CHANGE.search(edits)
    )
    style = bool(_STYLE.search(edits))
    scene = bool(_SCENE.search(edits))

    # Artifact locations ("background moiré") do not imply a separate scene edit.
    if artifact:
        scene = bool(re.search(r"(?:背景|天空|场景|background|sky|scene).{0,18}(?:亮|暗|颜色|换|改成|brighter|darker|color)", edits))
    domains = sum((artifact, character, composition, style, scene))
    unknown = domains == 0
    if unknown or domains > 1:
        revision_type = RevisionType.MIXED
    elif artifact:
        revision_type = RevisionType.ARTIFACT_REPAIR
    elif character:
        revision_type = RevisionType.CHARACTER_DETAIL
    elif composition:
        revision_type = RevisionType.COMPOSITION
    elif style:
        revision_type = RevisionType.STYLE
    else:
        revision_type = RevisionType.SCENE_ONLY

    if artifact:
        strategy = SourceStrategy.SOURCE_RESET
        role = GeneratedOutputRole.EXCLUDED
    elif character or style or unknown:
        strategy = SourceStrategy.REANCHOR_AND_REGENERATE
        role = GeneratedOutputRole.COMPOSITION_ANCHOR
    else:
        strategy = SourceStrategy.EDIT_CURRENT
        role = GeneratedOutputRole.PRIMARY_EDIT_SOURCE
    return RevisionPlan(revision_type, strategy, role, identity, outfit, external_required)
