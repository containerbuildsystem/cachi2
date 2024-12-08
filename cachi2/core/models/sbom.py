import datetime
import hashlib
import json
from collections import defaultdict
from functools import cached_property
from pathlib import Path
from typing import Annotated, Any, Dict, Iterable, Literal, Optional, Union
from urllib.parse import urlparse

import pydantic
from packageurl import PackageURL

from cachi2.core.models.validators import unique_sorted
from cachi2.core.utils import first

PropertyName = Literal[
    "cachi2:bundler:package:binary",
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

    def to_spdx(self, doc_namespace: str) -> "SPDXSbom":
        """Convert a CycloneDX SBOM to an SPDX SBOM.

        Args:
            doc_namespace: SPDX document namespace. Namespace is URI of indicating

        """
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
                        annotator="Tool: cachi2:jsonencoded",
                        annotationDate=datetime.datetime.now().isoformat()[:-7] + "Z",
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
                    SPDXID=f"SPDXRef-Package-{component.name}-{component.version}-{package_hash}",
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
            documentNamespace=doc_namespace,
            creationInfo=SPDXCreationInfo(
                creators=sum(
                    [
                        [f"Tool: {tool.name}", f"Organization: {tool.vendor}"]
                        for tool in self.metadata.tools
                    ],
                    [],
                ),
                created=datetime.datetime.now().isoformat()[:-7] + "Z",
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

    annotator: str
    annotationDate: str
    annotationType: Literal["OTHER", "REVIEW"]
    comment: str

    def __hash__(self) -> int:
        return hash((self.annotator, self.annotationDate, self.annotationType, self.comment))


class SPDXChecksum(pydantic.BaseModel):
    """A basic representation of a checksum entry."""

    algorithm: str
    checksumValue: str

    def __hash__(self) -> int:
        return hash(self.algorithm + self.checksumValue)


class SPDXFile(pydantic.BaseModel):
    """SPDX File.

    Compliant to the SPDX specification:
    https://spdx.github.io/spdx-spec/v2.3/package-information/

    An actual SPDX document generated from a directory or a container image
    would usually contain "files" section. This section would contain file
    entries of this shape.
    """

    SPDXID: Optional[str] = None
    fileName: str
    checksums: list[SPDXChecksum] = []  # TODO: flesh out proper cehcksums type
    licenseConcluded: str = "NOASSERTION"
    copyrightText: str = ""
    comment: str = ""

    def __hash__(self) -> int:
        return hash(
            hash(self.SPDXID)
            + hash(self.fileName)
            + hash(self.licenseConcluded + self.copyrightText + self.comment)
            + sum(hash(c) for c in self.checksums)
        )


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
        purls = [ref.referenceLocator for ref in refs if ref.referenceType == "purl"]
        parsed_purls = [PackageURL.from_string(purl) for purl in purls if purl]
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


class SPDXSbom(pydantic.BaseModel):
    """Software bill of materials in the SPDX format.

    See full specification at:
    https://spdx.github.io/spdx-spec/v2.3
    """

    # NOTE: The model is intentionally made non-strict for now because a strict model rejects
    # SBOMs generated by Syft. It is unclear at the moment if additional preprocessing will
    # be happening or desired.

    spdxVersion: Literal["SPDX-2.3"] = "SPDX-2.3"
    SPDXID: Literal["SPDXRef-DOCUMENT"] = "SPDXRef-DOCUMENT"
    dataLicense: Literal["CC0-1.0"] = "CC0-1.0"
    name: str = ""
    documentNamespace: str

    creationInfo: SPDXCreationInfo
    packages: list[SPDXPackage] = []
    files: list[SPDXFile] = []
    relationships: list[SPDXRelation] = []

    def __hash__(self) -> int:
        return hash(
            hash(self.name + self.documentNamespace)
            + hash(SPDXCreationInfo)
            + sum(hash(p) for p in self.packages)
            + sum(hash(f) for f in self.files)
            + sum(hash(r) for r in self.relationships)
        )

    @classmethod
    def from_file(cls, path: Path) -> "SPDXSbom":
        """Consume a SPDX json directly from a file."""
        return cls.model_validate_json(path.read_text())

    @staticmethod
    def deduplicate_spdx_packages(items: Iterable[SPDXPackage]) -> list[SPDXPackage]:
        """Deduplicate SPDX packages and merge external references.

        If package with same name and version is found multiple times in the list,
        merge external references of all the packages into one package.
        """
        # NOTE: keeping this implementation mostly intact for historical reasons.
        unique_items = {}
        for item in items:
            purls = [
                ref.referenceLocator for ref in item.externalRefs if ref.referenceType == "purl"
            ]
            if purls:
                keys = [PackageURL.from_string(purl) for purl in purls if purl]
                # name can exist in mutiple namespaces, e.g. rand exists in both math and
                # crypto, and must be distinguished between.
                p = keys[0]
                package_name = p.name
                if p.namespace is not None:
                    package_name = p.namespace + "/" + p.name
                purl_tnv = (p.type, package_name, p.version)
            else:
                purl_tnv = ("", item.name, item.versionInfo or "")

            if purl_tnv not in unique_items:
                # TODO: model_copy?
                unique_items[purl_tnv] = SPDXPackage(
                    SPDXID=item.SPDXID, name=item.name, versionInfo=item.versionInfo
                )
                unique_items[purl_tnv].externalRefs = item.externalRefs[:]
                unique_items[purl_tnv].annotations = item.annotations[:]
            else:
                unique_items[purl_tnv].externalRefs.extend(item.externalRefs)
                unique_items[purl_tnv].annotations.extend(item.annotations)

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

    @cached_property
    def root_id(self) -> str:
        """Return the root_id of this SBOM."""
        direct_relationships, inverse_relationships = defaultdict(list), dict()
        for rel in self.relationships:
            direct_relationships[rel.spdxElementId].append(rel.relatedSpdxElement)
            inverse_relationships[rel.relatedSpdxElement] = rel.spdxElementId
        # noqa because the name is bound to make local intent clearer and first() call easier to
        # follow.
        unidirectionally_related_package = (
            lambda p: inverse_relationships.get(p) == self.SPDXID  # noqa: E731
        )
        # Note: defaulting to top-level SPDXID is inherited from the original implementation.
        # It is unclear if it is really needed, but is left around to match the precedent.
        root_id = first(unidirectionally_related_package, direct_relationships, self.SPDXID)
        return root_id

    # NOTE: having this as cached will cause trouble when sequentially
    # constructing the object off of an empty state.
    @property
    def non_root_packages(self) -> list[SPDXPackage]:
        """Return non-root packages."""
        return [p for p in self.packages if p.SPDXID != self.root_id]

    @staticmethod
    def retarget_and_prune_relationships(
        from_sbom: "SPDXSbom",
        to_sbom: "SPDXSbom",
    ) -> list[SPDXRelation]:
        """Retarget and prune relationships."""
        out = []
        for r in from_sbom.relationships:
            # Do a copy to ensure we are not pulling a carpet from underneath us:
            new_rel = r.model_copy(deep=True)
            if new_rel.spdxElementId == from_sbom.root_id:
                new_rel.spdxElementId = to_sbom.root_id
            if new_rel.relatedSpdxElement == from_sbom.root_id:
                new_rel.spdxElementId = to_sbom.SPDXID
            # Old top-level "DESCRIBES" must go:
            if not (
                new_rel.relatedSpdxElement == from_sbom.root_id
                and new_rel.relationshipType == "DESCRIBES"
            ):
                out.append(new_rel)
        return out

    def __add__(self, other: Union["SPDXSbom", Sbom]) -> "SPDXSbom":
        if isinstance(other, self.__class__):
            # Packages are not going to be modified so it is OK to just pass references around.
            merged_packages = self.packages + other.non_root_packages
            # Relationships, on the other hand, are amended, so new
            # relationships will be constructed.
            # Further, identical relationships should be dropped.
            # Deduplication based on building a set is considered safe because all
            # fields of all elements are used to compute a hash.
            # Just using set won't work satisfactory since that would shuffle relationships.
            merged_relationships, seen_relationships = [], set()
            processed_other = self.retarget_and_prune_relationships(from_sbom=other, to_sbom=self)
            for r in self.relationships + processed_other:
                if r not in seen_relationships:
                    seen_relationships.add(r)
                    merged_relationships.append(r)
            # The same as packages: files are not modified, so keeping them as is.
            # Identical file entries should be skipped.
            merged_files = list(set(self.files + other.files))
            res = self.model_copy(
                update={
                    # At the moment of writing pydantic does not deem it necessary to
                    # validate updated fields because we should just trust them [1].
                    "packages": self.deduplicate_spdx_packages(merged_packages),
                    "relationships": merged_relationships,
                    "files": merged_files,
                },
                deep=True,
            )
            return res
        elif isinstance(other, Sbom):
            return self + other.to_spdx(doc_namespace="NOASSERTION")
        raise Exception("Something smart goes here")

    def to_cyclonedx(self) -> Sbom:
        """Convert a SPDX SBOM to a CycloneDX SBOM."""
        components = []
        for package in self.packages:
            properties = [
                (
                    Property(**json.loads(an.comment))
                    if an.annotator.endswith(":jsonencoded")
                    else Property(name=an.annotator, value=an.comment)
                )
                for an in package.annotations
            ]
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
        # Following approach is used as position of "Organization" and "Tool" is not
        # guaranteed by the standard
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


# References
# [1] https://github.com/pydantic/pydantic/blob/6fa92d139a297a26725dec0a7f9b0cce912d6a7f/pydantic/main.py#L383
