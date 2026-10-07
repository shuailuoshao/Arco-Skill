"""Pin old production regressions to their published pre-split contracts.

Historical behavior is exercised in an isolated root; current production keeps
the split selection and human-confirmation gates enabled.
"""
import atexit
from functools import lru_cache
from pathlib import Path
import shutil
import tempfile
import yaml


@lru_cache(maxsize=1)
def legacy_generation_root():
    project = Path(__file__).resolve().parents[1]
    holder = tempfile.TemporaryDirectory(prefix="arco-pre-split-")
    atexit.register(holder.cleanup)
    root = Path(holder.name)
    for directory in ("character", "variants", "runtime"):
        shutil.copytree(project / directory, root / directory)
    shutil.copy2(project / "SKILL.md", root / "SKILL.md")
    old_assets = project / "scripts/fixtures/calibration/cal-20260914T100205Z-77878a/candidate-root/character/assets.yaml"
    shutil.copy2(old_assets, root / "character/assets.yaml")
    for asset in yaml.safe_load(old_assets.read_text(encoding="utf-8"))["assets"]:
        destination = root / asset["path"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(project / asset["path"], destination)
    old_revision = yaml.safe_load(old_assets.read_text(encoding="utf-8"))["revision"]
    history = root / "calibration/history"
    history.mkdir(parents=True)
    for source in (project / "calibration/history").glob("*.yaml"):
        event = yaml.safe_load(source.read_text(encoding="utf-8"))
        if any(target.get("entity_ref") == "character.assets" and target.get("revision_after", 0) > old_revision
               for target in event.get("targets", [])):
            continue
        shutil.copy2(source, history / source.name)
        marker = source.with_suffix(".complete")
        if marker.exists():
            shutil.copy2(marker, history / marker.name)
    expression_staging = "calibration/staging/cal-20260910T145805Z-61c3e9"
    shutil.copytree(project / "scripts/fixtures/calibration/cal-20260910T145805Z-61c3e9", root / expression_staging)
    config_path = root / "runtime/generation.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["generation"].update(split_reference_selection=False, reference_analysis_required=False, max_total_image_inputs=4)
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return root
