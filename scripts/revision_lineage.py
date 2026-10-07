"""Phase 3 lineage and one-edit execution policy, without provider calls."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

from arco_production import ProductionGenerationError
from revision_intent import RevisionPlan, RevisionType, SourceStrategy


class ExecutionStrategy(str, Enum):
    DIRECT_EDIT = "DIRECT_EDIT"
    SOURCE_RESET = "SOURCE_RESET"


@dataclass(frozen=True)
class GenerationLineage:
    output_id: str
    generation_depth: int
    parent_output: str | None
    source_generation_id: str
    reset_triggered_from_output: str | None

    @classmethod
    def from_output(cls, output: Mapping[str, Any]) -> GenerationLineage:
        if not isinstance(output, Mapping):
            raise ProductionGenerationError("LINEAGE_REQUIRED", "Previous output and lineage are required.")
        fields = ("output_id", "generation_depth", "parent_output", "source_generation_id", "reset_triggered_from_output")
        if any(field not in output for field in fields):
            raise ProductionGenerationError("LINEAGE_REQUIRED", "Previous output has incomplete lineage.")
        lineage = cls(*(output[field] for field in fields))
        lineage.validate()
        path = output.get("path")
        if not isinstance(path, (str, Path)) or not str(path) or str(Path(path).resolve()) != lineage.output_id:
            raise ProductionGenerationError("LINEAGE_INVALID", "Previous output path and output_id disagree.")
        return lineage

    def validate(self) -> None:
        if (not isinstance(self.output_id, str) or not self.output_id
                or not isinstance(self.source_generation_id, str) or not self.source_generation_id
                or type(self.generation_depth) is not int or self.generation_depth not in (0, 1)):
            raise ProductionGenerationError("LINEAGE_INVALID", "Output lineage has invalid identifiers or depth.")
        for value in (self.parent_output, self.reset_triggered_from_output):
            if value is not None and (not isinstance(value, str) or not value):
                raise ProductionGenerationError("LINEAGE_INVALID", "Lineage links must be non-empty IDs or null.")
        if self.generation_depth == 1:
            if self.parent_output is None or self.reset_triggered_from_output is not None or self.source_generation_id == self.output_id:
                raise ProductionGenerationError("LINEAGE_INVALID", "Direct-edit lineage is inconsistent.")
        elif self.parent_output is not None or self.source_generation_id != self.output_id:
            raise ProductionGenerationError("LINEAGE_INVALID", "Root lineage is inconsistent.")


def choose_execution_strategy(parent: GenerationLineage, plan: RevisionPlan) -> ExecutionStrategy:
    parent.validate()
    if type(plan) is not RevisionPlan:
        raise ProductionGenerationError("REVISION_PLAN_REQUIRED", "A frozen RevisionPlan is required.")
    if plan.revision_type is RevisionType.ARTIFACT_REPAIR or plan.source_strategy is SourceStrategy.SOURCE_RESET:
        return ExecutionStrategy.SOURCE_RESET
    if parent.generation_depth == 1:
        return ExecutionStrategy.SOURCE_RESET
    return ExecutionStrategy.DIRECT_EDIT


def direct_edit_lineage(parent: GenerationLineage) -> dict[str, Any]:
    parent.validate()
    if parent.generation_depth != 0:
        raise ProductionGenerationError("EDIT_DEPTH_EXCEEDED", "A second direct generated edit is prohibited.")
    return {
        "generation_depth": 1,
        "parent_output": parent.output_id,
        "source_generation_id": parent.source_generation_id,
        "reset_triggered_from_output": None,
    }
