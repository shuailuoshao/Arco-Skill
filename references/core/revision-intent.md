# Revision Intent Resolver — Phase 1

`scripts.revision_intent.resolve_revision_intent(request_text, *, external_references=())` accepts an explicit revision request and returns a frozen `RevisionPlan`. The caller decides that a request is a revision before calling it. First-generation production requests continue through `run_production_generation()` without this resolver. No planning field is consumed by the production runtime in Phase 1.

`RevisionPlan` has six required fields and no defaults: closed `RevisionType`, `SourceStrategy`, and `GeneratedOutputRole` enums, plus strict booleans `requires_original_identity`, `requires_original_outfit`, and `requires_external_refs`. `as_dict()` emits these fields in that order with enum string values. Invalid constructor types raise `TypeError`.

Input text undergoes Unicode NFKC, case folding, trimming, and whitespace collapse. There is no translation, image inspection, model inference, or provider call. A small Chinese/English phrase vocabulary recognizes scene/environment, face/eyes/hair/identity, anatomy/hands/body proportion, outfit, composition/placement/scale in frame, rendering/style, and explicit artifact symptoms. Preservation clauses such as “背景不变” are excluded from edit detection. “保留构图” remains a composition requirement when paired with a character redraw. Unknown intent fails closed to `mixed`.

Explicit subject distance and frame-scale changes such as “人物往近一点”, “人物不要这么远”, “把人物放大一些”, and “人物占画面更多” are composition edits. The positive scale phrases are checked after preservation clauses are filtered; the negative-distance request “不要这么远” is recognized before that filter, since it requests a closer character rather than preserving an unchanged region. “人物往近一点，让脸清楚” is `mixed`, retaining the face-related identity requirement. “头太大” remains an anatomy edit, while “人物在画面里太大” is a framing edit.

| Detected edit | `revision_type` | `source_strategy` | `generated_output_role` |
| --- | --- | --- | --- |
| Scene only | `scene_only` | `edit_current` | `primary_edit_source` |
| Character detail only | `character_detail` | `reanchor_and_regenerate` | `composition_anchor` |
| Composition only | `composition` | `edit_current` | `primary_edit_source` |
| Style only | `style` | `reanchor_and_regenerate` | `composition_anchor` |
| Artifact symptom only, including a scene location | `artifact_repair` | `source_reset` | `excluded` |
| Multiple independent domains | `mixed` | Artifact: `source_reset`; otherwise character/style: `reanchor_and_regenerate`; otherwise `edit_current` | Artifact: `excluded`; otherwise character/style: `composition_anchor`; otherwise `primary_edit_source` |
| No recognized edit | `mixed` | `reanchor_and_regenerate` | `composition_anchor` |

Every detected domain is considered before classification; no first match wins. An artifact symptom and a separate scene color or lighting change are mixed, while “背景出现莫尔纹” is artifact repair alone. Identity requirement is true for face, eyes, hair, or explicit identity intent. Outfit requirement is true for clothing or outfit structure. Anatomy and hands are character detail without automatically requiring identity or outfit. `requires_external_refs` is true only when the request explicitly says to retain or use an external HOW reference and `external_references` contains a `source_scope: external_how` contract. A supplied reference alone does not set the flag.

This is semantic planning metadata. Phase 1 does not execute edit-current, re-anchor, source reset, reference carry-through, or image generation.
