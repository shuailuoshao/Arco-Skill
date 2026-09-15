# ARCO REAL ADAPTER

Date: 2026-09-15
Execution mode: ordinary, L2 new feature
Status: IMPLEMENTATION_IN_PROGRESS

## 1. Task essence

Add a real generation boundary that accepts an Invocation Plan, its ordered
Reference Contracts, and the corresponding reference image paths; validates
that all three representations agree; calls the injected `builtin_image_gen`
provider; and returns the generated file path without changing the Character
Library, managed assets, or Calibration records.

## 2. Existing evidence

- `scripts/reference_runtime.py:360-428` already selects published references,
  checks managed asset hashes and limits, and emits ordered contracts.
- `scripts/reference_runtime.py:565-625` already validates compiled reference
  instructions and serializes the exact built-in tool arguments.
- Existing baseline: `scripts/test_reference_runtime.py` is 29/29 PASS.
- No Real Adapter module or provider binding exists in the current project.
- The project is not a Git repository; this change adds new files and does not
  overwrite existing character, variant, asset, or calibration files.

## 3. External solution research

- Python's official `typing` documentation supports a callable Protocol for a
  precise injected provider boundary:
  https://docs.python.org/3/library/typing.html
- Python's official `pathlib` documentation supports `Path.resolve()` for
  canonical comparison and `Path.is_file()` for regular-file validation:
  https://docs.python.org/3/library/pathlib.html
- Agent Reach Exa/GitHub search found no high-signal dependency worth adding for
  this narrow boundary. A small standard-library adapter is safer and more
  compatible with the existing dependency-free Runtime.

## 4. Reuse decision

Reuse the existing Runtime validator and serializer as the single source of
truth. Add only adapter-specific checks that cannot be expressed by the pure
planner: provider/capability/mode, ordered ID and path equality, input file
existence, managed-contract authority, prompt exclusion propagation, provider
error normalization, and output-path extraction.

## 5. Product and safety boundaries

- The adapter must fail before provider invocation when the plan, contracts, or
  paths disagree.
- Only `reference_conditioned` plans with explicit local paths are accepted.
- The provider receives only `prompt` and `referenced_image_paths`.
- The adapter does not copy, upload, register, calibrate, or mutate any Arco
  library data. The provider owns generation output creation.
- Generated output must resolve to an existing regular file and must not be one
  of the reference inputs.

## 6. Acceptance criteria

1. A valid plan/contract/path triple calls `builtin_image_gen` once with the
   exact built-in argument shape and returns the generated `Path`.
2. Any ID, contract order, or path mismatch fails closed before provider call.
3. Invalid, missing, staging, or unauthorized reference contracts and missing
   reference files fail closed before provider call.
4. Provider failures and malformed/nonexistent output results are reported with
   stable adapter error codes.
5. Character/Variant/Asset/Calibration files remain byte-for-byte unchanged;
   the focused adapter tests and existing Runtime regression remain green.

## 7. Implementation plan

- Add `scripts/arco_real_adapter.py` with an injected callable Provider port,
  strict validation, result-path normalization, and no registration APIs.
- Add `scripts/test_arco_real_adapter.py` with success, failure, path,
  contract, provider, output, and read-only integrity coverage.
- Add the adapter contract documentation and update the Runtime boundary docs.
- Run focused tests, existing Runtime tests, then the full unittest discovery
  suite and formal library validation if the test suite remains green.

## 8. Rollback point

No Git rollback point is available because `D:\learn\Arco` is not a Git
repository. No existing file is being overwritten; rollback is limited to the
new adapter, test, task-log, and documentation files created by this task.

## 9. Execution record

- Added `scripts/arco_real_adapter.py` with an injected `builtin_image_gen`
  Provider boundary, fail-closed validation, output-path normalization, and no
  Character/Variant/Asset/Calibration mutation path.
- Added `scripts/test_arco_real_adapter.py` with 12 focused tests, including a
  read-only integration using the formal published Selector output.
- Updated `SKILL.md`, `references/core/generation-runtime.md`,
  `references/core/image-input-builder.md`, `references/core/language-safety.md`,
  and added `references/core/real-adapter.md`.
- Focused adapter tests: 12/12 PASS.
- Existing Runtime tests: 29/29 PASS.
- Full unittest discovery: 100/100 PASS.
- Python compilation: PASS. Ruff was not installed in the environment.
- Formal library structural validation: PASS, 0 errors and 0 warnings. The
  existing readiness report remains INCOMPLETE because formal facts are still
  `UNCERTAIN`; no data was changed by this task.
- No generated output, upload, asset registration, Character Library write, or
  Calibration write was performed by the test suite or adapter.

## 10. Authorized live generation

- The user explicitly authorized image generation after the adapter
  implementation and test gate completed.
- Provider binding: `builtin_image_gen`.
- Reference inputs were passed in validated plan order:
  `identity-p01-crop`, `identity-p01`, `casual-outfit-primary`.
- Output:
  `C:\Users\shuai\.codex\generated_images\01a0a359-c300-78b2-8048-654852fc4fa1\exec-c1d37aa7-9760-434a-aee5-66ee2b8cd6eb.png`.
- No Character, Variant, Asset, or Calibration files were changed or
  registered by the generation.
