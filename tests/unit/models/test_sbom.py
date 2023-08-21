import pydantic
import pytest

from cachi2.core.models.sbom import FOUND_BY_CACHI2_PROPERTY, Component, Property, Sbom


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
                "1 validation error for Component\nname\n  field required",
            ),
            (
                {"name": "x"},
                "1 validation error for Component\npurl\n  field required",
            ),
            (
                {
                    "type": "gomod",
                    "name": "github.com/org/cool-dep",
                    "purl": "pkg:golang/github.com/org/cool-dep",
                },
                "1 validation error for Component\ntype\n  unexpected value",
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
        print(sbom.components)
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
