# Phase 3 revision lineage and Source Reset

Each production result serializes `output_id` (absolute resolved output path),
`generation_depth` (`0` or `1`), `parent_output` (output ID or `null`),
`source_generation_id` (current root output ID), and
`reset_triggered_from_output` (output ID or `null`). A first generation is its
own root at depth 0. A direct edit has depth 1, names its direct parent, and
retains that parent's root. A Source Reset has depth 0, becomes a new root,
has no direct edit parent, and names the prior output as its reset trigger.

The revision executor consumes the frozen Phase 1 `RevisionPlan`. At depth 0,
an ordinary revision takes the existing direct-edit path. At depth 1, it takes
Source Reset. `artifact_repair` or `source_strategy=source_reset` takes Source
Reset at either depth. A direct edit from depth 1 is rejected before a provider
call. Missing or inconsistent parent lineage is also rejected.

Source Reset requires the canonical first-generation request. It compiles a
fresh-generation instruction from that source request and the complete ordered revision context.
The Phase 2A reference path restores formal managed Identity, formal Outfit
for a selected Variant, and canonical External HOW references. The previous
output is included only as a composition anchor when the frozen plan permits
it; an `excluded` role omits it. It never owns WHO or Variant authority.
Missing required source truth fails before a provider call. Source Reset does
not inspect pixels, score quality, retry, or perform visual A/B evaluation.

Caller-reported degradation forces Source Reset and excludes the parent image,
even when the intent plan would preserve composition. The result carries the
full revision context across resets and starts with visual review `unchecked`.
See [revision workflow](revision-reference.md) for review and legacy recovery.
