"""Purpose-bound preparation previews, candidate ledger and visual review.

Files and caller-supplied inspection records are validated here. This module
does not inspect pixels or turn a passing technical check into human approval.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
from typing import Any
from uuid import uuid4

import yaml

from reference_analysis import digest, fail, file_hash, text
from reference_runtime import validate_generation_reference_input

PURPOSES = {"outfit_preparation", "identity_calibration"}
CHECKS = ("identity", "parts", "wearing_occlusion", "cross_view", "image_quality")
IDENTITY_EXCLUSIONS = ["source_person_identity", "source_hair", "source_expression", "source_pose", "source_style", "source_background", "unselected_accessories"]
ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return prefix + "-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:6]


def load(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        fail("PREPARATION_INVALID", f"Expected a mapping: {path}")
    return data


def write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp-" + uuid4().hex)
    temporary.write_bytes(yaml.safe_dump(data, allow_unicode=True, sort_keys=False).encode("utf-8"))
    os.replace(temporary, path)


def inside(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        fail("PREPARATION_PATH_INVALID", "Expected a relative workspace path.")
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        fail("PREPARATION_PATH_INVALID", "Path escapes its workspace.")
    return path


def workspace(root: Path, preparation_id: str) -> Path:
    if not isinstance(preparation_id, str) or not re.fullmatch(r"(?:prep|identity)-[A-Za-z0-9-]+", preparation_id):
        fail("PREPARATION_PATH_INVALID", "Invalid preparation ID.")
    return inside(root, "calibration/preparations/" + preparation_id)


@contextmanager
def locked(path: Path):
    """Kernel-owned lock, released on process exit; no PID signalling.

    Windows uses the stdlib msvcrt byte lock; POSIX uses flock. The sentinel
    file remains in place to avoid racing deletion/recreation of a lock inode.
    https://docs.python.org/3/library/msvcrt.html#msvcrt.locking
    """
    handle = (path / ".record-lock").open("a+b")
    if handle.tell() == 0:
        handle.write(b"0")
        handle.flush()
    handle.seek(0)
    if os.name == "nt":
        import msvcrt
        acquire = lambda: msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        release = lambda: msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        acquire = lambda: fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        release = lambda: fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    try:
        acquire()
    except OSError:
        handle.close()
        fail("PREPARATION_BUSY", "Another operation owns this preparation.")
    try:
        yield
    finally:
        handle.seek(0)
        try:
            release()
        finally:
            handle.close()


def freeze(payload: dict) -> dict:
    result = deepcopy(payload)
    result["preview_sha256"] = digest(payload)
    return result


def check_preview(preview: dict) -> None:
    if preview.get("preview_sha256") != digest({k: v for k, v in preview.items() if k != "preview_sha256"}):
        fail("PREPARATION_PLAN_STALE", "Preview contents changed.")
    for path, expected in preview.get("bindings", {}).items():
        current = file_hash(path) if Path(path).is_file() else None
        if current != expected:
            fail("PREPARATION_PLAN_STALE", "Reference or library changed: " + path)


def confirm(confirmation: Any, preview: dict) -> dict:
    check_preview(preview)
    if not isinstance(confirmation, dict) or confirmation.get("user_confirmed") is not True:
        fail("PREPARATION_CONFIRMATION_REQUIRED", "Show the complete preview and obtain explicit human confirmation.")
    if confirmation.get("preview_sha256") != preview["preview_sha256"]:
        fail("PREPARATION_CONFIRMATION_STALE", "Confirmation does not bind to the current preview.")
    text(confirmation.get("user_message"), "confirmation.user_message")
    return deepcopy(confirmation)


def invocation(*, purpose: str, view_id: str, prompt: str, references: list[dict], bindings: dict, context: dict | None = None) -> dict:
    if purpose not in PURPOSES or not references or len(references) > 5:
        fail("REFERENCE_LIMIT_EXCEEDED", "A preparation view requires one to five explicitly selected image inputs.")
    if len({x["reference_id"] for x in references}) != len(references):
        fail("PREPARATION_CONTRACT_INVALID", "Reference IDs must be unique.")
    result = {"provider": "builtin_image_gen", "capability": "reference_conditioned_image_generation",
              "mode": "reference_conditioned", "purpose": purpose, "view_id": view_id,
              "prompt": prompt, "references": deepcopy(references), "bindings": deepcopy(bindings),
              "selected_reference_ids": [x["reference_id"] for x in references],
              "referenced_image_paths": [x["path"] for x in references], "max_automatic_repairs": 2}
    if context is not None:
        result["context_sha256"] = digest(context)
    result["plan_sha256"] = digest(result)
    return result


def validate_record(record: dict) -> None:
    """Authored design and source analysis must still be the approved inputs."""
    preview = record.get("previews", {}).get("design") or {}
    confirm(record.get("approvals", {}).get("design"), preview)
    expected = preview.get("selected_design") if record.get("purpose") == "outfit_preparation" else preview.get("design_definition")
    if record.get("design_definition") != expected or record.get("request") != preview.get("request") or record.get("identity_references") != preview.get("identity_references"):
        fail("PREPARATION_CONFIRMATION_STALE", "Design, request or identity selection changed; return to the design confirmation stage.")
    if record.get("purpose") == "outfit_preparation":
        sources = [{k: v for k, v in source.items() if k not in {"retained_path", "retained_original_path"}} for source in record.get("sources", [])]
        if sources != preview.get("sources"):
            fail("PREPARATION_CONFIRMATION_STALE", "Material analysis changed; return to the design confirmation stage.")


def _edit_reference(candidate: dict) -> dict:
    return {"reference_id": "edit-target-" + candidate["candidate_id"], "usage": "edit_target",
        "candidate_id": candidate["candidate_id"], "view_id": candidate["view_id"],
        "path": candidate["path"], "sha256": candidate["sha256"]}


def _repair_constraints(record: dict, review: dict | None) -> list[str]:
    """Emphasize selected approved parts, never compile inspection prose."""
    parts = (review or {}).get("restore_design_parts", [])
    if not isinstance(parts, list) or any(not isinstance(p, str) for p in parts) or len(set(parts)) != len(parts):
        fail("VISUAL_REVIEW_INVALID", "Restore distinct approved design parts only.")
    if not parts:
        return []
    design = record.get("design_definition", {}).get("parts", {})
    checks = (review or {}).get("checks", {})
    if (record["purpose"] != "outfit_preparation" or any(p not in design for p in parts)
            or not any(checks.get(k, {}).get("status") == "FAIL" for k in ("parts", "wearing_occlusion", "cross_view"))):
        fail("VISUAL_REVIEW_INVALID", "Part restoration requires a failed garment inspection and approved part IDs.")
    constraints = []
    for part_id in parts:
        part = design[part_id]
        constraints.extend([part["description"], *part["fixed_features"]])
    return constraints


def _attempt_invocation(original: dict, attempt: dict) -> dict:
    bound = deepcopy(original)
    if attempt["repair_number"]:
        bound["prompt"] += "\nRepair within the approved design only. Restore the original targets for: " + ", ".join(attempt["restore_dimensions"]) + ". Keep every other approved constraint."
        if attempt.get("restore_constraints"):
            bound["prompt"] += "\nPrioritize these exact approved requirements in this correction:\n" + "\n".join("- " + c for c in attempt["restore_constraints"])
            if original["view_id"] in {"front", "right-three-quarter", "back"} and any("主要露鞋尖" in c for c in attempt["restore_constraints"]):
                visible_foot_edge = ("leaving only small black rear heel or sole edges visible below the hem; keep both feet rear-facing and do not show front toe tips"
                    if original["view_id"] == "back" else "leaving only the black rounded toe tips visible below the hem")
                bound["prompt"] += ("\nRestore the approved shoe-tip-only hem coverage literally: all skirt layers must conceal the shins, ankles and shoe uppers, " + visible_foot_edge + ". "
                    "Extend the apron with the dress while retaining the approved continuous black dress border below the white apron ruffle. "
                    "The hosiery is intentionally hidden in this wearing view and will be checked in a separate garment detail image. Do not shorten the dress to display white stockings.")
            if original["view_id"] in {"back", "detail-back-apron"} and any("围裙覆盖连衣裙胸腹和裙身前方" in c for c in attempt["restore_constraints"]):
                bound["prompt"] += ("\nRestore the approved FRONT apron coverage: the bib and apron skirt cover the front of the black dress only. "
                    "In rear view only the front apron side edges may appear at the left and right sides; leave the central rear skirt black. "
                    "Do not join the two side edges with a white horizontal or U-shaped ruffle across the rear skirt. "
                    "Preserve the rear X shoulder straps and centered waist bow with exactly two tails.")
            if original["view_id"] == "detail-hosiery-footwear" and any("四条白色吊带（每腿前后各一条）" in c for c in attempt["restore_constraints"]):
                bound["prompt"] += ("\nThis correction is exclusively a garment-only flat-lay connection diagram of the approved hosiery and shoes. "
                    "Show ONE white waist belt and ONE pair of opaque white thigh-high stockings. Show exactly FOUR white straps physically connected from that belt to the stocking tops: "
                    "two straps per stocking, one front and one rear, each ending in a small plain clip actually gripping the stocking cuff. "
                    "Arrange the garments without a body so all four complete belt-to-cuff connections are visible; use a small garment-only rear connection inset if necessary. "
                    "Do not leave straps or clips dangling separately from the stockings. Do not duplicate the belt or depict extra stocking pairs. "
                    "Do not depict a person, skin, knees, body fragments, dress, apron, headband, collar, bow or general outfit sheet. "
                    "Keep the approved plain black closed rounded shoes and show their full low-heel silhouette, approximately two centimeters high, without a tall heel block.")
    if attempt.get("edit_target"):
        if attempt["repair_number"] < 1 or attempt.get("correction_code") != "back-knee-orientation" or original["view_id"] not in {"back", "identity-back"}:
            fail("PREPARATION_REPAIR_TARGET_INVALID", "This bounded correction restores rear knee orientation only.")
        ref = deepcopy(attempt["edit_target"])
        bound["references"].append(ref)
        bound["selected_reference_ids"].append(ref["reference_id"])
        bound["referenced_image_paths"].append(ref["path"])
        bound["bindings"][ref["path"]] = ref["sha256"]
        bound["correction_code"] = attempt["correction_code"]
        bound["prompt"] += (f"\nImage {len(bound['references'])} is the exact same-view edit target, not a new identity or outfit reference. "
            "Edit only both knee regions to a strict rear view. Depict the backs of the knees with soft recessed posterior folds transitioning into the rear calves beneath the same opaque dark stockings. "
            "Remove anterior kneecap bulges and oval patella highlights. Keep the existing stocking material and color, leg length, leg alignment and rear-facing feet. "
            "Preserve every region outside the knees, especially the exact hair silhouette, hair strands, silver-blue and pink color bands, head, clothing, hands, shoes, pose, camera, background and drawing style. No annotations.")
    bound.update(attempt_id=attempt["attempt_id"], repair_number=attempt["repair_number"])
    return bound


def validate_invocation(plan: dict, *, root: Path, record: dict) -> dict:
    """The adapter's candidate lane cannot accept ordinary or ad-hoc plans."""
    purpose = plan.get("purpose")
    if purpose not in PURPOSES or purpose != record.get("purpose"):
        fail("PREPARATION_PURPOSE_MISMATCH", "Preparation and adapter purposes must match.")
    validate_record(record)
    if plan.get("provider") != "builtin_image_gen" or plan.get("capability") != "reference_conditioned_image_generation" or plan.get("mode") != "reference_conditioned":
        fail("PREPARATION_CONTRACT_INVALID", "Use the built-in reference-conditioned generator.")
    original = record.get("plans", {}).get(plan.get("view_id"))
    if not original:
        fail("PREPARATION_CONTRACT_INVALID", "No approved plan for this view.")
    approval_key = "design" if plan["view_id"] in {"front", "identity-back"} else "main_and_views"
    approved = record.get("approvals", {}).get(approval_key)
    preview = record.get("previews", {}).get(approval_key)
    confirm(approved, preview or {})
    approved_plan = preview.get("main_plan") if approval_key == "design" else preview.get("plans", {}).get(plan["view_id"])
    if original != approved_plan or original.get("plan_sha256") != digest({k: v for k, v in original.items() if k != "plan_sha256"}):
        fail("PREPARATION_PLAN_STALE", "Saved invocation is no longer the plan shown in the approved preview.")
    attempt = next((item for item in record.get("attempts", []) if item["attempt_id"] == plan.get("attempt_id")), None)
    if not attempt or attempt["state"] != "RESERVED" or attempt["plan_sha256"] != original["plan_sha256"]:
        fail("PREPARATION_ATTEMPT_INVALID", "A saved attempt reservation is required.")
    if attempt["repair_number"] > 2:
        fail("AUTOMATIC_REPAIR_LIMIT", "At most two repairs per view and approved goal.")
    if attempt["repair_number"]:
        earlier = [a for a in record["attempts"] if a["view_id"] == plan["view_id"] and a["plan_sha256"] == original["plan_sha256"] and a["attempt_id"] != attempt["attempt_id"]]
        previous_review = next((c.get("review") for c in record["candidates"] if earlier and c["attempt_id"] == earlier[-1]["attempt_id"]), None)
        if attempt.get("restore_constraints", []) != _repair_constraints(record, previous_review):
            fail("PREPARATION_PLAN_STALE", "Repair emphasis differs from the failed inspection's approved design parts.")
    bound = _attempt_invocation(original, attempt)
    # The repair template is closed. Neither inspection prose nor failed output
    # is allowed to become a new design or a reference for another view.
    if plan != bound:
        fail("PREPARATION_PLAN_STALE", "Invocation differs from its approved plan or bounded repair.")
    check_preview(freeze({"bindings": original["bindings"]}))
    refs = plan["references"]
    if not refs or len(refs) > 5 or plan["referenced_image_paths"] != [x["path"] for x in refs]:
        fail("PREPARATION_CONTRACT_INVALID", "Image input paths must match the selected contracts.")
    for index, ref in enumerate(refs, 1):
        path = Path(ref["path"])
        if not path.is_file() or file_hash(path) != ref.get("sha256"):
            fail("PREPARATION_PLAN_STALE", "Reference contents changed.")
        normalized = path.as_posix().casefold()
        if "calibration/staging" in normalized:
            fail("UNPUBLISHED_ASSET", "Formal staging is never a generation input.")
        validate_generation_reference_input(ref, root=root)
        if ref["usage"] in {"garment", "identity_and_garment"}:
            exclusions = ref.get("garment_exclude") if ref["usage"] == "identity_and_garment" else ref.get("exclude")
            if exclusions != IDENTITY_EXCLUSIONS or not ref.get("parts"):
                fail("PREPARATION_CONTRACT_INVALID", "Garment inputs require selected regions and wearer/style exclusions.")
            if f"Image {index} garment-only" not in plan["prompt"]:
                fail("PREPARATION_CONTRACT_INVALID", "Prompt lost its garment-only binding.")
        elif ref["usage"] == "accepted_primary":
            main = record.get("locked_main") or {}
            if ref.get("candidate_id") != main.get("candidate_id") or ref["sha256"] != main.get("sha256"):
                fail("PREPARATION_MAIN_STALE", "Only the human-accepted primary may drive dependent views.")
        elif ref["usage"] == "edit_target":
            candidate = get_candidate(record, ref.get("candidate_id"))
            earlier = [a for a in record["attempts"] if a["view_id"] == plan["view_id"] and a["plan_sha256"] == original["plan_sha256"] and a["attempt_id"] != attempt["attempt_id"]]
            if (not earlier or candidate["attempt_id"] != earlier[-1]["attempt_id"]
                    or candidate["view_id"] != plan["view_id"] or candidate["plan_sha256"] != original["plan_sha256"]
                    or (candidate.get("review") or {}).get("status") != "FAIL" or ref != _edit_reference(candidate)):
                fail("PREPARATION_REPAIR_TARGET_INVALID", "Edit only the latest failed candidate of this view and approved goal.")
            text(attempt.get("user_repair_message"), "repair.user_message")
        elif ref["usage"] != "identity":
            fail("PREPARATION_CONTRACT_INVALID", "Unknown preparation input duty.")
        if "calibration/preparations" in normalized and ref["usage"] not in {"accepted_primary", "edit_target"}:
            fail("UNAPPROVED_PREPARATION_REFERENCE", "Candidates cannot supply identity or source garment authority.")
    return {"prompt": plan["prompt"], "referenced_image_paths": list(plan["referenced_image_paths"])}


def run_candidate(*, root: Path, preparation_id: str, view_id: str, adapter: Any, repair: bool = False,
                  repair_target_candidate_id: str | None = None, correction_code: str | None = None,
                  user_repair_message: str | None = None) -> dict:
    path = workspace(root, preparation_id)
    with locked(path):
        record = load(path / "preparation.yaml")
        if record.get("state") in {"PUBLISHED", "PUBLICATION_STAGED", "RECOVERY_REQUIRED"}:
            fail("PREPARATION_STATE_INVALID", "Generation is closed while publishing or after completion.")
        plan = record.get("plans", {}).get(view_id)
        if not plan:
            fail("PREPARATION_CONFIRMATION_REQUIRED", "Confirm this stage's exact preview first.")
        if any(x is not None for x in (repair_target_candidate_id, correction_code, user_repair_message)) and not repair:
            fail("PREPARATION_REPAIR_TARGET_INVALID", "An edit target belongs only to a bounded repair.")
        attempts = [x for x in record["attempts"] if x["view_id"] == view_id and x["plan_sha256"] == plan["plan_sha256"]]
        if attempts and not repair:
            fail("PREPARATION_RETRY_REQUIRES_REPAIR", "Retained attempts require a bounded repair or a newly confirmed plan.")
        number = len(attempts) if repair else 0
        if repair:
            if not attempts or number > 2:
                fail("AUTOMATIC_REPAIR_LIMIT", "Two automatic repairs are available, including failed calls.")
            previous = attempts[-1]
            review = next((x.get("review") for x in record["candidates"] if x["attempt_id"] == previous["attempt_id"]), None)
            if previous["state"] not in {"FAILED", "INTERRUPTED"} and (not review or review["status"] != "FAIL"):
                fail("AUTOMATIC_REPAIR_REVIEW_REQUIRED", "Repair needs a bound failed inspection or failed call.")
            restore = [k for k, v in (review or {}).get("checks", {}).items() if v["status"] == "FAIL"] or list(CHECKS)
        else:
            restore = []
        attempt = {"attempt_id": uuid4().hex, "view_id": view_id, "plan_sha256": plan["plan_sha256"],
                    "repair_number": number, "restore_dimensions": restore, "state": "RESERVED", "reserved_at": utc()}
        if repair:
            constraints = _repair_constraints(record, review)
            if constraints:
                attempt["restore_constraints"] = constraints
        if any(x is not None for x in (repair_target_candidate_id, correction_code, user_repair_message)):
            text(user_repair_message, "repair.user_message")
            candidate = get_candidate(record, repair_target_candidate_id)
            if (correction_code != "back-knee-orientation" or view_id not in {"back", "identity-back"}
                    or candidate["view_id"] != view_id or candidate["attempt_id"] != previous["attempt_id"]
                    or candidate["plan_sha256"] != plan["plan_sha256"] or (candidate.get("review") or {}).get("status") != "FAIL"):
                fail("PREPARATION_REPAIR_TARGET_INVALID", "Restore rear knees on the latest failed same-view candidate only.")
            if len(plan["references"]) >= 5:
                fail("REFERENCE_LIMIT_EXCEEDED", "A same-view edit target still counts toward the five-image limit.")
            attempt.update(edit_target=_edit_reference(candidate), correction_code=correction_code,
                user_repair_message=user_repair_message)
        record["attempts"].append(attempt)
        record["state"] = "GENERATING"
        call = _attempt_invocation(plan, attempt)
        attempt.update(actual_prompt_sha256=digest(call["prompt"]), invocation_sha256=digest(call))
        write(path / "preparation.yaml", record)  # Failed calls consume the reserved repair.
        try:
            operation = adapter.generate_identity_calibration if record["purpose"] == "identity_calibration" else adapter.generate_preparation
            output = operation(invocation_plan=call, root=root, preparation_id=preparation_id)
            candidate_id = view_id + "-" + attempt["attempt_id"][:8]
            target = inside(path, "candidates/" + candidate_id + Path(output).suffix)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(output, target)
            candidate = {"candidate_id": candidate_id, "view_id": view_id, "path": str(target),
                         "sha256": file_hash(target), "plan_sha256": plan["plan_sha256"],
                         "attempt_id": attempt["attempt_id"], "repair_number": number,
                         "actual_prompt_sha256": attempt["actual_prompt_sha256"],
                         "main_sha256": (record.get("locked_main") or {}).get("sha256"),
                         "review": None, "user_accepted": False, "invalidated": False}
            if attempt.get("edit_target"):
                candidate.update(repair_source_candidate_id=attempt["edit_target"]["candidate_id"],
                    correction_code=attempt["correction_code"], repair_input_bindings=deepcopy(call["references"]))
            record["candidates"].append(candidate)
            attempt.update(state="COMPLETED", candidate_id=candidate_id, completed_at=utc())
            record["state"] = "AWAITING_VISUAL_REVIEW"
            return deepcopy(candidate)
        except Exception as exc:
            attempt.update(state="FAILED", error=str(exc), completed_at=utc())
            record["state"] = "NEEDS_USER_DECISION" if number >= 2 else "GENERATION_FAILED"
            raise
        finally:
            write(path / "preparation.yaml", record)


def get_candidate(record: dict, candidate_id: str) -> dict:
    candidate = next((x for x in record["candidates"] if x["candidate_id"] == candidate_id), None)
    if candidate is None or candidate.get("invalidated") or not Path(candidate["path"]).is_file() or file_hash(candidate["path"]) != candidate["sha256"]:
        fail("PREPARATION_CANDIDATE_STALE", "Candidate is missing, changed or invalidated.")
    return candidate


def record_visual_review(*, root: Path, preparation_id: str, candidate_id: str, review: dict) -> dict:
    path = workspace(root, preparation_id)
    with locked(path):
        record = load(path / "preparation.yaml")
        if record.get("state") in {"PUBLICATION_STAGED", "PUBLISHED", "RECOVERY_REQUIRED"}:
            fail("PREPARATION_STATE_INVALID", "Inspection records are frozen by the accepted publication transaction.")
        candidate = get_candidate(record, candidate_id)
        if not isinstance(review, dict) or review.get("output_sha256") != candidate["sha256"] or review.get("plan_sha256") != candidate["plan_sha256"] or review.get("inspected_original_size") is not True:
            fail("VISUAL_REVIEW_INVALID", "Inspect the original-size candidate and bind its image and plan hashes.")
        checks = review.get("checks")
        if not isinstance(checks, dict) or set(checks) != set(CHECKS):
            fail("VISUAL_REVIEW_INVALID", "Check identity, parts, wearing/occlusion, cross-view consistency and image quality separately.")
        for key, check in checks.items():
            if not isinstance(check, dict) or check.get("status") not in {"PASS", "FAIL", "UNVERIFIED"}:
                fail("VISUAL_REVIEW_INVALID", "Invalid visual check: " + key)
            text(check.get("evidence"), "visual_review." + key)
        statuses = {x["status"] for x in checks.values()}
        _repair_constraints(record, review)
        if candidate.get("review"):
            candidate.setdefault("review_history", []).append(deepcopy(candidate["review"]))
        candidate["review"] = deepcopy(review)
        candidate["review"]["status"] = "FAIL" if "FAIL" in statuses else "UNVERIFIED" if "UNVERIFIED" in statuses else "PASS"
        candidate["review"]["user_accepted"] = False
        previous_pack = record.pop("pack_review", None)
        if previous_pack:
            record.setdefault("pack_review_history", []).append(previous_pack)
        if record.get("locked_main", {}).get("candidate_id") == candidate_id and candidate["review"]["status"] != "PASS":
            candidate["user_accepted"] = False
            invalidate_dependents(record)
            record.pop("locked_main", None)
        record["state"] = "AWAITING_ACCEPTANCE" if candidate["review"]["status"] == "PASS" else "NEEDS_REPAIR"
        write(path / "preparation.yaml", record)
        return deepcopy(candidate["review"])


def invalidate_dependents(record: dict) -> None:
    if record.get("previews", {}).get("main_and_views"):
        record.setdefault("plan_history", []).append({"at": utc(), "reason": "main_invalidated",
            "plans": deepcopy(record["plans"]), "previews": deepcopy(record["previews"]),
            "approvals": deepcopy(record["approvals"]), "locked_main": deepcopy(record.get("locked_main")), "pack_review": deepcopy(record.get("pack_review"))})
    for item in record["candidates"]:
        if item["view_id"] not in {"front", "identity-back"}:
            item.update(invalidated=True, user_accepted=False)
    record["plans"] = {k: v for k, v in record["plans"].items() if k in {"front", "identity-back"}}
    record["approvals"].pop("main_and_views", None)
    record["previews"].pop("main_and_views", None)
    previous_pack = record.pop("pack_review", None)
    if previous_pack:
        record.setdefault("pack_review_history", []).append(previous_pack)


def resume_preparation(*, root: Path, preparation_id: str) -> dict:
    path = workspace(root, preparation_id)
    with locked(path):
        record = load(path / "preparation.yaml")
        interrupted = False
        for attempt in record["attempts"]:
            if attempt["state"] == "RESERVED":
                attempt.update(state="INTERRUPTED", error="Interrupted provider call; attempt remains consumed.")
                interrupted = True
        if interrupted:
            record["state"] = "GENERATION_FAILED"
            write(path / "preparation.yaml", record)
        return deepcopy(record)
