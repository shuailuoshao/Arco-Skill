#!/usr/bin/env python3
"""Production Style Transfer generation entrypoint.

This module is the normal Arco Skill orchestration boundary.  It composes the
already validated reference runtime and real adapter; it does not contain an
experiment runner, manifest, retry loop, visual evaluation, or evidence writer.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import yaml

from arco_real_adapter import ArcoRealAdapter
from reference_runtime import (
    REFERENCE_ROLES,
    ReferenceRuntimeError,
    build_invocation_plan,
    compile_prompt,
    compute_request_reference_readiness,
    resolve_style_context,
    resolve_style_references,
    select_references,
)


ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_CONFIG_PATH = Path("runtime/production.yaml")
GENERATION_CONFIG_PATH = Path("runtime/generation.yaml")
IDENTITY_PATH = Path("character/identity.yaml")
ASSETS_PATH = Path("character/assets.yaml")
VARIANTS_PATH = Path("variants/index.yaml")
STYLE_BASELINE_PATH = Path("character/style-baseline.yaml")
HYGIENE_POLICY_PATH = Path("runtime/style-policy.yaml")

DEFAULT_REQUESTED_ROLES = ("identity_reference",)
VALID_HYGIENE_MODES = frozenset({"off", "hygiene_v11"})
ALLOWED_REQUEST_KEYS = frozenset(
    {
        "base_prompt",
        "exposure_profile",
        "variant_id",
        "arco_references",
        "request_scoped_arco_references",
        "external_references",
        "style_briefs",
        "user_style_overrides",
        "allow_uncertain_working",
        "rendering_hygiene",
    }
)


class ProductionGenerationError(ReferenceRuntimeError):
    """A stable production request/configuration error."""


def _error(code: str, message: str) -> None:
    raise ProductionGenerationError(code, message)


def _load_yaml(root: Path, relative: Path, *, label: str) -> dict[str, Any]:
    path = (root / relative).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError:
        _error("PRODUCTION_CONFIG_INVALID", f"{label} escapes the production root.")
    if not path.is_file():
        _error("PRODUCTION_CONFIG_INVALID", f"Missing {label}: {relative.as_posix()}")
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        _error("PRODUCTION_CONFIG_INVALID", f"Could not read {label}: {exc}")
    if not isinstance(value, dict):
        _error("PRODUCTION_CONFIG_INVALID", f"{label} must be a mapping.")
    return value


def _sequence(value: Any, *, field: str) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        _error("MALFORMED_GENERATION_PLAN", f"{field} must be a list.")
    return list(value)


def _mapping(value: Any, *, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _error("MALFORMED_GENERATION_PLAN", f"{field} must be a mapping.")
    return value


def _validate_production_config(config: Mapping[str, Any]) -> None:
    production = config.get("production")
    if not isinstance(production, Mapping):
        _error("PRODUCTION_CONFIG_INVALID", "Production config is missing its production mapping.")
    style_transfer = production.get("style_transfer")
    hygiene = production.get("rendering_hygiene")
    if not isinstance(style_transfer, Mapping) or style_transfer.get("default") != "enabled":
        _error("PRODUCTION_CONFIG_INVALID", "Production Style Transfer default must be enabled.")
    if not isinstance(hygiene, Mapping) or hygiene.get("default") != "disabled":
        _error("PRODUCTION_CONFIG_INVALID", "Production Rendering Hygiene default must be disabled.")
    if hygiene.get("experimental_opt_in") != "hygiene_v11":
        _error("PRODUCTION_CONFIG_INVALID", "Production Hygiene opt-in must be hygiene_v11.")


def _normalize_request(request: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(request, Mapping):
        _error("MALFORMED_GENERATION_PLAN", "Production request must be a mapping.")
    unknown = sorted(set(request) - ALLOWED_REQUEST_KEYS)
    if unknown:
        _error(
            "MALFORMED_GENERATION_PLAN",
            f"Experiment or unsupported request fields are not accepted: {unknown}",
        )
    base_prompt = request.get("base_prompt")
    if not isinstance(base_prompt, str) or not base_prompt.strip():
        _error("INVALID_PROMPT", "base_prompt must be non-empty text.")
    profile = request.get("exposure_profile", "upper_body")
    if not isinstance(profile, str) or not profile:
        _error("INVALID_EXPOSURE_PROFILE", str(profile))
    hygiene = request.get("rendering_hygiene", "off")
    if hygiene not in VALID_HYGIENE_MODES:
        _error("INVALID_RENDERING_HYGIENE_MODE", str(hygiene))
    variant_id = request.get("variant_id")
    if variant_id is not None and (not isinstance(variant_id, str) or not variant_id.strip()):
        _error("MALFORMED_GENERATION_PLAN", "variant_id must be a non-empty string when supplied.")
    allow_uncertain_working = request.get("allow_uncertain_working", False)
    if type(allow_uncertain_working) is not bool:
        _error("MALFORMED_GENERATION_PLAN", "allow_uncertain_working must be boolean.")
    return {
        "base_prompt": base_prompt,
        "exposure_profile": profile,
        "variant_id": variant_id,
        "arco_references": _sequence(request.get("arco_references"), field="arco_references"),
        "request_scoped_arco_references": _sequence(
            request.get("request_scoped_arco_references"),
            field="request_scoped_arco_references",
        ),
        "external_references": _sequence(
            request.get("external_references"),
            field="external_references",
        ),
        "style_briefs": request.get("style_briefs", []),
        "user_style_overrides": request.get("user_style_overrides"),
        "allow_uncertain_working": allow_uncertain_working,
        "rendering_hygiene": hygiene,
    }


def _managed_selection(
    *,
    request: Mapping[str, Any],
    all_assets: Sequence[Mapping[str, Any]],
) -> tuple[list[Mapping[str, Any]], list[str]]:
    descriptors = list(request["arco_references"])
    if descriptors and not all(isinstance(item, Mapping) for item in descriptors):
        _error("MALFORMED_GENERATION_PLAN", "arco_references must contain mappings.")

    if descriptors:
        by_id = {
            str(asset.get("asset_id")): asset
            for asset in all_assets
            if asset.get("asset_id") is not None
        }
        selected_assets: list[Mapping[str, Any]] = []
        roles: list[str] = []
        for descriptor in descriptors:
            asset_id = descriptor.get("asset_id")
            role = descriptor.get("role")
            if not isinstance(asset_id, str) or not asset_id:
                _error("MALFORMED_GENERATION_PLAN", "Managed Arco references require asset_id.")
            if not isinstance(role, str) or role not in REFERENCE_ROLES:
                _error("INVALID_REFERENCE_ROLE", str(role))
            if asset_id not in by_id:
                _error("REFERENCE_ASSET_NOT_FOUND", asset_id)
            selected_assets.append(by_id[asset_id])
            if role not in roles:
                roles.append(role)
        return selected_assets, roles

    return list(all_assets), []


def _reference_roles(
    *,
    managed_roles: Sequence[str],
    request_scoped: Sequence[Mapping[str, Any]],
    variant_id: str | None,
) -> list[str]:
    roles = list(managed_roles)
    scoped_roles: set[str] = set()
    for reference in request_scoped:
        if not isinstance(reference, Mapping):
            _error("MALFORMED_GENERATION_PLAN", "request_scoped_arco_references must contain mappings.")
        role = reference.get("role")
        if not isinstance(role, str) or role not in REFERENCE_ROLES:
            _error("INVALID_REFERENCE_ROLE", str(role))
        scoped_roles.add(role)
    roles = [role for role in roles if role not in scoped_roles]
    if not roles and not scoped_roles:
        roles.extend(DEFAULT_REQUESTED_ROLES)
    if variant_id is not None and "outfit_reference" not in roles and "outfit_reference" not in scoped_roles:
        roles.append("outfit_reference")
    return roles


def _copy_contracts(value: Sequence[Any], *, field: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            _error("MALFORMED_GENERATION_PLAN", f"{field} must contain mappings.")
        result.append(dict(item))
    return result


@dataclass(frozen=True)
class ProductionGenerationResult:
    """The frozen runtime result returned by the production entrypoint."""

    prompt: str
    style_context: Mapping[str, Any]
    selected_references: tuple[Mapping[str, Any], ...]
    invocation_plan: Mapping[str, Any]
    output_path: Path

    def as_dict(self) -> dict[str, Any]:
        return {
            "prompt": self.prompt,
            "style_context": dict(self.style_context),
            "selected_references": [dict(item) for item in self.selected_references],
            "invocation_plan": dict(self.invocation_plan),
            "output_path": str(self.output_path),
        }


def run_production_generation(
    request: Mapping[str, Any],
    *,
    builtin_image_gen: Callable[..., Any],
    root: Path = ROOT,
) -> ProductionGenerationResult:
    """Resolve, compile, validate, and generate one normal Arco request.

    The host supplies ``builtin_image_gen``.  All style and reference work is
    request-scoped and read-only; only the provider creates the output file.
    """

    root = Path(root).resolve()
    normalized = _normalize_request(request)
    production_config = _load_yaml(root, PRODUCTION_CONFIG_PATH, label="production config")
    _validate_production_config(production_config)
    generation_document = _load_yaml(root, GENERATION_CONFIG_PATH, label="generation config")
    generation_config = generation_document.get("generation")
    if not isinstance(generation_config, Mapping):
        _error("PRODUCTION_CONFIG_INVALID", "Generation config is missing its generation mapping.")
    identity = _load_yaml(root, IDENTITY_PATH, label="Identity")
    assets_document = _load_yaml(root, ASSETS_PATH, label="asset registry")
    all_assets = assets_document.get("assets")
    if not isinstance(all_assets, list):
        _error("PRODUCTION_CONFIG_INVALID", "Asset registry must contain an assets list.")
    # Loading the published Variant Index is an explicit production gate even
    # when the current request does not select a Variant.
    variants_document = _load_yaml(root, VARIANTS_PATH, label="Variant index")
    if not isinstance(variants_document.get("variants"), list):
        _error("PRODUCTION_CONFIG_INVALID", "Variant index must contain a variants list.")
    baseline = _load_yaml(root, STYLE_BASELINE_PATH, label="Official Style Baseline")

    managed_assets, managed_roles = _managed_selection(request=normalized, all_assets=all_assets)
    scoped = _copy_contracts(
        normalized["request_scoped_arco_references"],
        field="request_scoped_arco_references",
    )
    external = _copy_contracts(normalized["external_references"], field="external_references")
    requested_roles = _reference_roles(
        managed_roles=managed_roles,
        request_scoped=scoped,
        variant_id=normalized["variant_id"],
    )
    variant_required = "outfit_reference" in requested_roles or any(
        ref.get("role") == "outfit_reference" for ref in scoped
    )
    selected = select_references(
        root=root,
        managed_assets=managed_assets,
        requested_roles=requested_roles,
        request_scoped_references=scoped,
        external_references=external,
        exposure_profile=normalized["exposure_profile"],
        variant_required=variant_required,
        selected_variant_id=normalized["variant_id"],
        config=generation_config,
    )
    readiness = compute_request_reference_readiness(
        exposure_profile=normalized["exposure_profile"],
        references=selected,
        variant_required=variant_required,
        selected_variant_id=normalized["variant_id"],
    )
    if readiness.get("status") != "READY":
        code = "REFERENCE_CONFLICT" if readiness.get("status") == "CONFLICT" else "REFERENCE_ASSETS_INCOMPLETE"
        _error(code, f"Request reference readiness is {readiness.get('status')}: {readiness.get('missing_fields', [])}")

    resolved_style_references = resolve_style_references(selected)
    # resolve_style_context performs the existing source/axis/priority-bound
    # validate_style_brief checks for every request-scoped Style Brief.
    style_context = resolve_style_context(
        resolved_style_references=resolved_style_references,
        style_briefs=normalized["style_briefs"],
        official_style_baseline=baseline,
        user_style_overrides=normalized["user_style_overrides"],
    )
    hygiene_policy = None
    if normalized["rendering_hygiene"] == "hygiene_v11":
        hygiene_policy = _load_yaml(root, HYGIENE_POLICY_PATH, label="Rendering Hygiene policy")
    prompt = compile_prompt(
        base_prompt=normalized["base_prompt"],
        references=selected,
        identity=identity,
        exposure_profile=normalized["exposure_profile"],
        allow_uncertain_working=bool(normalized["allow_uncertain_working"]),
        style_context=style_context,
        rendering_hygiene_policy=hygiene_policy,
    )
    invocation_plan = build_invocation_plan(
        mode="reference_conditioned",
        prompt=prompt,
        selected_references=selected,
    )
    output_path = ArcoRealAdapter(builtin_image_gen).generate(
        invocation_plan=invocation_plan,
        reference_contracts=selected,
        reference_image_paths=[str(reference["path"]) for reference in selected],
    )
    return ProductionGenerationResult(
        prompt=prompt,
        style_context=style_context,
        selected_references=tuple(selected),
        invocation_plan=invocation_plan,
        output_path=output_path,
    )


__all__ = [
    "ProductionGenerationError",
    "ProductionGenerationResult",
    "run_production_generation",
]
