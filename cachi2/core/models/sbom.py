import datetime
import hashlib
import json
import logging
from functools import reduce
from itertools import groupby
from typing import Annotated, Any, Dict, Iterable, Literal, Optional, Union
from urllib.parse import urlparse

import pydantic
from packageurl import PackageURL

from cachi2.core.models.property_semantics import Property, PropertySet
from cachi2.core.models.validators import unique_sorted

log = logging.getLogger(__name__)


class ExternalReference(pydantic.BaseModel):
    """An ExternalReference inside an SBOM component."""

    url: str
    type: Literal["distribution"] = "distribution"


FOUND_BY_CACHI2_PROPERTY: Property = Property(name="cachi2:found_by", value="cachi2")


class Component(pydantic.BaseModel):
    """A software component such as a dependency or a package.

    Compliant to the CycloneDX specification:
    https://cyclonedx.org/docs/1.4/json/#components
    """

    name: str
    purl: str
    version: Optional[str] = None
    properties: list[Property] = pydantic.Field(default_factory=list, validate_default=True)
    type: Literal["library", "file"] = "library"
    external_references: Optional[list[ExternalReference]] = pydantic.Field(
        serialization_alias="externalReferences", default=None
    )

    def key(self) -> str:
        """Uniquely identifies a package.

        Used mainly for sorting and deduplication.
        """
        return self.purl

    @pydantic.field_validator("properties")
    def _add_found_by_property(cls, properties: list[Property]) -> list[Property]:
        if FOUND_BY_CACHI2_PROPERTY not in properties:
            properties.append(FOUND_BY_CACHI2_PROPERTY)

        return properties

    @classmethod
    def from_package_dict(cls, package: dict[str, Any]) -> "Component":
        """Create a Component from a Cachi2 package dictionary.

        A Cachi2 package has extra fields which are unnecessary and can cause validation errors.
        """
        return cls(
            name=package.get("name", None),
            version=package.get("version", None),
            purl=package.get("purl", None),
        )


class Tool(pydantic.BaseModel):
    """A tool used to generate the SBOM content."""

    vendor: str
    name: str


class Metadata(pydantic.BaseModel):
    """Metadata field in a SBOM."""

    tools: list[Tool] = [Tool(vendor="red hat", name="cachi2")]


def spdx_now() -> str:
    """Return a time stamp in SPDX-compliant format.

    See https://spdx.github.io/spdx-spec/v2.3/search.html?q=date
    for details.
    """
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Sbom(pydantic.BaseModel):
    """Software bill of materials in the CycloneDX format.

    See full specification at:
    https://cyclonedx.org/docs/1.4/json
    """

    bom_format: Literal["CycloneDX"] = pydantic.Field(alias="bomFormat", default="CycloneDX")
    components: list[Component] = []
    metadata: Metadata = Metadata()
    spec_version: str = pydantic.Field(alias="specVersion", default="1.4")
    version: int = 1

    @pydantic.field_validator("components")
    def _unique_components(cls, components: list[Component]) -> list[Component]:
        """Sort and de-duplicate components."""
        return unique_sorted(components, by=lambda component: component.key())


class SPDXPackageExternalRefReferenceLocatorURI(pydantic.BaseModel):
    """SPDX Package External Reference with URI reference locator."""

    referenceLocator: str

    @pydantic.field_validator("referenceLocator")
    @classmethod
    def _validate_uri_reference_locator(cls, referenceLocator: str) -> str:
        parsed = urlparse(referenceLocator)
        if not (parsed.scheme and (parsed.path or parsed.netloc)):
            raise ValueError("Invalid URI reference locator")
        return referenceLocator


class SPDXPackageExternalRef(pydantic.BaseModel):
    """SPDX Package External Reference.

    Compliant to the SPDX specification:
    https://spdx.github.io/spdx-spec/v2.3/package-information/#721-external-reference-field
    """

    model_config = pydantic.ConfigDict(frozen=True)

    referenceLocator: str
    referenceType: str
    referenceCategory: str

    def __hash__(self) -> int:
        return hash((self.referenceLocator, self.referenceType, self.referenceCategory))


class SPDXPackageExternalRefSecurity(SPDXPackageExternalRef):
    """SPDX Package External Reference for category package-manager.

    Compliant to the SPDX specification:
    https://spdx.github.io/spdx-spec/v2.3/package-information/#721-external-reference-field
    """

    referenceCategory: Literal["SECURITY"]


class SPDXPackageExternalRefPackageManager(SPDXPackageExternalRef):
    """SPDX Package External Reference for category package-manager.

    Compliant to the SPDX specification:
    https://spdx.github.io/spdx-spec/v2.3/package-information/#721-external-reference-field
    """

    referenceCategory: Literal["PACKAGE-MANAGER"]


class SPDXPackageExternalRefPackageManagerPURL(
    SPDXPackageExternalRefPackageManager, SPDXPackageExternalRefReferenceLocatorURI
):
    """SPDX Package External Reference for category package-manager and type purl.

    Compliant to the SPDX specification:
    https://spdx.github.io/spdx-spec/v2.3/package-information/#721-external-reference-field
    """

    referenceCategory: Literal["PACKAGE-MANAGER"]
    referenceType: Literal["purl"]


class SPDXPackageExternalRefSecurityPURL(
    SPDXPackageExternalRefSecurity, SPDXPackageExternalRefReferenceLocatorURI
):
    """SPDX Package External Reference for category package-manager and type purl.

    Compliant to the SPDX specification:
    https://spdx.github.io/spdx-spec/v2.3/package-information/#721-external-reference-field
    """

    referenceCategory: Literal["SECURITY"]
    referenceType: Literal["cpe23Type"]


SPDXPackageExternalRefPackageManagerType = Annotated[
    SPDXPackageExternalRefPackageManagerPURL,
    pydantic.Field(discriminator="referenceType"),
]

SPDXPackageExternalRefSecurityType = Annotated[
    SPDXPackageExternalRefSecurityPURL,
    pydantic.Field(discriminator="referenceType"),
]


SPDXPackageExternalRefType = Annotated[
    Union[SPDXPackageExternalRefPackageManagerType, SPDXPackageExternalRefSecurityType],
    pydantic.Field(discriminator="referenceCategory"),
]


class SPDXPackageAnnotation(pydantic.BaseModel):
    """SPDX Package Annotation.

    Compliant to the SPDX specification:
    https://github.com/spdx/spdx-spec/blob/development/v2.3/schemas/spdx-schema.json#L237
    """

    model_config = pydantic.ConfigDict(frozen=True)

    annotator: str
    annotationDate: str
    annotationType: Literal["OTHER", "REVIEW"]
    comment: str

    def __hash__(self) -> int:
        return hash((self.annotator, self.annotationDate, self.annotationType, self.comment))


def _extract_purls(from_refs: list[SPDXPackageExternalRefType]) -> list[str]:
    return [ref.referenceLocator for ref in from_refs if ref.referenceType == "purl"]


def _parse_purls(purls: list[str]) -> list[PackageURL]:
    return [PackageURL.from_string(purl) for purl in purls if purl]


class SPDXPackage(pydantic.BaseModel):
    """SPDX Package.

    Compliant to the SPDX specification:
    https://spdx.github.io/spdx-spec/v2.3/package-information/
    """

    SPDXID: Optional[str] = None
    name: str
    versionInfo: Optional[str] = None
    externalRefs: list[SPDXPackageExternalRefType] = []
    annotations: list[SPDXPackageAnnotation] = []
    downloadLocation: str = "NOASSERTION"

    def __lt__(self, other: "SPDXPackage") -> bool:
        return (self.SPDXID or "") < (other.SPDXID or "")

    def __hash__(self) -> int:
        return hash(
            hash(self.SPDXID)
            + hash(self.name)
            + hash(self.versionInfo)
            + hash(self.downloadLocation)
            + sum(hash(e) for e in self.externalRefs)
            + sum(hash(a) for a in self.annotations)
        )

    @staticmethod
    def _calculate_package_hash_from_dict(package_dict: Dict[str, Any]) -> str:
        return hashlib.sha256(json.dumps(package_dict, sort_keys=True).encode()).hexdigest()

    @pydantic.field_validator("externalRefs")
    def _purls_validation(
        cls, refs: list[SPDXPackageExternalRefType]
    ) -> list[SPDXPackageExternalRefType]:
        """Validate that SPDXPackage includes only one purl with the same type, name, version."""
        parsed_purls = _parse_purls(_extract_purls(from_refs=refs))
        unique_purls_parts = set([(p.type, p.name, p.version) for p in parsed_purls])
        if len(unique_purls_parts) > 1:
            raise ValueError(
                "SPDXPackage includes multiple purls with different (type,name,version) tuple: "
                + f"{unique_purls_parts}"
            )
        return refs

    @classmethod
    def from_package_dict(cls, package: dict[str, Any]) -> "SPDXPackage":
        """Create a SPDXPackage from a Cachi2 package dictionary."""
        external_refs = package.get("externalRefs", [])
        annotations = [SPDXPackageAnnotation(**an) for an in package.get("annotations", [])]
        if package.get("SPDXID") is None:
            purls = sorted(
                [
                    ref["referenceLocator"]
                    for ref in package["externalRefs"]
                    if ref["referenceType"] == "purl"
                ]
            )
            package_hash = cls._calculate_package_hash_from_dict(
                {
                    "name": package["name"],
                    "version": package.get("versionInfo", None),
                    "purls": purls,
                }
            )
            SPDXID = (
                f"SPDXRef-Package-{package['name']}-{package.get('versionInfo', '')}-{package_hash}"
            )
        else:
            SPDXID = package["SPDXID"]
        return cls(
            SPDXID=SPDXID,
            name=package["name"],
            versionInfo=package.get("versionInfo", None),
            externalRefs=external_refs,
            annotations=annotations,
        )


class SPDXCreationInfo(pydantic.BaseModel):
    """SPDX Creation Information.

    Compliant to the SPDX specification:
    https://spdx.github.io/spdx-spec/v2.3/document-creation-information/
    """

    creators: list[str] = []
    created: str


class SPDXRelation(pydantic.BaseModel):
    """SPDX Relationship.

    Compliant to the SPDX specification:
    https://spdx.github.io/spdx-spec/v2.3/relationships-between-SPDX-elements/
    """

    spdxElementId: str
    comment: Optional[str] = None
    relatedSpdxElement: str
    relationshipType: str

    def __hash__(self) -> int:
        return hash(
            hash(self.spdxElementId + self.relatedSpdxElement + self.relationshipType)
            + hash(self.comment)
        )


def merge_component_properties(components: Iterable[Component]) -> list[Component]:
    """Sort and de-duplicate components while merging their `properties`."""
    components = sorted(components, key=Component.key)
    grouped_components = groupby(components, key=Component.key)

    def merge_component_group(component_group: Iterable[Component]) -> Component:
        component_group = list(component_group)
        prop_sets = (PropertySet.from_properties(c.properties) for c in component_group)
        merged_prop_set = reduce(PropertySet.merge, prop_sets)
        component = component_group[0]
        return component.model_copy(update={"properties": merged_prop_set.to_properties()})

    return [merge_component_group(g) for _, g in grouped_components]
