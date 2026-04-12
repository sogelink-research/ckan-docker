# GeoDCAT-AP Mapping

This repository uses `ckanext-dcat` plus a custom profile named `geodcat_ap`.

Official references used for this mapping:

- GeoDCAT-AP 3.1.0: https://semiceu.github.io/GeoDCAT-AP/releases/3.1.0/
- `ckanext-dcat` writing profiles: https://docs.ckan.org/projects/ckanext-dcat/en/latest/writing-profiles/
- `ckanext-dcat` configuration: https://docs.ckan.org/projects/ckanext-dcat/en/latest/configuration/

The profile is intentionally incremental. Core DCAT-AP serialization is still
handled by `ckanext-dcat`. The local profile adds or tightens selected
GeoDCAT-AP terms that are not represented cleanly by the current schema.

## Covered by current schema/profile

| CKAN field | RDF output |
| --- | --- |
| `spatial_coverage` | `dct:spatial` + `skos:prefLabel` |
| `spatial_uri` | `dct:spatial` node URI |
| `spatial_bbox` or bbox edge fields | `locn:geometry`, `dcat:bbox` |
| `spatial_centroid` or bbox edge fields | `locn:geometry`, `dcat:centroid` |
| `reference_system` or `coordinate_system` | `geodcatap:referenceSystem` |
| `spatial_resolution_in_meters` | `dcat:spatialResolutionInMeters` |
| `spatial_resolution_as_text` | `geodcatap:spatialResolutionAsText` |
| `temporal_resolution` | `dcat:temporalResolution` |
| `topic_category` | `geodcatap:topicCategory` |
| `resource_type` | `geodcatap:resourceType` |
| `purpose` | `geodcatap:purpose` |
| `provenance` | `dct:provenance` |
| `theme` | `dcat:theme` |
| `access_rights` | `dct:accessRights` |
| `conforms_to` | `dct:conformsTo` |
| `applicable_legislation` | `geodcatap:applicableLegislation` |
| `documentation` | `foaf:page` |
| `is_referenced_by` | `dct:isReferencedBy` |
| `related_resource` | `dct:relation` |
| `source` | `dct:source` |
| `sample` | `adms:sample` |
| `landing_page` | `dcat:landingPage` |
| `frequency` | `dct:accrualPeriodicity` |
| `language` | `dct:language` |
| `rights` | `dct:rights` |
| `version` | `dcat:version` |
| `version_notes` | `adms:versionNotes` |
| `other_identifier` | `adms:identifier / skos:notation` |
| `originator` | `geodcatap:originator` |
| `principal_investigator` | `geodcatap:principalInvestigator` |
| `processor` | `geodcatap:processor` |
| `custodian` | `geodcatap:custodian` |
| `resource_provider` | `geodcatap:resourceProvider` |
| `user` | `geodcatap:user` |

## Not yet covered

The current implementation is still not a full GeoDCAT-AP conformance layer. It
does not yet model the full set of GeoDCAT-AP classes, repeated multilingual
values, distribution-level and service-level GeoDCAT enrichment, qualified
relations/attributions, dataset series support, or SHACL validation.

For Dutch-profile-specific gaps and additions, see:

- `docs/DCAT_AP_NL_GAPS.md`

## Usage

Use the profile in combination with the base `ckanext-dcat` profiles:

`CKANEXT__DCAT__RDF__PROFILES="euro_dcat_ap_2 euro_dcat_ap_scheming geodcat_ap"`
