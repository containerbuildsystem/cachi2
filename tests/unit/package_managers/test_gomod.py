# SPDX-License-Identifier: GPL-3.0-or-later
import json
import os
import re
import subprocess
import textwrap
from pathlib import Path
from textwrap import dedent
from typing import Any, Optional, Union
from unittest import mock

import git
import pytest

from cachi2.core.errors import GoModError, PackageRejected, UnexpectedFormat, UnsupportedFeature
from cachi2.core.models.input import Flag, Request
from cachi2.core.models.output import BuildConfig, Component, RequestOutput, Sbom
from cachi2.core.package_managers import gomod
from cachi2.core.package_managers.gomod import (
    GoModule,
    _contains_package,
    _get_golang_version,
    _match_parent_module,
    _parse_vendor,
    _path_to_subpackage,
    _resolve_gomod,
    _run_download_cmd,
    _set_full_local_dep_relpaths,
    _should_vendor_deps,
    _vendor_changed,
    _vendor_deps,
    _vet_local_deps,
    fetch_gomod_source,
)
from cachi2.core.rooted_path import PathOutsideRoot, RootedPath
from tests.common_utils import write_file_tree


def setup_module():
    """Re-enable logging that was disabled at some point in previous tests."""
    gomod.log.disabled = False
    gomod.log.setLevel("DEBUG")


@pytest.fixture
def gomod_input_packages() -> list[dict[str, str]]:
    return [{"type": "gomod"}]


@pytest.fixture
def gomod_request(tmp_path: Path, gomod_input_packages: list[dict[str, str]]) -> Request:
    # Create folder in the specified path, otherwise Request validation would fail
    for package in gomod_input_packages:
        if "path" in package:
            (tmp_path / package["path"]).mkdir(exist_ok=True)

    return Request(
        source_dir=tmp_path,
        output_dir=tmp_path / "output",
        packages=gomod_input_packages,
    )


@pytest.fixture
def rooted_tmp_path(tmp_path: Path) -> RootedPath:
    return RootedPath(tmp_path)


def proc_mock(
    args: Union[str, list[str]] = "", *, returncode: int, stdout: Optional[str]
) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args, returncode=returncode, stdout=stdout)


def get_mocked_data(data_dir: Path, filepath: Union[str, Path]) -> str:
    return data_dir.joinpath("gomod-mocks", filepath).read_text()


@pytest.mark.parametrize("cgo_disable", [False, True])
@pytest.mark.parametrize("force_gomod_tidy", [False, True])
@mock.patch("cachi2.core.package_managers.gomod._get_golang_version")
@mock.patch("cachi2.core.package_managers.gomod._vet_local_deps")
@mock.patch("cachi2.core.package_managers.gomod._set_full_local_dep_relpaths")
@mock.patch("subprocess.run")
def test_resolve_gomod(
    mock_run: mock.Mock,
    mock_set_full_relpaths: mock.Mock,
    mock_vet_local_deps: mock.Mock,
    mock_golang_version: mock.Mock,
    cgo_disable: bool,
    force_gomod_tidy: bool,
    tmp_path: Path,
    data_dir: Path,
    gomod_request: Request,
) -> None:
    # Mock the "subprocess.run" calls
    run_side_effects = []
    run_side_effects.append(
        proc_mock(
            "go mod download -json",
            returncode=0,
            stdout=get_mocked_data(data_dir, "non-vendored/go_mod_download.json"),
        )
    )
    if force_gomod_tidy:
        run_side_effects.append(proc_mock("go mod tidy", returncode=0, stdout=None))
    run_side_effects.append(
        proc_mock(
            "go list -e -mod readonly -m",
            returncode=0,
            stdout="github.com/cachito-testing/gomod-pandemonium",
        )
    )
    run_side_effects.append(
        proc_mock(
            "go list -e -mod readonly -deps -json all",
            returncode=0,
            stdout=get_mocked_data(data_dir, "non-vendored/go_list_deps_all.json"),
        )
    )
    run_side_effects.append(
        proc_mock(
            "go list -e -mod readonly -deps -json ./...",
            returncode=0,
            stdout=get_mocked_data(data_dir, "non-vendored/go_list_deps_threedot.json"),
        )
    )
    mock_run.side_effect = run_side_effects

    mock_golang_version.return_value = "v0.1.0"

    flags: list[Flag] = []
    if cgo_disable:
        flags.append("cgo-disable")
    if force_gomod_tidy:
        flags.append("force-gomod-tidy")

    gomod_request.flags = frozenset(flags)

    module_dir = gomod_request.source_dir.join_within_root("path/to/module")

    gomod = _resolve_gomod(module_dir, gomod_request, tmp_path)

    if force_gomod_tidy:
        assert mock_run.call_args_list[1][0][0] == ("go", "mod", "tidy")

    # when not vendoring, go list should be called with -mod readonly
    listdeps_cmd = [
        "go",
        "list",
        "-e",
        "-mod",
        "readonly",
        "-deps",
        "-json=ImportPath,Module,Standard,Deps",
    ]
    assert mock_run.call_args_list[-2][0][0] == [*listdeps_cmd, "all"]
    assert mock_run.call_args_list[-1][0][0] == [*listdeps_cmd, "./..."]

    for call in mock_run.call_args_list:
        env = call.kwargs["env"]
        if cgo_disable:
            assert env["CGO_ENABLED"] == "0"
        else:
            assert "CGO_ENABLED" not in env

    expect_gomod = json.loads(get_mocked_data(data_dir, "expected-results/resolve_gomod.json"))
    assert gomod == expect_gomod

    expect_module_deps = expect_gomod["module_deps"]
    expect_pkg_deps = expect_gomod["packages"][0]["pkg_deps"]

    mock_vet_local_deps.assert_has_calls(
        [mock.call(expect_module_deps), mock.call(expect_pkg_deps)],
    )
    mock_set_full_relpaths.assert_called_once_with(expect_pkg_deps, expect_module_deps)


@pytest.mark.parametrize("force_gomod_tidy", [False, True])
@mock.patch("cachi2.core.package_managers.gomod._get_golang_version")
@mock.patch("subprocess.run")
def test_resolve_gomod_vendor_dependencies(
    mock_run: mock.Mock,
    mock_golang_version: mock.Mock,
    force_gomod_tidy: bool,
    tmp_path: Path,
    data_dir: Path,
    gomod_request: Request,
) -> None:
    # Mock the "subprocess.run" calls
    run_side_effects = []
    run_side_effects.append(proc_mock("go mod vendor", returncode=0, stdout=None))
    if force_gomod_tidy:
        run_side_effects.append(proc_mock("go mod tidy", returncode=0, stdout=None))
    run_side_effects.append(
        proc_mock(
            "go list -e -m",
            returncode=0,
            stdout="github.com/cachito-testing/gomod-pandemonium",
        )
    )
    run_side_effects.append(
        proc_mock(
            "go list -e -deps -json all",
            returncode=0,
            stdout=get_mocked_data(data_dir, "vendored/go_list_deps_all.json"),
        )
    )
    run_side_effects.append(
        proc_mock(
            "go list -e -deps -json ./...",
            returncode=0,
            stdout=get_mocked_data(data_dir, "vendored/go_list_deps_threedot.json"),
        )
    )
    mock_run.side_effect = run_side_effects

    mock_golang_version.return_value = "v0.1.0"

    flags: list[Flag] = ["gomod-vendor"]
    if force_gomod_tidy:
        flags.append("force-gomod-tidy")

    gomod_request.flags = frozenset(flags)

    module_dir = gomod_request.source_dir.join_within_root("path/to/module")
    module_dir.path.joinpath("vendor").mkdir(parents=True)
    module_dir.path.joinpath("vendor/modules.txt").write_text(
        get_mocked_data(data_dir, "vendored/modules.txt")
    )

    gomod = _resolve_gomod(module_dir, gomod_request, tmp_path)

    assert mock_run.call_args_list[0][0][0] == ("go", "mod", "vendor")
    # when vendoring, go list should be called without -mod readonly
    assert mock_run.call_args_list[-2][0][0] == [
        "go",
        "list",
        "-e",
        "-deps",
        "-json=ImportPath,Module,Standard,Deps",
        "all",
    ]

    expect_gomod = json.loads(
        get_mocked_data(data_dir, "expected-results/resolve_gomod_vendored.json")
    )
    assert gomod == expect_gomod


def test_resolve_gomod_vendor_without_flag(tmp_path: Path, gomod_request: Request) -> None:
    module_dir = gomod_request.source_dir.join_within_root("path/to/module")
    module_dir.path.joinpath("vendor").mkdir(parents=True)

    expected_error = (
        'The "gomod-vendor" or "gomod-vendor-check" flag must be set when your repository has '
        "vendored dependencies."
    )
    with pytest.raises(PackageRejected, match=expected_error):
        _resolve_gomod(module_dir, gomod_request, tmp_path)


@pytest.mark.parametrize("force_gomod_tidy", [False, True])
@mock.patch("cachi2.core.package_managers.gomod._get_golang_version")
@mock.patch("subprocess.run")
def test_resolve_gomod_no_deps(
    mock_run: mock.Mock,
    mock_golang_version: mock.Mock,
    force_gomod_tidy: bool,
    tmp_path: Path,
    gomod_request: Request,
) -> None:
    mock_pkg_deps_no_deps = dedent(
        """
        {
            "ImportPath": "github.com/release-engineering/retrodep/v2",
            "Module": {
                "Path": "github.com/release-engineering/retrodep/v2",
                "Main": true
            }
        }
        """
    )

    # Mock the "subprocess.run" calls
    run_side_effects = []
    run_side_effects.append(proc_mock("go mod download -json", returncode=0, stdout=""))
    if force_gomod_tidy:
        run_side_effects.append(proc_mock("go mod tidy", returncode=0, stdout=None))
    run_side_effects.append(
        proc_mock(
            "go list -e -mod readonly -m",
            returncode=0,
            stdout="github.com/release-engineering/retrodep/v2",
        )
    )
    run_side_effects.append(
        proc_mock(
            "go list -e -mod readonly -deps -json all", returncode=0, stdout=mock_pkg_deps_no_deps
        )
    )
    run_side_effects.append(
        proc_mock(
            "go list -e -mod readonly -deps -json ./...", returncode=0, stdout=mock_pkg_deps_no_deps
        )
    )
    mock_run.side_effect = run_side_effects

    mock_golang_version.return_value = "v2.1.1"

    if force_gomod_tidy:
        gomod_request.flags = frozenset({"force-gomod-tidy"})

    module_path = gomod_request.source_dir.join_within_root("path/to/module")
    gomod = _resolve_gomod(module_path, gomod_request, tmp_path)

    assert gomod["module"] == {
        "type": "gomod",
        "name": "github.com/release-engineering/retrodep/v2",
        "version": "v2.1.1",
    }
    assert not gomod["module_deps"]
    assert len(gomod["packages"]) == 1
    assert gomod["packages"][0]["pkg"] == {
        "type": "go-package",
        "name": "github.com/release-engineering/retrodep/v2",
        "version": "v2.1.1",
    }
    assert not gomod["packages"][0]["pkg_deps"]


@pytest.mark.parametrize(
    "symlinked_file",
    [
        "go.mod",
        "go.sum",
        "vendor/modules.txt",
        "some-package/foo.go",
        "vendor/github.com/foo/bar/main.go",
    ],
)
def test_resolve_gomod_suspicious_symlinks(symlinked_file: str, gomod_request: Request) -> None:
    tmp_path = gomod_request.source_dir.path
    tmp_path.joinpath(symlinked_file).parent.mkdir(parents=True, exist_ok=True)
    tmp_path.joinpath(symlinked_file).symlink_to("/foo")

    app_dir = gomod_request.source_dir

    expect_err_msg = re.escape(f"Joining path '{symlinked_file}' to '{app_dir}'")
    with pytest.raises(PathOutsideRoot, match=expect_err_msg) as exc_info:
        _resolve_gomod(app_dir, gomod_request, tmp_path)

    e = exc_info.value
    assert "Found a potentially harmful symlink" in e.friendly_msg()


@pytest.mark.parametrize(("go_mod_rc", "go_list_rc"), ((0, 1), (1, 0)))
@mock.patch("cachi2.core.package_managers.gomod.get_config")
@mock.patch("subprocess.run")
def test_go_list_cmd_failure(
    mock_run: mock.Mock,
    mock_config: mock.Mock,
    tmp_path: Path,
    go_mod_rc: int,
    go_list_rc: int,
    gomod_request: Request,
) -> None:
    module_path = gomod_request.source_dir.join_within_root("path/to/module")

    mock_config.return_value.gomod_download_max_tries = 1

    # Mock the "subprocess.run" calls
    mock_run.side_effect = [
        proc_mock("go mod download", returncode=go_mod_rc, stdout=""),
        proc_mock(
            "go list -e -mod readonly -m",
            returncode=go_list_rc,
            stdout="",
        ),
    ]

    expect_error = "Processing gomod dependencies failed"
    if go_mod_rc == 0:
        expect_error += ": `go list -e -mod readonly -m` failed with rc=1"
    else:
        expect_error += ". Cachi2 tried the go mod download -json command 1 times"

    with pytest.raises(GoModError, match=expect_error):
        _resolve_gomod(module_path, gomod_request, tmp_path)


@pytest.mark.parametrize(
    "module_suffix, ref, expected, subpath",
    (
        # First commit with no tag
        (
            "",
            "78510c591e2be635b010a52a7048b562bad855a3",
            "v0.0.0-20191107200220-78510c591e2b",
            None,
        ),
        # No prior tag at all
        (
            "",
            "5a6e50a1f0e3ce42959d98b3c3a2619cb2516531",
            "v0.0.0-20191107202433-5a6e50a1f0e3",
            None,
        ),
        # Only a non-semver tag (v1)
        (
            "",
            "7911d393ab186f8464884870fcd0213c36ecccaf",
            "v0.0.0-20191107202444-7911d393ab18",
            None,
        ),
        # Directly maps to a semver tag (v1.0.0)
        ("", "d1b74311a7bf590843f3b58bf59ab047a6f771ae", "v1.0.0", None),
        # One commit after a semver tag (v1.0.0)
        (
            "",
            "e92462c73bbaa21540f7385e90cb08749091b66f",
            "v1.0.1-0.20191107202936-e92462c73bba",
            None,
        ),
        # A semver tag (v2.0.0) without the corresponding go.mod bump, which happens after a v1.0.0
        # semver tag
        (
            "",
            "61fe6324077c795fc81b602ee27decdf4a4cf908",
            "v1.0.1-0.20191107202953-61fe6324077c",
            None,
        ),
        # A semver tag (v2.1.0) after the go.mod file was bumped
        ("/v2", "39006a0b5b0654a299cc43f71e0dc1aa50c2bc72", "v2.1.0", None),
        # A pre-release semver tag (v2.2.0-alpha)
        ("/v2", "0b3468852566617379215319c0f4dfe7f5948a8f", "v2.2.0-alpha", None),
        # Two commits after a pre-release semver tag (v2.2.0-alpha)
        (
            "/v2",
            "863073fae6efd5e04bb972a05db0b0706ec8276e",
            "v2.2.0-alpha.0.20191107204050-863073fae6ef",
            None,
        ),
        # Directly maps to a semver non-annotated tag (v2.2.0)
        ("/v2", "709b220511038f443fe1b26ac09c3e6c06c9f7c7", "v2.2.0", None),
        # A non-semver tag (random-tag)
        (
            "/v2",
            "37cea8ddd9e6b6b81c7cfbc3223ce243c078388a",
            "v2.2.1-0.20191107204245-37cea8ddd9e6",
            None,
        ),
        # The go.mod file is bumped but there is no versioned commit
        (
            "/v2",
            "6c7249e8c989852f2a0ee0900378d55d8e1d7fe0",
            "v2.0.0-20191108212303-6c7249e8c989",
            None,
        ),
        # Three semver annotated tags on the same commit
        ("/v2", "a77e08ced4d6ae7d9255a1a2e85bd3a388e61181", "v2.2.5", None),
        # A non-annotated semver tag and an annotated semver tag
        ("/v2", "bf2707576336626c8bbe4955dadf1916225a6a60", "v2.3.3", None),
        # Two non-annotated semver tags
        ("/v2", "729d0e6d60317bae10a71fcfc81af69a0f6c07be", "v2.4.1", None),
        # Two semver tags, with one having the wrong major version and the other with the correct
        # major version
        ("/v2", "3decd63971ed53a5b7ff7b2ca1e75f3915e99cf2", "v2.5.0", None),
        # A semver tag that is incorrectly lower then the preceding semver tag
        ("/v2", "0dd249ad59176fee9b5451c2f91cc859e5ddbf45", "v2.0.1", None),
        # A commit after the incorrect lower semver tag
        (
            "/v2",
            "2883f3ddbbc811b112ff1fe51ba2ee7596ddbf24",
            "v2.5.1-0.20191118190931-2883f3ddbbc8",
            None,
        ),
        # Newest semver tag is applied to a submodule, but the root module is being processed
        (
            "/v2",
            "f3ee3a4a394fb44b055ed5710b8145e6e98c0d55",
            "v2.5.1-0.20211209210936-f3ee3a4a394f",
            None,
        ),
        # Submodule has a semver tag applied to it
        ("/v2", "f3ee3a4a394fb44b055ed5710b8145e6e98c0d55", "v2.5.1", "submodule"),
        # A commit after a submodule tag
        (
            "/v2",
            "cc6c9f554c0982786ff9e077c2b37c178e46828c",
            "v2.5.2-0.20211223131312-cc6c9f554c09",
            "submodule",
        ),
        # A commit with multiple tags in different submodules
        ("/v2", "5401bdd8a8ebfcccd2eea9451d407a5fdae6fc76", "v2.5.3", "submodule"),
        # Malformed semver tag, root module being processed
        ("/v2", "4a481f0bae82adef3ea6eae3d167af6e74499cb2", "v2.6.0", None),
        # Malformed semver tag, submodule being processed
        ("/v2", "4a481f0bae82adef3ea6eae3d167af6e74499cb2", "v2.6.0", "submodule"),
    ),
)
def test_get_golang_version(
    golang_repo_path: Path, module_suffix: str, ref: str, expected: str, subpath: Optional[str]
) -> None:
    module_name = f"github.com/mprahl/test-golang-pseudo-versions{module_suffix}"

    module_dir = RootedPath(golang_repo_path)
    if subpath:
        module_dir = module_dir.join_within_root(subpath)

    version = _get_golang_version(module_name, module_dir, ref)
    assert version == expected


@pytest.mark.parametrize(
    "platform_specific_path",
    [
        "/home/user/go/src/k8s.io/kubectl",
        "\\Users\\user\\go\\src\\k8s.io\\kubectl",
        "C:\\Users\\user\\go\\src\\k8s.io\\kubectl",
    ],
)
def test_vet_local_deps_abspath(platform_specific_path):
    dependencies = [{"name": "foo", "version": platform_specific_path}]

    expect_error = re.escape(
        f"Absolute paths to gomod dependencies are not supported: {platform_specific_path}"
    )
    with pytest.raises(UnsupportedFeature, match=expect_error):
        _vet_local_deps(dependencies)


@pytest.mark.parametrize("path", ["../local/path", "./local/../path"])
def test_vet_local_deps_parent_dir(path):
    dependencies = [{"name": "foo", "version": path}]

    expect_error = re.escape(f"Path to gomod dependency contains '..': {path}.")
    with pytest.raises(UnsupportedFeature, match=expect_error):
        _vet_local_deps(dependencies)


@pytest.mark.parametrize(
    "main_module_deps, pkg_deps_pre, pkg_deps_post",
    [
        (
            # module deps
            [{"name": "example.org/foo", "version": "./src/foo"}],
            # package deps pre
            [{"name": "example.org/foo", "version": "./src/foo"}],
            # package deps post (package name was the same as module name, no change)
            [{"name": "example.org/foo", "version": "./src/foo"}],
        ),
        (
            [{"name": "example.org/foo", "version": "./src/foo"}],
            [{"name": "example.org/foo/bar", "version": "./src/foo"}],
            # path is changed
            [{"name": "example.org/foo/bar", "version": "./src/foo/bar"}],
        ),
        (
            [{"name": "example.org/foo", "version": "./src/foo"}],
            [
                {"name": "example.org/foo/bar", "version": "./src/foo"},
                {"name": "example.org/foo/bar/baz", "version": "./src/foo"},
            ],
            # both packages match, both paths are changed
            [
                {"name": "example.org/foo/bar", "version": "./src/foo/bar"},
                {"name": "example.org/foo/bar/baz", "version": "./src/foo/bar/baz"},
            ],
        ),
        (
            [
                {"name": "example.org/foo", "version": "./src/foo"},
                {"name": "example.org/foo/bar", "version": "./src/bar"},
            ],
            [{"name": "example.org/foo/bar", "version": "./src/bar"}],
            # longer match wins, no change
            [{"name": "example.org/foo/bar", "version": "./src/bar"}],
        ),
        (
            [
                {"name": "example.org/foo", "version": "./src/foo"},
                {"name": "example.org/foo/bar", "version": "./src/bar"},
            ],
            [{"name": "example.org/foo/bar/baz", "version": "./src/bar"}],
            # longer match wins, path is changed
            [{"name": "example.org/foo/bar/baz", "version": "./src/bar/baz"}],
        ),
        (
            [
                {"name": "example.org/foo", "version": "./src/foo"},
                {"name": "example.org/foo/bar", "version": "v1.0.0"},
            ],
            [{"name": "example.org/foo/bar", "version": "./src/foo"}],
            # longer match does not have a local replacement, shorter match used
            # this can happen if replacement is only applied to a specific version of a module
            [{"name": "example.org/foo/bar", "version": "./src/foo/bar"}],
        ),
        (
            [{"name": "example.org/foo", "version": "./src/foo"}],
            [{"name": "example.org/foo/bar", "version": "v1.0.0"}],
            # Package does not have a local replacement, no change
            [{"name": "example.org/foo/bar", "version": "v1.0.0"}],
        ),
    ],
)
def test_set_full_local_dep_relpaths(main_module_deps, pkg_deps_pre, pkg_deps_post):
    _set_full_local_dep_relpaths(pkg_deps_pre, main_module_deps)
    # pkg_deps_pre should be modified in place
    assert pkg_deps_pre == pkg_deps_post


def test_set_full_local_dep_relpaths_no_match():
    pkg_deps = [{"name": "example.org/foo", "version": "./src/foo"}]
    err_msg = "Could not find parent Go module for local dependency: example.org/foo"

    with pytest.raises(RuntimeError, match=err_msg):
        _set_full_local_dep_relpaths(pkg_deps, [])


@pytest.mark.parametrize(
    "parent_name, package_name, expect_result",
    [
        ("github.com/foo", "github.com/foo", True),
        ("github.com/foo", "github.com/foo/bar", True),
        ("github.com/foo", "github.com/bar", False),
        ("github.com/foo", "github.com/foobar", False),
        ("github.com/foo/bar", "github.com/foo", False),
    ],
)
def test_contains_package(parent_name, package_name, expect_result):
    assert _contains_package(parent_name, package_name) == expect_result


@pytest.mark.parametrize(
    "parent, subpackage, expect_path",
    [
        ("github.com/foo", "github.com/foo", ""),
        ("github.com/foo", "github.com/foo/bar", "bar"),
        ("github.com/foo", "github.com/foo/bar/baz", "bar/baz"),
        ("github.com/foo/bar", "github.com/foo/bar/baz", "baz"),
        ("github.com/foo", "github.com/foo/github.com/foo", "github.com/foo"),
    ],
)
def test_path_to_subpackage(parent, subpackage, expect_path):
    assert _path_to_subpackage(parent, subpackage) == expect_path


def test_path_to_subpackage_not_a_subpackage():
    with pytest.raises(ValueError, match="Package github.com/b does not belong to github.com/a"):
        _path_to_subpackage("github.com/a", "github.com/b")


@pytest.mark.parametrize(
    "package_name, module_names, expect_parent_module",
    [
        ("github.com/foo/bar", ["github.com/foo/bar"], "github.com/foo/bar"),
        ("github.com/foo/bar", [], None),
        ("github.com/foo/bar", ["github.com/spam/eggs"], None),
        ("github.com/foo/bar/baz", ["github.com/foo/bar"], "github.com/foo/bar"),
        (
            "github.com/foo/bar/baz",
            ["github.com/foo/bar", "github.com/foo/bar/baz"],
            "github.com/foo/bar/baz",
        ),
        ("github.com/foo/bar", {"github.com/foo/bar": 1}, "github.com/foo/bar"),
    ],
)
def test_match_parent_module(package_name, module_names, expect_parent_module):
    assert _match_parent_module(package_name, module_names) == expect_parent_module


@pytest.mark.parametrize(
    "flags, vendor_exists, expect_result",
    [
        # no flags => should not vendor, cannot modify (irrelevant)
        ([], True, (False, False)),
        ([], False, (False, False)),
        # gomod-vendor => should vendor, can modify
        (["gomod-vendor"], True, (True, True)),
        (["gomod-vendor"], False, (True, True)),
        # gomod-vendor-check, vendor exists => should vendor, cannot modify
        (["gomod-vendor-check"], True, (True, False)),
        # gomod-vendor-check, vendor does not exist => should vendor, can modify
        (["gomod-vendor-check"], False, (True, True)),
        # both vendor flags => gomod-vendor-check takes priority
        (["gomod-vendor", "gomod-vendor-check"], True, (True, False)),
    ],
)
def test_should_vendor_deps(flags, vendor_exists, expect_result, rooted_tmp_path: RootedPath):
    if vendor_exists:
        rooted_tmp_path.join_within_root("vendor").path.mkdir()

    assert _should_vendor_deps(flags, rooted_tmp_path, False) == expect_result


@pytest.mark.parametrize(
    "flags, vendor_exists, expect_error",
    [
        ([], True, True),
        ([], False, False),
        (["gomod-vendor"], True, False),
        (["gomod-vendor-check"], True, False),
    ],
)
def test_should_vendor_deps_strict(flags, vendor_exists, expect_error, rooted_tmp_path: RootedPath):
    if vendor_exists:
        rooted_tmp_path.join_within_root("vendor").path.mkdir()

    if expect_error:
        msg = 'The "gomod-vendor" or "gomod-vendor-check" flag must be set'
        with pytest.raises(PackageRejected, match=msg):
            _should_vendor_deps(flags, rooted_tmp_path, True)
    else:
        _should_vendor_deps(flags, rooted_tmp_path, True)


@pytest.mark.parametrize("can_make_changes", [True, False])
@pytest.mark.parametrize("vendor_changed", [True, False])
@mock.patch("cachi2.core.package_managers.gomod._run_download_cmd")
@mock.patch("cachi2.core.package_managers.gomod._vendor_changed")
def test_vendor_deps(
    mock_vendor_changed: mock.Mock,
    mock_run_cmd: mock.Mock,
    can_make_changes: bool,
    vendor_changed: bool,
    rooted_tmp_path: RootedPath,
) -> None:
    app_dir = rooted_tmp_path.join_within_root("some/module")
    run_params = {"cwd": app_dir}
    mock_vendor_changed.return_value = vendor_changed
    expect_error = vendor_changed and not can_make_changes

    if expect_error:
        msg = "The content of the vendor directory is not consistent with go.mod."
        with pytest.raises(PackageRejected, match=msg):
            _vendor_deps(app_dir, can_make_changes, run_params)
    else:
        _vendor_deps(app_dir, can_make_changes, run_params)

    mock_run_cmd.assert_called_once_with(("go", "mod", "vendor"), run_params)
    if not can_make_changes:
        mock_vendor_changed.assert_called_once_with(app_dir)


def test_parse_vendor(rooted_tmp_path: RootedPath, data_dir: Path) -> None:
    modules_txt = rooted_tmp_path.join_within_root("vendor/modules.txt")
    modules_txt.path.parent.mkdir(parents=True)
    modules_txt.path.write_text(get_mocked_data(data_dir, "vendored/modules.txt"))
    expect_modules = [
        GoModule(path="github.com/Azure/go-ansiterm", version="v0.0.0-20210617225240-d185dfc1b5a1"),
        GoModule(path="github.com/Masterminds/semver", version="v1.4.2"),
        GoModule(path="github.com/Microsoft/go-winio", version="v0.6.0"),
        GoModule(
            path="github.com/cachito-testing/gomod-pandemonium/terminaltor",
            version="v0.0.0",
            replace=GoModule(path="./terminaltor"),
        ),
        GoModule(
            path="github.com/cachito-testing/gomod-pandemonium/weird",
            version="v0.0.0",
            replace=GoModule(path="./weird"),
        ),
        GoModule(path="github.com/go-logr/logr", version="v1.2.3"),
        GoModule(
            path="github.com/go-task/slim-sprig", version="v0.0.0-20230315185526-52ccab3ef572"
        ),
        GoModule(path="github.com/google/go-cmp", version="v0.5.9"),
        GoModule(path="github.com/google/pprof", version="v0.0.0-20210407192527-94a9f03dee38"),
        GoModule(path="github.com/moby/term", version="v0.0.0-20221205130635-1aeaba878587"),
        GoModule(path="github.com/onsi/ginkgo/v2", version="v2.9.2"),
        GoModule(path="github.com/onsi/gomega", version="v1.27.4"),
        GoModule(path="github.com/op/go-logging", version="v0.0.0-20160315200505-970db520ece7"),
        GoModule(path="github.com/pkg/errors", version="v0.8.1"),
        GoModule(
            path="github.com/release-engineering/retrodep/v2",
            version="v2.1.0",
            replace=GoModule(path="github.com/cachito-testing/retrodep/v2", version="v2.1.1"),
        ),
        GoModule(path="golang.org/x/mod", version="v0.9.0"),
        GoModule(path="golang.org/x/net", version="v0.8.0"),
        GoModule(path="golang.org/x/sys", version="v0.6.0"),
        GoModule(path="golang.org/x/text", version="v0.8.0"),
        GoModule(path="golang.org/x/tools", version="v0.7.0"),
        GoModule(path="gopkg.in/yaml.v2", version="v2.2.2"),
        GoModule(path="gopkg.in/yaml.v3", version="v3.0.1"),
    ]
    assert _parse_vendor(rooted_tmp_path) == expect_modules


@pytest.mark.parametrize(
    "file_content, expect_error_msg",
    [
        ("#invalid-line", "vendor/modules.txt: unexpected format: '#invalid-line'"),
        ("# main-module", "vendor/modules.txt: unexpected module line format: '# main-module'"),
        (
            "github.com/x/package",
            "vendor/modules.txt: package has no parent module: github.com/x/package",
        ),
    ],
)
def test_parse_vendor_unexpected_format(
    file_content: str, expect_error_msg: str, rooted_tmp_path: RootedPath
) -> None:
    vendor = rooted_tmp_path.join_within_root("vendor")
    vendor.path.mkdir()
    vendor.join_within_root("modules.txt").path.write_text(file_content)

    with pytest.raises(UnexpectedFormat, match=expect_error_msg):
        _parse_vendor(rooted_tmp_path)


@pytest.mark.parametrize("subpath", ["", "some/app/"])
@pytest.mark.parametrize(
    "vendor_before, vendor_changes, expected_change",
    [
        # no vendor/ dirs
        ({}, {}, None),
        # no changes
        ({"vendor": {"modules.txt": "foo v1.0.0\n"}}, {}, None),
        # vendor/modules.txt was added
        (
            {},
            {"vendor": {"modules.txt": "foo v1.0.0\n"}},
            textwrap.dedent(
                """
                --- /dev/null
                +++ b/{subpath}vendor/modules.txt
                @@ -0,0 +1 @@
                +foo v1.0.0
                """
            ),
        ),
        # vendor/modules.txt changed
        (
            {"vendor": {"modules.txt": "foo v1.0.0\n"}},
            {"vendor": {"modules.txt": "foo v2.0.0\n"}},
            textwrap.dedent(
                """
                --- a/{subpath}vendor/modules.txt
                +++ b/{subpath}vendor/modules.txt
                @@ -1 +1 @@
                -foo v1.0.0
                +foo v2.0.0
                """
            ),
        ),
        # vendor/some_file was added
        (
            {},
            {"vendor": {"some_file": "foo"}},
            textwrap.dedent(
                """
                A\t{subpath}vendor/some_file
                """
            ),
        ),
        # multiple additions and modifications
        (
            {"vendor": {"some_file": "foo"}},
            {"vendor": {"some_file": "bar", "other_file": "baz"}},
            textwrap.dedent(
                """
                A\t{subpath}vendor/other_file
                M\t{subpath}vendor/some_file
                """
            ),
        ),
        # vendor/ was added but only contains empty dirs => will be ignored
        ({}, {"vendor": {"empty_dir": {}}}, None),
        # change will be tracked even if vendor/ is .gitignore'd
        (
            {".gitignore": "vendor/"},
            {"vendor": {"some_file": "foo"}},
            textwrap.dedent(
                """
                A\t{subpath}vendor/some_file
                """
            ),
        ),
    ],
)
def test_vendor_changed(
    subpath: str,
    vendor_before: dict[str, Any],
    vendor_changes: dict[str, Any],
    expected_change: Optional[str],
    fake_repo: tuple[str, str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    repo_dir, _ = fake_repo
    repo = git.Repo(repo_dir)

    app_dir = RootedPath(repo_dir).join_within_root(subpath)
    os.makedirs(app_dir, exist_ok=True)

    write_file_tree(vendor_before, app_dir)
    repo.index.add([app_dir.join_within_root(path) for path in vendor_before])
    repo.index.commit("before vendoring", skip_hooks=True)

    write_file_tree(vendor_changes, app_dir, exist_ok=True)

    assert _vendor_changed(app_dir) == bool(expected_change)
    if expected_change:
        assert expected_change.format(subpath=subpath) in caplog.text

    # The _vendor_changed function should reset the `git add` => added files should not be tracked
    assert not repo.git.diff("--diff-filter", "A")


@pytest.mark.parametrize("tries_needed", [1, 2, 3, 4, 5])
@mock.patch("cachi2.core.package_managers.gomod.get_config")
@mock.patch("subprocess.run")
@mock.patch("time.sleep")
def test_run_download_cmd_success(mock_sleep, mock_run, mock_config, tries_needed, caplog):
    mock_config.return_value.gomod_download_max_tries = 5

    failure = proc_mock(returncode=1, stdout="")
    success = proc_mock(returncode=0, stdout="")
    mock_run.side_effect = [failure for _ in range(tries_needed - 1)] + [success]

    _run_download_cmd(["go", "mod", "download"], {})
    assert mock_run.call_count == tries_needed
    assert mock_sleep.call_count == tries_needed - 1

    for n in range(tries_needed - 1):
        wait = 2**n
        assert f"Backing off run_go(...) for {wait:.1f}s" in caplog.text


@mock.patch("cachi2.core.package_managers.gomod.get_config")
@mock.patch("subprocess.run")
@mock.patch("time.sleep")
def test_run_download_cmd_failure(mock_sleep, mock_run, mock_config, caplog):
    mock_config.return_value.gomod_download_max_tries = 5

    failure = proc_mock(returncode=1, stdout="")
    mock_run.side_effect = [failure] * 5

    expect_msg = (
        "Processing gomod dependencies failed. Cachi2 tried the go mod download command 5 times."
    )

    with pytest.raises(GoModError, match=expect_msg):
        _run_download_cmd(["go", "mod", "download"], {})

    assert mock_run.call_count == 5
    assert mock_sleep.call_count == 4

    assert "Backing off run_go(...) for 1.0s" in caplog.text
    assert "Backing off run_go(...) for 2.0s" in caplog.text
    assert "Backing off run_go(...) for 4.0s" in caplog.text
    assert "Backing off run_go(...) for 8.0s" in caplog.text
    assert "Giving up run_go(...) after 5 tries" in caplog.text


@pytest.mark.parametrize(
    "file_tree",
    (
        {".": {}},
        {"foo": {}, "bar": {}},
        {"foo": {}, "bar": {"go.mod": ""}},
    ),
)
def test_missing_gomod_file(file_tree, tmp_path):
    write_file_tree(file_tree, tmp_path, exist_ok=True)

    packages = [{"path": path, "type": "gomod"} for path, _ in file_tree.items()]
    request = Request(source_dir=tmp_path, output_dir=tmp_path, packages=packages)

    paths_without_gomod = [
        str(tmp_path / path)
        for path, contents in file_tree.items()
        if "go.mod" not in contents.keys()
    ]
    path_error_string = "; ".join(paths_without_gomod)

    with pytest.raises(PackageRejected, match=path_error_string):
        fetch_gomod_source(request)


@pytest.mark.parametrize(
    "dep_replacements, gomod_input_packages, raises_error",
    (
        ([], [{"type": "gomod", "path": "."}], False),
        (
            [{"name": "github.com/pkg/errors", "type": "gomod", "version": "v0.8.1"}],
            [{"type": "gomod", "path": "."}],
            False,
        ),
        (
            [],
            [{"type": "gomod", "path": "bar"}, {"type": "gomod", "path": "foo"}],
            False,
        ),
        (
            [{"name": "github.com/pkg/errors", "type": "gomod", "version": "v0.8.1"}],
            [{"type": "gomod", "path": "."}, {"type": "gomod", "path": "foo"}],
            True,
        ),
    ),
)
@mock.patch("cachi2.core.package_managers.gomod._find_missing_gomod_files")
@mock.patch("cachi2.core.package_managers.gomod._resolve_gomod")
@mock.patch("cachi2.core.package_managers.gomod.RequestOutput")
@mock.patch("cachi2.core.package_managers.gomod.Component")
@mock.patch("cachi2.core.package_managers.gomod.GoCacheTemporaryDirectory")
def test_dep_replacements(
    mock_tmp_dir,
    mock_component,
    mock_request_output,
    mock_resolve_gomod,
    mock_find_missing_gomod_files,
    dep_replacements,
    gomod_request,
    raises_error,
):
    gomod_request.dep_replacements = dep_replacements
    mock_find_missing_gomod_files.return_value = []

    if raises_error:
        msg = "Dependency replacements are only supported for a single go module path."
        with pytest.raises(UnsupportedFeature, match=msg):
            fetch_gomod_source(gomod_request)
    else:
        fetch_gomod_source(gomod_request)
        tmp_dir = Path(mock_tmp_dir.return_value.__enter__.return_value)
        expected_calls = [
            mock.call(gomod_request.source_dir.join_within_root(pkg.path), gomod_request, tmp_dir)
            for pkg in gomod_request.packages
        ]
        mock_resolve_gomod.assert_has_calls(expected_calls, any_order=True)


@pytest.mark.parametrize(
    "gomod_input_packages, packages_output_by_path, expect_components",
    (
        (
            [{"type": "gomod", "path": "."}],
            {
                ".": {
                    "module": {
                        "type": "gomod",
                        "name": "github.com/my-org/my-repo",
                        "version": "1.0.0",
                    },
                    "module_deps": [
                        {
                            "type": "gomod",
                            "name": "golang.org/x/net",
                            "version": "v0.0.0-20190311183353-d8887717615a",
                        }
                    ],
                    "packages": [
                        {
                            "pkg": {
                                "type": "go-package",
                                "name": "github.com/my-org/my-repo",
                                "version": "1.0.0",
                            },
                            "pkg_deps": [
                                {
                                    "type": "go-package",
                                    "name": "golang.org/x/net/http",
                                    "version": "v0.0.0-20190311183353-d8887717615a",
                                }
                            ],
                        }
                    ],
                },
            },
            [
                Component(name="github.com/my-org/my-repo", version="1.0.0"),
                Component(name="golang.org/x/net", version="v0.0.0-20190311183353-d8887717615a"),
                Component(
                    name="golang.org/x/net/http", version="v0.0.0-20190311183353-d8887717615a"
                ),
            ],
        ),
        (
            [{"type": "gomod", "path": "."}, {"type": "gomod", "path": "path"}],
            {
                ".": {
                    "module": {
                        "type": "gomod",
                        "name": "github.com/my-org/my-repo",
                        "version": "1.0.0",
                    },
                    "module_deps": [],
                    "packages": [],
                },
                "path": {
                    "module": {
                        "type": "gomod",
                        "name": "github.com/my-org/my-repo/path",
                        "version": "1.0.0",
                    },
                    "module_deps": [],
                    "packages": [],
                },
            },
            [
                Component(name="github.com/my-org/my-repo", version="1.0.0"),
                Component(name="github.com/my-org/my-repo/path", version="1.0.0"),
            ],
        ),
    ),
)
@mock.patch("cachi2.core.package_managers.gomod._find_missing_gomod_files")
@mock.patch("cachi2.core.package_managers.gomod._resolve_gomod")
@mock.patch("cachi2.core.package_managers.gomod.GoCacheTemporaryDirectory")
def test_fetch_gomod_source(
    mock_tmp_dir: mock.Mock,
    mock_resolve_gomod: mock.Mock,
    mock_find_missing_gomod_files: mock.Mock,
    gomod_request: Request,
    packages_output_by_path: dict[str, dict[str, Any]],
    expect_components: list[Component],
    env_variables: list[dict[str, Any]],
) -> None:
    def resolve_gomod_mocked(app_dir: RootedPath, request: Request, tmp_dir: Path):
        # Find package output based on the path being processed
        return packages_output_by_path[
            app_dir.path.relative_to(gomod_request.source_dir).as_posix()
        ]

    mock_resolve_gomod.side_effect = resolve_gomod_mocked
    mock_find_missing_gomod_files.return_value = []

    output = fetch_gomod_source(gomod_request)

    tmp_dir = Path(mock_tmp_dir.return_value.__enter__.return_value)
    calls = [
        mock.call(gomod_request.source_dir.join_within_root(package.path), gomod_request, tmp_dir)
        for package in gomod_request.packages
    ]
    mock_resolve_gomod.assert_has_calls(calls)

    if len(gomod_request.packages) == 0:
        expected_output = RequestOutput.empty()
    else:
        expected_output = RequestOutput(
            sbom=Sbom(components=expect_components),
            build_config=BuildConfig(environment_variables=env_variables),
        )

    assert output == expected_output
