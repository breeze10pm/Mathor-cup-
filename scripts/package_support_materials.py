"""Copy compact, attributable question outputs into a GitHub-readable folder."""

from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAPPINGS = {
    "output/question1/top5_factors.csv": "support_materials/results/question1/top5_factors.csv",
    "output/question1/factor_contrast.png": "support_materials/results/question1/factor_contrast.png",
    "output/event_context/source_candidate_screening.csv": "support_materials/results/question2/source_candidate_screening.csv",
    "output/question3/question3_metrics.csv": "support_materials/results/question3/question3_metrics.csv",
    "output/question3/question3_trigger_time_scenarios.csv": "support_materials/results/question3/question3_trigger_time_scenarios.csv",
    "output/question4/question4_arrival_sensitivity.csv": "support_materials/results/question4/question4_arrival_sensitivity.csv",
    "output/question4/question4_local_sediment_budget.csv": "support_materials/results/question4/question4_local_sediment_budget.csv",
    "output/question4/question4_transition_positions.csv": "support_materials/results/question4/question4_transition_positions.csv",
    "output/question4/question4_georeferenced_scenarios.png": "support_materials/results/question4/question4_georeferenced_scenarios.png",
}


def main() -> None:
    missing = [src for src in MAPPINGS if not (ROOT / src).is_file()]
    if missing:
        raise FileNotFoundError(
            "Generate analysis outputs first; missing: " + ", ".join(missing)
        )
    for source, destination in MAPPINGS.items():
        target = ROOT / destination
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / source, target)
        print(f"{source} -> {destination}")


if __name__ == "__main__":
    main()
