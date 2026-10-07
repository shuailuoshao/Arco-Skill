"""Deterministic, revision-only direct-edit preservation guidance."""

from __future__ import annotations

from dataclasses import dataclass

from revision_intent import RevisionPlan, RevisionType, normalize_revision_text


_SCOPE = {
    RevisionType.SCENE_ONLY: (
        "Change only the requested scene properties.",
        ("Preserve character appearance and identity.", "Preserve unrequested scene structures and lighting relationships."),
    ),
    RevisionType.CHARACTER_DETAIL: (
        "Change only the requested character detail or region.",
        ("Preserve the background and overall composition.", "Preserve unrequested character features and scene lighting."),
    ),
    RevisionType.COMPOSITION: (
        "Allow the requested spatial or compositional transformation, including necessary geometry changes.",
        ("Preserve unrelated character design and scene identity.", "Preserve unrequested lighting and rendering style."),
    ),
    RevisionType.STYLE: (
        "Allow the requested rendering or style transformation.",
        ("Preserve unrelated character and scene content and structure.",),
    ),
    RevisionType.MIXED: (
        "Allow every component explicitly requested in this revision to change.",
        ("Preserve character, scene, composition, and style properties unrelated to the request.",),
    ),
}

_LOW_FREQUENCY = (
    "Keep unaffected smooth backgrounds, gradients, and blurred regions smooth and visually stable.",
    "Keep unaffected large flat-color fields, soft lighting transitions, atmospheric haze, shadow fields, and broad glow regions stable.",
)
_ARTIFACT_AVOIDANCE = (
    "Do not introduce unrequested detail or texture into unaffected areas.",
    "Avoid ripple-like patterns, moire-like patterns, repetitive textures, and texture accumulation in unaffected areas.",
)


@dataclass(frozen=True)
class RevisionStabilityGuard:
    enabled: bool
    execution_scope: str
    requested_scope: str
    preserve_unaffected_regions: tuple[str, ...]
    protect_low_frequency_regions: tuple[str, ...]
    avoid_revision_artifacts: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "execution_scope": self.execution_scope,
            "requested_scope": self.requested_scope,
            "preserve_unaffected_regions": list(self.preserve_unaffected_regions),
            "protect_low_frequency_regions": list(self.protect_low_frequency_regions),
            "avoid_revision_artifacts": list(self.avoid_revision_artifacts),
        }


def build_revision_stability_guard(
    plan: RevisionPlan, execution_strategy: object, request_text: str,
) -> RevisionStabilityGuard | None:
    """Consume Phase 1 and Phase 3 decisions without revisiting either."""
    from revision_lineage import ExecutionStrategy

    if type(plan) is not RevisionPlan:
        raise TypeError("plan must be RevisionPlan")
    if type(execution_strategy) is not ExecutionStrategy:
        raise TypeError("execution_strategy must be ExecutionStrategy")
    normalized = normalize_revision_text(request_text)
    if not normalized:
        raise ValueError("revision request must be non-empty")
    if execution_strategy is ExecutionStrategy.SOURCE_RESET:
        return None
    if plan.revision_type is RevisionType.ARTIFACT_REPAIR:
        raise ValueError("artifact_repair cannot receive direct-edit Stability")
    scope, preservation = _SCOPE[plan.revision_type]
    return RevisionStabilityGuard(
        True, ExecutionStrategy.DIRECT_EDIT.value,
        f"{scope} Requested revision: {normalized}", preservation,
        _LOW_FREQUENCY, _ARTIFACT_AVOIDANCE,
    )


def compile_revision_stability(guard: RevisionStabilityGuard) -> str:
    if type(guard) is not RevisionStabilityGuard or not guard.enabled or guard.execution_scope != "DIRECT_EDIT":
        raise ValueError("an enabled DIRECT_EDIT Stability guard is required")
    lines = [
        "[Revision Stability — DIRECT_EDIT]",
        "Requested scope: " + guard.requested_scope,
        "Preserve unaffected regions: " + " ".join(guard.preserve_unaffected_regions),
        "Protect smooth regions: " + " ".join(guard.protect_low_frequency_regions),
        "Avoid unrequested artifacts: " + " ".join(guard.avoid_revision_artifacts),
        "These instructions apply only outside the requested change and do not override formal Identity, Outfit, or External HOW references.",
        "[/Revision Stability]",
    ]
    return "\n".join(lines)
