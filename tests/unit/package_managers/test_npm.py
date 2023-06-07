import json
import urllib.parse
from typing import Any, Dict, Iterator, List, Optional, Union
from unittest import mock

import pytest
from packageurl import PackageURL

from cachi2.core.checksum import ChecksumInfo
from cachi2.core.errors import PackageRejected, UnexpectedFormat, UnsupportedFeature
from cachi2.core.models.input import Request
from cachi2.core.models.output import Component, ProjectFile, RequestOutput
from cachi2.core.package_managers.npm import (
    Package,
    PackageLock,
    _clone_repo_pack_archive,
    _extract_git_info_npm,
    _get_npm_dependencies,
    _Purlifier,
    _resolve_npm,
    _update_vcs_url_with_full_hostname,
    fetch_npm_source,
)
from cachi2.core.rooted_path import RootedPath
from cachi2.core.scm import RepoID

MOCK_REPO_ID = RepoID("https://github.com/foolish/bar.git", "abcdef1234")
MOCK_REPO_VCS_URL = "git%2Bhttps://github.com/foolish/bar.git%40abcdef1234"


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


@pytest.fixture
def mock_get_repo_id() -> Iterator[mock.Mock]:
    with mock.patch("cachi2.core.package_managers.npm.get_repo_id") as mocked_get_repo_id:
        mocked_get_repo_id.return_value = MOCK_REPO_ID
        yield mocked_get_repo_id


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

    def test_eq(self) -> None:
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

    @pytest.mark.parametrize("lockfile_version", [1, 2])
    def test_get_sbom_components(self, lockfile_version: int) -> None:
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
        names = {component["name"] for component in components}
        if lockfile_version == 1:
            assert names == {"bar"}
        else:
            assert names == {"foo"}


def urlq(url: str) -> str:
    return urllib.parse.quote(url, safe=":/")


class TestPurlifier:
    @pytest.mark.parametrize(
        "pkg_data, expect_purl",
        [
            (
                ("registry-dep", "1.0.0", "https://registry.npmjs.org/registry-dep-1.0.0.tgz"),
                "pkg:npm/registry-dep@1.0.0",
            ),
            (
                (
                    "@scoped/registry-dep",
                    "2.0.0",
                    "https://registry.npmjs.org/registry-dep-2.0.0.tgz",
                ),
                "pkg:npm/%40scoped/registry-dep@2.0.0",
            ),
            (
                (
                    "sus-registry-dep",
                    "1.0.0",
                    "https://registry.yarnpkg.com/sus-registry-dep-1.0.0.tgz",
                ),
                "pkg:npm/sus-registry-dep@1.0.0",
            ),
            (
                ("https-dep", None, "https://host.org/https-dep-1.0.0.tar.gz"),
                "pkg:npm/https-dep?download_url=https://host.org/https-dep-1.0.0.tar.gz",
            ),
            (
                ("https-dep", "1.0.0", "https://host.org/https-dep-1.0.0.tar.gz"),
                "pkg:npm/https-dep@1.0.0?download_url=https://host.org/https-dep-1.0.0.tar.gz",
            ),
            (
                ("http-dep", None, "http://host.org/http-dep-1.0.0.tar.gz"),
                "pkg:npm/http-dep?download_url=http://host.org/http-dep-1.0.0.tar.gz",
            ),
            (
                ("http-dep", "1.0.0", "http://host.org/http-dep-1.0.0.tar.gz"),
                "pkg:npm/http-dep@1.0.0?download_url=http://host.org/http-dep-1.0.0.tar.gz",
            ),
            (
                ("git-dep", None, "git://github.com/org/git-dep.git#deadbeef"),
                f"pkg:npm/git-dep?vcs_url={urlq('git+git://github.com/org/git-dep.git@deadbeef')}",
            ),
            (
                ("git-dep", "1.0.0", "git://github.com/org/git-dep.git#deadbeef"),
                f"pkg:npm/git-dep@1.0.0?vcs_url={urlq('git+git://github.com/org/git-dep.git@deadbeef')}",
            ),
            (
                ("gitplus-dep", None, "git+https://github.com/org/git-dep.git#deadbeef"),
                f"pkg:npm/gitplus-dep?vcs_url={urlq('git+https://github.com/org/git-dep.git@deadbeef')}",
            ),
            (
                ("github-dep", None, "github:org/git-dep#deadbeef"),
                f"pkg:npm/github-dep?vcs_url={urlq('git+ssh://git@github.com/org/git-dep.git@deadbeef')}",
            ),
            (
                ("gitlab-dep", None, "gitlab:org/git-dep#deadbeef"),
                f"pkg:npm/gitlab-dep?vcs_url={urlq('git+ssh://git@gitlab.com/org/git-dep.git@deadbeef')}",
            ),
            (
                ("bitbucket-dep", None, "bitbucket:org/git-dep#deadbeef"),
                f"pkg:npm/bitbucket-dep?vcs_url={urlq('git+ssh://git@bitbucket.org/org/git-dep.git@deadbeef')}",
            ),
        ],
    )
    def test_get_purl_for_remote_package(
        self,
        pkg_data: tuple[str, Optional[str], str],
        expect_purl: str,
        rooted_tmp_path: RootedPath,
    ) -> None:
        purl = _Purlifier(rooted_tmp_path).get_purl(*pkg_data, integrity=None)
        assert purl.to_string() == expect_purl

    @pytest.mark.parametrize(
        "main_pkg_subpath, pkg_data, expect_purl",
        [
            (
                ".",
                ("main-pkg", None, "file:."),
                f"pkg:npm/main-pkg?vcs_url={MOCK_REPO_VCS_URL}",
            ),
            (
                "subpath",
                ("main-pkg", None, "file:."),
                f"pkg:npm/main-pkg?vcs_url={MOCK_REPO_VCS_URL}#subpath",
            ),
            (
                ".",
                ("main-pkg", "1.0.0", "file:."),
                f"pkg:npm/main-pkg@1.0.0?vcs_url={MOCK_REPO_VCS_URL}",
            ),
            (
                "subpath",
                ("main-pkg", "2.0.0", "file:."),
                f"pkg:npm/main-pkg@2.0.0?vcs_url={MOCK_REPO_VCS_URL}#subpath",
            ),
            (
                ".",
                ("file-dep", "1.0.0", "file:packages/foo"),
                f"pkg:npm/file-dep@1.0.0?vcs_url={MOCK_REPO_VCS_URL}#packages/foo",
            ),
            (
                "subpath",
                ("file-dep", "1.0.0", "file:packages/foo"),
                f"pkg:npm/file-dep@1.0.0?vcs_url={MOCK_REPO_VCS_URL}#subpath/packages/foo",
            ),
            (
                "subpath",
                ("parent-is-file-dep", "1.0.0", "file:.."),
                f"pkg:npm/parent-is-file-dep@1.0.0?vcs_url={MOCK_REPO_VCS_URL}",
            ),
            (
                "subpath",
                ("nephew-is-file-dep", "1.0.0", "file:../packages/foo"),
                f"pkg:npm/nephew-is-file-dep@1.0.0?vcs_url={MOCK_REPO_VCS_URL}#packages/foo",
            ),
        ],
    )
    def test_get_purl_for_local_package(
        self,
        main_pkg_subpath: str,
        pkg_data: tuple[str, Optional[str], str],
        expect_purl: PackageURL,
        rooted_tmp_path: RootedPath,
        mock_get_repo_id: mock.Mock,
    ) -> None:
        pkg_path = rooted_tmp_path.join_within_root(main_pkg_subpath)
        purl = _Purlifier(pkg_path).get_purl(*pkg_data, integrity=None)
        assert purl.to_string() == expect_purl
        mock_get_repo_id.assert_called_once_with(rooted_tmp_path.root)

    @pytest.mark.parametrize(
        "resolved_url, integrity, expect_checksum_qualifier",
        [
            # integrity ignored for registry deps
            ("https://registry.npmjs.org/registry-dep-1.0.0.tgz", "sha512-3q2+7w==", None),
            # as well as git deps, if they somehow have it
            ("git+https://github.com/foo/bar.git#deeadbeef", "sha512-3q2+7w==", None),
            # and file deps
            ("file:foo.tar.gz", "sha512-3q2+7w==", None),
            # checksum qualifier added for http(s) deps
            ("https://foohub.com/foo.tar.gz", "sha512-3q2+7w==", "sha512:deadbeef"),
            # unless integrity is missing
            ("https://foohub.com/foo.tar.gz", None, None),
        ],
    )
    def test_get_purl_integrity_handling(
        self,
        resolved_url: str,
        integrity: Optional[str],
        expect_checksum_qualifier: Optional[str],
        mock_get_repo_id: mock.Mock,
    ) -> None:
        purl = _Purlifier(RootedPath("/foo")).get_purl("foo", None, resolved_url, integrity)
        assert isinstance(purl.qualifiers, dict)
        assert purl.qualifiers.get("checksum") == expect_checksum_qualifier

    def test_get_purl_unsupported_scheme(self) -> None:
        with pytest.raises(
            UnsupportedFeature,
            match="Cannot generate purl for npm dependency resolved from codeberg:foo/bar#deadbeef",
        ):
            _Purlifier(RootedPath("/foo")).get_purl("foo", None, "codeberg:foo/bar#deadbeef", None)


@pytest.mark.parametrize(
    "npm_input_packages, resolved_packages, request_output",
    [
        pytest.param(
            [{"type": "npm", "path": "."}],
            [
                {
                    "package": {"name": "foo", "version": "1.0.0", "purl": "pkg:npm/foo@1.0.0"},
                    "dependencies": [
                        {"name": "bar", "version": "2.0.0", "purl": "pkg:npm/bar@2.0.0"}
                    ],
                    "dependencies_to_download": {
                        "https://some.registry.org/bar/-/bar-2.0.0.tgz": {
                            "integrity": "sha512-JCB8C6SnDoQf",
                            "name": "bar",
                            "version": "2.0.0",
                        }
                    },
                    "package_lock_file": ProjectFile(abspath="/some/path", template="some text"),
                },
            ],
            {
                "components": [
                    Component(name="foo", version="1.0.0", purl="pkg:npm/foo@1.0.0"),
                    Component(name="bar", version="2.0.0", purl="pkg:npm/bar@2.0.0"),
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
                    "package": {"name": "foo", "version": "1.0.0", "purl": "pkg:npm/foo@1.0.0"},
                    "dependencies": [
                        {"name": "bar", "version": "2.0.0", "purl": "pkg:npm/bar@2.0.0"}
                    ],
                    "dependencies_to_download": {
                        "https://some.registry.org/bar/-/bar-2.0.0.tgz": {
                            "integrity": "sha512-JCB8C6SnDoQf",
                            "name": "bar",
                            "version": "2.0.0",
                        }
                    },
                    "package_lock_file": ProjectFile(abspath="/some/path", template="some text"),
                },
                {
                    "package": {"name": "spam", "version": "3.0.0", "purl": "pkg:npm/spam@3.0.0"},
                    "dependencies": [
                        {"name": "eggs", "version": "4.0.0", "purl": "pkg:npm/eggs@4.0.0"}
                    ],
                    "dependencies_to_download": {
                        "https://some.registry.org/eggs/-/eggs-1.0.0.tgz": {
                            "integrity": "sha512-JCB8C6SnDoQfYOLOO",
                            "name": "eggs",
                            "version": "1.0.0",
                        }
                    },
                    "package_lock_file": ProjectFile(
                        abspath="/some/other/path", template="some other text"
                    ),
                },
            ],
            {
                "components": [
                    Component(name="foo", version="1.0.0", purl="pkg:npm/foo@1.0.0"),
                    Component(name="bar", version="2.0.0", purl="pkg:npm/bar@2.0.0"),
                    Component(name="spam", version="3.0.0", purl="pkg:npm/spam@3.0.0"),
                    Component(name="eggs", version="4.0.0", purl="pkg:npm/eggs@4.0.0"),
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
@mock.patch("cachi2.core.package_managers.npm._get_npm_dependencies")
def test_fetch_npm_source(
    mock_get_npm_dependencies: mock.Mock,
    mock_resolve_npm: mock.Mock,
    npm_request: Request,
    npm_input_packages: dict[str, str],
    resolved_packages: List[dict[str, Any]],
    request_output: dict[str, list[Any]],
) -> None:
    """Test fetch_npm_source with different Request inputs."""
    mock_resolve_npm.side_effect = resolved_packages
    output = fetch_npm_source(npm_request)
    calls = []
    for r in resolved_packages:
        calls.append(
            mock.call(
                npm_request.output_dir.join_within_root("deps", "npm"),
                r["dependencies_to_download"],
            )
        )
    mock_get_npm_dependencies.assert_has_calls(calls)
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
    "main_pkg_subpath, package_lock_json, expected_output",
    [
        pytest.param(
            ".",
            {
                "name": "foo",
                "version": "1.0.0",
                "lockfileVersion": 1,
                "dependencies": {
                    "bar": {
                        "version": "2.0.0",
                        "resolved": "https://registry.npmjs.org/bar/-/bar-2.0.0.tgz",
                        "integrity": "sha512-JCB8C6SnDoQf",
                    },
                },
            },
            {
                "package": {
                    "name": "foo",
                    "version": "1.0.0",
                    "purl": f"pkg:npm/foo@1.0.0?vcs_url={MOCK_REPO_VCS_URL}",
                },
                "dependencies": [
                    {
                        "name": "bar",
                        "version": "2.0.0",
                        "purl": "pkg:npm/bar@2.0.0",
                    }
                ],
                "dependencies_to_download": {
                    "https://registry.npmjs.org/bar/-/bar-2.0.0.tgz": {
                        "integrity": "sha512-JCB8C6SnDoQf",
                        "name": "bar",
                        "version": "2.0.0",
                    },
                },
            },
            id="npm_v1_lockfile",
        ),
        pytest.param(
            ".",
            {
                "name": "foo",
                "version": "1.0.0",
                "lockfileVersion": 1,
                "dependencies": {
                    "bar": {
                        "version": "2.0.0",
                        "resolved": "https://registry.npmjs.org/bar/-/bar-2.0.0.tgz",
                        "integrity": "sha512-JCB8C6SnDoQf",
                        "dependencies": {
                            "bar": {
                                "version": "3.0.0",
                                "resolved": "https://registry.npmjs.org/bar/-/bar-3.0.0.tgz",
                                "integrity": "sha512-YOLOYOLO",
                            },
                        },
                    },
                },
            },
            {
                "package": {
                    "name": "foo",
                    "version": "1.0.0",
                    "purl": f"pkg:npm/foo@1.0.0?vcs_url={MOCK_REPO_VCS_URL}",
                },
                "dependencies": [
                    {
                        "name": "bar",
                        "version": "2.0.0",
                        "purl": "pkg:npm/bar@2.0.0",
                    },
                    {
                        "name": "bar",
                        "version": "3.0.0",
                        "purl": "pkg:npm/bar@3.0.0",
                    },
                ],
                "dependencies_to_download": {
                    "https://registry.npmjs.org/bar/-/bar-2.0.0.tgz": {
                        "integrity": "sha512-JCB8C6SnDoQf",
                        "name": "bar",
                        "version": "2.0.0",
                    },
                    "https://registry.npmjs.org/bar/-/bar-3.0.0.tgz": {
                        "integrity": "sha512-YOLOYOLO",
                        "name": "bar",
                        "version": "3.0.0",
                    },
                },
            },
            id="npm_v1_lockfile_nested_deps",
        ),
        pytest.param(
            ".",
            {
                "name": "foo",
                "version": "1.0.0",
                "lockfileVersion": 1,
                "dependencies": {
                    "bar": {
                        "version": "https://foohub.org/bar/-/bar-2.0.0.tgz",
                        "integrity": "sha512-JCB8C6SnDoQf",
                    },
                    "baz": {
                        "version": "file:baz",
                    },
                    "spam": {
                        "version": "git+ssh://git@github.com/spam/spam.git#deadbeef",
                    },
                },
            },
            {
                "package": {
                    "name": "foo",
                    "version": "1.0.0",
                    "purl": f"pkg:npm/foo@1.0.0?vcs_url={MOCK_REPO_VCS_URL}",
                },
                "dependencies": [
                    {
                        "name": "bar",
                        "purl": "pkg:npm/bar?checksum=sha512:24207c0ba4a70e841f&download_url=https://foohub.org/bar/-/bar-2.0.0.tgz",
                    },
                    {
                        "name": "baz",
                        "purl": f"pkg:npm/baz?vcs_url={MOCK_REPO_VCS_URL}#baz",
                    },
                    {
                        "name": "spam",
                        "purl": f"pkg:npm/spam?vcs_url={urlq('git+ssh://git@github.com/spam/spam.git@deadbeef')}",
                    },
                ],
                "dependencies_to_download": {
                    "https://foohub.org/bar/-/bar-2.0.0.tgz": {
                        "integrity": "sha512-JCB8C6SnDoQf",
                        "name": "bar",
                        "version": "https://foohub.org/bar/-/bar-2.0.0.tgz",
                    },
                    "git+ssh://git@github.com/spam/spam.git#deadbeef": {
                        "integrity": None,
                        "name": "spam",
                        "version": "git+ssh://git@github.com/spam/spam.git#deadbeef",
                    },
                },
            },
            id="npm_v1_lockfile_non_registry_deps",
        ),
        pytest.param(
            "subpath",
            {
                "name": "foo",
                "version": "1.0.0",
                "lockfileVersion": 1,
                "dependencies": {
                    "baz": {
                        "version": "file:baz",
                    },
                },
            },
            {
                "package": {
                    "name": "foo",
                    "version": "1.0.0",
                    "purl": f"pkg:npm/foo@1.0.0?vcs_url={MOCK_REPO_VCS_URL}#subpath",
                },
                "dependencies": [
                    {
                        "name": "baz",
                        "purl": f"pkg:npm/baz?vcs_url={MOCK_REPO_VCS_URL}#subpath/baz",
                    },
                ],
                "dependencies_to_download": {},
            },
            id="npm_v1_at_subpath_with_file_dep",
        ),
        pytest.param(
            ".",
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
                        "resolved": "https://registry.npmjs.org/bar/-/bar-2.0.0.tgz",
                        "integrity": "sha512-JCB8C6SnDoQf",
                    },
                },
                "dependencies": {
                    "bar": {
                        "version": "2.0.0",
                        "resolved": "https://registry.npmjs.org/bar/-/bar-2.0.0.tgz",
                        "integrity": "sha512-JCB8C6SnDoQf",
                    },
                },
            },
            {
                "package": {
                    "name": "foo",
                    "version": "1.0.0",
                    "purl": f"pkg:npm/foo@1.0.0?vcs_url={MOCK_REPO_VCS_URL}",
                },
                "dependencies": [
                    {
                        "name": "bar",
                        "version": "2.0.0",
                        "purl": "pkg:npm/bar@2.0.0",
                    }
                ],
                "dependencies_to_download": {
                    "https://registry.npmjs.org/bar/-/bar-2.0.0.tgz": {
                        "integrity": "sha512-JCB8C6SnDoQf",
                        "name": "bar",
                        "version": "2.0.0",
                    },
                },
            },
            id="npm_v2_lockfile",
        ),
        pytest.param(
            ".",
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
                        "resolved": "https://registry.npmjs.org/bar/-/bar-2.0.0.tgz",
                        "integrity": "sha512-JCB8C6SnDoQf",
                    },
                    "node_modules/bar/node_modules/baz": {
                        "version": "3.0.0",
                        "resolved": "https://registry.npmjs.org/baz/-/baz-3.0.0.tgz",
                        "integrity": "sha512-YOLOYOLO",
                    },
                },
                "dependencies": {
                    "bar": {
                        "version": "2.0.0",
                        "resolved": "https://registry.npmjs.org/bar/-/bar-2.0.0.tgz",
                        "integrity": "sha512-JCB8C6SnDoQf",
                        "dependencies": {
                            "baz": {
                                "version": "3.0.0",
                                "resolved": "https://registry.npmjs.org/baz/-/baz-3.0.0.tgz",
                            },
                        },
                    },
                },
            },
            {
                "package": {
                    "name": "foo",
                    "version": "1.0.0",
                    "purl": f"pkg:npm/foo@1.0.0?vcs_url={MOCK_REPO_VCS_URL}",
                },
                "dependencies": [
                    {
                        "name": "bar",
                        "version": "2.0.0",
                        "purl": "pkg:npm/bar@2.0.0",
                    },
                    {
                        "name": "baz",
                        "version": "3.0.0",
                        "purl": "pkg:npm/baz@3.0.0",
                    },
                ],
                "dependencies_to_download": {
                    "https://registry.npmjs.org/bar/-/bar-2.0.0.tgz": {
                        "integrity": "sha512-JCB8C6SnDoQf",
                        "name": "bar",
                        "version": "2.0.0",
                    },
                    "https://registry.npmjs.org/baz/-/baz-3.0.0.tgz": {
                        "integrity": "sha512-YOLOYOLO",
                        "name": "baz",
                        "version": "3.0.0",
                    },
                },
            },
            id="npm_v2_lockfile_nested_deps",
        ),
        pytest.param(
            ".",
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
                "package": {
                    "name": "foo",
                    "version": "1.0.0",
                    "purl": f"pkg:npm/foo@1.0.0?vcs_url={MOCK_REPO_VCS_URL}",
                },
                "dependencies": [
                    {
                        "name": "not-bar",
                        "version": "2.0.0",
                        "purl": f"pkg:npm/not-bar@2.0.0?vcs_url={MOCK_REPO_VCS_URL}#bar",
                    }
                ],
                "dependencies_to_download": {},
            },
            id="npm_v2_lockfile_workspace",
        ),
        pytest.param(
            "subpath",
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
                "package": {
                    "name": "foo",
                    "version": "1.0.0",
                    "purl": f"pkg:npm/foo@1.0.0?vcs_url={MOCK_REPO_VCS_URL}#subpath",
                },
                "dependencies": [
                    {
                        "name": "not-bar",
                        "version": "2.0.0",
                        "purl": f"pkg:npm/not-bar@2.0.0?vcs_url={MOCK_REPO_VCS_URL}#subpath/bar",
                    }
                ],
                "dependencies_to_download": {},
            },
            id="npm_v2_at_subpath_with_workspace",
        ),
        pytest.param(
            ".",
            {
                "name": "foo",
                "version": "1.0.0",
                "lockfileVersion": 2,
                "packages": {
                    "": {
                        "name": "foo",
                        "version": "1.0.0",
                    },
                    "node_modules/bar": {
                        "version": "2.0.0",
                        "resolved": "https://foohub.org/bar/-/bar-2.0.0.tgz",
                        "integrity": "sha512-JCB8C6SnDoQf",
                    },
                    "node_modules/spam": {
                        "version": "3.0.0",
                        "resolved": "git+ssh://git@github.com/spam/spam.git#deadbeef",
                    },
                },
                "dependencies": {
                    "bar": {
                        "version": "https://foohub.org/bar/-/bar-2.0.0.tgz",
                        "integrity": "sha512-JCB8C6SnDoQf",
                    },
                    "spam": {
                        "version": "git+ssh://git@github.com/spam/spam.git#deadbeef",
                    },
                },
            },
            {
                "package": {
                    "name": "foo",
                    "version": "1.0.0",
                    "purl": f"pkg:npm/foo@1.0.0?vcs_url={MOCK_REPO_VCS_URL}",
                },
                "dependencies": [
                    {
                        "name": "bar",
                        "version": "2.0.0",
                        "purl": "pkg:npm/bar@2.0.0?checksum=sha512:24207c0ba4a70e841f&download_url=https://foohub.org/bar/-/bar-2.0.0.tgz",
                    },
                    {
                        "name": "spam",
                        "version": "3.0.0",
                        "purl": f"pkg:npm/spam@3.0.0?vcs_url={urlq('git+ssh://git@github.com/spam/spam.git@deadbeef')}",
                    },
                ],
                "dependencies_to_download": {
                    "https://foohub.org/bar/-/bar-2.0.0.tgz": {
                        "integrity": "sha512-JCB8C6SnDoQf",
                        "name": "bar",
                        "version": "2.0.0",
                    },
                    "git+ssh://git@github.com/spam/spam.git#deadbeef": {
                        "integrity": None,
                        "name": "spam",
                        "version": "3.0.0",
                    },
                },
            },
            id="npm_v2_lockfile_non_registry_deps",
        ),
        pytest.param(
            ".",
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
                        "resolved": "https://registry.npmjs.org/@bar/baz/-/baz-2.0.0.tgz",
                        "integrity": "sha512-JCB8C6SnDoQf",
                    },
                },
                "dependencies": {
                    "@bar/baz": {
                        "version": "2.0.0",
                        "resolved": "https://registry.npmjs.org/@bar/baz/-/baz-2.0.0.tgz",
                        "integrity": "sha512-JCB8C6SnDoQf",
                    },
                },
            },
            {
                "package": {
                    "name": "foo",
                    "version": "1.0.0",
                    "purl": f"pkg:npm/foo@1.0.0?vcs_url={MOCK_REPO_VCS_URL}",
                },
                "dependencies": [
                    {
                        "name": "@bar/baz",
                        "version": "2.0.0",
                        "purl": "pkg:npm/%40bar/baz@2.0.0",
                    }
                ],
                "dependencies_to_download": {
                    "https://registry.npmjs.org/@bar/baz/-/baz-2.0.0.tgz": {
                        "integrity": "sha512-JCB8C6SnDoQf",
                        "name": "@bar/baz",
                        "version": "2.0.0",
                    }
                },
            },
            id="npm_v2_lockfile_grouped_deps",
        ),
        pytest.param(
            ".",
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
                        "resolved": "https://registry.npmjs.org/bar/-/bar-2.0.0.tgz",
                        "integrity": "sha512-JCB8C6SnDoQf",
                    },
                },
            },
            {
                "package": {
                    "name": "foo",
                    "version": "1.0.0",
                    "purl": f"pkg:npm/foo@1.0.0?vcs_url={MOCK_REPO_VCS_URL}",
                },
                "dependencies": [
                    {
                        "name": "bar",
                        "version": "2.0.0",
                        "purl": "pkg:npm/bar@2.0.0",
                    }
                ],
                "dependencies_to_download": {
                    "https://registry.npmjs.org/bar/-/bar-2.0.0.tgz": {
                        "integrity": "sha512-JCB8C6SnDoQf",
                        "name": "bar",
                        "version": "2.0.0",
                    }
                },
            },
            id="npm_v3_lockfile",
        ),
    ],
)
def test_resolve_npm(
    rooted_tmp_path: RootedPath,
    main_pkg_subpath: str,
    package_lock_json: dict[str, Union[str, dict]],
    expected_output: dict[str, Any],
    mock_get_repo_id: mock.Mock,
) -> None:
    """Test _resolve_npm with different package-lock.json inputs."""
    pkg_dir = rooted_tmp_path.join_within_root(main_pkg_subpath)
    pkg_dir.path.mkdir(exist_ok=True)

    lockfile_path = pkg_dir.join_within_root("package-lock.json").path
    with lockfile_path.open("w") as f:
        json.dump(package_lock_json, f)

    pkg_info = _resolve_npm(pkg_dir)
    expected_output["package_lock_file"] = ProjectFile(
        abspath=lockfile_path.resolve(), template=json.dumps(package_lock_json, indent=2) + "\n"
    )
    assert pkg_info == expected_output
    mock_get_repo_id.assert_called_once_with(rooted_tmp_path.root)


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


@pytest.mark.parametrize(
    "vcs, expected",
    [
        (
            (
                "git+ssh://git@bitbucket.org/cachi-testing/cachi2-without-deps.git#9e164b97043a2d91bbeb992f6cc68a3d1015086a"
            ),
            {
                "url": "ssh://git@bitbucket.org/cachi-testing/cachi2-without-deps.git",
                "ref": "9e164b97043a2d91bbeb992f6cc68a3d1015086a",
                "host": "bitbucket.org",
                "namespace": "cachi-testing",
                "repo": "cachi2-without-deps",
            },
        ),
    ],
)
def test_extract_git_info_npm(vcs: str, expected: Dict[str, str]) -> None:
    assert _extract_git_info_npm(vcs) == expected


def test_extract_git_info_with_missing_ref() -> None:
    vcs = "git+ssh://git@bitbucket.org/cachi-testing/cachi2-without-deps.git"
    expected_error = (
        "ssh://git@bitbucket.org/cachi-testing/cachi2-without-deps.git "
        "is not valid VCS url. ref is missing."
    )
    with pytest.raises(UnexpectedFormat, match=expected_error):
        _extract_git_info_npm(vcs)


@pytest.mark.parametrize(
    "vcs, expected",
    [
        (
            "github:kevva/is-positive#97edff6",
            "git+ssh://git@github.com/kevva/is-positive.git#97edff6",
        ),
        ("github:kevva/is-positive", "git+ssh://git@github.com/kevva/is-positive.git"),
        (
            "bitbucket:cachi-testing/cachi2-without-deps#9e164b9",
            "git+ssh://git@bitbucket.org/cachi-testing/cachi2-without-deps.git#9e164b9",
        ),
        ("gitlab:foo/bar#YOLO", "git+ssh://git@gitlab.com/foo/bar.git#YOLO"),
    ],
)
def test_update_vcs_url_with_full_hostname(vcs: str, expected: str) -> None:
    assert _update_vcs_url_with_full_hostname(vcs) == expected


@mock.patch("cachi2.core.package_managers.npm.clone_as_tarball")
def test_clone_repo_pack_archive(
    mock_clone_as_tarball: mock.Mock, rooted_tmp_path: RootedPath
) -> None:
    vcs = "git+ssh://bitbucket.org/cachi-testing/cachi2-without-deps.git#9e164b9"
    download_path = _clone_repo_pack_archive(vcs, rooted_tmp_path)
    expected_path = rooted_tmp_path.join_within_root(
        "bitbucket.org",
        "cachi-testing",
        "cachi2-without-deps",
        "cachi2-without-deps-external-gitcommit-9e164b9.tgz",
    )
    assert download_path.path.parent.is_dir()
    mock_clone_as_tarball.assert_called_once_with(
        "ssh://bitbucket.org/cachi-testing/cachi2-without-deps.git", "9e164b9", expected_path.path
    )


@pytest.mark.parametrize(
    "deps_to_download, expected_download_subpaths",
    [
        (
            {
                "https://github.com/cachito-testing/ms-1.0.0.tgz": {
                    "name": "ms",
                    "version": "1.0.0",
                    "integrity": "sha512-YOLO1111==",
                },
                # Test handling package with the same name but different version and integrity
                "https://github.com/cachito-testing/ms-2.0.0.tgz": {
                    "name": "ms",
                    "version": "2.0.0",
                    "integrity": "sha512-YOLO2222==",
                },
                "https://registry.npmjs.org/@types/react-dom/-/react-dom-18.0.11.tgz": {
                    "name": "@types/react-dom",
                    "version": "18.0.11",
                    "integrity": "sha512-YOLO00000==",
                },
                "https://registry.yarnpkg.com/abbrev/-/abbrev-2.0.0.tgz": {
                    "name": "abbrev",
                    "version": "2.0.0",
                    "integrity": "sha512-YOLO33333==",
                },
                "git+ssh://git@bitbucket.org/cachi-testing/cachi2-without-deps-second.git#09992d418fc44a2895b7a9ff27c4e32d6f74a982": {
                    "version": "2.0.0",
                    "name": "cachi2-without-deps-second",
                },
                # Test short representation of git reference
                "git+ssh://git@github.com/kevva/is-positive.git#97edff6f": {
                    "integrity": "sha512-8ND1j3y9YOLO==",
                    "name": "is-positive",
                },
                # The name of the package is different from the repo name, we expect the result archive to have the repo name in it
                "git+ssh://git@gitlab.foo.bar.com/osbs/cachito-tests.git#c300503": {
                    "integrity": "sha512-FOOOOOOOOOYOLO==",
                    "name": "gitlab-cachi2-npm-without-deps-second",
                },
            },
            {
                "https://github.com/cachito-testing/ms-1.0.0.tgz": "external-ms/ms-external-sha256-YOLO1111.tgz",
                "https://github.com/cachito-testing/ms-2.0.0.tgz": "external-ms/ms-external-sha256-YOLO2222.tgz",
                "git+ssh://git@bitbucket.org/cachi-testing/cachi2-without-deps-second.git#09992d418fc44a2895b7a9ff27c4e32d6f74a982": "bitbucket.org/cachi-testing/cachi2-without-deps-second/cachi2-without-deps-second-external-gitcommit-09992d418fc44a2895b7a9ff27c4e32d6f74a982.tgz",
                "https://registry.npmjs.org/@types/react-dom/-/react-dom-18.0.11.tgz": "types-react-dom-18.0.11.tgz",
                "https://registry.yarnpkg.com/abbrev/-/abbrev-2.0.0.tgz": "abbrev-2.0.0.tgz",
                "git+ssh://git@github.com/kevva/is-positive.git#97edff6f": "github.com/kevva/is-positive/is-positive-external-gitcommit-97edff6f.tgz",
                "git+ssh://git@gitlab.foo.bar.com/osbs/cachito-tests.git#c300503": "gitlab.foo.bar.com/osbs/cachito-tests/cachito-tests-external-gitcommit-c300503.tgz",
            },
        ),
    ],
)
@mock.patch("cachi2.core.package_managers.npm.async_download_files")
@mock.patch("cachi2.core.package_managers.npm.must_match_any_checksum")
@mock.patch("cachi2.core.checksum.ChecksumInfo.from_sri")
@mock.patch("cachi2.core.package_managers.npm.clone_as_tarball")
def test_get_npm_dependencies(
    mock_clone_as_tarball: mock.Mock,
    mock_from_sri: mock.Mock,
    mock_must_match_any_checksum: mock.Mock,
    mock_async_download_files: mock.Mock,
    rooted_tmp_path: RootedPath,
    deps_to_download: Dict[str, Dict[str, str]],
    expected_download_subpaths: Dict[str, str],
) -> None:
    def args_based_return_checksum(integrity: str) -> ChecksumInfo:
        if integrity == "sha512-YOLO1111==":
            return ChecksumInfo("sha256", "YOLO1111")
        elif integrity == "sha512-YOLO2222==":
            return ChecksumInfo("sha256", "YOLO2222")
        else:
            return ChecksumInfo("sha256", "YOLO")

    mock_from_sri.side_effect = args_based_return_checksum
    mock_must_match_any_checksum.return_value = None
    mock_clone_as_tarball.return_value = None
    mock_async_download_files.return_value = None

    download_paths = _get_npm_dependencies(rooted_tmp_path, deps_to_download)
    expected_download_paths = {}
    for url, subpath in expected_download_subpaths.items():
        expected_download_paths[url] = rooted_tmp_path.join_within_root(subpath)

    assert download_paths == expected_download_paths
