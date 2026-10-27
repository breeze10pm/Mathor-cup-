"""Project-relative inputs and executable discovery, independent of the caller's CWD."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def open_hdf5_netcdf(path: Path, **kwargs):
    """Read this project's HDF5/NetCDF4 input through a Unicode-safe backend.

    The native netCDF4 path API on the tested Windows build rejects existing
    Chinese paths. h5netcdf preserves this source's arrays and attributes.
    """
    import xarray as xr

    return xr.open_dataset(path, engine="h5netcdf", **kwargs)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_observation_window(root: Path | None = None):
    """Use versioned factual metadata; crosscheck optional full official cache.

    Returns naive Beijing label datetimes, not measurement support intervals or
    disaster-stage times. No network access, generated output, or CWD is required.
    """
    root = Path(root) if root is not None else PROJECT_ROOT
    path = root / "config/observation-reference.json"
    reference = json.loads(path.read_text(encoding="utf-8"))
    labels = tuple(
        datetime.fromisoformat(reference["labels"][key]) for key in ["startTime", "endTime"]
    )
    if any(value.tzinfo is not None for value in labels):
        raise ValueError("Reference labels must be Beijing wall-clock labels")
    epochs = tuple(
        datetime.fromtimestamp(reference["export_epoch_ms"][key] / 1000, timezone.utc)
        .astimezone(ZoneInfo(reference["timezone"]))
        .replace(tzinfo=None)
        for key in ["startTime", "endTime"]
    )
    if labels != epochs or labels[0] > labels[1]:
        raise ValueError("Frozen metadata label/epoch conflict")
    cache = root / "output/metadata_review/official_pages"
    checked = []
    for kind in ["metadata_export", "standard_detail"]:
        cached_path = cache / f"attachment_1_{kind}.json"
        if not cached_path.exists():
            continue
        cached = json.loads(cached_path.read_text(encoding="utf-8-sig"))
        if kind == "standard_detail":
            cached = cached["context"]["metadataVO"]
            expected = reference["labels"]
            observed = {key: str(cached[key]) for key in ["startTime", "endTime"]}
        else:
            expected = reference["export_epoch_ms"]
            observed = {key: cached[key] for key in ["startTime", "endTime"]}
        if cached["id"] != reference["dataset_id"] or observed != expected:
            raise ValueError(
                f"Official cache/reference conflict in {cached_path.name}; review source version before continuing"
            )
        checked.append(cached_path.relative_to(root).as_posix())
    evidence = {
        "reference_file": path.relative_to(root).as_posix(),
        "reference_sha256": sha256_file(path),
        "official_snapshot_sha256": reference["official_snapshot_sha256"],
        "local_cache_checked": bool(checked),
        "cache_files_checked": checked,
    }
    return labels[0], labels[1], evidence


def find_archive_tar() -> str:
    """Prefer libarchive bsdtar, with PATH tar as a compatible fallback."""
    for name in ["bsdtar", "tar"]:
        executable = shutil.which(name)
        if executable:
            return executable
    raise FileNotFoundError("RAR extraction needs a RAR-capable bsdtar/tar on PATH. See README.md.")


def verify_input_files(root: Path | None = None) -> dict:
    root = Path(root) if root is not None else PROJECT_ROOT
    manifest = json.loads((root / "config/input-manifest.json").read_text(encoding="utf-8"))
    entries = manifest["archives"]
    if len(entries) != 8 or {row["attachment"] for row in entries} != set(range(1, 9)):
        raise ValueError("Expected the eight versioned official archives")
    hashes = {}
    for row in entries:
        path = root / row["path"]
        if not path.is_file():
            raise FileNotFoundError(
                f"Missing input: {row['path']}. Copy official archives as described in README.md."
            )
        digest = sha256_file(path)
        if digest != row["sha256"] or path.stat().st_size != row["bytes"]:
            raise ValueError(
                f"Input version/hash mismatch: {row['path']}; do not silently replace the reference version"
            )
        hashes[row["path"]] = digest
    return hashes
