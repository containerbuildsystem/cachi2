from pathlib import Path
from textwrap import dedent
from typing import Any

import pydantic
import pytest

from cachi2.core.models.output import (
    BuildConfig,
    Component,
    EnvironmentVariable,
    ProjectFile,
    RequestOutput,
    Sbom,
)


class TestComponent:
    @pytest.mark.parametrize(
        "input_data, expected_data",
        [
            ({"name": "mypkg"}, Component(name="mypkg")),
            ({"name": "mypkg", "version": "1.0.0"}, Component(name="mypkg", version="1.0.0")),
            (
                {"name": "mypkg", "version": "random-version-string"},
                Component(name="mypkg", version="random-version-string"),
            ),
            (
                {
                    "name": "mypkg",
                    "version": "1.0.0",
                    "type": "gomod",
                    "path": ".",
                    "dependencies": [],
                },
                Component(name="mypkg", version="1.0.0"),
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
                {},
                "1 validation error for Component\nname\n  field required",
            ),
            (
                {"type": "gomod", "name": "github.com/org/cool-dep"},
                "1 validation error for Component\ntype\n  unexpected value",
            ),
        ],
    )
    def test_invalid_components(self, input_data: dict[str, str], expect_error: str) -> None:
        with pytest.raises(pydantic.ValidationError, match=expect_error):
            Component(**input_data)


class TestSbom:
    def test_sort_and_dedupe_components(self) -> None:
        sbom = Sbom(
            components=[
                {"name": "github.com/org/B", "version": "v1.0.0"},
                {"name": "github.com/org/A", "version": "v1.1.0"},
                {"name": "github.com/org/A", "version": "v1.0.0"},
                {"name": "github.com/org/A", "version": "v1.0.0"},
                {"name": "github.com/org/B", "version": "v1.0.0"},
                {"name": "fmt", "version": None},
                {"name": "fmt", "version": None},
                {"name": "bytes", "version": None},
            ],
        )
        assert sbom.components == [
            Component(name="bytes", version=None),
            Component(name="fmt", version=None),
            Component(name="github.com/org/A", version="v1.0.0"),
            Component(name="github.com/org/A", version="v1.1.0"),
            Component(name="github.com/org/B", version="v1.0.0"),
        ]


class TestProjectFile:
    def test_resolve_content(self) -> None:
        template = dedent(
            """
            no placeholders
            $unknown_placeholder
            invalid placeholder: $5
            ${output_dir}/deps/gomod
            file://$output_dir/deps/pip
            """
        )
        expect_content = dedent(
            """
            no placeholders
            $unknown_placeholder
            invalid placeholder: $5
            /some/output/deps/gomod
            file:///some/output/deps/pip
            """
        )
        project_file = ProjectFile(abspath="/some/path", template=template)
        assert project_file.resolve_content(Path("/some/output")) == expect_content


class TestBuildConfig:
    def test_conflicting_env_vars(self) -> None:
        expect_error = (
            "conflict by GOSUMDB: "
            "name='GOSUMDB' value='on' kind='literal' "
            "X name='GOSUMDB' value='sum.golang.org' kind='literal'"
        )
        with pytest.raises(pydantic.ValidationError, match=expect_error):
            BuildConfig(
                environment_variables=[
                    {"name": "GOSUMDB", "value": "on", "kind": "literal"},
                    {"name": "GOSUMDB", "value": "sum.golang.org", "kind": "literal"},
                ],
                project_files=[],
            )

    def test_sort_and_dedupe_env_vars(self) -> None:
        build_config = BuildConfig(
            environment_variables=[
                {"name": "B", "value": "y", "kind": "literal"},
                {"name": "A", "value": "x", "kind": "literal"},
                {"name": "B", "value": "y", "kind": "literal"},
            ],
            project_files=[],
        )
        assert build_config.environment_variables == [
            EnvironmentVariable(name="A", value="x", kind="literal"),
            EnvironmentVariable(name="B", value="y", kind="literal"),
        ]

    def test_conflicting_project_files(self) -> None:
        expect_error = "conflict by /some/path:"
        with pytest.raises(pydantic.ValidationError, match=expect_error):
            BuildConfig(
                environment_variables=[],
                project_files=[
                    {"abspath": "/some/path", "template": "foo"},
                    {"abspath": "/some/path", "template": "bar"},
                ],
            )

    def test_sort_and_dedupe_project_files(self) -> None:
        build_config = BuildConfig(
            environment_variables=[],
            project_files=[
                {"abspath": "/second/path", "template": "bar"},
                {"abspath": "/first/path", "template": "foo"},
                {"abspath": "/second/path", "template": "bar"},
            ],
        )
        assert build_config.project_files == [
            ProjectFile(abspath="/first/path", template="foo"),
            ProjectFile(abspath="/second/path", template="bar"),
        ]


class TestRequestOutput:
    @pytest.mark.parametrize(
        "input_data, expected_data",
        [
            (
                {"components": [{"name": "mypkg"}]},
                RequestOutput(
                    sbom=Sbom(components=[{"name": "mypkg"}]),
                    build_config=BuildConfig(),
                ),
            ),
            (
                {
                    "components": [{"name": "mypkg"}],
                    "environment_variables": [{"name": "a", "value": "y", "kind": "literal"}],
                    "project_files": [{"abspath": "/first/path", "template": "foo"}],
                },
                RequestOutput(
                    sbom=Sbom(components=[{"name": "mypkg"}]),
                    build_config=BuildConfig(
                        environment_variables=[
                            EnvironmentVariable(name="a", value="y", kind="literal")
                        ],
                        project_files=[ProjectFile(abspath="/first/path", template="foo")],
                    ),
                ),
            ),
        ],
    )
    def test_create_from_obj_lists(
        self, input_data: dict[str, Any], expected_data: RequestOutput
    ) -> None:
        request_output = RequestOutput.from_obj_list(**input_data)
        assert request_output == expected_data
