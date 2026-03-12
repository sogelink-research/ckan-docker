#!/usr/bin/env python3
"""Extract metadata from https://maps.amsterdam.nl/open_geodata/ into JSONL.

This script:
1. Reads dataset IDs and category labels from the main HTML page.
2. Calls haal.meta.php per dataset ID.
3. Writes one normalized JSON document per dataset to JSONL.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, Iterable, List, Optional
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen

BASE = "https://maps.amsterdam.nl/open_geodata"
INDEX_URL = f"{BASE}/"
META_URL = f"{BASE}/haal.meta.php"


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: List[str] = []

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if text:
            self.parts.append(text)


def html_to_text(value: str) -> str:
    parser = _TextExtractor()
    parser.feed(value)
    return " ".join(parser.parts).strip()


def html_list_items(value: str) -> List[str]:
    return [html_to_text(item) for item in re.findall(r"<li>(.*?)</li>", value, flags=re.I | re.S)]


def slugify(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-")
    return value or "dataset"


def get_text(
    url: str,
    method: str = "GET",
    body: Optional[bytes] = None,
    timeout: int = 15,
    retries: int = 2,
) -> str:
    req = Request(url=url, method=method)
    if body is not None:
        req.add_header("Content-Type", "application/x-www-form-urlencoded")

    last_exc: Optional[Exception] = None
    for attempt in range(retries + 1):
        try:
            with urlopen(req, body, timeout=timeout) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt < retries:
                time.sleep(min(2 * (attempt + 1), 5))
                continue
            break
    raise RuntimeError(f"HTTP request failed after {retries + 1} attempts: {url}") from last_exc


@dataclass
class Entry:
    dataset_id: int
    title: str
    category: str


def parse_entries(index_html: str) -> List[Entry]:
    entries: List[Entry] = []
    cat_pattern = re.compile(
        r"<button[^>]*class='cat'[^>]*>(.*?)<span.*?</button>\s*<ul[^>]*>(.*?)</ul>",
        flags=re.I | re.S,
    )
    item_pattern = re.compile(
        r"<li[^>]*class='dataset'[^>]*id='(\d+)'[^>]*>(.*?)</li>",
        flags=re.I | re.S,
    )

    for cat_html, ul_html in cat_pattern.findall(index_html):
        category = html_to_text(cat_html)
        for dataset_id_str, title_html in item_pattern.findall(ul_html):
            entries.append(
                Entry(
                    dataset_id=int(dataset_id_str),
                    title=html_to_text(title_html),
                    category=category,
                )
            )
    return entries


def fetch_meta(dataset_id: int, timeout: int, retries: int) -> List[object]:
    payload = urlencode({"ID": str(dataset_id)}).encode("utf-8")
    raw = get_text(META_URL, method="POST", body=payload, timeout=timeout, retries=retries)
    # Some responses include trailing whitespace/newlines. json.loads handles this.
    return json.loads(raw)


def infer_format_from_url(url: str) -> Optional[str]:
    u = url.lower()
    if "geojson_lnglat.php" in u or u.endswith(".geojson"):
        return "GeoJSON"
    if "geojson_latlng.php" in u:
        return "GeoJSON"
    if "excel.php" in u or u.endswith(".xlsx") or u.endswith(".xls"):
        return "XLSX"
    if "zip.php" in u or u.endswith(".zip"):
        return "ZIP"
    if u.endswith(".gpkg"):
        return "GPKG"
    if u.endswith(".csv"):
        return "CSV"
    if u.endswith(".kml"):
        return "KML"
    if u.endswith(".gml"):
        return "GML"
    return None


def query_page_resources(dataset_id: int, timeout: int, retries: int) -> List[Dict[str, str]]:
    page_url = f"{BASE}/?k={dataset_id}"
    html = get_text(page_url, timeout=timeout, retries=retries)
    links = re.findall(r"href=['\"]([^'\"]+)['\"]", html, flags=re.I)

    resources: List[Dict[str, str]] = []
    seen = set()
    for href in links:
        full = urljoin(BASE + "/", href.strip())
        if full in seen:
            continue
        fmt = infer_format_from_url(full)
        if not fmt:
            continue
        seen.add(full)
        resources.append(
            {
                "name": fmt,
                "url": full,
                "format": fmt,
                "description": "Direct link discovered on dataset page",
            }
        )
    return resources


def to_record(entry: Entry, meta: List[object], include_latlng: bool = False) -> Dict[str, object]:
    if len(meta) < 12:
        raise ValueError(f"Unexpected meta payload length for ID {entry.dataset_id}: {len(meta)}")

    kaartlaag = str(meta[0])
    data_type = str(meta[10]).lower()
    thema = str(meta[11])
    service_or_file = meta[12] if len(meta) > 12 else None

    title_slug = slugify(entry.title)[:80]
    geojson_lnglat = (
        f"{BASE}/geojson_lnglat.php/{title_slug}.geojson?"
        f"{urlencode({'KAARTLAAG': kaartlaag, 'THEMA': thema})}"
    )
    geojson_latlng = (
        f"{BASE}/geojson_latlng.php/{title_slug}.geojson?"
        f"{urlencode({'KAARTLAAG': kaartlaag, 'THEMA': thema})}"
    )
    excel_url = f"{BASE}/excel.php?{urlencode({'KAARTLAAG': kaartlaag, 'THEMA': thema})}"

    attributes = html_list_items(str(meta[2])) if meta[2] else []

    external_id = f"amsterdam-open-geodata-{entry.dataset_id}-{title_slug}"

    resources: List[Dict[str, object]] = [
        {
            "name": "GeoJSON",
            "url": geojson_lnglat,
            "format": "GeoJSON",
            "description": f"Auto-generated GeoJSON link for {entry.title} (standard lng,lat order)",
        },
        {
            "name": "Excel",
            "url": excel_url,
            "format": "XLSX",
            "description": f"Auto-generated Excel link for {entry.title}",
        },
    ]

    if include_latlng:
        resources.insert(
            1,
            {
                "name": "GeoJSON (lat,lng)",
                "url": geojson_latlng,
                "format": "GeoJSON",
                "description": f"Alternative coordinate order for {entry.title}",
            },
        )

    # Replicate source page behavior for ZIP datasets:
    #   https://maps.amsterdam.nl/<THEMA>/<FILENAME>
    if data_type == "zip" and isinstance(service_or_file, str) and service_or_file.strip():
        zip_url = f"https://maps.amsterdam.nl/{thema}/{service_or_file}"
        resources.insert(
            1,
            {
                "name": "ZIP",
                "url": zip_url,
                "format": "ZIP",
                "description": f"ZIP link constructed from source metadata for {entry.title}",
            },
        )

    # Include direct source file/service URL when provided by source metadata.
    if isinstance(service_or_file, str) and service_or_file.strip().startswith("http"):
        existing_urls = {str(r.get("url", "")) for r in resources if isinstance(r, dict)}
        if service_or_file not in existing_urls:
            format_hint = data_type.upper() if data_type else "FILE"
            resources.append(
                {
                    "name": format_hint,
                    "url": service_or_file,
                    "format": format_hint,
                    "description": f"Direct source link from metadata ({format_hint})",
                }
            )

    record: Dict[str, object] = {
        "source": {
            "extractor": "amsterdam_open_geodata",
            "source_url": INDEX_URL,
            "dataset_id": entry.dataset_id,
            "query_url": f"{BASE}/?k={entry.dataset_id}",
        },
        "dataset": {
            "external_id": external_id,
            "title": entry.title,
            "category": entry.category,
            "description": str(meta[6] or "").strip(),
            "author": str(meta[8] or "").strip(),
            "author_email": str(meta[9] or "").strip(),
            "maintainer": str(meta[8] or "").strip(),
            "maintainer_email": str(meta[9] or "").strip(),
            "source_organization": str(meta[7] or "").strip(),
            "coverage_period": str(meta[4] or "").strip(),
            "raw_data_type": data_type,
            "tags": ["amsterdam", "geodata", entry.category.lower()],
        },
        "resources": resources,
        "extras": {
            "kaartlaag": kaartlaag,
            "thema": thema,
            "attributes": attributes,
            "declared_download_type": data_type,
            "service_or_file": service_or_file,
            "source_link_text": html_to_text(str(meta[1])) if meta[1] else "",
            "provider_link_text": html_to_text(str(meta[5])) if meta[5] else "",
            "feature_count": meta[3],
        },
        "enrichment": {
            "geojson_downloaded": False,
            "extent_computed": False,
        },
    }

    return record


def write_jsonl(path: Path, records: Iterable[Dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("data/metadata/amsterdam_open_geodata.raw.jsonl"),
        help="Output JSONL file",
    )
    parser.add_argument("--http-timeout", type=int, default=15, help="Per-request timeout in seconds")
    parser.add_argument("--http-retries", type=int, default=2, help="Retries per request")
    parser.add_argument("--limit", type=int, default=0, help="Only process first N datasets (0 = all)")
    parser.add_argument(
        "--scrape-query-links",
        action="store_true",
        help="Also scrape each ?k=<id> page to discover direct links such as ZIP",
    )
    parser.add_argument(
        "--include-latlng",
        action="store_true",
        help="Also include alternative GeoJSON lat,lng resource URLs",
    )
    return parser.parse_args(argv)


def main(argv: List[str]) -> int:
    args = parse_args(argv)
    args.out.parent.mkdir(parents=True, exist_ok=True)

    html = get_text(INDEX_URL, timeout=args.http_timeout, retries=args.http_retries)
    entries = parse_entries(html)
    if not entries:
        print("No datasets found on source page", file=sys.stderr)
        return 2

    if args.limit > 0:
        entries = entries[: args.limit]

    records: List[Dict[str, object]] = []
    for i, entry in enumerate(entries, start=1):
        try:
            meta = fetch_meta(entry.dataset_id, timeout=args.http_timeout, retries=args.http_retries)
            rec = to_record(entry, meta, include_latlng=args.include_latlng)
            if args.scrape_query_links:
                try:
                    discovered = query_page_resources(entry.dataset_id, timeout=args.http_timeout, retries=args.http_retries)
                    existing = {str(r.get("url", "")) for r in rec.get("resources", []) if isinstance(r, dict)}
                    for r in discovered:
                        if r["url"] not in existing:
                            rec["resources"].append(r)
                except Exception as exc:  # noqa: BLE001
                    print(f"[WARN] query-link-scrape failed ID={entry.dataset_id}: {exc}", file=sys.stderr)
            records.append(rec)
        except Exception as exc:  # noqa: BLE001
            print(f"[WARN] Failed ID={entry.dataset_id} title={entry.title!r}: {exc}", file=sys.stderr)
        if i % 25 == 0:
            print(f"Processed {i}/{len(entries)} entries", file=sys.stderr)

    write_jsonl(args.out, records)
    print(f"Wrote {len(records)} records to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
