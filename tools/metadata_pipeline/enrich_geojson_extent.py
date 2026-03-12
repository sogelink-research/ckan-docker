#!/usr/bin/env python3
"""Download dataset resources and compute extents when GeoJSON is available.

Input: JSONL from extract_amsterdam_open_geodata.py
Output: enriched JSONL with bbox/WKT when possible and downloaded file linkage.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple
from urllib.request import Request, urlopen


def slugify(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-")
    return value or "dataset"


def read_jsonl(path: Path) -> Iterator[Dict[str, object]]:
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL at {path}:{line_no}: {exc}") from exc


def write_jsonl(path: Path, records: Iterable[Dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def load_cache_index(path: Path) -> Dict[str, Dict[str, str]]:
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    if not isinstance(raw, dict):
        return {}

    out: Dict[str, Dict[str, str]] = {}
    for k, v in raw.items():
        if not isinstance(k, str):
            continue
        if isinstance(v, str):
            out[k] = {"path": v}
        elif isinstance(v, dict):
            cleaned: Dict[str, str] = {}
            for key, value in v.items():
                if isinstance(key, str) and isinstance(value, str):
                    cleaned[key] = value
            if cleaned:
                out[k] = cleaned
    return out


def save_cache_index(path: Path, mapping: Dict[str, Dict[str, str]]) -> None:
    path.write_text(json.dumps(mapping, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def download(
    url: str,
    timeout: int,
    total_timeout: int,
    max_bytes: int,
    retries: int,
) -> Tuple[bytes, str]:
    req = Request(url=url, headers={"User-Agent": "ckan-metadata-pipeline/1.0"})
    last_exc: Optional[Exception] = None
    for attempt in range(retries + 1):
        try:
            deadline = time.monotonic() + total_timeout
            with urlopen(req, timeout=timeout) as resp:
                chunks: List[bytes] = []
                total = 0
                while True:
                    if time.monotonic() > deadline:
                        raise TimeoutError(f"Total download timeout after {total_timeout}s")
                    chunk = resp.read(1024 * 64)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max_bytes:
                        raise ValueError(f"Download exceeds max bytes ({max_bytes})")
                    chunks.append(chunk)
                content_type = str(resp.headers.get("Content-Type", ""))
                return b"".join(chunks), content_type
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt < retries:
                time.sleep(min(2 * (attempt + 1), 5))
                continue
            break
    raise RuntimeError(f"Failed to download {url} after {retries + 1} attempts") from last_exc


def iter_coords(geometry: Dict[str, object]) -> Iterator[Tuple[float, float]]:
    coords = geometry.get("coordinates")
    if coords is None:
        return

    def _walk(node: object) -> Iterator[Tuple[float, float]]:
        if isinstance(node, list):
            if len(node) >= 2 and isinstance(node[0], (int, float)) and isinstance(node[1], (int, float)):
                yield float(node[0]), float(node[1])
            else:
                for child in node:
                    yield from _walk(child)

    yield from _walk(coords)


def compute_bbox(geojson_obj: Dict[str, object]) -> Optional[Tuple[float, float, float, float]]:
    west = math.inf
    south = math.inf
    east = -math.inf
    north = -math.inf

    def update(lon: float, lat: float) -> None:
        nonlocal west, south, east, north
        west = min(west, lon)
        south = min(south, lat)
        east = max(east, lon)
        north = max(north, lat)

    geo_type = geojson_obj.get("type")
    if geo_type == "FeatureCollection":
        features = geojson_obj.get("features", [])
        if isinstance(features, list):
            for feature in features:
                if not isinstance(feature, dict):
                    continue
                geometry = feature.get("geometry")
                if isinstance(geometry, dict):
                    for lon, lat in iter_coords(geometry):
                        update(lon, lat)
    elif geo_type == "Feature":
        geometry = geojson_obj.get("geometry")
        if isinstance(geometry, dict):
            for lon, lat in iter_coords(geometry):
                update(lon, lat)
    elif isinstance(geo_type, str):
        for lon, lat in iter_coords(geojson_obj):
            update(lon, lat)

    if not math.isfinite(west):
        return None

    return west, south, east, north


def as_wkt_bbox(west: float, south: float, east: float, north: float) -> str:
    return f"POLYGON(({west} {south}, {east} {south}, {east} {north}, {west} {north}, {west} {south}))"


def as_wkt_point(lon: float, lat: float) -> str:
    return f"POINT({lon} {lat})"


def _priority(fmt: str) -> int:
    order = {
        "geojson": 0,
        "json": 1,
        "zip": 2,
        "gpkg": 3,
        "shp": 4,
        "gml": 5,
        "kml": 6,
        "csv": 7,
        "xlsx": 8,
        "xls": 9,
    }
    return order.get(fmt.lower(), 99)


def choose_download_resources(record: Dict[str, object]) -> List[Dict[str, object]]:
    resources = record.get("resources", [])
    if not isinstance(resources, list):
        return []

    usable: List[Dict[str, object]] = []
    for res in resources:
        if not isinstance(res, dict):
            continue
        url = str(res.get("url", "")).strip()
        if not url or not url.startswith("http"):
            continue
        usable.append(res)

    def key(res: Dict[str, object]) -> Tuple[int, str]:
        fmt = str(res.get("format", "")).strip().lower()
        return (_priority(fmt), str(res.get("name", "")).lower())

    return sorted(usable, key=key)


def resource_extension(resource: Dict[str, object]) -> str:
    fmt = str(resource.get("format", "")).strip().lower()
    url = str(resource.get("url", "")).strip().lower()

    if fmt in {"geojson", "json"} or "geojson" in url:
        return ".geojson"
    if fmt == "zip" or ".zip" in url:
        return ".zip"
    if fmt in {"xlsx", "xls"} or ".xlsx" in url or ".xls" in url:
        return ".xlsx"
    if fmt == "csv" or ".csv" in url:
        return ".csv"
    if fmt == "gpkg" or ".gpkg" in url:
        return ".gpkg"
    if fmt == "kml" or ".kml" in url:
        return ".kml"
    if fmt == "gml" or ".gml" in url:
        return ".gml"
    return ".bin"


def extension_for_detected_format(detected_format: str, expected_format: str) -> str:
    fmt = detected_format.lower()
    if fmt == "geojson":
        return ".geojson"
    if fmt == "csv":
        return ".csv"
    if fmt == "zip":
        return ".zip"
    if fmt == "xlsx":
        return ".xlsx"
    if fmt == "kml":
        return ".kml"
    if fmt == "gml":
        return ".gml"
    if fmt == "gpkg":
        return ".gpkg"
    # Fallback to extension inferred from declared resource format/url.
    return resource_extension({"format": expected_format, "url": ""})


def classify_content(
    data: bytes,
    expected_format: str,
    content_type: str = "",
    source_url: str = "",
) -> Dict[str, str]:
    lowered = data[:4096].decode("utf-8", errors="ignore").lower()
    expected = expected_format.lower().strip()
    ctype = content_type.lower()

    if "deze dataset is niet beschikbaar" in lowered or "this dataset is not available" in lowered:
        return {"status": "invalid", "reason": "dataset unavailable", "detected_format": "text"}
    if "dit is geen geografische dataset" in lowered:
        return {"status": "invalid", "reason": "not a geographic dataset", "detected_format": "text"}

    # Detect GeoJSON by actual content regardless of declared format.
    maybe_json = lowered.lstrip().startswith("{") or lowered.lstrip().startswith("[")
    if maybe_json or "json" in ctype or "geojson" in source_url.lower() or "outputformat=geojson" in source_url.lower():
        try:
            obj = json.loads(data.decode("utf-8"))
        except Exception:  # noqa: BLE001
            if expected in {"geojson", "json"}:
                return {"status": "invalid", "reason": "invalid geojson/json payload", "detected_format": "text"}
        else:
            if isinstance(obj, dict) and isinstance(obj.get("type"), str):
                return {"status": "ok", "reason": "", "detected_format": "geojson"}
            if expected in {"geojson", "json"}:
                return {"status": "invalid", "reason": "json does not look like geojson", "detected_format": "json"}

    if data.startswith(b"PK\x03\x04"):
        detected = "xlsx" if expected in {"xlsx", "xls"} else "zip"
        return {"status": "ok", "reason": "", "detected_format": detected}

    if "text/csv" in ctype or ";" in lowered[:300] or "," in lowered[:300]:
        if "\n" in lowered:
            return {"status": "ok", "reason": "", "detected_format": "csv"}

    if expected in {"xlsx", "xls"}:
        # Excel endpoint sometimes returns CSV text.
        return {"status": "ok", "reason": "", "detected_format": "csv"}

    return {"status": "ok", "reason": "", "detected_format": expected or "bin"}


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--in", dest="input_path", type=Path, required=True, help="Input JSONL path")
    parser.add_argument("--out", dest="output_path", type=Path, required=True, help="Output JSONL path")
    parser.add_argument(
        "--download-dir",
        type=Path,
        default=Path("data/downloads/geojson"),
        help="Directory to save downloaded files",
    )
    parser.add_argument("--skip-download", action="store_true", help="Only compute extents from already downloaded files")
    parser.add_argument("--http-timeout", type=int, default=20, help="Socket timeout per request (seconds)")
    parser.add_argument("--total-timeout", type=int, default=120, help="Total timeout per download (seconds)")
    parser.add_argument("--http-retries", type=int, default=1, help="Retries per download")
    parser.add_argument("--max-bytes", type=int, default=50_000_000, help="Maximum bytes per downloaded file")
    parser.add_argument("--limit", type=int, default=0, help="Only process first N datasets (0 = all)")
    parser.add_argument(
        "--cache-index",
        type=Path,
        default=None,
        help="Path to URL->file cache index JSON (default: <download-dir>/_index.json)",
    )
    return parser.parse_args(argv)


def main(argv: List[str]) -> int:
    args = parse_args(argv)
    args.output_path.parent.mkdir(parents=True, exist_ok=True)
    args.download_dir.mkdir(parents=True, exist_ok=True)
    cache_index_path = args.cache_index or (args.download_dir / "_index.json")
    cache = load_cache_index(cache_index_path)

    out_records: List[Dict[str, object]] = []
    for idx, record in enumerate(read_jsonl(args.input_path), start=1):
        if args.limit > 0 and idx > args.limit:
            break

        dataset = record.get("dataset", {})
        title = str(dataset.get("title", f"dataset-{idx}")) if isinstance(dataset, dict) else f"dataset-{idx}"
        ext_id = str(dataset.get("external_id", slugify(title))) if isinstance(dataset, dict) else slugify(title)

        candidates = choose_download_resources(record)
        # Backward-compatible ZIP fallback when old raw files don't include ZIP URL.
        extras = record.get("extras", {}) if isinstance(record.get("extras"), dict) else {}
        if str(extras.get("declared_download_type", "")).lower() == "zip":
            thema = str(extras.get("thema", "")).strip()
            filename = str(extras.get("service_or_file", "")).strip()
            if thema and filename:
                zip_url = f"https://maps.amsterdam.nl/{thema}/{filename}"
                existing_urls = {str(r.get("url", "")) for r in candidates if isinstance(r, dict)}
                if zip_url not in existing_urls:
                    candidates.insert(
                        0,
                        {
                            "name": "ZIP",
                            "url": zip_url,
                            "format": "ZIP",
                            "description": "Synthesized ZIP link from metadata",
                        },
                    )
        if not candidates:
            out_records.append(record)
            continue

        enrichment = record.setdefault("enrichment", {})
        if not isinstance(enrichment, dict):
            enrichment = {}
            record["enrichment"] = enrichment

        processed = False
        errors: List[str] = []

        for resource in candidates:
            url = str(resource.get("url", "")).strip()
            fmt = str(resource.get("format", "")).strip() or "FILE"
            fmt_lower = fmt.lower()
            ext = resource_extension(resource)

            url_hash = hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]
            preferred_name = f"{slugify(ext_id)}-{url_hash}{ext}"
            default_path = args.download_dir / preferred_name

            cached_info = cache.get(url_hash)
            candidate = None
            cache_hit = False
            if cached_info and isinstance(cached_info, dict) and cached_info.get("path"):
                p = Path(cached_info["path"])
                if p.exists():
                    candidate = p
                    cache_hit = True
            path = candidate if candidate else default_path

            dataset_info = record.get("dataset", {}) if isinstance(record.get("dataset"), dict) else {}
            source_info = record.get("source", {}) if isinstance(record.get("source"), dict) else {}
            index_info = {
                "path": str(path),
                "url": url,
                "dataset_external_id": str(dataset_info.get("external_id", "")),
                "dataset_title": str(dataset_info.get("title", "")),
                "dataset_id": str(source_info.get("dataset_id", "")),
                "resource_name": str(resource.get("name", "")),
                "resource_format": fmt,
            }

            try:
                data: Optional[bytes] = None
                detected_format = fmt
                if not args.skip_download and not path.exists():
                    data, content_type = download(
                        url,
                        timeout=args.http_timeout,
                        total_timeout=args.total_timeout,
                        max_bytes=args.max_bytes,
                        retries=args.http_retries,
                    )
                    content_state = classify_content(
                        data,
                        expected_format=fmt,
                        content_type=content_type,
                        source_url=url,
                    )
                    if content_state["status"] != "ok":
                        raise ValueError(content_state["reason"])
                    detected_format = content_state["detected_format"]
                    ext = extension_for_detected_format(detected_format, fmt)
                    path = args.download_dir / f"{slugify(ext_id)}-{url_hash}{ext}"
                    path.write_bytes(data)
                    index_info["path"] = str(path)
                    index_info["resource_format"] = fmt
                    index_info["detected_format"] = detected_format
                    cache[url_hash] = index_info
                elif path.exists():
                    data = path.read_bytes()
                    content_state = classify_content(data, expected_format=fmt, source_url=url)
                    if content_state["status"] != "ok":
                        # Stale/invalid cached artifact (eg 83-byte text in .geojson): ignore and try next resource.
                        try:
                            path.unlink()
                        except Exception:  # noqa: BLE001
                            pass
                        raise ValueError(content_state["reason"])
                    detected_format = content_state["detected_format"]
                    index_info["resource_format"] = fmt
                    index_info["detected_format"] = detected_format
                    cache[url_hash] = index_info

                enrichment["source_file_path"] = str(path)
                enrichment["source_file_url_hash"] = url_hash
                enrichment["source_file_cache_hit"] = cache_hit
                enrichment["source_file_url"] = url
                enrichment["source_file_format"] = detected_format
                enrichment["source_file_resource_name"] = str(resource.get("name", ""))

                if detected_format.lower() == "geojson":
                    if data is None:
                        data = path.read_bytes()
                    geojson_obj = json.loads(data.decode("utf-8"))
                    bbox = compute_bbox(geojson_obj)
                    if bbox is None:
                        raise ValueError("No geometry coordinates found")

                    west, south, east, north = bbox
                    centroid_lon = (west + east) / 2.0
                    centroid_lat = (south + north) / 2.0

                    dataset_dict = record.setdefault("dataset", {})
                    if isinstance(dataset_dict, dict):
                        dataset_dict["bbox_west"] = west
                        dataset_dict["bbox_south"] = south
                        dataset_dict["bbox_east"] = east
                        dataset_dict["bbox_north"] = north
                        dataset_dict["spatial_bbox"] = as_wkt_bbox(west, south, east, north)
                        dataset_dict["spatial_centroid"] = as_wkt_point(centroid_lon, centroid_lat)

                    enrichment["geojson_downloaded"] = True
                    enrichment["extent_computed"] = True
                    enrichment["geojson_path"] = str(path)
                    enrichment["geojson_url_hash"] = url_hash
                    enrichment["geojson_cache_hit"] = cache_hit
                    enrichment["geojson_source_url"] = url
                    enrichment.pop("error", None)
                    processed = True
                    break

                enrichment["geojson_downloaded"] = False
                enrichment["extent_computed"] = False
                enrichment["error"] = f"GeoJSON unavailable; downloaded fallback resource format={fmt}"
                processed = True
                break

            except Exception as exc:  # noqa: BLE001
                errors.append(f"{fmt}:{exc}")
                continue

        if not processed:
            enrichment["extent_computed"] = False
            enrichment["geojson_downloaded"] = False
            enrichment["error"] = "; ".join(errors) if errors else "No downloadable resources"
            print(f"[WARN] {ext_id}: {enrichment['error']}", file=sys.stderr)

        out_records.append(record)

    write_jsonl(args.output_path, out_records)
    save_cache_index(cache_index_path, cache)
    print(f"Wrote {len(out_records)} records to {args.output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
