# ckanext-geodcatap

Local extension that adds a small `ckanext-dcat` RDF profile entry point named
`geodcat_ap`.

Use it in combination with the existing DCAT-AP profiles from `ckanext-dcat`,
for example:

`euro_dcat_ap_2 euro_dcat_ap_scheming geodcat_ap`

This profile does not implement the full GeoDCAT-AP specification. It adds a
targeted subset of GeoDCAT-AP terms for the schema used in this repository.

Current coverage includes:

- `spatial_coverage`
- `spatial_uri`
- `spatial_bbox`
- `spatial_centroid`
- `bbox_north`, `bbox_south`, `bbox_east`, `bbox_west`
- `reference_system`
- `coordinate_system`
- `spatial_resolution_in_meters`
- `spatial_resolution_as_text`
- `temporal_resolution`
- `topic_category`
- `resource_type`
- `purpose`
- `provenance`
