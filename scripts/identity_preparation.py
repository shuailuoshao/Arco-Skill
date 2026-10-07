"""Independent, explicitly approved global back-identity calibration."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

from outfit_design import descriptions
from outfit_preparation import ROOT, _bindings, _style_prompt, identity_references
from preparation_support import confirm, freeze, invocation, load, new_id, utc, workspace, write
from reference_analysis import fail


def plan_identity_calibration(request: dict, *, root: Path = ROOT) -> dict:
    request = deepcopy(request)
    definition = request.get("back_definition")
    if not isinstance(definition, dict) or definition.get("schema_version") != 1:
        fail("IDENTITY_DESIGN_INVALID", "Define the proposed back hair/body construction before calibration.")
    descriptions(definition.get("fixed_constraints"), "back_definition.fixed_constraints", required=True)
    descriptions(definition.get("completion_decisions"), "back_definition.completion_decisions")
    refs, missing = identity_references(root, ["front", "right-three-quarter"], request.get("identity_assets"))
    if missing:
        fail("IDENTITY_CALIBRATION_PREREQUISITE", "This back-calibration path requires approved front and right three-quarter identity references.")
    references = [refs["front"], refs["right-three-quarter"]]
    bindings = _bindings(root, [], refs)
    prompt = "\n".join([
        "Identity Change: prepare a reusable global Arco back identity reference.",
        "Back full-body neutral standing view with no visible face or facial features, clear plain background. Preserve the approved Arco identity, hair color/construction and body proportions from the two official clothed identity inputs. Keep their existing clothing; this calibration does not define a new outfit.",
        "Apply only the following explicitly proposed rear construction and approved authored completions:",
        *definition["fixed_constraints"], *definition["completion_decisions"],
        "Image 1 and Image 2: approved Arco identity anchors. Do not inherit pose, expression or background.",
        _style_prompt(load(root / "character/style-baseline.yaml"))])
    plan = invocation(purpose="identity_calibration", view_id="identity-back", prompt=prompt, references=references, bindings=bindings)
    return freeze({"schema_version": 1, "purpose": "identity_calibration", "phase": "identity_design_and_generation", "status": "READY",
        "identity_change": True, "scope": "Global reusable back identity; separate from all outfit designs",
        "request": request, "design_definition": definition, "identity_references": refs,
        "main_plan": plan, "bindings": bindings, "max_automatic_repairs_per_image": 2,
        "calibration_targets": ["character.identity", "character.assets"]})


def create_identity_preparation(preview: dict, confirmation: dict, *, root: Path = ROOT) -> dict:
    confirm(confirmation, preview)
    if preview.get("purpose") != "identity_calibration" or not preview.get("identity_change") or plan_identity_calibration(preview["request"], root=root) != preview:
        fail("IDENTITY_APPROVAL_REQUIRED", "Confirm the separate global Identity Change preview.")
    pid = new_id("identity")
    path = workspace(root, pid)
    path.mkdir(parents=True, exist_ok=False)
    record = {"schema_version": 1, "preparation_id": pid, "purpose": "identity_calibration", "created_at": utc(), "state": "MAIN_READY",
        "request": deepcopy(preview["request"]), "sources": [], "design_definition": deepcopy(preview["design_definition"]),
        "required_views": ["identity-back"], "identity_references": deepcopy(preview["identity_references"]),
        "plans": {"identity-back": deepcopy(preview["main_plan"])}, "previews": {"design": deepcopy(preview)},
        "approvals": {"design": deepcopy(confirmation)}, "attempts": [], "candidates": [], "events": []}
    write(path / "preparation.yaml", record)
    return deepcopy(record)
