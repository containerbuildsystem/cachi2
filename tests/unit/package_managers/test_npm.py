import json
from typing import Any, Union
from unittest import mock

import pytest

from cachi2.core.errors import PackageRejected, UnsupportedFeature
from cachi2.core.models.input import Request
from cachi2.core.models.output import Component, ProjectFile, RequestOutput
from cachi2.core.package_managers.npm import Package, PackageLock, _resolve_npm, fetch_npm_source
from cachi2.core.rooted_path import RootedPath


@pytest.fixture
def npm_request(rooted_tmp_path: RootedPath, npm_input_packages: list[dict[str, str]]) -> Request:
    # Create folder in the specified path, otherwise Request validation would fail
    for package in npm_input_packages:
        if "path" in package:
            (rooted_tmp_path.path / package["path"]).mkdir(exist_ok=True)

    return Request(
        source_dir=rooted_tmp_path,
        output_dir=rooted_tmp_path.join_within_root("output"),
        packages=npm_input_packages,
    )


class TestPackage:
    @pytest.mark.parametrize(
        "package, expected_resolved_url",
        [
            pytest.param(
                Package(
                    "foo",
                    "",
                    {
                        "version": "1.0.0",
                        "resolved": "https://some.registry.org/foo/-/foo-1.0.0.tgz",
                    },
                ),
                "https://some.registry.org/foo/-/foo-1.0.0.tgz",
                id="registry_dependency",
            ),
            pytest.param(
                Package(
                    "foo",
                    "",
                    {
                        "version": "https://foohub.org/foo/-/foo-1.0.0.tgz",
                    },
                ),
                "https://foohub.org/foo/-/foo-1.0.0.tgz",
                id="non_registry_dependency",
            ),
            pytest.param(
                Package(
                    "foo",
                    "node_modules/foo",
                    {
                        "version": "1.0.0",
                        "resolved": "https://some.registry.org/foo/-/foo-1.0.0.tgz",
                    },
                ),
                "https://some.registry.org/foo/-/foo-1.0.0.tgz",
                id="package",
            ),
            pytest.param(
                Package(
                    "foo",
                    "foo",
                    {
                        "version": "1.0.0",
                    },
                ),
                "file:foo",
                id="workspace_package",
            ),
        ],
    )
    def test_get_resolved_url(self, package: Package, expected_resolved_url: str) -> None:
        assert package.resolved_url == expected_resolved_url

    @pytest.mark.parametrize(
        "package, expected_version, expected_resolved_url",
        [
            pytest.param(
                Package(
                    "foo",
                    "",
                    {
                        "version": "1.0.0",
                        "resolved": "https://some.registry.org/foo/-/foo-1.0.0.tgz",
                    },
                ),
                "1.0.0",
                "file:///foo-1.0.0.tgz",
                id="registry_dependency",
            ),
            pytest.param(
                Package(
                    "foo",
                    "",
                    {
                        "version": "https://foohub.org/foo/-/foo-1.0.0.tgz",
                    },
                ),
                "file:///foo-1.0.0.tgz",
                "file:///foo-1.0.0.tgz",
                id="non_registry_dependency",
            ),
            pytest.param(
                Package(
                    "foo",
                    "node_modules/foo",
                    {
                        "version": "1.0.0",
                        "resolved": "https://some.registry.org/foo/-/foo-1.0.0.tgz",
                    },
                ),
                "1.0.0",
                "file:///foo-1.0.0.tgz",
                id="package",
            ),
        ],
    )
    def test_set_resolved_url(
        self, package: Package, expected_version: str, expected_resolved_url: str
    ) -> None:
        package.resolved_url = "file:///foo-1.0.0.tgz"
        assert package.version == expected_version
        assert package.resolved_url == expected_resolved_url

    def test_eq(self):
        assert Package("foo", "", {}) == Package("foo", "", {})
        assert Package("foo", "", {}) != Package("bar", "", {})
        assert 1 != Package("foo", "", {})


class TestPackageLock:
    @pytest.mark.parametrize(
        "lockfile_data, expected_packages",
        [
            pytest.param(
                {},
                [],
                id="no_deps",
            ),
            pytest.param(
                {"dependencies": {"foo": {"version": "1.0.0"}}},
                [Package("foo", "", {"version": "1.0.0"})],
                id="single_level_deps",
            ),
            pytest.param(
                {
                    "dependencies": {
                        "foo": {"version": "1.0.0", "dependencies": {"bar": {"version": "2.0.0"}}}
                    }
                },
                [
                    Package(
                        "foo",
                        "",
                        {"version": "1.0.0", "dependencies": {"bar": {"version": "2.0.0"}}},
                    ),
                    Package("bar", "", {"version": "2.0.0"}),
                ],
                id="nested_deps",
            ),
        ],
    )
    def test_get_dependencies(
        self,
        rooted_tmp_path: RootedPath,
        lockfile_data: dict[str, Any],
        expected_packages: list[Package],
    ) -> None:
        package_lock = PackageLock(rooted_tmp_path, lockfile_data)
        assert package_lock._dependencies == expected_packages

    @pytest.mark.parametrize(
        "lockfile_data, expected_packages",
        [
            pytest.param(
                {},
                [],
                id="no_packages",
            ),
            pytest.param(
                {
                    "packages": {
                        "": {"version": "1.0.0"},
                        "node_modules/foo": {"version": "1.0.0"},
                        "node_modules/bar": {"version": "2.0.0"},
                    }
                },
                [
                    Package("foo", "node_modules/foo", {"version": "1.0.0"}),
                    Package("bar", "node_modules/bar", {"version": "2.0.0"}),
                ],
                id="normal_packages",
            ),
            pytest.param(
                {
                    "packages": {
                        "": {"version": "1.0.0"},
                        "foo": {"version": "1.0.0"},
                        "node_modules/foo": {"link": True},
                    }
                },
                [
                    Package("foo", "foo", {"version": "1.0.0"}),
                ],
                id="workspace_link",
            ),
            pytest.param(
                {
                    "packages": {
                        "": {"version": "1.0.0"},
                        "foo": {"name": "not-foo", "version": "1.0.0"},
                        "node_modules/not-foo": {"link": True},
                    }
                },
                [
                    Package("not-foo", "foo", {"name": "not-foo", "version": "1.0.0"}),
                ],
                id="workspace_different_name",
            ),
            pytest.param(
                {
                    "packages": {
                        "": {"version": "1.0.0"},
                        "node_modules/@foo/bar": {"version": "1.0.0"},
                    }
                },
                [
                    Package("@foo/bar", "node_modules/@foo/bar", {"version": "1.0.0"}),
                ],
                id="group_package",
            ),
        ],
    )
    def test_get_packages(
        self,
        rooted_tmp_path: RootedPath,
        lockfile_data: dict[str, Any],
        expected_packages: list[Package],
    ) -> None:
        package_lock = PackageLock(rooted_tmp_path, lockfile_data)
        assert package_lock._packages == expected_packages

    @pytest.mark.parametrize(
        "lockfile_version, expected_components",
        [
            (
                1,
                [
                    {"name": "bar", "version": "2.0.0"},
                ],
            ),
            (
                2,
                [
                    {"name": "foo", "version": "1.0.0"},
                ],
            ),
        ],
    )
    def test_get_sbom_components(
        self, lockfile_version: int, expected_components: list[dict[str, str]]
    ) -> None:
        mock_package_lock = mock.Mock()
        mock_package_lock.get_sbom_components = PackageLock.get_sbom_components
        mock_package_lock.lockfile_version = lockfile_version
        mock_package_lock._packages = [
            Package("foo", "node_modules/foo", {"version": "1.0.0"}),
        ]
        mock_package_lock._dependencies = [
            Package("bar", "", {"version": "2.0.0"}),
        ]

        components = mock_package_lock.get_sbom_components(mock_package_lock)
        assert components == expected_components


@pytest.mark.parametrize(
    "npm_input_packages, resolved_packages, request_output",
    [
        pytest.param(
            [{"type": "npm", "path": "."}],
            [
                {
                    "package": {"name": "foo", "version": "1.0.0"},
                    "dependencies": [{"name": "bar", "version": "2.0.0"}],
                    "package_lock_file": ProjectFile(abspath="/some/path", template="some text"),
                },
            ],
            {
                "components": [
                    Component(name="foo", version="1.0.0"),
                    Component(name="bar", version="2.0.0"),
                ],
                "environment_variables": [],
                "project_files": [
                    ProjectFile(abspath="/some/path", template="some text"),
                ],
            },
            id="single_input_package",
        ),
        pytest.param(
            [{"type": "npm", "path": "."}, {"type": "npm", "path": "path"}],
            [
                {
                    "package": {"name": "foo", "version": "1.0.0"},
                    "dependencies": [{"name": "bar", "version": "2.0.0"}],
                    "package_lock_file": ProjectFile(abspath="/some/path", template="some text"),
                },
                {
                    "package": {"name": "spam", "version": "3.0.0"},
                    "dependencies": [{"name": "eggs", "version": "4.0.0"}],
                    "package_lock_file": ProjectFile(
                        abspath="/some/other/path", template="some other text"
                    ),
                },
            ],
            {
                "components": [
                    Component(name="foo", version="1.0.0"),
                    Component(name="bar", version="2.0.0"),
                    Component(name="spam", version="3.0.0"),
                    Component(name="eggs", version="4.0.0"),
                ],
                "environment_variables": [],
                "project_files": [
                    ProjectFile(abspath="/some/path", template="some text"),
                    ProjectFile(abspath="/some/other/path", template="some other text"),
                ],
            },
            id="multiple_input_package",
        ),
    ],
)
@mock.patch("cachi2.core.package_managers.npm._resolve_npm")
def test_fetch_npm_source(
    mock_resolve_npm: mock.Mock,
    npm_request: Request,
    npm_input_packages: dict[str, str],
    resolved_packages: dict[str, Any],
    request_output: dict[str, list[Any]],
) -> None:
    """Test fetch_npm_source with different Request inputs."""
    mock_resolve_npm.side_effect = resolved_packages
    output = fetch_npm_source(npm_request)
    expected_output = RequestOutput.from_obj_list(
        components=request_output["components"],
        environment_variables=request_output["environment_variables"],
        project_files=request_output["project_files"],
    )

    assert output == expected_output


@mock.patch("pathlib.Path.exists")
def test_resolve_npm_no_lock(
    mock_exists: mock.Mock,
    rooted_tmp_path: RootedPath,
) -> None:
    """Test resolve_npm where npm-shrinkwrap.json or package-lock.json do not exist."""
    mock_exists.return_value = False
    expected_error = (
        "The npm-shrinkwrap.json or package-lock.json file must be present for the npm "
        "package manager"
    )
    with pytest.raises(PackageRejected, match=expected_error):
        _resolve_npm(rooted_tmp_path)


@pytest.mark.parametrize(
    "package_lock_json, expected_output",
    [
        pytest.param(
            {
                "name": "foo",
                "version": "1.0.0",
                "lockfileVersion": 1,
                "dependencies": {
                    "bar": {
                        "version": "2.0.0",
                        "resolved": "https://some.registry.org/bar/-/bar-2.0.0.tgz",
                    },
                },
            },
            {
                "package": {"name": "foo", "version": "1.0.0"},
                "dependencies": [{"name": "bar", "version": "2.0.0"}],
            },
            id="npm_v1_lockfile",
        ),
        pytest.param(
            {
                "name": "foo",
                "version": "1.0.0",
                "lockfileVersion": 1,
                "dependencies": {
                    "bar": {
                        "version": "2.0.0",
                        "resolved": "https://some.registry.org/bar/-/bar-2.0.0.tgz",
                        "dependencies": {
                            "baz": {
                                "version": "3.0.0",
                                "resolved": "https://some.registry.org/baz/-/baz-3.0.0.tgz",
                            },
                        },
                    },
                },
            },
            {
                "package": {"name": "foo", "version": "1.0.0"},
                "dependencies": [
                    {"name": "bar", "version": "2.0.0"},
                    {"name": "baz", "version": "3.0.0"},
                ],
            },
            id="npm_v1_lockfile_nested_deps",
        ),
        pytest.param(
            {
                "name": "foo",
                "version": "1.0.0",
                "lockfileVersion": 1,
                "dependencies": {
                    "bar": {
                        "version": "https://foohub.org/bar/-/bar-2.0.0.tgz",
                    },
                    "baz": {
                        "version": "file:baz",
                    },
                },
            },
            {
                "package": {"name": "foo", "version": "1.0.0"},
                "dependencies": [
                    {"name": "bar", "version": "https://foohub.org/bar/-/bar-2.0.0.tgz"},
                    {"name": "baz", "version": "file:baz"},
                ],
            },
            id="npm_v1_lockfile_non_registry_deps",
        ),
        pytest.param(
            {
                "name": "foo",
                "version": "1.0.0",
                "lockfileVersion": 2,
                "packages": {
                    "": {
                        "name": "foo",
                        "version": "1.0.0",
                        "dependencies": {"bar": "^2.0.0"},
                    },
                    "node_modules/bar": {
                        "version": "2.0.0",
                        "resolved": "https://some.registry.org/bar/-/bar-2.0.0.tgz",
                    },
                },
                "dependencies": {
                    "bar": {
                        "version": "2.0.0",
                        "resolved": "https://some.registry.org/bar/-/bar-2.0.0.tgz",
                    },
                },
            },
            {
                "package": {"name": "foo", "version": "1.0.0"},
                "dependencies": [{"name": "bar", "version": "2.0.0"}],
            },
            id="npm_v2_lockfile",
        ),
        pytest.param(
            {
                "name": "foo",
                "version": "1.0.0",
                "lockfileVersion": 2,
                "packages": {
                    "": {
                        "name": "foo",
                        "version": "1.0.0",
                        "dependencies": {"bar": "^2.0.0"},
                    },
                    "node_modules/bar": {
                        "version": "2.0.0",
                        "resolved": "https://some.registry.org/bar/-/bar-2.0.0.tgz",
                    },
                    "node_modules/bar/node_modules/baz": {
                        "version": "3.0.0",
                        "resolved": "https://some.registry.org/baz/-/baz-3.0.0.tgz",
                    },
                },
                "dependencies": {
                    "bar": {
                        "version": "2.0.0",
                        "resolved": "https://some.registry.org/bar/-/bar-2.0.0.tgz",
                        "dependencies": {
                            "baz": {
                                "version": "3.0.0",
                                "resolved": "https://some.registry.org/baz/-/baz-3.0.0.tgz",
                            },
                        },
                    },
                },
            },
            {
                "package": {"name": "foo", "version": "1.0.0"},
                "dependencies": [
                    {"name": "bar", "version": "2.0.0"},
                    {"name": "baz", "version": "3.0.0"},
                ],
            },
            id="npm_v2_lockfile_nested_deps",
        ),
        pytest.param(
            {
                "name": "foo",
                "version": "1.0.0",
                "lockfileVersion": 2,
                "packages": {
                    "": {
                        "name": "foo",
                        "version": "1.0.0",
                        "workspaces": ["bar"],
                    },
                    "bar": {
                        "name": "not-bar",
                        "version": "2.0.0",
                    },
                    "node_modules/not-bar": {"resolved": "bar", "link": True},
                },
                "dependencies": {
                    "not-bar": {
                        "version": "file:bar",
                    },
                },
            },
            {
                "package": {"name": "foo", "version": "1.0.0"},
                "dependencies": [{"name": "not-bar", "version": "2.0.0"}],
            },
            id="npm_v2_lockfile_workspace",
        ),
        pytest.param(
            {
                "name": "foo",
                "version": "1.0.0",
                "lockfileVersion": 2,
                "packages": {
                    "": {
                        "name": "foo",
                        "version": "1.0.0",
                        "dependencies": {"@bar/baz": "^2.0.0"},
                    },
                    "node_modules/@bar/baz": {
                        "version": "2.0.0",
                        "resolved": "https://some.registry.org/@bar/baz/-/baz-2.0.0.tgz",
                    },
                },
                "dependencies": {
                    "@bar/baz": {
                        "version": "2.0.0",
                        "resolved": "https://some.registry.org/@bar/baz/-/baz-2.0.0.tgz",
                    },
                },
            },
            {
                "package": {"name": "foo", "version": "1.0.0"},
                "dependencies": [{"name": "@bar/baz", "version": "2.0.0"}],
            },
            id="npm_v2_lockfile_grouped_deps",
        ),
        pytest.param(
            {
                "name": "foo",
                "version": "1.0.0",
                "lockfileVersion": 3,
                "packages": {
                    "": {
                        "name": "foo",
                        "version": "1.0.0",
                        "dependencies": {"bar": "^2.0.0"},
                    },
                    "node_modules/bar": {
                        "version": "2.0.0",
                        "resolved": "https://some.registry.org/bar/-/bar-2.0.0.tgz",
                    },
                },
            },
            {
                "package": {"name": "foo", "version": "1.0.0"},
                "dependencies": [{"name": "bar", "version": "2.0.0"}],
            },
            id="npm_v3_lockfile",
        ),
    ],
)
def test_resolve_npm(
    rooted_tmp_path: RootedPath,
    package_lock_json: dict[str, Union[str, dict]],
    expected_output: dict[str, Any],
) -> None:
    """Test _resolve_npm with different package-lock.json inputs."""
    lockfile_path = rooted_tmp_path.path / "package-lock.json"
    with lockfile_path.open("w") as f:
        json.dump(package_lock_json, f)

    pkg_info = _resolve_npm(rooted_tmp_path)
    expected_output["package_lock_file"] = ProjectFile(
        abspath=lockfile_path.resolve(), template=json.dumps(package_lock_json, indent=2) + "\n"
    )
    assert pkg_info == expected_output


def test_resolve_npm_unsupported_lockfileversion(rooted_tmp_path: RootedPath) -> None:
    """Test _resolve_npm with unsupported lockfileVersion."""
    package_lock_json = {
        "name": "foo",
        "version": "1.0.0",
        "lockfileVersion": 4,
    }
    lockfile_path = rooted_tmp_path.path / "package-lock.json"
    with lockfile_path.open("w") as f:
        json.dump(package_lock_json, f)

    expected_error = f"lockfileVersion {package_lock_json['lockfileVersion']} from {lockfile_path} is not supported"
    with pytest.raises(UnsupportedFeature, match=expected_error):
        _resolve_npm(rooted_tmp_path)
