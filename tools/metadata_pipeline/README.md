# Metadata Pipeline

This folder contains a source-agnostic metadata pipeline:

1. Extract metadata from a source catalog into a fixed JSONL format.
2. Enrich metadata by downloading GeoJSON and computing extents.
3. Upsert into CKAN using the action API.

## Fixed Format (JSONL)

Each line is one dataset object:

```json
{
  "source": {
    "extractor": "amsterdam_open_geodata",
    "source_url": "https://maps.amsterdam.nl/open_geodata/",
    "dataset_id": 598,
    "query_url": "https://maps.amsterdam.nl/open_geodata/?k=598"
  },
  "dataset": {
    "external_id": "amsterdam-open-geodata-598",
    "title": "Tram- en metrolijnen 2025",
    "category": "Verkeer & Infrastructuur",
    "description": "...",
    "author": "...",
    "author_email": "...",
    "maintainer": "...",
    "maintainer_email": "...",
    "tags": ["amsterdam", "geodata", "verkeer & infrastructuur"],
    "bbox_west": 4.728,
    "bbox_south": 52.278,
    "bbox_east": 5.079,
    "bbox_north": 52.431,
    "spatial_bbox": "POLYGON((...))",
    "spatial_centroid": "POINT(...)"
  },
  "resources": [
    {
      "name": "GeoJSON (lng,lat)",
      "url": "https://...geojson_lnglat.php?...",
      "format": "GeoJSON",
      "description": "..."
    }
  ],
  "extras": {
    "kaartlaag": "TRAMMETRO_LIJNEN_2025",
    "thema": "trammetro"
  },
  "enrichment": {
    "geojson_downloaded": true,
    "extent_computed": true
  }
}
```

## Scripts

- `extract_amsterdam_open_geodata.py`
  - Scrapes dataset IDs/categories from `open_geodata` HTML.
  - Calls `haal.meta.php` for full metadata.
  - Optional: `--scrape-query-links` scrapes each `?k=<id>` page to discover direct links (eg ZIP).
  - Adds standard GeoJSON (`lng,lat`) by default.
  - Optional: add `--include-latlng` to also include the non-standard `lat,lng` variant.
  - Writes raw fixed-format JSONL.

- `enrich_geojson_extent.py`
  - Tries to download GeoJSON first, and falls back to other available resources (eg ZIP) when GeoJSON is unavailable.
  - Computes bbox and writes `bbox_*`, `spatial_bbox`, `spatial_centroid` when a valid GeoJSON is available.
  - Stores downloads as `<dataset-slug>-<urlhash>.<ext>`.
  - Maintains `data/downloads/geojson/_index.json` to deduplicate by URL across runs.

- `import_ckan_upsert.py`
  - Upserts records into CKAN (`package_create`/`package_patch`).

## Usage

From repo root:

```bash
python3 tools/metadata_pipeline/extract_amsterdam_open_geodata.py \
  --out data/metadata/amsterdam_open_geodata.raw.jsonl \
  --http-timeout 15 \
  --http-retries 2 \
  --scrape-query-links

python3 tools/metadata_pipeline/enrich_geojson_extent.py \
  --in data/metadata/amsterdam_open_geodata.raw.jsonl \
  --out data/metadata/amsterdam_open_geodata.enriched.jsonl \
  --download-dir data/downloads/geojson \
  --http-timeout 20 \
  --total-timeout 120 \
  --max-bytes 50000000

python3 tools/metadata_pipeline/import_ckan_upsert.py \
  --in data/metadata/amsterdam_open_geodata.enriched.jsonl \
  --ckan-url https://localhost:8443 \
  --api-key "<CKAN_API_KEY>" \
  --insecure \
  --owner-org alfa
```

For fast test runs (avoid waiting on all datasets):

```bash
python3 tools/metadata_pipeline/extract_amsterdam_open_geodata.py \
  --out data/metadata/amsterdam_open_geodata.raw.jsonl \
  --limit 20

python3 tools/metadata_pipeline/enrich_geojson_extent.py \
  --in data/metadata/amsterdam_open_geodata.raw.jsonl \
  --out data/metadata/amsterdam_open_geodata.enriched.jsonl \
  --download-dir data/downloads/geojson \
  --limit 20
```

Dry-run import:

```bash
python3 tools/metadata_pipeline/import_ckan_upsert.py \
  --in data/metadata/amsterdam_open_geodata.enriched.jsonl \
  --ckan-url https://localhost:8443 \
  --api-key "<CKAN_API_KEY>" \
  --insecure \
  --dry-run
```

## Extending to Other Sources

To add a new source, create a new `extract_*.py` that emits the same fixed format JSONL.
No changes are needed in `enrich_geojson_extent.py` or `import_ckan_upsert.py` if the format is respected.

Linkage fields written in each record under `enrichment`:

- `source_file_path`: local file path used/downloaded
- `source_file_format`: format of the resource used/downloaded
- `source_file_url`: source URL used/downloaded
- `source_file_url_hash`: stable hash key derived from source URL
- `source_file_cache_hit`: `true` when cached file was reused (no download)
