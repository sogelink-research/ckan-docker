# DCAT-AP-NL Dataset Gaps

Official source used:

- DCAT-AP-NL 3.0, Geonovum, definitieve versie 26 mei 2025:
  https://docs.geostandaarden.nl/dcat/dcat-ap-nl30/

Relevant dataset properties in the official profile include:

- `dcat:contactPoint` (mandatory, 1..1)
- `dct:creator`
- `dcat:hasVersion`
- `dcatap:hvdCategory`
- `dcat:inSeries`
- `prov:qualifiedAttribution`
- `dcat:qualifiedRelation`
- `adms:status`
- `prov:wasGeneratedBy`

This repository now models these additional Dutch-profile fields in a pragmatic
way in the scheming form and RDF profile.

## Added schema fields

- `contact_point_name`
- `contact_point_email`
- `contact_point_url`
- `creator`
- `creator_uri`
- `creator_type`
- `hvd_category`
- `status`
- `has_version`
- `in_series`
- `was_generated_by`
- `qualified_relation`
- `qualified_relation_role`
- `qualified_attribution_agent`
- `qualified_attribution_role`

## Current limitations

This is still a simplified implementation compared to full DCAT-AP-NL:

- repeated values are generally modeled as single-value form fields
- `qualifiedRelation` supports one relation and one role field
- `qualifiedAttribution` supports one agent and one role field
- `contactPoint` is not yet enforced as mandatory in CKAN validation
- no Dutch controlled-vocabulary validation is enforced yet
- no SHACL validation is wired into the repo yet
