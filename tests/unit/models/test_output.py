import re
from typing import Any

import pydantic
import pytest

from cachi2.core.models.output import (
    Dependency,
    EnvironmentVariable,
    Package,
    RequestOutput,
)


class TestDependency:
    @pytest.mark.parametrize(
        "input_data",
        [
            {"type": "gomod", "name": "github.com/org/cool-dep", "version": "v1.0.0"},
            {"type": "go-package", "name": "fmt", "version": None},
        ],
    )
    def test_valid_deps(self, input_data: dict[str, Any]):
        dep = Dependency.parse_obj(input_data)
        assert dep.dict() == input_data

    @pytest.mark.parametrize(
        "input_data, expect_error",
        [
            (
                {"type": "made-up-type", "name": "foo", "version": "1.0"},
                "type\n  unexpected value; permitted: .* given=made-up-type;",
            ),
            (
                {"type": "gomod", "name": "github.com/org/cool-dep", "version": None},
                "version\n  gomod dependencies must have a version",
            ),
        ],
    )
    def test_invalid_deps(self, input_data: dict[str, Any], expect_error: str):
        with pytest.raises(pydantic.ValidationError, match=expect_error):
            Dependency.parse_obj(input_data)


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
            Dependency(type="go-package", name="bytes", version=None),
            Dependency(type="go-package", name="fmt", version=None),
            Dependency(type="go-package", name="github.com/org/B", version="v1.0.0"),
            Dependency(type="gomod", name="github.com/org/A", version="v1.0.0"),
            Dependency(type="gomod", name="github.com/org/A", version="v1.1.0"),
            Dependency(type="gomod", name="github.com/org/B", version="v1.0.0"),
        ]


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
            )

    def test_sort_and_dedupe_env_vars(self):
        output = RequestOutput(
            packages=[],
            environment_variables=[
                {"name": "B", "value": "y", "kind": "literal"},
                {"name": "A", "value": "x", "kind": "literal"},
                {"name": "B", "value": "y", "kind": "literal"},
            ],
        )
        assert output.environment_variables == [
            EnvironmentVariable(name="A", value="x", kind="literal"),
            EnvironmentVariable(name="B", value="y", kind="literal"),
        ]
