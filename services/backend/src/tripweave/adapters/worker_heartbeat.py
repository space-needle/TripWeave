import json
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile

HEARTBEAT_FILENAME = "worker-heartbeat.json"


def heartbeat_path(blob_dir: Path) -> Path:
    return blob_dir / HEARTBEAT_FILENAME


def write_heartbeat(blob_dir: Path, *, status: str = "ok") -> None:
    blob_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "status": status,
        "updated_at": datetime.now(UTC).isoformat(),
    }
    path = heartbeat_path(blob_dir)
    with NamedTemporaryFile("w", dir=blob_dir, delete=False, encoding="utf-8") as temp_file:
        json.dump(payload, temp_file)
        temp_file.write("\n")
        temp_name = temp_file.name
    Path(temp_name).replace(path)


def read_heartbeat(blob_dir: Path) -> dict[str, str] | None:
    path = heartbeat_path(blob_dir)
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as heartbeat_file:
        data = json.load(heartbeat_file)
    if not isinstance(data, dict):
        return None
    status = data.get("status")
    updated_at = data.get("updated_at")
    if not isinstance(status, str) or not isinstance(updated_at, str):
        return None
    return {"status": status, "updated_at": updated_at}
