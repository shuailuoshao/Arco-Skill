# Current state

- Arco is in stable normal production use. Style Transfer ON, Rendering Hygiene OFF unless explicitly opted in.
- Workspace organized on 2026-10-01. Daily artwork: 作品/<中文主题>/<香港日期>_<批次>/, including all versions, external original reference copies and generation records.
- Production returns archive_image_path/archive_record_path/archive_error while preserving provider output_path, output_id and revision lineage.
- Historical experiments are under archive/实验; minimal historical calibration fixtures are under scripts/fixtures/calibration. Normal generation must not load archives as character authority.
- Automatic repair ledger is runtime/records/reference-repairs; the one-repair constraint remains enforced.
- Formal facts and asset pixels unchanged by organization. Project image hashes verified; library structure PASS; no new test regressions. Six existing frozen-baseline tests still report PROTECTED_RUNTIME_DIRTY, also reproduced in the pre-change snapshot.
- Rollback snapshot: D:\learn\Arco-rollback-20261001. Detailed receipt: archive/整理记录/整理结果.md.
- Next: normal explicitly requested generation. Do not automatically run old experiments, calibration or image generation.
