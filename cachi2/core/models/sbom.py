import datetime
import hashlib
import json
from typing import Annotated, Any, Dict, Iterable, Literal, Optional, Union
from urllib.parse import urlparse

import pydantic

from cachi2.core.models.validators import unique_sorted

PropertyName = Literal[
    "cachi2:found_by",
    "cachi2:missing_hash:in_file",
    "cachi2:pip:package:binary",
    "cdx:npm:package:bundled",
    "cdx:npm:package:development",
]


class Property(pydantic.BaseModel):
    """A property inside an SBOM component."""

    name: PropertyName
    value: str


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
    type: Literal["library"] = "library"

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


class Sbom(pydantic.BaseModel):
    """Software bill of materials in the CycloneDX format.

    See full specification at:
    https://cyclonedx.org/docs/1.4/json
    """

    model_config = pydantic.ConfigDict(extra="forbid")

    bom_format: Literal["CycloneDX"] = pydantic.Field(alias="bomFormat", default="CycloneDX")
    components: list[Component] = []
    metadata: Metadata = Metadata()
    spec_version: str = pydantic.Field(alias="specVersion", default="1.4")
    version: int = 1

    @pydantic.field_validator("components")
    def _unique_components(cls, components: list[Component]) -> list[Component]:
        """Sort and de-duplicate components."""
        return unique_sorted(components, by=lambda component: component.key())

    def to_spdx(self) -> "SPDXSbom":
        """Convert a CycloneDX SBOM to an SPDX SBOM."""
        packages = []
        relationships = []

        packages.append(
            SPDXPackage(
                name="",
                versionInfo="",
                SPDXID="SPDXRef-DocumentRoot-File-",
            )
        )

        for component in self.components:
            annotations = []
            for prop in component.properties:
                annotations.append(
                    SPDXPackageAnnotation(
                        annotator="cachi2",
                        annotationDate=datetime.datetime.now().isoformat(),
                        annotationType="OTHER",
                        comment=json.dumps(
                            {"name": f"{prop.name}", "value": f"{prop.value}"},
                        ),
                    )
                )
            package_hash = SPDXPackage._calculate_package_hash_from_dict(
                {
                    "name": component.name,
                    "version": component.version,
                    "purl": component.purl,
                }
            )

            packages.append(
                SPDXPackage(
                    SPDXID=f"SPDXID-Package-{component.name}-{component.version}-{package_hash}",
                    name=component.name,
                    versionInfo=component.version,
                    externalRefs=[
                        dict(
                            referenceCategory="PACKAGE-MANAGER",
                            referenceLocator=component.purl,
                            referenceType="purl",
                        )
                    ],
                    annotations=annotations,
                )
            )

        relationships.append(
            SPDXRelation(
                spdxElementId="SPDXRef-DOCUMENT",
                comment="",
                relatedSpdxElement="SPDXRef-DocumentRoot-File-",
                relationshipType="DESCRIBES",
            )
        )

        for package in packages:
            if package.SPDXID == "SPDXRef-DocumentRoot-File-":
                continue
            relationships.append(
                SPDXRelation(
                    spdxElementId="SPDXRef-DocumentRoot-File-",
                    comment="",
                    relatedSpdxElement=package.SPDXID,
                    relationshipType="CONTAINS",
                )
            )
        return SPDXSbom(
            packages=packages,
            relationships=relationships,
            creationInfo=SPDXCreationInfo(
                creators=sum(
                    [
                        [f"Tool: {tool.name}", f"Organization: {tool.vendor}"]
                        for tool in self.metadata.tools
                    ],
                    [],
                )
            ),
        )


class SPDXPackageExternalRefReferenceLocatorURI(pydantic.BaseModel):
    """SPDX Package External Reference with URI reference locator."""

    referenceLocator: str

    @pydantic.validator("referenceLocator")
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

    referenceLocator: str
    referenceType: str
    referenceCategory: str

    def __hash__(self) -> int:
        return hash((self.referenceLocator, self.referenceType, self.referenceCategory))


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


SPDXPackageExternalRefPackageManagerType = Annotated[
    SPDXPackageExternalRefPackageManagerPURL,
    pydantic.Field(discriminator="referenceType"),
]


SPDXPackageExternalRefType = Annotated[
    Union[SPDXPackageExternalRefPackageManagerType,],
    pydantic.Field(discriminator="referenceCategory"),
]


class SPDXPackageAnnotation(pydantic.BaseModel):
    """SPDX Package Annotation.

    Compliant to the SPDX specification:
    https://github.com/spdx/spdx-spec/blob/development/v2.3/schemas/spdx-schema.json#L237
    """

    annotator: str
    annotationDate: str
    annotationType: Literal["OTHER", "REVIEW"]
    comment: str

    def __hash__(self) -> int:
        return hash((self.annotator, self.annotationDate, self.annotationType, self.comment))


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

    @staticmethod
    def _calculate_package_hash_from_dict(package_dict: Dict[str, Any]) -> str:
        return hashlib.sha256(json.dumps(package_dict, sort_keys=True).encode()).hexdigest()

    @classmethod
    def from_package_dict(cls, package: dict[str, Any]) -> "SPDXPackage":
        """Create a SPDXPackage from a Cachi2 package dictionary."""
        external_refs = package.get("externalRefs", [])
        annotations = [SPDXPackageAnnotation(**an) for an in package.get("annotations", [])]
        if not package.get("SPDXID"):
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


class SPDXRelation(pydantic.BaseModel):
    """SPDX Relationship.

    Compliant to the SPDX specification:
    https://spdx.github.io/spdx-spec/v2.3/relationships-between-SPDX-elements/
    """

    spdxElementId: str
    comment: Optional[str] = None
    relatedSpdxElement: str
    relationshipType: str


class SPDXSbom(pydantic.BaseModel):
    """Software bill of materials in the SPDX format.

    See full specification at:
    https://spdx.github.io/spdx-spec/v2.3
    """

    model_config = pydantic.ConfigDict(extra="forbid")

    spdxVersion: Literal["SPDX-2.3"] = "SPDX-2.3"
    SPDXID: Literal["SPDXRef-DOCUMENT"] = "SPDXRef-DOCUMENT"
    dataLicense: Literal["CC0-1.0"] = "CC0-1.0"
    name: str = ""

    creationInfo: SPDXCreationInfo
    packages: list[SPDXPackage] = []
    relationships: list[SPDXRelation] = []

    @staticmethod
    def deduplicate_spdx_packages(items: Iterable[SPDXPackage]) -> list[SPDXPackage]:
        """Deduplicate SPDX packages and merge external references.

        If package with same name and version is found multiple times in the list,
        merge external references of all the packages into one package.
        """
        unique_items = {}
        for item in items:
            key = (item.name, item.versionInfo)
            if key not in unique_items:
                unique_items[key] = SPDXPackage(
                    SPDXID=item.SPDXID, name=item.name, versionInfo=item.versionInfo
                )
                unique_items[key].externalRefs = item.externalRefs[:]
                unique_items[key].annotations = item.annotations[:]
            else:
                unique_items[key].externalRefs.extend(item.externalRefs)
                unique_items[key].annotations.extend(item.annotations)

        for item in unique_items.values():
            item.externalRefs = sorted(
                set(item.externalRefs),
                key=lambda ref: (ref.referenceLocator, ref.referenceType, ref.referenceCategory),
            )
            item.annotations = sorted(
                set(item.annotations),
                key=lambda annotation: (
                    annotation.annotator,
                    annotation.annotationDate,
                    annotation.comment,
                ),
            )
        return sorted(unique_items.values(), key=lambda item: (item.name, item.versionInfo or ""))

    @pydantic.field_validator("packages")
    def _unique_packages(cls, packages: list[SPDXPackage]) -> list[SPDXPackage]:
        """Sort and de-duplicate components."""
        return cls.deduplicate_spdx_packages(packages)

    def to_cyclonedx(self) -> Sbom:
        """Convert a SPDX SBOM to a CycloneDX SBOM."""
        components = []
        for package in self.packages:
            properties = [Property(**json.loads(an.comment)) for an in package.annotations]
            purls = [
                ref.referenceLocator for ref in package.externalRefs if ref.referenceType == "purl"
            ]

            # cyclonedx doesn't support multiple purls, therefore
            # new component is created for each purl
            for purl in purls:
                components.append(
                    Component(
                        name=package.name,
                        version=package.versionInfo,
                        purl=purl,
                        properties=properties,
                    )
                )
            # if there's no purl and no package name or version, it's just wrapping element for
            # spdx package which is one layer bellow SPDXDocument in relationships
            if not any((purls, package.name, package.versionInfo)):
                continue
            # if there's no purl, add it as single component
            elif not purls:
                components.append(
                    Component(
                        name=package.name,
                        version=package.versionInfo,
                        properties=properties,
                        purl="",
                    )
                )
        tools = []
        name, vendor = None, None
        for creator in self.creationInfo.creators:
            if creator.startswith("Organization:"):
                vendor = creator.replace("Organization:", "").strip()
            elif creator.startswith("Tool:"):
                name = creator.replace("Tool:", "").strip()
            if name is not None and vendor is not None:
                tools.append(Tool(vendor=vendor, name=name))
                name, vendor = None, None

        return Sbom(
            components=components,
            metadata=Metadata(tools=tools),
        )
