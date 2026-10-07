#!/usr/bin/env python3
"""Real generation boundary for Arco reference-conditioned requests.

The adapter is deliberately small and side-effect limited.  It validates the
already-selected Invocation Plan, Reference Contracts, and image paths, then
passes only the documented built-in image-generation arguments to an injected
``builtin_image_gen`` callable.  It never discovers assets, copies outputs,
uploads files, registers evidence, or mutates the Arco library. It reads the
published Body Base fingerprints solely to enforce the local-only input rule.

The host application owns the concrete provider binding.  A binding can wrap
the host's ``builtin_image_gen`` tool as a keyword-callable with the signature
declared by :class:`BuiltinImageGen` and return a local output path (or a
mapping containing one of the supported path keys).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol

from reference_runtime import (
    ReferenceRuntimeError,
    build_builtin_imagegen_args,
    validate_reference_contract,
    validate_reference_instructions,
    validate_generation_reference_input,
)


BUILTIN_PROVIDER = "builtin_image_gen"
BUILTIN_CAPABILITY = "reference_conditioned_image_generation"
REFERENCE_CONDITIONED_MODE = "reference_conditioned"
MAX_TOTAL_IMAGE_INPUTS = 5
OUTPUT_PATH_KEYS = (
    "path",
    "file_path",
    "output_path",
    "image_path",
    "generated_image_path",
)


class BuiltinImageGen(Protocol):
    """The host-side callable bound to the built-in image generator."""

    def __call__(
        self,
        *,
        prompt: str,
        referenced_image_paths: list[str],
    ) -> Any:
        """Generate an image and return a local path or a path-bearing result."""


class ArcoRealAdapterError(ReferenceRuntimeError):
    """A stable error raised by the real-generation boundary."""


def _error(code: str, message: str) -> None:
    raise ArcoRealAdapterError(code, message)


def _adapterize(operation: Callable[[], Any]) -> Any:
    """Keep Runtime validation codes while exposing the adapter error type."""

    try:
        return operation()
    except ArcoRealAdapterError:
        raise
    except ReferenceRuntimeError as exc:
        raise ArcoRealAdapterError(exc.code, str(exc)) from exc


def _canonical_path(value: str | Path) -> str:
    """Return a comparable absolute path without requiring it to exist."""

    return str(Path(value).expanduser().resolve(strict=False)).casefold()


def _as_contract_list(value: Any) -> list[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        values: list[Any] = [value]
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        values = list(value)
    else:
        _error(
            "INVALID_REFERENCE_CONTRACTS",
            "Reference Contracts must be a mapping or a sequence of mappings.",
        )

    if not values or not all(isinstance(item, Mapping) for item in values):
        _error(
            "INVALID_REFERENCE_CONTRACTS",
            "Reference Contracts must contain at least one mapping.",
        )
    return [item for item in values if isinstance(item, Mapping)]


def _as_path_list(value: Any, *, field_name: str) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        _error("INVALID_REFERENCE_PATHS", f"{field_name} must be a sequence of paths.")
    paths = list(value)
    if not paths or not all(isinstance(path, (str, Path)) and str(path) for path in paths):
        _error("INVALID_REFERENCE_PATHS", f"{field_name} must contain non-empty paths.")
    return [str(path) for path in paths]


def _validate_input_path(path: str) -> None:
    normalized = path.replace("\\", "/").casefold()
    if any(area in normalized for area in ("calibration/staging", "calibration/preparations")):
        _error("UNPUBLISHED_ASSET", "Staging and preparation paths cannot be ordinary generation inputs.")
    if not Path(path).is_file():
        _error("REFERENCE_PATH_NOT_FOUND", path)


def _validate_managed_contract(contract: Mapping[str, Any]) -> None:
    """Require the provenance markers emitted by the published selector."""

    if contract.get("authority") != "published_asset" or contract.get("persistent") is not True:
        _error(
            "UNPUBLISHED_ASSET",
            f"Managed reference is not a published persistent contract: {contract.get('reference_id')}",
        )
    if contract.get("can_be_generation_reference") is not True:
        _error(
            "ASSET_NOT_ALLOWED_FOR_GENERATION",
            str(contract.get("asset_id") or contract.get("reference_id")),
        )
    if contract.get("asset_type") in {"body_base", "faceless_composite", "expression_layer"} and (
        contract.get("can_be_generation_reference") is not True
        or contract.get("role") not in contract.get("supported_roles", [])
    ):
        _error(
            "ASSET_NOT_ALLOWED_FOR_GENERATION",
            str(contract.get("asset_id") or contract.get("reference_id")),
        )


def _validate_plan_and_contracts(
    invocation_plan: Mapping[str, Any],
    reference_contracts: Sequence[Mapping[str, Any]],
    reference_image_paths: Sequence[str | Path],
) -> dict[str, Any]:
    if not isinstance(invocation_plan, Mapping):
        _error("INVALID_INVOCATION_PLAN", "Invocation Plan must be a mapping.")
    if invocation_plan.get("provider") != BUILTIN_PROVIDER:
        _error("INVALID_PROVIDER", str(invocation_plan.get("provider")))
    if invocation_plan.get("capability") != BUILTIN_CAPABILITY:
        _error("INVALID_CAPABILITY", str(invocation_plan.get("capability")))
    if invocation_plan.get("mode") != REFERENCE_CONDITIONED_MODE:
        _error(
            "INVALID_ADAPTER_MODE",
            "ArcoRealAdapter requires a reference-conditioned Invocation Plan.",
        )

    plan_ids = invocation_plan.get("selected_reference_ids")
    if not isinstance(plan_ids, list) or not plan_ids or not all(
        isinstance(reference_id, str) and reference_id for reference_id in plan_ids
    ):
        _error(
            "INVOCATION_CONTRACT_MISMATCH",
            "Invocation Plan must contain non-empty selected_reference_ids.",
        )
    if len(set(plan_ids)) != len(plan_ids):
        _error(
            "INVOCATION_CONTRACT_MISMATCH",
            "Invocation Plan contains duplicate reference IDs.",
        )

    plan_paths = _as_path_list(
        invocation_plan.get("referenced_image_paths"),
        field_name="Invocation Plan referenced_image_paths",
    )
    if "num_last_images_to_include" in invocation_plan:
        _error(
            "IMAGE_INPUT_BUILD_FAILED",
            "Real Adapter requires explicit referenced_image_paths.",
        )
    if len(plan_paths) > MAX_TOTAL_IMAGE_INPUTS:
        _error("REFERENCE_LIMIT_EXCEEDED", "Too many reference image paths.")

    contracts = list(reference_contracts)
    if len(contracts) != len(plan_ids) or len(contracts) != len(plan_paths):
        _error(
            "INVOCATION_CONTRACT_MISMATCH",
            "Invocation Plan, Reference Contracts, and paths must have equal lengths.",
        )

    contract_ids: list[str] = []
    contract_paths: list[str] = []
    local_count = 0
    external_count = 0
    for contract in contracts:
        _adapterize(lambda contract=contract: validate_reference_contract(contract))
        reference_id = contract.get("reference_id")
        if not isinstance(reference_id, str) or not reference_id:
            _error("INVALID_REFERENCE_CONTRACTS", "Each contract requires reference_id.")
        path = contract.get("path")
        if not isinstance(path, str) or not path:
            _error(
                "INVALID_REFERENCE_CONTRACTS",
                f"Reference Contract {reference_id} requires a path.",
            )
        if contract.get("source_scope") == "managed_arco":
            _validate_managed_contract(contract)
            if contract.get("sha256") is not None:
                from reference_analysis import file_hash
                if file_hash(path) != contract["sha256"]:
                    _error("ASSET_HASH_MISMATCH", str(reference_id))
            local_count += 1
        elif contract.get("source_scope") == "request_scoped_arco" and not contract.get("generated_output_role"):
            local_count += 1
        elif contract.get("source_scope") == "external_how":
            external_count += 1
        contract_ids.append(reference_id)
        contract_paths.append(path)

    if len(set(contract_ids)) != len(contract_ids) or contract_ids != plan_ids:
        _error(
            "INVOCATION_CONTRACT_MISMATCH",
            "Reference Contract IDs do not match Invocation Plan order.",
        )
    if local_count > 3 or external_count > 2:
        _error("REFERENCE_LIMIT_EXCEEDED", "Reference Contracts exceed runtime limits.")

    supplied_paths = _as_path_list(
        reference_image_paths,
        field_name="reference_image_paths",
    )
    if len(supplied_paths) != len(plan_paths):
        _error(
            "REFERENCE_PATH_MISMATCH",
            "Supplied reference_image_paths do not match the Invocation Plan length.",
        )

    for index, (plan_path, supplied_path, contract_path) in enumerate(
        zip(plan_paths, supplied_paths, contract_paths, strict=True)
    ):
        expected = _canonical_path(plan_path)
        if _canonical_path(supplied_path) != expected or _canonical_path(contract_path) != expected:
            _error(
                "REFERENCE_PATH_MISMATCH",
                f"Reference path mismatch at index {index}.",
            )
        _validate_input_path(plan_path)

    prompt = invocation_plan.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        _error("INVALID_PROMPT", "Invocation Plan prompt must be non-empty.")
    _adapterize(lambda: validate_reference_instructions(contracts, prompt))

    # Reuse the existing serializer as the sole source of truth for the
    # provider-facing shape.  It also rejects an accidental second transport.
    return _adapterize(lambda: build_builtin_imagegen_args(invocation_plan))


def _result_path(result: Any) -> str | Path | None:
    if isinstance(result, (str, Path)):
        return result
    if not isinstance(result, Mapping):
        return None
    for key in OUTPUT_PATH_KEYS:
        value = result.get(key)
        if isinstance(value, (str, Path)) and str(value):
            return value
    for key in ("result", "structuredContent", "output"):
        nested = result.get(key)
        path = _result_path(nested)
        if path is not None:
            return path
    return None


def _validate_output_path(result: Any, reference_image_paths: Sequence[str]) -> Path:
    raw_path = _result_path(result)
    if raw_path is None:
        _error(
            "INVALID_GENERATION_RESULT",
            "builtin_image_gen must return a local output path.",
        )
    output_path = Path(raw_path).expanduser().resolve(strict=False)
    if not output_path.is_file():
        _error("GENERATED_OUTPUT_NOT_FOUND", str(output_path))
    if _canonical_path(output_path) in {_canonical_path(path) for path in reference_image_paths}:
        _error(
            "INVALID_GENERATION_RESULT",
            "Generated output cannot be one of the reference inputs.",
        )
    return output_path


class ArcoRealAdapter:
    """Validate and execute one Arco reference-conditioned generation."""

    def __init__(self, builtin_image_gen: BuiltinImageGen | Callable[..., Any]):
        if not callable(builtin_image_gen):
            _error("INVALID_PROVIDER_BINDING", "builtin_image_gen must be callable.")
        self._builtin_image_gen = builtin_image_gen

    def generate(
        self,
        *,
        invocation_plan: Mapping[str, Any],
        reference_contracts: Mapping[str, Any] | Sequence[Mapping[str, Any]],
        reference_image_paths: Sequence[str | Path],
    ) -> Path:
        """Generate exactly one image and return its verified local path."""

        contracts = _as_contract_list(reference_contracts)
        for contract in contracts:
            _adapterize(lambda contract=contract: validate_generation_reference_input(contract))
        for path in _as_path_list(reference_image_paths, field_name="reference_image_paths"):
            _adapterize(lambda path=path: validate_generation_reference_input({"path": path}))
        from reference_analysis import validate_plan_binding
        _adapterize(lambda: validate_plan_binding(invocation_plan, contracts))
        args = _validate_plan_and_contracts(
            invocation_plan,
            contracts,
            reference_image_paths,
        )
        if any(contract.get("asset_type") in {"body_base", "faceless_composite"}
               or (contract.get("source_scope") == "managed_arco" and contract.get("role") == "face_reference")
               for contract in contracts) and not invocation_plan.get("analysis_preview"):
            _error("ANALYSIS_CONFIRMATION_REQUIRED", "Split reference generation requires the human-confirmed frozen analysis.")
        input_paths = [str(path) for path in args["referenced_image_paths"]]
        try:
            result = self._builtin_image_gen(**args)
        except ArcoRealAdapterError:
            raise
        except Exception as exc:  # provider errors must not leak through as success
            raise ArcoRealAdapterError(
                "BUILTIN_IMAGE_GEN_FAILED",
                "builtin_image_gen invocation failed.",
            ) from exc
        return _validate_output_path(result, input_paths)

    def _generate_prepared(self, *, invocation_plan: Mapping[str, Any], root: Path,
                           preparation_id: str, purpose: str) -> Path:
        """Controlled candidate lane; ordinary generate keeps published rules."""
        from preparation_support import load, validate_invocation, workspace
        record = load(workspace(root, preparation_id) / "preparation.yaml")
        if record.get("purpose") != purpose or invocation_plan.get("purpose") != purpose:
            _error("PREPARATION_PURPOSE_MISMATCH", "Use the separately approved purpose-specific adapter path.")
        args = _adapterize(lambda: validate_invocation(dict(invocation_plan), root=root, record=record))
        try:
            result = self._builtin_image_gen(**args)
        except Exception as exc:
            raise ArcoRealAdapterError("BUILTIN_IMAGE_GEN_FAILED", "builtin_image_gen preparation invocation failed.") from exc
        return _validate_output_path(result, args["referenced_image_paths"])

    def generate_preparation(self, *, invocation_plan: Mapping[str, Any], root: Path,
                             preparation_id: str) -> Path:
        return self._generate_prepared(invocation_plan=invocation_plan, root=root,
            preparation_id=preparation_id, purpose="outfit_preparation")

    def generate_identity_calibration(self, *, invocation_plan: Mapping[str, Any], root: Path,
                                      preparation_id: str) -> Path:
        return self._generate_prepared(invocation_plan=invocation_plan, root=root,
            preparation_id=preparation_id, purpose="identity_calibration")

    def generate_reference_correction(self, *, invocation_plan: Mapping[str, Any], root: Path,
                                      preview_path: Path) -> Path:
        """Explicit calibration edit of a published reference; no formal writes."""
        from reference_correction import validate_reference_correction
        args = _adapterize(lambda: validate_reference_correction(dict(invocation_plan),
            root=root, preview_path=preview_path))
        try:
            result = self._builtin_image_gen(**args)
        except Exception as exc:
            raise ArcoRealAdapterError("BUILTIN_IMAGE_GEN_FAILED", "Reference correction invocation failed.") from exc
        return _validate_output_path(result, args['referenced_image_paths'])

    def invoke(
        self,
        *,
        invocation_plan: Mapping[str, Any],
        reference_contracts: Mapping[str, Any] | Sequence[Mapping[str, Any]],
        reference_image_paths: Sequence[str | Path],
    ) -> Path:
        """Compatibility alias for callers that name the adapter operation invoke."""

        return self.generate(
            invocation_plan=invocation_plan,
            reference_contracts=reference_contracts,
            reference_image_paths=reference_image_paths,
        )


__all__ = [
    "ArcoRealAdapter",
    "ArcoRealAdapterError",
    "BuiltinImageGen",
]
