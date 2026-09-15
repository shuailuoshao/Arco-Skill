"""Reset only a cleanly rolled-back Casual publication for an authorized retry."""
from pathlib import Path
import os
import yaml

STAGING = Path(__file__).resolve().parents[1] / "calibration/staging/cal-20260914T070842Z-68b810"

def main() -> None:
    path = STAGING / "publish-manifest.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if data.get("publication_state") != "RECOVERY_REQUIRED" or data.get("rollback_status") != "PASS":
        raise SystemExit("Refusing reset: recovery was not clean")
    data["publication_state"] = "AUTHORIZED_AWAITING_PREFLIGHT"
    data["publication_status"] = "pending"
    data["publication_authorized"] = True
    data.pop("failure", None)
    data.pop("rollback_errors", None)
    data["write_journal"] = []
    for item in data.get("files", []):
        item["after_hash"] = None
        item["publication_status"] = "pending"
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    os.replace(tmp, path)
    lock = STAGING / "calibration-lock.yaml"
    lock_data = yaml.safe_load(lock.read_text(encoding="utf-8"))
    lock_data["state"] = "AUTHORIZED_AWAITING_PREFLIGHT"
    tmp = lock.with_name(lock.name + ".tmp")
    tmp.write_text(yaml.safe_dump(lock_data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    os.replace(tmp, lock)

if __name__ == "__main__":
    main()
