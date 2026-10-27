"""Run a fresh offline project copy from another working directory.

Copies code/configuration, links or copies only the immutable raw archives,
starts without generated output/metadata caches, and compares numerical CSVs.
"""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from project_runtime import PROJECT_ROOT, sha256_file, verify_input_files


REQUIRED_OUTPUTS = {
    "tabular": ["output/data_audit/tabular/hourly_field_quality.csv"],
    "spatial": [
        "output/data_audit/spatial/historical_dem_coverage.csv",
        "output/data_audit/spatial/glacier_raster_inventory.csv",
    ],
    "exploration": ["output/observation_exploration/hourly_field_year.csv"],
    "relations": ["output/variable_relations/correlations.csv"],
    "profiles": [
        "output/vertical_profiles/" + name
        for name in [
            "selected_fields.csv",
            "source_coverage.csv",
            "source_qc_counts.csv",
            "source_fidelity.csv",
            "eligibility_counts.csv",
            "pair_qc_counts.csv",
            "gradient_summary.csv",
            "profile_summary.csv",
            "joint_summary.csv",
            "joint_eligibility_counts.csv",
            "sensitivity_comparison.csv",
            "full_height_profiles_qc0.csv.gz",
            "full_height_profiles_qc0_plus4.csv.gz",
            "paired_gradients_qc0.csv.gz",
            "paired_gradients_qc0_plus4.csv.gz",
            "simultaneous_ta_ws_qc0.csv.gz",
            "simultaneous_ta_ws_qc0_plus4.csv.gz",
        ]
    ],
}


def compare_required_outputs(original: Path, relocated: Path, expected: list[str]) -> dict:
    comparisons = {}
    for relative in expected:
        source, moved = original / relative, relocated / relative
        if not source.is_file() or not moved.is_file():
            raise FileNotFoundError(f"Missing required comparison output: {relative}")
        comparisons[relative] = sha256_file(source) == sha256_file(moved)
    return comparisons


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--steps",
        default="environment,tabular,spatial,report,verify,exploration,relations,profiles",
    )
    args = parser.parse_args()
    original_hashes = verify_input_files()
    base = PROJECT_ROOT / "tmp"
    base.mkdir(exist_ok=True)
    comparisons = {}
    log_output = PROJECT_ROOT / "output/reproduction"
    log_output.mkdir(parents=True, exist_ok=True)
    selected = [name.strip() for name in args.steps.split(",") if name.strip()]
    result_path = log_output / "relocation_verification.json"
    result_path.write_text(
        json.dumps({"passed": False, "status": "running", "steps": selected}, indent=2),
        encoding="utf-8",
    )
    # The cleanup target is created and verified under this project's tmp only.
    with tempfile.TemporaryDirectory(prefix="relocate-", dir=base) as folder:
        temporary = Path(folder).resolve()
        if not temporary.is_relative_to(base.resolve()):
            raise ValueError("Relocation cleanup directory must stay within project tmp")
        moved = temporary / "中文 project with spaces"
        moved.mkdir()
        for name in ["scripts", "config", "docs"]:
            shutil.copytree(
                PROJECT_ROOT / name, moved / name, ignore=shutil.ignore_patterns("__pycache__")
            )
        for relative in original_hashes:
            source = PROJECT_ROOT / relative
            target = moved / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                target.hardlink_to(source)
            except OSError:
                shutil.copy2(source, target)
        assert not (moved / "output").exists()
        command = [sys.executable, str(moved / "scripts/run_pipeline.py"), "--steps", args.steps]
        # Different CWD from the relocated root; no original-path module search.
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
        env.pop("PYTHONPATH", None)
        with (log_output / "relocation.log").open("w", encoding="utf-8") as log:
            result = subprocess.run(
                command, cwd=temporary, env=env, stdout=log, stderr=subprocess.STDOUT
            )
        if result.returncode:
            result_path.write_text(
                json.dumps(
                    {
                        "passed": False,
                        "status": "pipeline_failed",
                        "steps": selected,
                        "returncode": result.returncode,
                        "log": "output/reproduction/relocation.log",
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            print(
                "\n".join(
                    (log_output / "relocation.log").read_text(encoding="utf-8").splitlines()[-25:]
                ),
                file=sys.stderr,
            )
            raise SystemExit(result.returncode)
        required = [relative for name in selected for relative in REQUIRED_OUTPUTS.get(name, [])]
        comparisons = compare_required_outputs(PROJECT_ROOT, moved, required)
        moved_hashes = verify_input_files(moved)
        original_after = verify_input_files()
        checks = {
            "fresh_copy_without_generated_caches": True,
            "different_cwd_chinese_and_space_directory": True,
            "selected_pipeline_succeeded": result.returncode == 0,
            "all_required_comparison_files_present": len(comparisons) == len(required)
            and len(required) > 0,
            "all_compared_csv_bytes_identical": all(comparisons.values()),
            "original_and_relocated_inputs_unchanged": original_hashes
            == moved_hashes
            == original_after,
        }
        verification = {
            "passed": all(checks.values()),
            "status": "completed",
            "checked_at_utc": datetime.now(timezone.utc).isoformat(),
            "checks": checks,
            "steps": args.steps.split(","),
            "csv_comparisons": comparisons,
            "scope": "Same installed environment, real relocated code/config/raw inputs, no generated cache copied; not proof of every operating system or dependency version.",
        }
        (log_output / "relocation_verification.json").write_text(
            json.dumps(verification, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    for name, ok in checks.items():
        print(f"{'PASS' if ok else 'FAIL'} {name}")
    if not verification["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
