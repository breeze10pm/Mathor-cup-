"""保存/核验TPDC公开元数据；不登录，不访问管理接口，不下载原始数据。

默认核验已有快照；--refresh重新获取公开页面对应的详情/导出/文档列表。
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import requests
import yaml

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output/metadata_review/official_pages"
GLACIER_CATALOG_URL = (
    "https://api.sedoo.fr/theia-catalogue-prod/metadata/c428c5b9-df8f-4f86-9b75-e04c778e29b9"
)
GLACIER_CATALOG_PATH = ROOT / "output/metadata_review/upstream_glacier/sedoo_metadata.txt"
IDS = {
    1: "5b09afd1-d11b-4150-a291-50f0484dddf1",
    2: "94d1bc8e-b912-413e-bd2b-851f2ff8f8f7",
    3: "f94c33c4-f521-4247-80ec-55dfa2dd453a",
    4: "c2875b3e-7fd4-4b38-9814-fef64193d1a4",
    5: "4e1e74fb-dcee-4ce4-8b07-ec3f3109eabe",
    6: "db142594-2819-403b-8da0-5ebb2a0ca951",
    7: "88b5ab22-19a1-480f-bcdc-cec41776ab46",
    8: "8662c472-43d6-4e92-bff8-e26923970642",
}


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def fetch_one(item: tuple[int, str]) -> list[dict]:
    index, identifier = item
    queries = [
        (
            "standard_detail",
            "POST",
            "https://www.tpdc.ac.cn/view/metadataView/detail/",
            {"metadataId": identifier, "userId": ""},
        ),
        (
            "metadata_export",
            "GET",
            f"https://www.tpdc.ac.cn/view/export/exportJsonMetadata?metadataId={identifier}",
            None,
        ),
        (
            "documents",
            "GET",
            f"https://www.tpdc.ac.cn/view/metadataView/getDocumentList?metadataId={identifier}",
            None,
        ),
    ]
    records = []
    for label, method, url, body in queries:
        response = requests.request(method, url, json=body, timeout=(8, 25))
        response.raise_for_status()
        parsed = response.json()
        if label != "metadata_export" and str(parsed.get("code")) != "200":
            raise RuntimeError(
                f"Public endpoint not successful: {index} {label} {parsed.get('code')}"
            )
        path = OUT / f"attachment_{index}_{label}.json"
        path.write_bytes(response.content)
        records.append(
            {
                "attachment": index,
                "kind": label,
                "url": url,
                "method": method,
                "http_status": response.status_code,
                "sha256": hashlib.sha256(response.content).hexdigest(),
                "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
            }
        )
    return records


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    if args.refresh:
        access = [
            row for group in ThreadPoolExecutor(4).map(fetch_one, IDS.items()) for row in group
        ]
        glacier_response = requests.get(GLACIER_CATALOG_URL, timeout=(8, 25))
        glacier_response.raise_for_status()
        glacier_response.json()
        GLACIER_CATALOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        GLACIER_CATALOG_PATH.write_bytes(glacier_response.content)
        access.append(
            {
                "kind": "upstream_glacier_catalog",
                "url": GLACIER_CATALOG_URL,
                "sha256": hashlib.sha256(glacier_response.content).hexdigest(),
                "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
            }
        )
        (OUT / "reproducible_access_log.json").write_text(
            json.dumps(access, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    sources, metadata, english = [], {}, {}
    checks = {}
    for index, identifier in IDS.items():
        detail = read_json(OUT / f"attachment_{index}_standard_detail.json")
        exported = read_json(OUT / f"attachment_{index}_metadata_export.json")
        context = detail["context"]
        metadata[index] = context["metadataVO"]
        english[index] = context.get("metadataWordVO") or {}
        documents = read_json(OUT / f"attachment_{index}_documents.json")
        checks[f"dataset_{index}_id_matches_problem"] = (
            detail["code"] == "200" and metadata[index]["id"] == exported["id"] == identifier
        )
        sources.append(
            {
                "attachment": index,
                "id": identifier,
                "title": metadata[index]["title"],
                "page_url": f"https://www.tpdc.ac.cn/zh-hans/data/{identifier}",
                "export_url": f"https://www.tpdc.ac.cn/view/export/exportJsonMetadata?metadataId={identifier}",
                "export_sha256": hashlib.sha256(
                    (OUT / f"attachment_{index}_metadata_export.json").read_bytes()
                ).hexdigest(),
                "catalog_updated_as_stored": metadata[index].get("tsUpdated"),
                "public_documents_count": len(documents.get("data") or []),
                "metadata_attachments": context.get("metadataAttachments"),
                "observed_catalog_time": {
                    key: metadata[index].get(key)
                    for key in ["startTime", "endTime", "timeDescription", "temporalResolution"]
                },
            }
        )

    description = metadata[1]["description"]
    instructions = metadata[1]["instructions"]
    constraints = yaml.safe_load(
        (ROOT / "config/analysis-constraints.yml").read_text(encoding="utf-8")
    )
    checks["hourly_utc8_explicit_in_both_languages"] = (
        "北京时间（UTC+8）" in description and "Beijing Time (UTC+8)" in english[1]["description"]
    )
    qc = constraints["hourly_observations"]["qc_definitions"]
    checks["qc_dictionary_matches_official_text"] = set(qc) == {0, 1, 2, 4, 8, 9} and all(
        f"{code}：{meaning}" in description for code, meaning in qc.items()
    )
    checks["missing_code_explicit"] = (
        "缺失数据为9999.9" in instructions
        and constraints["hourly_observations"]["official_missing_value"] == 9999.9
    )
    checks["daily_temperature_celsius_explicit"] = (
        "温度单位为摄氏度（℃）" in metadata[2]["instructions"]
    )
    checks["latitude_conflict_preserved"] = (
        "北纬28.86°" in description
        and "28.26°N" in english[1]["description"]
        and constraints["hourly_observations"]["station_latitude_resolved"] is None
    )
    checks["case_phase_timezone_and_stage_times_unassigned"] = all(
        constraints["case_reference"][key] is None
        for key in [
            "timezone",
            "event_phase",
            "hazard_onset_time",
            "debris_flow_trigger_time",
            "arrival_time_at_port",
            "report_time",
        ]
    )
    checks["labels_and_rain_features_deferred"] = (
        constraints["prediction"]["final_time_labels"] == "deferred"
        and constraints["precipitation"]["final_rolling_features"] == "deferred"
    )
    checks["raw_write_and_new_imputation_forbidden"] = (
        constraints["raw_inputs"]["modification_allowed"] is False
        and constraints["raw_inputs"]["new_imputation_allowed"] is False
    )
    glacier_catalog = read_json(GLACIER_CATALOG_PATH)
    glacier_description = glacier_catalog["resourceAbstract"]["en"]
    checks["upstream_glacier_rate_and_sigma_explicit"] = (
        glacier_catalog["id"] == "c428c5b9-df8f-4f86-9b75-e04c778e29b9"
        and "rates (meters per year)" in glacier_description
        and "1-sigma uncertainty" in glacier_description
    )
    checks["local_glacier_error_inheritance_unverified"] = (
        constraints["glacier_elevation_change"]["local_unit_and_error_processing_inheritance"]
        == "unverified"
        and constraints["glacier_elevation_change"]["final_uncertainty_propagation"] == "deferred"
    )
    findings = {
        "station_latitude": {
            "chinese": 28.86,
            "structured_north": metadata[1]["north"],
            "english": 28.26,
            "resolved": None,
        },
        "temperature_date_conflict": {
            "instructions_end": "2025-08-02",
            "catalog_end": metadata[2]["endTime"],
            "resolution": "use file coverage for descriptive counts; keep metadata conflict open",
        },
        "no_documents_scope": "public document-list and metadataAttachments checked; empty results do not prove all possible private/versioned documents absent",
        "rainfall_accumulation": "not established by inspected metadata; no cumulative features defined",
        "upstream_glacier": {
            "doi": "10.6096/13",
            "catalog_url": GLACIER_CATALOG_URL,
            "catalog_sha256": hashlib.sha256(GLACIER_CATALOG_PATH.read_bytes()).hexdigest(),
            "rate_unit": "meter/year",
            "uncertainty_sigma": 1,
            "local_processing_inheritance": "unverified",
        },
    }
    result = {
        "passed": all(checks.values()),
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "checks": checks,
        "sources": sources,
        "findings": findings,
    }
    path = ROOT / "output/metadata_review/official_verification.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    for key, value in checks.items():
        print(f"{'PASS' if value else 'FAIL'} {key}")
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
