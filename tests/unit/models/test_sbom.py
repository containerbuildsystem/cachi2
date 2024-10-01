import datetime
import json

import pydantic
import pytest

from cachi2.core.models.sbom import (
    FOUND_BY_CACHI2_PROPERTY,
    Component,
    Property,
    Sbom,
    SPDXPackage,
    SPDXPackageAnnotation,
    SPDXPackageExternalRefPackageManagerPURL,
    SPDXPackageExternalRefType,
    SPDXRelation,
    SPDXSbom,
)


class TestComponent:
    @pytest.mark.parametrize(
        "input_data, expected_data",
        [
            (
                {"name": "mypkg", "purl": "pkg:generic/mypkg"},
                Component(name="mypkg", purl="pkg:generic/mypkg"),
            ),
            (
                {"name": "mypkg", "purl": "pkg:generic/mypkg@1.0.0", "version": "1.0.0"},
                Component(name="mypkg", version="1.0.0", purl="pkg:generic/mypkg@1.0.0"),
            ),
            (
                {"name": "mypkg", "purl": "pkg:generic/mypkg", "version": "random-version-string"},
                Component(name="mypkg", version="random-version-string", purl="pkg:generic/mypkg"),
            ),
            (
                {
                    "name": "mypkg",
                    "purl": "pkg:generic/mypkg@1.0.0",
                    "version": "1.0.0",
                    "type": "gomod",
                    "path": ".",
                    "dependencies": [],
                },
                Component(name="mypkg", version="1.0.0", purl="pkg:generic/mypkg@1.0.0"),
            ),
        ],
    )
    def test_construct_from_package_dict(
        self, input_data: dict[str, str], expected_data: Component
    ) -> None:
        component = Component.from_package_dict(input_data)
        assert component == expected_data

    @pytest.mark.parametrize(
        "input_data, expect_error",
        [
            (
                {"purl": "pkg:generic/x"},
                "1 validation error for Component\nname\n  Field required",
            ),
            (
                {"name": "x"},
                "1 validation error for Component\npurl\n  Field required",
            ),
            (
                {
                    "type": "gomod",
                    "name": "github.com/org/cool-dep",
                    "purl": "pkg:golang/github.com/org/cool-dep",
                },
                "1 validation error for Component\ntype\n  Input should be 'library'",
            ),
        ],
    )
    def test_invalid_components(self, input_data: dict[str, str], expect_error: str) -> None:
        with pytest.raises(pydantic.ValidationError, match=expect_error):
            Component(**input_data)

    @pytest.mark.parametrize(
        "input_properties, expected_properties",
        [
            (
                [],
                [FOUND_BY_CACHI2_PROPERTY],
            ),
            (
                [Property(name="cachi2:missing_hash:in_file", value="go.sum")],
                [
                    Property(name="cachi2:missing_hash:in_file", value="go.sum"),
                    FOUND_BY_CACHI2_PROPERTY,
                ],
            ),
            (
                [FOUND_BY_CACHI2_PROPERTY],
                [FOUND_BY_CACHI2_PROPERTY],
            ),
        ],
    )
    def test_default_property(
        self, input_properties: list[Property], expected_properties: list[Property]
    ) -> None:
        assert (
            Component(name="foo", purl="pkg:generic/foo", properties=input_properties).properties
            == expected_properties
        )


class TestSPDXPackage:
    @pytest.mark.parametrize(
        "input_data, expected_data",
        [
            (
                {
                    "SPDXID": "SPDXRef-Package-mypkg--4035f88e9e6be21e9717c7170c40cbdce83f591dc862c5a8e4ac21b5636fa875",
                    "name": "mypkg",
                    "externalRefs": [
                        {
                            "referenceLocator": "pkg:generic/mypkg",
                            "referenceCategory": "PACKAGE-MANAGER",
                            "referenceType": "purl",
                        }
                    ],
                },
                SPDXPackage(
                    SPDXID="SPDXRef-Package-mypkg--4035f88e9e6be21e9717c7170c40cbdce83f591dc862c5a8e4ac21b5636fa875",
                    name="mypkg",
                    externalRefs=[
                        SPDXPackageExternalRefPackageManagerPURL(
                            referenceLocator="pkg:generic/mypkg",
                            referenceCategory="PACKAGE-MANAGER",
                            referenceType="purl",
                        ),
                    ],
                ),
            ),
            (
                {
                    "name": "mypkg",
                    "versionInfo": "1.0.0",
                    "externalRefs": [
                        {
                            "referenceLocator": "pkg:generic/mypkg@1.0.0",
                            "referenceCategory": "PACKAGE-MANAGER",
                            "referenceType": "purl",
                        }
                    ],
                },
                SPDXPackage(
                    SPDXID="SPDXRef-Package-mypkg-1.0.0-ded235cb82fb6d084178a362048a549edb6586fd5cd5f84c7afbd919789b801d",
                    name="mypkg",
                    versionInfo="1.0.0",
                    externalRefs=[
                        SPDXPackageExternalRefPackageManagerPURL(
                            referenceLocator="pkg:generic/mypkg@1.0.0",
                            referenceCategory="PACKAGE-MANAGER",
                            referenceType="purl",
                        ),
                    ],
                ),
            ),
            (
                {
                    "name": "mypkg",
                    "versionInfo": "random-version-string",
                    "externalRefs": [
                        {
                            "referenceLocator": "pkg:generic/mypkg",
                            "referenceCategory": "PACKAGE-MANAGER",
                            "referenceType": "purl",
                        }
                    ],
                },
                SPDXPackage(
                    SPDXID="SPDXRef-Package-mypkg-random-version-string-5c73e2936cdb76c672fbee4c7a357695b052c97bcddacc5fb886f82bc78098d4",
                    name="mypkg",
                    versionInfo="random-version-string",
                    externalRefs=[
                        SPDXPackageExternalRefPackageManagerPURL(
                            referenceLocator="pkg:generic/mypkg",
                            referenceCategory="PACKAGE-MANAGER",
                            referenceType="purl",
                        )
                    ],
                ),
            ),
            (
                {
                    "name": "mypkg",
                    "externalRefs": [
                        {
                            "referenceLocator": "pkg:generic/mypkg@1.0.0",
                            "referenceCategory": "PACKAGE-MANAGER",
                            "referenceType": "purl",
                        }
                    ],
                    "versionInfo": "1.0.0",
                    "path": ".",
                    "dependencies": [],
                },
                SPDXPackage(
                    SPDXID="SPDXRef-Package-mypkg-1.0.0-ded235cb82fb6d084178a362048a549edb6586fd5cd5f84c7afbd919789b801d",
                    name="mypkg",
                    versionInfo="1.0.0",
                    externalRefs=[
                        SPDXPackageExternalRefPackageManagerPURL(
                            referenceLocator="pkg:generic/mypkg@1.0.0",
                            referenceCategory="PACKAGE-MANAGER",
                            referenceType="purl",
                        )
                    ],
                ),
            ),
        ],
    )
    def test_construct_from_package_dict(
        self, input_data: dict[str, str], expected_data: SPDXPackage
    ) -> None:
        spdx_package = SPDXPackage.from_package_dict(input_data)
        assert spdx_package == expected_data

    @pytest.mark.parametrize(
        "input_data, expect_error",
        [
            (
                {"versionInfo": "some-version"},
                "1 validation error for SPDXPackage\nname\n  Field required",
            )
        ],
    )
    def test_invalid_packages(self, input_data: dict[str, str], expect_error: str) -> None:
        with pytest.raises(pydantic.ValidationError, match=expect_error):
            SPDXPackage(**input_data)

    @pytest.mark.parametrize(
        "category,type,locator,valid",
        [
            ("SECURITY", "cpe22Type", "cpe:/o:canonical:ubuntu_linux:10.04:-:lts", False),
            (
                "SECURITY",
                "cpe23Type",
                "cpe:2.3:a:microsoft:internet_explorer:8.0.6001:beta:*:*:*:*:*:*",
                False,
            ),
            ("SECURITY", "advisory", "https://nvd.nist.gov/vuln/detail/CVE-2020-28498", False),
            ("SECURITY", "fix", "https://github.com/indutny/elliptic/commit/441b7428", False),
            (
                "SECURITY",
                "url",
                "https://github.com/christianlundkvist/blog/blob/master/2020_05_26_secp256k1_twist_attacks/secp256k1_twist_attacks.md",
                False,
            ),
            ("SECURITY", "swid", "2df9de35-0aff-4a86-ace6-f7dddd1ade4c", False),
            ("PACKAGE-MANAGER", "maven-central", "org.apache.tomcat:tomcat:9.0.0.M4", False),
            ("PACKAGE-MANAGER", "npm", "http-server@0.3.0", False),
            ("PACKAGE-MANAGER", "nuget", "Microsoft.AspNet.MVC/5.0.0", False),
            ("PACKAGE-MANAGER", "bower", "modernizr#2.6.2", False),
            ("PERSISTENT-ID", "swh", "swh:1:cnt:94a9ed024d3859793618152ea559a168bbcbb5e2", False),
            (
                "PERSISTENT-ID",
                "gitoid",
                "gitoid:blob:sha1:261eeb9e9f8b2b4b0d119366dda99c6fd7d35c64",
                False,
            ),
            (
                "OTHER",
                "some-id",
                "anythingcangohere",
                False,
            ),
        ],
    )
    def test_package_unsupported_external_ref(
        self, category: str, type: str, locator: str, valid: str
    ) -> None:
        """Fails on unsupported category and type combinations.

        Only PACKAGE-MANAGER category with type purl is supported.
        """
        adapter: pydantic.TypeAdapter = pydantic.TypeAdapter(SPDXPackageExternalRefType)
        with pytest.raises(pydantic.ValidationError):
            adapter.validate_python(
                dict(referenceCategory=category, referenceLocator=locator, referenceType=type)
            )


class TestSbom:
    def test_sort_and_dedupe_components(self) -> None:
        sbom = Sbom(
            components=[
                {
                    "name": "github.com/org/B",
                    "version": "v1.0.0",
                    "purl": "pkg:golang/github.com/org/B@v1.0.0",
                },
                {
                    "name": "github.com/org/A",
                    "version": "v1.1.0",
                    "purl": "pkg:golang/github.com/org/A@v1.1.0",
                },
                {
                    "name": "github.com/org/A",
                    "version": "v1.0.0",
                    "purl": "pkg:golang/github.com/org/A@v1.0.0",
                },
                {
                    "name": "github.com/org/A",
                    "version": "v1.0.0",
                    "purl": "pkg:golang/github.com/org/A@v1.0.0",
                },
                {
                    "name": "github.com/org/B",
                    "version": "v1.0.0",
                    "purl": "pkg:golang/github.com/org/B@v1.0.0",
                },
                {"name": "fmt", "version": None, "purl": "pkg:golang/fmt"},
                {"name": "fmt", "version": None, "purl": "pkg:golang/fmt"},
                {"name": "bytes", "version": None, "purl": "pkg:golang/bytes"},
            ],
        )
        assert sbom.components == [
            Component(name="bytes", purl="pkg:golang/bytes"),
            Component(name="fmt", purl="pkg:golang/fmt"),
            Component(
                name="github.com/org/A", purl="pkg:golang/github.com/org/A@v1.0.0", version="v1.0.0"
            ),
            Component(
                name="github.com/org/A", purl="pkg:golang/github.com/org/A@v1.1.0", version="v1.1.0"
            ),
            Component(
                name="github.com/org/B", purl="pkg:golang/github.com/org/B@v1.0.0", version="v1.0.0"
            ),
        ]

    def test_to_spdx(self, isodate: datetime.datetime) -> None:
        sbom = Sbom(
            components=[
                {
                    "name": "spdx-expression-parse",
                    "version": "v1.0.0",
                    "purl": "pkg:npm/spdx-expression-parse@1.0.0",
                },
                {
                    "name": "github.com/org/A",
                    "version": "v1.0.0",
                    "purl": "pkg:golang/github.com/org/A@v1.0.0",
                },
                {
                    "name": "github.com/org/A",
                    "version": "v1.1.0",
                    "purl": "pkg:golang/github.com/org/A@v1.1.0",
                },
            ],
        )
        sbom.components[0].properties.extend(
            [
                Property(name="cdx:npm:package:bundled", value="true"),
            ]
        )
        spdx_sbom = sbom.to_spdx()

        assert spdx_sbom.packages == [
            SPDXPackage(
                SPDXID="SPDXRef-DocumentRoot-File-",
                name="",
                versionInfo="",
                externalRefs=[],
                annotations=[],
            ),
            SPDXPackage(
                SPDXID="SPDXID-Package-github.com/org/A-v1.0.0-8090f86e9eb851549de5f8391948c1df6a2c8976bfa33c3cbd82e917564ac94f",
                name="github.com/org/A",
                versionInfo="v1.0.0",
                externalRefs=[
                    SPDXPackageExternalRefPackageManagerPURL(
                        referenceCategory="PACKAGE-MANAGER",
                        referenceLocator="pkg:golang/github.com/org/A@v1.0.0",
                        referenceType="purl",
                    )
                ],
                annotations=[
                    SPDXPackageAnnotation(
                        annotator="cachi2",
                        annotationDate="2021-07-01T00:00:00Z",
                        annotationType="OTHER",
                        comment=json.dumps({"name": "cachi2:found_by", "value": "cachi2"}),
                    ),
                    SPDXPackageAnnotation(
                        annotator="cachi2",
                        annotationDate="2021-07-01T00:00:00Z",
                        annotationType="OTHER",
                        comment=json.dumps({"name": "cdx:npm:package:bundled", "value": "true"}),
                    ),
                ],
            ),
            SPDXPackage(
                SPDXID="SPDXID-Package-github.com/org/A-v1.1.0-898f4d436d82296d12247741855acc48a1f80639d2418e556268f30ae2336303",
                name="github.com/org/A",
                versionInfo="v1.1.0",
                externalRefs=[
                    SPDXPackageExternalRefPackageManagerPURL(
                        referenceCategory="PACKAGE-MANAGER",
                        referenceLocator="pkg:golang/github.com/org/A@v1.1.0",
                        referenceType="purl",
                    )
                ],
                annotations=[
                    SPDXPackageAnnotation(
                        annotator="cachi2",
                        annotationDate="2021-07-01T00:00:00Z",
                        annotationType="OTHER",
                        comment=json.dumps({"name": "cachi2:found_by", "value": "cachi2"}),
                    ),
                ],
            ),
            SPDXPackage(
                SPDXID="SPDXID-Package-spdx-expression-parse-v1.0.0-2d5c537d20208409089cf9c7ae9398b7105beef1f883cfc4c0b1f804bca86b02",
                name="spdx-expression-parse",
                versionInfo="v1.0.0",
                externalRefs=[
                    SPDXPackageExternalRefPackageManagerPURL(
                        referenceCategory="PACKAGE-MANAGER",
                        referenceLocator="pkg:npm/spdx-expression-parse@1.0.0",
                        referenceType="purl",
                    )
                ],
                annotations=[
                    SPDXPackageAnnotation(
                        annotator="cachi2",
                        annotationDate="2021-07-01T00:00:00Z",
                        annotationType="OTHER",
                        comment=json.dumps({"name": "cachi2:found_by", "value": "cachi2"}),
                    ),
                ],
            ),
        ]
        assert spdx_sbom.relationships == [
            SPDXRelation(
                spdxElementId="SPDXRef-DOCUMENT",
                comment="",
                relatedSpdxElement="SPDXRef-DocumentRoot-File-",
                relationshipType="DESCRIBES",
            ),
            SPDXRelation(
                spdxElementId="SPDXRef-DocumentRoot-File-",
                comment="",
                relatedSpdxElement="SPDXID-Package-github.com/org/A-v1.0.0-8090f86e9eb851549de5f8391948c1df6a2c8976bfa33c3cbd82e917564ac94f",
                relationshipType="CONTAINS",
            ),
            SPDXRelation(
                spdxElementId="SPDXRef-DocumentRoot-File-",
                comment="",
                relatedSpdxElement="SPDXID-Package-github.com/org/A-v1.1.0-898f4d436d82296d12247741855acc48a1f80639d2418e556268f30ae2336303",
                relationshipType="CONTAINS",
            ),
            SPDXRelation(
                spdxElementId="SPDXRef-DocumentRoot-File-",
                comment="",
                relatedSpdxElement="SPDXID-Package-spdx-expression-parse-v1.0.0-2d5c537d20208409089cf9c7ae9398b7105beef1f883cfc4c0b1f804bca86b02",
                relationshipType="CONTAINS",
            ),
        ]


class TestSPDXSbom:
    def test_sort_and_dedupe_packages(self) -> None:
        sbom = SPDXSbom(
            creationInfo={"creators": []},
            packages=[
                {
                    "name": "github.com/org/B",
                    "versionInfo": "v1.0.0",
                    "externalRefs": [
                        {
                            "referenceCategory": "PACKAGE-MANAGER",
                            "referenceLocator": "pkg:golang/github.com/org/B@v1.0.0",
                            "referenceType": "purl",
                        }
                    ],
                },
                {
                    "name": "github.com/org/A",
                    "versionInfo": "v1.1.0",
                    "externalRefs": [
                        {
                            "referenceCategory": "PACKAGE-MANAGER",
                            "referenceLocator": "pkg:golang/github.com/org/A@v1.1.0?repository_id=R1",
                            "referenceType": "purl",
                        }
                    ],
                },
                {
                    "name": "github.com/org/A",
                    "versionInfo": "v1.1.0",
                    "externalRefs": [
                        {
                            "referenceCategory": "PACKAGE-MANAGER",
                            "referenceLocator": "pkg:golang/github.com/org/A@v1.1.0?repository_id=R2",
                            "referenceType": "purl",
                        }
                    ],
                },
                {
                    "name": "github.com/org/A",
                    "versionInfo": "v1.0.0",
                    "externalRefs": [
                        {
                            "referenceCategory": "PACKAGE-MANAGER",
                            "referenceLocator": "pkg:golang/github.com/org/A@v1.0.0",
                            "referenceType": "purl",
                        }
                    ],
                },
                {
                    "name": "github.com/org/A",
                    "versionInfo": "v1.0.0",
                    "externalRefs": [
                        {
                            "referenceCategory": "PACKAGE-MANAGER",
                            "referenceLocator": "pkg:golang/github.com/org/A@v1.0.0",
                            "referenceType": "purl",
                        }
                    ],
                },
                {
                    "name": "github.com/org/B",
                    "versionInfo": "v1.0.0",
                    "externalRefs": [
                        {
                            "referenceCategory": "PACKAGE-MANAGER",
                            "referenceLocator": "pkg:golang/github.com/org/B@v1.0.0",
                            "referenceType": "purl",
                        }
                    ],
                },
                {
                    "name": "fmt",
                    "versionInfo": None,
                    "externalRefs": [
                        {
                            "referenceCategory": "PACKAGE-MANAGER",
                            "referenceLocator": "pkg:golang/fmt",
                            "referenceType": "purl",
                        }
                    ],
                },
                {
                    "name": "bytes",
                    "versionInfo": None,
                    "externalRefs": [
                        {
                            "referenceCategory": "PACKAGE-MANAGER",
                            "referenceLocator": "pkg:golang/bytes",
                            "referenceType": "purl",
                        }
                    ],
                },
            ],
        )
        assert len(sbom.packages) == 5
        assert sbom.packages == [
            SPDXPackage(
                name="bytes",
                externalRefs=[
                    SPDXPackageExternalRefPackageManagerPURL(
                        referenceCategory="PACKAGE-MANAGER",
                        referenceLocator="pkg:golang/bytes",
                        referenceType="purl",
                    )
                ],
            ),
            SPDXPackage(
                name="fmt",
                externalRefs=[
                    SPDXPackageExternalRefPackageManagerPURL(
                        referenceCategory="PACKAGE-MANAGER",
                        referenceLocator="pkg:golang/fmt",
                        referenceType="purl",
                    )
                ],
            ),
            SPDXPackage(
                name="github.com/org/A",
                versionInfo="v1.0.0",
                externalRefs=[
                    SPDXPackageExternalRefPackageManagerPURL(
                        referenceCategory="PACKAGE-MANAGER",
                        referenceLocator="pkg:golang/github.com/org/A@v1.0.0",
                        referenceType="purl",
                    )
                ],
            ),
            SPDXPackage(
                name="github.com/org/A",
                versionInfo="v1.1.0",
                externalRefs=[
                    SPDXPackageExternalRefPackageManagerPURL(
                        referenceCategory="PACKAGE-MANAGER",
                        referenceLocator="pkg:golang/github.com/org/A@v1.1.0?repository_id=R1",
                        referenceType="purl",
                    ),
                    SPDXPackageExternalRefPackageManagerPURL(
                        referenceCategory="PACKAGE-MANAGER",
                        referenceLocator="pkg:golang/github.com/org/A@v1.1.0?repository_id=R2",
                        referenceType="purl",
                    ),
                ],
            ),
            SPDXPackage(
                name="github.com/org/B",
                versionInfo="v1.0.0",
                externalRefs=[
                    SPDXPackageExternalRefPackageManagerPURL(
                        referenceCategory="PACKAGE-MANAGER",
                        referenceLocator="pkg:golang/github.com/org/B@v1.0.0",
                        referenceType="purl",
                    )
                ],
            ),
        ]

    def test_package_external_ref_invalid_reference_type_for_category(self) -> None:
        adapter: pydantic.TypeAdapter = pydantic.TypeAdapter(SPDXPackageExternalRefType)

        with pytest.raises(pydantic.ValidationError):
            adapter.validate_python(
                dict(
                    referenceCategory="SECURITY",
                    referenceLocator="pkg:golang/github.com/org/B@v1.0.0",
                    referenceType="purl",
                )
            )
        with pytest.raises(pydantic.ValidationError):
            adapter.validate_python(
                dict(
                    referenceCategory="PERSISTENT-ID",
                    referenceLocator="pkg:golang/github.com/org/B@v1.0.0",
                    referenceType="purl",
                )
            )
        with pytest.raises(pydantic.ValidationError):
            adapter.validate_python(
                dict(
                    referenceCategory="PACKAGE-MANAGER",
                    referenceLocator="gitoid:blob:sha1:261eeb9e9f8b2b4b0d119366dda99c6fd7d35c64",
                    referenceType="gitbom",
                )
            )

    def test_package_external_ref_invalid_reference(self) -> None:
        adapter: pydantic.TypeAdapter = pydantic.TypeAdapter(SPDXPackageExternalRefType)
        with pytest.raises(
            pydantic.ValidationError,
        ):
            adapter.validate_python(
                dict(
                    referenceCategory="INVALID",
                    referenceLocator="pkg:golang/github.com/org/B@v1.0.0",
                    referenceType="purl",
                )
            )


def test_deduplicate_spdx_packages() -> None:
    packages = [
        SPDXPackage(
            name="github.com/org/A",
            versionInfo="v1.0.0",
            externalRefs=[
                SPDXPackageExternalRefPackageManagerPURL(
                    referenceCategory="PACKAGE-MANAGER",
                    referenceLocator="pkg:golang/github.com/org/A@v1.0.0?repository_id=R1",
                    referenceType="purl",
                )
            ],
        ),
        SPDXPackage(
            name="github.com/org/A",
            versionInfo="v1.0.0",
            externalRefs=[
                SPDXPackageExternalRefPackageManagerPURL(
                    referenceCategory="PACKAGE-MANAGER",
                    referenceLocator="pkg:golang/github.com/org/A@v1.0.0?repository_id=R1",
                    referenceType="purl",
                ),
                SPDXPackageExternalRefPackageManagerPURL(
                    referenceCategory="PACKAGE-MANAGER",
                    referenceLocator="pkg:golang/github.com/org/A@v1.0.0?repository_id=R2",
                    referenceType="purl",
                ),
            ],
        ),
        SPDXPackage(
            name="github.com/org/B",
            versionInfo="v1.0.0",
            externalRefs=[
                SPDXPackageExternalRefPackageManagerPURL(
                    referenceCategory="PACKAGE-MANAGER",
                    referenceLocator="pkg:golang/github.com/org/B@v1.0.0",
                    referenceType="purl",
                )
            ],
        ),
        SPDXPackage(
            name="github.com/org/B",
            versionInfo="v1.0.0",
            externalRefs=[
                SPDXPackageExternalRefPackageManagerPURL(
                    referenceCategory="PACKAGE-MANAGER",
                    referenceLocator="pkg:golang/github.com/org/B@v1.0.0?repository_id=R1",
                    referenceType="purl",
                )
            ],
        ),
    ]
    deduped_packages = SPDXSbom.deduplicate_spdx_packages(packages)
    assert len(deduped_packages) == 2
    assert deduped_packages == [
        SPDXPackage(
            name="github.com/org/A",
            versionInfo="v1.0.0",
            externalRefs=[
                SPDXPackageExternalRefPackageManagerPURL(
                    referenceCategory="PACKAGE-MANAGER",
                    referenceLocator="pkg:golang/github.com/org/A@v1.0.0?repository_id=R1",
                    referenceType="purl",
                ),
                SPDXPackageExternalRefPackageManagerPURL(
                    referenceCategory="PACKAGE-MANAGER",
                    referenceLocator="pkg:golang/github.com/org/A@v1.0.0?repository_id=R2",
                    referenceType="purl",
                ),
            ],
        ),
        SPDXPackage(
            name="github.com/org/B",
            versionInfo="v1.0.0",
            externalRefs=[
                SPDXPackageExternalRefPackageManagerPURL(
                    referenceCategory="PACKAGE-MANAGER",
                    referenceLocator="pkg:golang/github.com/org/B@v1.0.0",
                    referenceType="purl",
                ),
                SPDXPackageExternalRefPackageManagerPURL(
                    referenceCategory="PACKAGE-MANAGER",
                    referenceLocator="pkg:golang/github.com/org/B@v1.0.0?repository_id=R1",
                    referenceType="purl",
                ),
            ],
        ),
    ]
