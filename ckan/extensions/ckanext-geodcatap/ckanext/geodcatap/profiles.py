import json
import re

from rdflib import BNode, Literal, Namespace, URIRef
from rdflib.namespace import DCTERMS, FOAF, RDF, SKOS, XSD

from ckanext.dcat.profiles import RDFProfile


DCT = Namespace("http://purl.org/dc/terms/")
DCAT = Namespace("http://www.w3.org/ns/dcat#")
LOCN = Namespace("http://www.w3.org/ns/locn#")
GSP = Namespace("http://www.opengis.net/ont/geosparql#")
GEODCATAP = Namespace("http://data.europa.eu/930/")
ADMS = Namespace("http://www.w3.org/ns/adms#")
DCATAP = Namespace("http://data.europa.eu/r5r/")
PROV = Namespace("http://www.w3.org/ns/prov#")
VCARD = Namespace("http://www.w3.org/2006/vcard/ns#")


class GeoDCATAPProfile(RDFProfile):
    """
    Add GeoDCAT-style spatial triples from this repository's custom schema.

    This profile is intended to be chained after the regular DCAT-AP profiles:

        euro_dcat_ap_2 euro_dcat_ap_scheming geodcat_ap

    It only adds extra spatial triples and leaves the core DCAT serialization to
    ckanext-dcat.
    """

    def parse_dataset(self, dataset_dict, dataset_ref):
        return dataset_dict

    def graph_from_dataset(self, dataset_dict, dataset_ref):
        spatial = self._spatial_values(dataset_dict)

        g = self.g
        if any(spatial.values()):
            spatial_ref = self._existing_spatial_ref(dataset_ref, spatial["uri"])
            if spatial_ref is None:
                spatial_ref = URIRef(spatial["uri"]) if spatial["uri"] else BNode()
                g.add((dataset_ref, DCT.spatial, spatial_ref))

            g.add((spatial_ref, RDF.type, DCT.Location))

            if spatial["label"]:
                g.add((spatial_ref, SKOS.prefLabel, Literal(spatial["label"])))

            if spatial["bbox_wkt"]:
                bbox = Literal(spatial["bbox_wkt"], datatype=GSP.wktLiteral)
                g.add((spatial_ref, LOCN.geometry, bbox))
                g.add((spatial_ref, DCAT.bbox, bbox))

            if spatial["centroid_wkt"]:
                centroid = Literal(spatial["centroid_wkt"], datatype=GSP.wktLiteral)
                g.add((spatial_ref, LOCN.geometry, centroid))
                g.add((spatial_ref, DCAT.centroid, centroid))

        reference_system = self._coerce_reference_system(dataset_dict)
        if reference_system is not None:
            g.add((dataset_ref, GEODCATAP.referenceSystem, reference_system))
            g.add(
                (
                    reference_system,
                    DCT.type,
                    URIRef("http://inspire.ec.europa.eu/glossary/SpatialReferenceSystem"),
                )
            )

        spatial_resolution_text = self._get_text_value(
            dataset_dict, "spatial_resolution_as_text"
        )
        if spatial_resolution_text:
            g.add(
                (
                    dataset_ref,
                    GEODCATAP.spatialResolutionAsText,
                    Literal(spatial_resolution_text),
                )
            )

        temporal_resolution = self._get_text_value(dataset_dict, "temporal_resolution")
        if temporal_resolution:
            g.add(
                (
                    dataset_ref,
                    DCAT.temporalResolution,
                    Literal(temporal_resolution, datatype=XSD.duration),
                )
            )

        purpose = self._get_text_value(dataset_dict, "purpose")
        if purpose:
            g.add((dataset_ref, GEODCATAP.purpose, Literal(purpose)))

        provenance = self._get_text_value(dataset_dict, "provenance")
        if provenance:
            g.add((dataset_ref, DCTERMS.provenance, Literal(provenance)))

        self._add_concept(dataset_ref, GEODCATAP.topicCategory, dataset_dict, "topic_category")
        self._add_concept(dataset_ref, GEODCATAP.resourceType, dataset_dict, "resource_type")
        self._add_concept(dataset_ref, DCT.accessRights, dataset_dict, "access_rights")
        self._add_concept(dataset_ref, DCAT.theme, dataset_dict, "theme")
        self._add_resource(dataset_ref, DCT.conformsTo, dataset_dict, "conforms_to")
        self._add_resource(
            dataset_ref,
            GEODCATAP.applicableLegislation,
            dataset_dict,
            "applicable_legislation",
        )
        self._add_resource(dataset_ref, FOAF.page, dataset_dict, "documentation")
        self._add_resource(dataset_ref, DCT.isReferencedBy, dataset_dict, "is_referenced_by")
        self._add_resource(dataset_ref, DCT.relation, dataset_dict, "related_resource")
        self._add_resource(dataset_ref, DCT.source, dataset_dict, "source")
        self._add_resource(dataset_ref, ADMS.sample, dataset_dict, "sample")
        self._add_resource(dataset_ref, DCAT.landingPage, dataset_dict, "landing_page")
        self._add_concept(dataset_ref, DCT.accrualPeriodicity, dataset_dict, "frequency")
        self._add_concept(dataset_ref, DCT.language, dataset_dict, "language")
        self._add_status_concept(dataset_ref, dataset_dict, "status")
        self._add_concept(dataset_ref, DCATAP.hvdCategory, dataset_dict, "hvd_category")
        self._add_literal(dataset_ref, DCT.rights, dataset_dict, "rights")
        self._add_literal(dataset_ref, DCAT.version, dataset_dict, "version")
        self._add_literal(dataset_ref, ADMS.versionNotes, dataset_dict, "version_notes")
        self._add_identifier(dataset_ref, dataset_dict, "other_identifier")
        self._add_contact_point(dataset_ref, dataset_dict)
        self._add_creator(dataset_ref, dataset_dict)
        self._add_version_relation(dataset_ref, dataset_dict, "has_version")
        self._add_series_relation(dataset_ref, dataset_dict, "in_series")
        self._add_activity(dataset_ref, dataset_dict, "was_generated_by")
        self._add_qualified_relation(dataset_ref, dataset_dict)
        self._add_agent_relation(dataset_ref, GEODCATAP.originator, dataset_dict, "originator")
        self._add_agent_relation(
            dataset_ref,
            GEODCATAP.principalInvestigator,
            dataset_dict,
            "principal_investigator",
        )
        self._add_agent_relation(dataset_ref, GEODCATAP.processor, dataset_dict, "processor")
        self._add_agent_relation(dataset_ref, GEODCATAP.custodian, dataset_dict, "custodian")
        self._add_agent_relation(
            dataset_ref,
            GEODCATAP.resourceProvider,
            dataset_dict,
            "resource_provider",
        )
        self._add_agent_relation(dataset_ref, GEODCATAP.user, dataset_dict, "user")
        self._add_qualified_attribution(dataset_ref, dataset_dict)

    def _spatial_values(self, dataset_dict):
        return {
            "uri": self._coerce_uri(self._get_dataset_value(dataset_dict, "spatial_uri")),
            "label": self._coerce_label(
                self._get_dataset_value(dataset_dict, "spatial_coverage")
            ),
            "bbox_wkt": self._coerce_bbox_wkt(dataset_dict),
            "centroid_wkt": self._coerce_centroid_wkt(dataset_dict),
        }

    def _coerce_uri(self, value):
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return None

    def _get_text_value(self, dataset_dict, field_name):
        value = self._get_dataset_value(dataset_dict, field_name)
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return None

    def _coerce_label(self, value):
        if isinstance(value, str):
            value = value.strip()
            if not value:
                return None
            if value[:1] in "[{":
                try:
                    parsed = json.loads(value)
                except ValueError:
                    return value
                return self._coerce_label(parsed)
            return value

        if isinstance(value, dict):
            for key in ("text", "label", "name"):
                item = value.get(key)
                if isinstance(item, str) and item.strip():
                    return item.strip()
            return None

        if isinstance(value, list):
            for item in value:
                label = self._coerce_label(item)
                if label:
                    return label
        return None

    def _coerce_bbox_wkt(self, dataset_dict):
        bbox_wkt = self._get_dataset_value(dataset_dict, "spatial_bbox")
        if isinstance(bbox_wkt, str) and bbox_wkt.strip():
            return bbox_wkt.strip()

        north = self._as_float(self._get_dataset_value(dataset_dict, "bbox_north"))
        south = self._as_float(self._get_dataset_value(dataset_dict, "bbox_south"))
        east = self._as_float(self._get_dataset_value(dataset_dict, "bbox_east"))
        west = self._as_float(self._get_dataset_value(dataset_dict, "bbox_west"))
        if None in (north, south, east, west):
            return None

        return (
            f"POLYGON(({west} {south}, {east} {south}, {east} {north}, "
            f"{west} {north}, {west} {south}))"
        )

    def _coerce_centroid_wkt(self, dataset_dict):
        centroid_wkt = self._get_dataset_value(dataset_dict, "spatial_centroid")
        if isinstance(centroid_wkt, str) and centroid_wkt.strip():
            return centroid_wkt.strip()

        north = self._as_float(self._get_dataset_value(dataset_dict, "bbox_north"))
        south = self._as_float(self._get_dataset_value(dataset_dict, "bbox_south"))
        east = self._as_float(self._get_dataset_value(dataset_dict, "bbox_east"))
        west = self._as_float(self._get_dataset_value(dataset_dict, "bbox_west"))
        if None in (north, south, east, west):
            return None

        lon = (east + west) / 2
        lat = (north + south) / 2
        return f"POINT({lon} {lat})"

    def _coerce_reference_system(self, dataset_dict):
        value = self._get_text_value(dataset_dict, "reference_system")
        if value:
            return self._uri_or_label_node(value)

        value = self._get_text_value(dataset_dict, "coordinate_system")
        if not value:
            return None

        if re.fullmatch(r"EPSG:\d+", value, re.IGNORECASE):
            code = value.split(":", 1)[1]
            return URIRef(f"http://www.opengis.net/def/crs/EPSG/0/{code}")

        return self._uri_or_label_node(value)

    def _existing_spatial_ref(self, dataset_ref, spatial_uri=None):
        if spatial_uri:
            uri_ref = URIRef(spatial_uri)
            if (dataset_ref, DCT.spatial, uri_ref) in self.g:
                return uri_ref

        for spatial_ref in self.g.objects(dataset_ref, DCT.spatial):
            return spatial_ref

        return None

    def _add_concept(self, dataset_ref, predicate, dataset_dict, field_name):
        value = self._get_text_value(dataset_dict, field_name)
        if not value:
            return

        concept_ref = self._uri_or_label_node(value)
        self.g.add((dataset_ref, predicate, concept_ref))

    def _add_resource(self, dataset_ref, predicate, dataset_dict, field_name):
        value = self._get_text_value(dataset_dict, field_name)
        if not value:
            return

        self.g.add((dataset_ref, predicate, self._uri_or_label_node(value)))

    def _add_status_concept(self, dataset_ref, dataset_dict, field_name):
        value = self._get_text_value(dataset_dict, field_name)
        if not value:
            return

        status_ref = self._uri_or_label_node(value)
        self.g.add((dataset_ref, ADMS.status, status_ref))

        # Keep ADMS as the canonical dataset status predicate if another
        # profile happens to map the same value to dct:status.
        if (dataset_ref, DCT.status, status_ref) in self.g:
            self.g.remove((dataset_ref, DCT.status, status_ref))

    def _add_version_relation(self, dataset_ref, dataset_dict, field_name):
        value = self._get_text_value(dataset_dict, field_name)
        if not value:
            return

        version_ref = self._uri_or_label_node(value)
        self.g.add((dataset_ref, DCAT.hasVersion, version_ref))

        # ckanext-dcat may also emit dct:hasVersion from the same source value.
        # Remove that duplicate so the graph follows DCAT-AP-NL more closely.
        if (dataset_ref, DCT.hasVersion, version_ref) in self.g:
            self.g.remove((dataset_ref, DCT.hasVersion, version_ref))

    def _add_series_relation(self, dataset_ref, dataset_dict, field_name):
        value = self._get_text_value(dataset_dict, field_name)
        if not value:
            return

        series_ref = self._uri_or_label_node(value)
        self.g.add((dataset_ref, DCAT.inSeries, series_ref))

        # Some DCAT serializers use dct:isPartOf for the same semantic relation.
        # Prefer the DCAT-specific predicate when both point at the same object.
        if (dataset_ref, DCT.isPartOf, series_ref) in self.g:
            self.g.remove((dataset_ref, DCT.isPartOf, series_ref))

    def _add_literal(self, dataset_ref, predicate, dataset_dict, field_name):
        value = self._get_text_value(dataset_dict, field_name)
        if value:
            self.g.add((dataset_ref, predicate, Literal(value)))

    def _add_identifier(self, dataset_ref, dataset_dict, field_name):
        value = self._get_text_value(dataset_dict, field_name)
        if not value:
            return

        identifier_ref = BNode()
        self.g.add((dataset_ref, ADMS.identifier, identifier_ref))
        self.g.add((identifier_ref, SKOS.notation, Literal(value)))

    def _add_agent_relation(self, dataset_ref, predicate, dataset_dict, field_name):
        value = self._get_text_value(dataset_dict, field_name)
        if not value:
            return

        agent_ref = self._agent_node(value)
        self.g.add((dataset_ref, predicate, agent_ref))

    def _add_contact_point(self, dataset_ref, dataset_dict):
        name = self._get_text_value(dataset_dict, "contact_point_name")
        email = self._get_text_value(dataset_dict, "contact_point_email")
        url = self._get_text_value(dataset_dict, "contact_point_url")
        if not any((name, email, url)):
            return

        contact_ref = BNode()
        self.g.add((dataset_ref, DCAT.contactPoint, contact_ref))
        self.g.add((contact_ref, RDF.type, VCARD.Kind))
        if name:
            self.g.add((contact_ref, VCARD.fn, Literal(name)))
        if email:
            email_ref = URIRef(email) if email.startswith("mailto:") else URIRef(f"mailto:{email}")
            self.g.add((contact_ref, VCARD.hasEmail, email_ref))
        if url:
            self.g.add((contact_ref, VCARD.hasURL, URIRef(url)))

    def _add_creator(self, dataset_ref, dataset_dict):
        creator_uri = self._get_text_value(dataset_dict, "creator_uri")
        creator_name = self._get_text_value(dataset_dict, "creator")
        creator_type = self._get_text_value(dataset_dict, "creator_type")
        if not any((creator_uri, creator_name, creator_type)):
            return

        creator_ref = URIRef(creator_uri) if creator_uri else BNode()
        self.g.add((dataset_ref, DCT.creator, creator_ref))
        self.g.add((creator_ref, RDF.type, FOAF.Agent))
        if creator_name:
            self.g.add((creator_ref, FOAF.name, Literal(creator_name)))
        if creator_type:
            self.g.add((creator_ref, DCT.type, self._uri_or_label_node(creator_type)))

    def _add_activity(self, dataset_ref, dataset_dict, field_name):
        value = self._get_text_value(dataset_dict, field_name)
        if not value:
            return

        activity_ref = URIRef(value) if self._is_absolute_uri(value) else BNode()
        self.g.add((dataset_ref, PROV.wasGeneratedBy, activity_ref))
        self.g.add((activity_ref, RDF.type, PROV.Activity))
        if not isinstance(activity_ref, URIRef):
            self.g.add((activity_ref, SKOS.prefLabel, Literal(value)))

    def _add_qualified_relation(self, dataset_ref, dataset_dict):
        relation = self._get_text_value(dataset_dict, "qualified_relation")
        role = self._get_text_value(dataset_dict, "qualified_relation_role")
        if not relation:
            return

        relation_ref = BNode()
        self.g.add((dataset_ref, DCAT.qualifiedRelation, relation_ref))
        self.g.add((relation_ref, RDF.type, DCAT.Relationship))
        self.g.add((relation_ref, DCT.relation, self._uri_or_label_node(relation)))
        if role:
            self.g.add((relation_ref, DCAT.hadRole, self._uri_or_label_node(role)))

    def _add_qualified_attribution(self, dataset_ref, dataset_dict):
        agent = self._get_text_value(dataset_dict, "qualified_attribution_agent")
        role = self._get_text_value(dataset_dict, "qualified_attribution_role")
        if not agent:
            return

        attribution_ref = BNode()
        self.g.add((dataset_ref, PROV.qualifiedAttribution, attribution_ref))
        self.g.add((attribution_ref, RDF.type, PROV.Attribution))
        self.g.add((attribution_ref, PROV.agent, self._agent_node(agent)))
        if role:
            self.g.add((attribution_ref, PROV.hadRole, self._uri_or_label_node(role)))

    def _agent_node(self, value):
        if self._is_absolute_uri(value):
            agent_ref = URIRef(value)
            self.g.add((agent_ref, RDF.type, FOAF.Agent))
            return agent_ref

        agent_ref = BNode()
        self.g.add((agent_ref, RDF.type, FOAF.Agent))
        self.g.add((agent_ref, FOAF.name, Literal(value)))
        return agent_ref

    def _uri_or_label_node(self, value):
        if self._is_absolute_uri(value):
            return URIRef(value)

        node = BNode()
        self.g.add((node, SKOS.prefLabel, Literal(value)))
        return node

    def _is_absolute_uri(self, value):
        return bool(re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:[^\s]+$", value))

    def _as_float(self, value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
