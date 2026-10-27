"""路径迁移与离线元数据定义的真实边界。"""

import importlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
try:
    runtime = importlib.import_module("project_runtime")
except ModuleNotFoundError:
    runtime = None


class PortabilityBoundaries(unittest.TestCase):
    def test_relocation_check_rejects_a_missing_expected_output(self):
        import verify_relocation

        compare = getattr(verify_relocation, "compare_required_outputs", None)
        self.assertIsNotNone(compare, "Missing outputs must not be silently skipped")
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            source, moved = base / "source", base / "moved"
            source.mkdir()
            moved.mkdir()
            (source / "table.csv").write_text("x\n1\n", encoding="utf-8")
            with self.assertRaises(FileNotFoundError):
                compare(source, moved, ["table.csv"])

    def test_netcdf_read_in_chinese_space_directory_preserves_arrays_and_attrs(self):
        self.assertIsNotNone(runtime)
        reader = getattr(runtime, "open_hdf5_netcdf", None)
        self.assertIsNotNone(reader, "Unicode-safe NetCDF reader is required")
        import xarray as xr

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "中文 project with spaces" / "sample.nc"
            path.parent.mkdir()
            expected = xr.Dataset({"value": ("x", [1.0, 2.0])}, attrs={"source": "synthetic"})
            expected.value.attrs["units"] = "m"
            expected.to_netcdf(path, engine="h5netcdf")
            with reader(path) as actual:
                xr.testing.assert_identical(actual.load(), expected)

    def test_frozen_window_loads_without_generated_output_or_network(self):
        self.assertIsNotNone(runtime, "Portable runtime helper is required")
        with tempfile.TemporaryDirectory() as folder:
            copied = Path(folder) / "换目录 project with spaces"
            (copied / "config").mkdir(parents=True)
            shutil.copy2(
                ROOT / "config/observation-reference.json",
                copied / "config/observation-reference.json",
            )
            start, end, evidence = runtime.load_observation_window(copied)
            self.assertEqual(str(start), "2021-04-26 20:00:00")
            self.assertEqual(str(end), "2026-08-27 08:00:00")
            self.assertFalse(evidence["local_cache_checked"])
            self.assertEqual(evidence["reference_file"], "config/observation-reference.json")

    def test_changed_cache_does_not_silently_replace_frozen_reference(self):
        self.assertIsNotNone(runtime)
        with tempfile.TemporaryDirectory() as folder:
            copied = Path(folder)
            (copied / "config").mkdir()
            shutil.copy2(
                ROOT / "config/observation-reference.json",
                copied / "config/observation-reference.json",
            )
            cache = copied / "output/metadata_review/official_pages"
            cache.mkdir(parents=True)
            (cache / "attachment_1_metadata_export.json").write_text(
                json.dumps(
                    {
                        "id": "5b09afd1-d11b-4150-a291-50f0484dddf1",
                        "startTime": 0,
                        "endTime": 1787788800000,
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "conflict"):
                runtime.load_observation_window(copied)

    def test_relocated_runtime_discovers_its_own_project_not_cwd(self):
        self.assertIsNotNone(runtime)
        with tempfile.TemporaryDirectory() as folder:
            moved = Path(folder) / "中文 project"
            (moved / "scripts").mkdir(parents=True)
            shutil.copy2(ROOT / "scripts/project_runtime.py", moved / "scripts/project_runtime.py")
            result = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "import project_runtime; print(project_runtime.PROJECT_ROOT)",
                ],
                cwd=folder,
                env={
                    **__import__("os").environ,
                    "PYTHONPATH": str(moved / "scripts"),
                    "PYTHONIOENCODING": "utf-8",
                },
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=True,
            )
            self.assertEqual(Path(result.stdout.strip()), moved.resolve())

    def test_tar_is_discovered_on_path_and_absence_is_actionable(self):
        self.assertIsNotNone(runtime)
        with patch.object(
            runtime.shutil,
            "which",
            side_effect=lambda name: "/tool/bin/bsdtar" if name == "bsdtar" else None,
        ):
            self.assertEqual(runtime.find_archive_tar(), "/tool/bin/bsdtar")
        with patch.object(runtime.shutil, "which", return_value=None):
            with self.assertRaisesRegex(FileNotFoundError, "PATH"):
                runtime.find_archive_tar()

    def test_pipeline_dry_run_runs_from_outside_project_without_data(self):
        runner = ROOT / "scripts/run_pipeline.py"
        self.assertTrue(runner.is_file(), "Portable pipeline entry is required")
        result = subprocess.run(
            [sys.executable, str(runner), "--dry-run", "--steps", "tabular,exploration,relations"],
            cwd=ROOT.parent,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        )
        self.assertIn("audit_tabular.py", result.stdout)
        self.assertIn("explore_observations.py", result.stdout)
        self.assertNotIn("fetch_official_metadata.py", result.stdout)


if __name__ == "__main__":
    unittest.main()
