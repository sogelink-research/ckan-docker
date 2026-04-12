#!/usr/bin/env python3
"""Upsert metadata JSONL records into CKAN via action API.

Expected input format: records produced by this pipeline's extract/enrich scripts.
"""

from __future__ import annotations

import argparse
import json
import re
import ssl
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Set, Tuple
from urllib.error import HTTPError
from urllib.parse import urljoin
from urllib.request import Request, urlopen


OPEN_ACCESS_RIGHTS_URI = "http://publications.europa.eu/resource/authority/access-right/PUBLIC"
OGC_EPSG_PREFIX = "http://www.opengis.net/def/crs/EPSG/0/"


def slugify(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-")
    return value or "dataset"


def read_jsonl(path: Path) -> Iterator[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL at {path}:{line_no}: {exc}") from exc


def ckan_action(
    base_url: str,
    api_key: Optional[str],
    action: str,
    data: Dict[str, Any],
    insecure: bool = False,
) -> Dict[str, Any]:
    endpoint = urljoin(base_url.rstrip("/") + "/", f"api/3/action/{action}")
    body = json.dumps(data).encode("utf-8")
    req = Request(endpoint, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    if api_key:
        req.add_header("Authorization", api_key)

    ssl_context = ssl._create_unverified_context() if insecure else None

    try:
        with urlopen(req, timeout=60, context=ssl_context) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"CKAN {action} failed: HTTP {exc.code} {details}") from exc

    if not payload.get("success"):
        raise RuntimeError(f"CKAN {action} returned success=false: {payload}")
    return payload["result"]


def package_exists(base_url: str, api_key: Optional[str], package_name: str, insecure: bool = False) -> bool:
    try:
        ckan_action(base_url, api_key, "package_show", {"id": package_name}, insecure=insecure)
        return True
    except Exception:  # noqa: BLE001
        return False


def package_show(base_url: str, api_key: Optional[str], package_name: str, insecure: bool = False) -> Dict[str, Any]:
    return ckan_action(base_url, api_key, "package_show", {"id": package_name}, insecure=insecure)


def ensure_org(base_url: str, api_key: Optional[str], owner_org: Optional[str], insecure: bool = False) -> Optional[str]:
    if not owner_org:
        return None

    try:
        org = ckan_action(base_url, api_key, "organization_show", {"id": owner_org}, insecure=insecure)
        return org.get("id") or org.get("name")
    except Exception:  # noqa: BLE001
        return None


def clean_tags(tags: Iterable[str]) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    seen = set()
    for t in tags:
        value = slugify(t)
        if not value or value in seen:
            continue
        seen.add(value)
        out.append({"name": value})
    return out


def text_value(value: Any) -> str:
    return str(value or "").strip()


def first_email(*values: Any) -> str:
    for value in values:
        text = text_value(value)
        if text and "@" in text:
            return text
    return ""


def first_nonempty(*values: Any) -> str:
    for value in values:
        text = text_value(value)
        if text:
            return text
    return ""


def ogc_reference_system(value: Any) -> str:
    text = text_value(value)
    match = re.fullmatch(r"EPSG:(\d+)", text, flags=re.I)
    if match:
        return f"{OGC_EPSG_PREFIX}{match.group(1)}"
    return text


def infer_resource_type(dataset: Dict[str, Any], resources: List[Dict[str, Any]]) -> str:
    raw_type = text_value(dataset.get("raw_data_type")).lower()
    if raw_type in {"geojson", "json", "zip", "xlsx", "xls", "csv", "gpkg", "gml", "kml"}:
        return raw_type.upper()

    formats = {
        text_value(resource.get("format")).upper()
        for resource in resources
        if isinstance(resource, dict) and text_value(resource.get("format"))
    }
    if len(formats) == 1:
        return next(iter(formats))
    if formats:
        return "dataset"
    return ""


def resource_identity(resource: Dict[str, Any]) -> Tuple[str, str, str]:
    return (
        str(resource.get("url") or "").strip(),
        str(resource.get("name") or "").strip().lower(),
        str(resource.get("format") or "").strip().lower(),
    )


def desired_resource_views(resource: Dict[str, Any]) -> List[Tuple[str, str]]:
    fmt = str(resource.get("format") or "").strip().lower()
    if fmt in {"geojson", "gjson"}:
        return [("geo_view", "Map view"), ("geojson_view", "GeoJSON view")]
    if fmt == "wmts":
        return [("wmts_view", "WMTS view")]
    return []


def ensure_resource_views(
    base_url: str,
    api_key: Optional[str],
    resource_id: str,
    resource: Dict[str, Any],
    insecure: bool = False,
    dry_run: bool = False,
) -> None:
    target_views = desired_resource_views(resource)
    if not target_views:
        return

    listed = ckan_action(base_url, api_key, "resource_view_list", {"id": resource_id}, insecure=insecure)
    existing_types = {
        str(v.get("view_type") or "").strip().lower()
        for v in listed
        if isinstance(v, dict)
    }

    for view_type, title in target_views:
        if view_type in existing_types:
            continue
        if dry_run:
            print(f"[DRY-RUN] resource_view_create {resource_id}:{view_type}")
            continue
        try:
            ckan_action(
                base_url,
                api_key,
                "resource_view_create",
                {
                    "resource_id": resource_id,
                    "view_type": view_type,
                    "title": title,
                },
                insecure=insecure,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[WARN] resource_view_create failed for {resource_id}:{view_type}: {exc}", file=sys.stderr)


def sync_package_resources(
    base_url: str,
    api_key: Optional[str],
    package_name: str,
    desired_resources: List[Dict[str, Any]],
    insecure: bool = False,
    dry_run: bool = False,
) -> None:
    pkg = package_show(base_url, api_key, package_name, insecure=insecure)
    existing = pkg.get("resources", []) if isinstance(pkg.get("resources"), list) else []

    existing_by_url: Dict[str, Dict[str, Any]] = {}
    existing_by_name_format: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for res in existing:
        if not isinstance(res, dict):
            continue
        url = str(res.get("url") or "").strip()
        name = str(res.get("name") or "").strip().lower()
        fmt = str(res.get("format") or "").strip().lower()
        if url and url not in existing_by_url:
            existing_by_url[url] = res
        if (name, fmt) not in existing_by_name_format:
            existing_by_name_format[(name, fmt)] = res

    matched_existing_ids: Set[str] = set()

    for desired in desired_resources:
        url, name, fmt = resource_identity(desired)
        matched = existing_by_url.get(url)
        if not matched:
            matched = existing_by_name_format.get((name, fmt))

        if matched and str(matched.get("id") or "").strip():
            resource_id = str(matched.get("id")).strip()
            matched_existing_ids.add(resource_id)
            update_payload = {
                "id": resource_id,
                "package_id": package_name,
                "name": desired.get("name", ""),
                "url": desired.get("url", ""),
                "description": desired.get("description", ""),
                "format": desired.get("format", ""),
                "wms_layer": desired.get("wms_layer", ""),
            }
            if dry_run:
                print(f"[DRY-RUN] resource_update {package_name}:{resource_id}")
            else:
                ckan_action(base_url, api_key, "resource_update", update_payload, insecure=insecure)
            ensure_resource_views(
                base_url,
                api_key,
                resource_id,
                desired,
                insecure=insecure,
                dry_run=dry_run,
            )
        else:
            create_payload = {
                "package_id": package_name,
                "name": desired.get("name", ""),
                "url": desired.get("url", ""),
                "description": desired.get("description", ""),
                "format": desired.get("format", ""),
                "wms_layer": desired.get("wms_layer", ""),
            }
            if dry_run:
                print(f"[DRY-RUN] resource_create {package_name}:{url}")
            else:
                created = ckan_action(base_url, api_key, "resource_create", create_payload, insecure=insecure)
                created_id = str(created.get("id") or "").strip()
                if created_id:
                    ensure_resource_views(
                        base_url,
                        api_key,
                        created_id,
                        desired,
                        insecure=insecure,
                        dry_run=dry_run,
                    )

    for res in existing:
        if not isinstance(res, dict):
            continue
        resource_id = str(res.get("id") or "").strip()
        if not resource_id or resource_id in matched_existing_ids:
            continue
        if dry_run:
            print(f"[DRY-RUN] resource_delete {package_name}:{resource_id}")
        else:
            ckan_action(base_url, api_key, "resource_delete", {"id": resource_id}, insecure=insecure)


def map_record_to_ckan(record: Dict[str, Any], fallback_org: Optional[str], license_id: str) -> Dict[str, Any]:
    dataset = record.get("dataset", {}) if isinstance(record.get("dataset"), dict) else {}
    resources = record.get("resources", []) if isinstance(record.get("resources"), list) else []
    source = record.get("source", {}) if isinstance(record.get("source"), dict) else {}
    extras = record.get("extras", {}) if isinstance(record.get("extras"), dict) else {}

    external_id = text_value(dataset.get("external_id") or dataset.get("title") or "dataset")
    package_name = slugify(external_id)

    title = text_value(dataset.get("title") or package_name)
    notes = text_value(dataset.get("description"))
    if not notes:
        # Scheming marks notes as required; provide a stable fallback for sparse sources.
        notes = f"Metadata imported from source: {title}."

    query_url = text_value(source.get("query_url"))
    source_url = text_value(source.get("source_url"))
    source_org = text_value(dataset.get("source_organization"))
    contact_name = first_nonempty(dataset.get("maintainer"), dataset.get("author"), source_org)
    contact_email = first_email(dataset.get("maintainer_email"), dataset.get("author_email"))
    creator_name = first_nonempty(source_org, dataset.get("author"), dataset.get("maintainer"))
    provider_text = first_nonempty(extras.get("provider_link_text"), source_org)
    resource_type = infer_resource_type(dataset, resources)
    coverage_period = text_value(dataset.get("coverage_period"))
    feature_count = extras.get("feature_count")
    reference_system = ogc_reference_system(dataset.get("coordinate_system") or "EPSG:4326")

    provenance_parts = ["Imported from Amsterdam Open Geodata metadata pipeline"]
    if source_url:
        provenance_parts.append(f"source={source_url}")
    if query_url:
        provenance_parts.append(f"record={query_url}")
    if feature_count not in (None, ""):
        provenance_parts.append(f"feature_count={feature_count}")
    provenance = "; ".join(provenance_parts)

    mapped_resources: List[Dict[str, Any]] = []
    for res in resources:
        if not isinstance(res, dict):
            continue
        url = text_value(res.get("url"))
        if not url:
            continue
        mapped_resources.append(
            {
                "name": text_value(res.get("name") or "Resource"),
                "url": url,
                "description": text_value(res.get("description")),
                "format": text_value(res.get("format")),
                "wms_layer": text_value(res.get("wms_layer")),
            }
        )

    owner_org = text_value(dataset.get("owner_org") or fallback_org) or None

    payload: Dict[str, Any] = {
        "name": package_name,
        "title": title,
        "notes": notes,
        "tag_string": ",".join(clean_tag["name"] for clean_tag in clean_tags(dataset.get("tags", []))),
        "license_id": text_value(dataset.get("license_id") or license_id),
        "owner_org": owner_org,
        "author": text_value(dataset.get("author")),
        "author_email": text_value(dataset.get("author_email")),
        "maintainer": text_value(dataset.get("maintainer")),
        "maintainer_email": text_value(dataset.get("maintainer_email")),
        "spatial_coverage": text_value(dataset.get("spatial_coverage") or dataset.get("category")),
        "bbox_north": dataset.get("bbox_north"),
        "bbox_south": dataset.get("bbox_south"),
        "bbox_east": dataset.get("bbox_east"),
        "bbox_west": dataset.get("bbox_west"),
        "spatial_bbox": text_value(dataset.get("spatial_bbox")),
        "spatial_centroid": text_value(dataset.get("spatial_centroid")),
        "coordinate_system": text_value(dataset.get("coordinate_system") or "EPSG:4326"),
        "temporal_start": text_value(dataset.get("temporal_start")),
        "temporal_end": text_value(dataset.get("temporal_end")),
        "spatial_resolution_in_meters": text_value(dataset.get("spatial_resolution_in_meters")),
        "theme": text_value(dataset.get("category")),
        "contact_point_name": contact_name,
        "contact_point_email": contact_email,
        "landing_page": query_url,
        "documentation": source_url,
        "source": source_url,
        "language": text_value(dataset.get("language") or "nl"),
        "other_identifier": external_id,
        "reference_system": reference_system,
        "topic_category": text_value(dataset.get("category")),
        "resource_type": resource_type,
        "purpose": text_value(extras.get("source_link_text") or title),
        "provenance": provenance,
        "access_rights": text_value(dataset.get("access_rights") or OPEN_ACCESS_RIGHTS_URI),
        "creator": creator_name,
        "resource_provider": provider_text,
        "originator": creator_name,
        "custodian": provider_text,
        "was_generated_by": "Amsterdam Open Geodata metadata pipeline import",
        "qualified_relation": query_url,
        "qualified_relation_role": "source record",
        "resources": mapped_resources,
    }

    if coverage_period:
        payload["version_notes"] = coverage_period

    # Remove keys CKAN may reject as null.
    return {k: v for k, v in payload.items() if v not in (None, "") or k in {"notes", "resources"}}


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--in", dest="input_path", type=Path, required=True, help="Input JSONL path")
    parser.add_argument("--ckan-url", required=True, help="Base CKAN URL, eg https://localhost:8443")
    parser.add_argument("--api-key", default=None, help="CKAN API key/token")
    parser.add_argument("--owner-org", default=None, help="Default owner organization name/id")
    parser.add_argument("--license-id", default="notspecified", help="Fallback CKAN license_id")
    parser.add_argument("--insecure", action="store_true", help="Disable HTTPS certificate verification (for local self-signed certs)")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without writing to CKAN")
    return parser.parse_args(argv)


def main(argv: List[str]) -> int:
    args = parse_args(argv)

    owner_org = ensure_org(args.ckan_url, args.api_key, args.owner_org, insecure=args.insecure)
    if args.owner_org and not owner_org:
        print(f"[WARN] owner org {args.owner_org!r} not found; owner_org will be omitted", file=sys.stderr)

    created = 0
    updated = 0
    skipped = 0

    for record in read_jsonl(args.input_path):
        payload = map_record_to_ckan(record, owner_org, args.license_id)
        package_name = payload["name"]
        resources_payload = payload.get("resources", []) if isinstance(payload.get("resources"), list) else []
        action = "package_patch" if package_exists(args.ckan_url, args.api_key, package_name, insecure=args.insecure) else "package_create"

        if args.dry_run:
            print(f"[DRY-RUN] {action} {package_name}")
            if action == "package_patch":
                sync_package_resources(
                    args.ckan_url,
                    args.api_key,
                    package_name,
                    resources_payload,
                    insecure=args.insecure,
                    dry_run=True,
                )
            skipped += 1
            continue

        try:
            if action == "package_create":
                ckan_action(args.ckan_url, args.api_key, action, payload, insecure=args.insecure)
            else:
                dataset_payload = dict(payload)
                dataset_payload.pop("resources", None)
                dataset_payload["id"] = package_name
                ckan_action(args.ckan_url, args.api_key, action, dataset_payload, insecure=args.insecure)

            # Keep resources and resource views in sync for both create and patch paths.
            sync_package_resources(
                args.ckan_url,
                args.api_key,
                package_name,
                resources_payload,
                insecure=args.insecure,
            )
            if action == "package_create":
                created += 1
            else:
                updated += 1
            print(f"[{action}] {package_name}")
        except Exception as exc:  # noqa: BLE001
            print(f"[ERROR] {package_name}: {exc}", file=sys.stderr)

    print(f"Done. created={created} updated={updated} dry_run={skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
