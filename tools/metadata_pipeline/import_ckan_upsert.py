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

    external_id = str(dataset.get("external_id") or dataset.get("title") or "dataset")
    package_name = slugify(external_id)

    title = str(dataset.get("title") or package_name)
    notes = str(dataset.get("description") or "").strip()
    if not notes:
        # Scheming marks notes as required; provide a stable fallback for sparse sources.
        notes = f"Metadata imported from source: {title}."

    mapped_resources: List[Dict[str, Any]] = []
    for res in resources:
        if not isinstance(res, dict):
            continue
        url = str(res.get("url") or "").strip()
        if not url:
            continue
        mapped_resources.append(
            {
                "name": str(res.get("name") or "Resource").strip(),
                "url": url,
                "description": str(res.get("description") or "").strip(),
                "format": str(res.get("format") or "").strip(),
                "wms_layer": str(res.get("wms_layer") or "").strip(),
            }
        )

    owner_org = str(dataset.get("owner_org") or fallback_org or "").strip() or None

    payload: Dict[str, Any] = {
        "name": package_name,
        "title": title,
        "notes": notes,
        "tag_string": ",".join(clean_tag["name"] for clean_tag in clean_tags(dataset.get("tags", []))),
        "license_id": str(dataset.get("license_id") or license_id),
        "owner_org": owner_org,
        "author": str(dataset.get("author") or "").strip(),
        "author_email": str(dataset.get("author_email") or "").strip(),
        "maintainer": str(dataset.get("maintainer") or "").strip(),
        "maintainer_email": str(dataset.get("maintainer_email") or "").strip(),
        "spatial_coverage": str(dataset.get("spatial_coverage") or dataset.get("category") or "").strip(),
        "bbox_north": dataset.get("bbox_north"),
        "bbox_south": dataset.get("bbox_south"),
        "bbox_east": dataset.get("bbox_east"),
        "bbox_west": dataset.get("bbox_west"),
        "spatial_bbox": str(dataset.get("spatial_bbox") or "").strip(),
        "spatial_centroid": str(dataset.get("spatial_centroid") or "").strip(),
        "coordinate_system": str(dataset.get("coordinate_system") or "EPSG:4326").strip(),
        "temporal_start": str(dataset.get("temporal_start") or "").strip(),
        "temporal_end": str(dataset.get("temporal_end") or "").strip(),
        "spatial_resolution_in_meters": str(dataset.get("spatial_resolution_in_meters") or "").strip(),
        "resources": mapped_resources,
    }

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
