import re
from pathlib import Path
from textwrap import dedent
from typing import Any

import pydantic
import pytest

from cachi2.core.models.output import (
    Dependency,
    EnvironmentVariable,
    GomodDependency,
    GoPackageDependency,
    Package,
    PipDependency,
    ProjectFile,
    RequestOutput,
)


class TestDependency:
    @pytest.mark.parametrize(
        "input_data",
        [
            {"type": "gomod", "name": "github.com/org/cool-dep", "version": "v1.0.0"},
            {"type": "go-package", "name": "fmt", "version": None},
            {"type": "pip", "name": "requests", "version": "2.27.1", "dev": False},
        ],
    )
    def test_valid_deps(self, input_data: dict[str, Any]):
        # doesn't pass type check: https://github.com/pydantic/pydantic/issues/1847
        dep = pydantic.parse_obj_as(Dependency, input_data)  # type: ignore
        assert dep.dict() == input_data

    @pytest.mark.parametrize(
        "input_data, expect_error",
        [
            (
                {"type": "made-up-type", "name": "foo", "version": "1.0"},
                "No match for discriminator 'type' and value 'made-up-type'",
            ),
            (
                {"type": "gomod", "name": "github.com/org/cool-dep", "version": None},
                "version\n  none is not an allowed value",
            ),
        ],
    )
    def test_invalid_deps(self, input_data: dict[str, Any], expect_error: str):
        with pytest.raises(pydantic.ValidationError, match=expect_error):
            # doesn't pass type check: https://github.com/pydantic/pydantic/issues/1847
            pydantic.parse_obj_as(Dependency, input_data)  # type: ignore


class TestPackage:
    def test_sort_and_dedupe_deps(self):
        package = Package(
            type="gomod",
            name="github.com/my-org/my-module",
            version="v1.0.0",
            path=".",
            dependencies=[
                {"type": "gomod", "name": "github.com/org/B", "version": "v1.0.0"},
                {"type": "gomod", "name": "github.com/org/A", "version": "v1.1.0"},
                {"type": "gomod", "name": "github.com/org/A", "version": "v1.0.0"},
                {"type": "gomod", "name": "github.com/org/A", "version": "v1.0.0"},
                {"type": "go-package", "name": "github.com/org/B", "version": "v1.0.0"},
                {"type": "go-package", "name": "fmt", "version": None},
                {"type": "go-package", "name": "fmt", "version": None},
                {"type": "go-package", "name": "bytes", "version": None},
            ],
        )
        assert package.dependencies == [
            GoPackageDependency(type="go-package", name="bytes", version=None),
            GoPackageDependency(type="go-package", name="fmt", version=None),
            GoPackageDependency(type="go-package", name="github.com/org/B", version="v1.0.0"),
            GomodDependency(type="gomod", name="github.com/org/A", version="v1.0.0"),
            GomodDependency(type="gomod", name="github.com/org/A", version="v1.1.0"),
            GomodDependency(type="gomod", name="github.com/org/B", version="v1.0.0"),
        ]

    def test_sort_and_dedupe_dev_deps(self):
        package = Package(
            type="pip",
            name="cachi2",
            version="1.0.0",
            path=".",
            dependencies=[
                {"type": "pip", "name": "packaging", "version": "0.23", "dev": True},
                {"type": "pip", "name": "packaging", "version": "0.22", "dev": True},
                {"type": "pip", "name": "requests", "version": "2.28.1", "dev": False},
                {"type": "pip", "name": "packaging", "version": "0.23", "dev": False},
                # de-duplicate
                {"type": "pip", "name": "requests", "version": "2.28.1", "dev": False},
                {"type": "pip", "name": "packaging", "version": "0.23", "dev": True},
            ],
        )
        assert package.dependencies == [
            # dev -> name -> version
            PipDependency(type="pip", name="packaging", version="0.23", dev=False),
            PipDependency(type="pip", name="requests", version="2.28.1", dev=False),
            PipDependency(type="pip", name="packaging", version="0.22", dev=True),
            PipDependency(type="pip", name="packaging", version="0.23", dev=True),
        ]


class TestProjectFile:
    def test_resolve_content(self):
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


class TestRequestOutput:
    def test_duplicate_packages(self):
        package = {
            "type": "gomod",
            "name": "github.com/my-org/my-module",
            "version": "v1.0.0",
            "path": ".",
            "dependencies": [],
        }
        package2 = package | {"path": "subpath"}

        expect_error = f"conflict by {('gomod', 'github.com/my-org/my-module', 'v1.0.0')}"
        with pytest.raises(pydantic.ValidationError, match=re.escape(expect_error)):
            RequestOutput(
                packages=[package, package2],
                environment_variables=[],
                project_files=[],
            )

    def test_conflicting_env_vars(self):
        expect_error = (
            "conflict by GOSUMDB: "
            "name='GOSUMDB' value='on' kind='literal' "
            "X name='GOSUMDB' value='off' kind='literal'"
        )
        with pytest.raises(pydantic.ValidationError, match=expect_error):
            RequestOutput(
                packages=[],
                environment_variables=[
                    {"name": "GOSUMDB", "value": "on", "kind": "literal"},
                    {"name": "GOSUMDB", "value": "off", "kind": "literal"},
                ],
                project_files=[],
            )

    def test_sort_and_dedupe_env_vars(self):
        output = RequestOutput(
            packages=[],
            environment_variables=[
                {"name": "B", "value": "y", "kind": "literal"},
                {"name": "A", "value": "x", "kind": "literal"},
                {"name": "B", "value": "y", "kind": "literal"},
            ],
            project_files=[],
        )
        assert output.environment_variables == [
            EnvironmentVariable(name="A", value="x", kind="literal"),
            EnvironmentVariable(name="B", value="y", kind="literal"),
        ]

    def test_conflicting_project_files(self):
        expect_error = "conflict by /some/path:"
        with pytest.raises(pydantic.ValidationError, match=expect_error):
            RequestOutput(
                packages=[],
                environment_variables=[],
                project_files=[
                    {"abspath": "/some/path", "template": "foo"},
                    {"abspath": "/some/path", "template": "bar"},
                ],
            )

    def test_sort_and_dedupe_project_files(self):
        output = RequestOutput(
            packages=[],
            environment_variables=[],
            project_files=[
                {"abspath": "/second/path", "template": "bar"},
                {"abspath": "/first/path", "template": "foo"},
                {"abspath": "/second/path", "template": "bar"},
            ],
        )
        assert output.project_files == [
            ProjectFile(abspath="/first/path", template="foo"),
            ProjectFile(abspath="/second/path", template="bar"),
        ]


def mock_output(pkg_names: list[str], env_names: list[str]) -> RequestOutput:
    return RequestOutput(
        packages=[
            Package(type="pip", name=name, version="1.0.0", path=".", dependencies=[])
            for name in pkg_names
        ],
        environment_variables=[
            EnvironmentVariable(name=name, value="foo", kind="literal") for name in env_names
        ],
        project_files=[],
    )
