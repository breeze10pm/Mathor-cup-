"""Run selected reproducible stages using the active Python, from any CWD."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from project_runtime import PROJECT_ROOT, load_observation_window, verify_input_files

STEPS = {
    "environment": ("check_environment.py", []),
    "tabular": ("audit_tabular.py", []),
    "spatial": ("audit_spatial.py", []),
    "report": ("build_audit_report.py", []),
    "verify": ("verify_data_audit.py", []),
    "exploration": ("explore_observations.py", []),
    "relations": ("analyze_variable_relations.py", []),
    "profiles": ("analyze_vertical_profiles.py", []),
    "metadata": ("fetch_official_metadata.py", ["--refresh"]),
}
DEFAULT = "tabular,spatial,report,verify,exploration,relations,profiles"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--steps",
        default=DEFAULT,
        help="Comma-separated stages in execution order; metadata is opt-in and uses the network",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show commands without reading data or writing output",
    )
    parser.add_argument(
        "--check-inputs", action="store_true", help="Verify input versions and frozen window only"
    )
    args = parser.parse_args()
    selected = [name.strip() for name in args.steps.split(",") if name.strip()]
    if not selected or any(name not in STEPS for name in selected):
        parser.error("Choose stages from: " + ", ".join(STEPS))
    if args.dry_run:
        for name in selected:
            script, extra = STEPS[name]
            print(f"{name}: python scripts/{script}" + (" " + " ".join(extra) if extra else ""))
        return
    hashes = verify_input_files()
    _, _, window = load_observation_window()
    print(
        f"PASS input versions: {len(hashes)} archives; frozen observation window verified",
        flush=True,
    )
    if args.check_inputs:
        return
    output = PROJECT_ROOT / "output/reproduction"
    output.mkdir(parents=True, exist_ok=True)
    (PROJECT_ROOT / "docs").mkdir(exist_ok=True)
    record = {
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "python_version": sys.version,
        "observation_reference": window,
        "input_hashes": hashes,
        "steps": [],
    }
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    for name in selected:
        script, extra = STEPS[name]
        command = [sys.executable, str(PROJECT_ROOT / "scripts" / script), *extra]
        log_path = output / f"{name}.log"
        started = time.monotonic()
        print(f"RUN {name}: scripts/{script}", flush=True)
        with log_path.open("w", encoding="utf-8") as log:
            completed = subprocess.run(
                command, cwd=PROJECT_ROOT, env=env, stdout=log, stderr=subprocess.STDOUT
            )
        record["steps"].append(
            {
                "stage": name,
                "script": f"scripts/{script}",
                "returncode": completed.returncode,
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "log": log_path.relative_to(PROJECT_ROOT).as_posix(),
            }
        )
        record["passed"] = all(row["returncode"] == 0 for row in record["steps"])
        (output / "run_manifest.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        if completed.returncode:
            print(
                "\n".join(log_path.read_text(encoding="utf-8").splitlines()[-20:]), file=sys.stderr
            )
            raise SystemExit(completed.returncode)
        print(f"PASS {name}", flush=True)
    print("Selected pipeline stages completed.", flush=True)


if __name__ == "__main__":
    main()
