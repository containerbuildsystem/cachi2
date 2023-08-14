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

from cachi2.core.errors import GoModError, PackageRejected, UnexpectedFormat
from cachi2.core.models.input import Flag, Request
from cachi2.core.models.output import BuildConfig, RequestOutput
from cachi2.core.models.sbom import Component
from cachi2.core.package_managers import gomod
from cachi2.core.package_managers.gomod import (
    Module,
    ModuleID,
    Package,
    ParsedModule,
    ParsedPackage,
    ResolvedGoModule,
    StandardPackage,
    _create_modules_from_parsed_data,
    _create_packages_from_parsed_data,
    _deduplicate_resolved_modules,
    _get_golang_version,
    _get_repository_name,
    _parse_go_sum,
    _parse_vendor,
    _resolve_gomod,
    _run_download_cmd,
    _should_vendor_deps,
    _validate_local_replacements,
    _vendor_changed,
    _vendor_deps,
    fetch_gomod_source,
)
from cachi2.core.rooted_path import PathOutsideRoot, RootedPath
from tests.common_utils import write_file_tree


def setup_module() -> None:
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


def proc_mock(
    args: Union[str, list[str]] = "", *, returncode: int, stdout: Optional[str]
) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args, returncode=returncode, stdout=stdout)


def get_mocked_data(data_dir: Path, filepath: Union[str, Path]) -> str:
    return data_dir.joinpath("gomod-mocks", filepath).read_text()


def _parse_mocked_data(data_dir: Path, file_path: str) -> ResolvedGoModule:
    mocked_data = json.loads(get_mocked_data(data_dir, file_path))

    main_module = ParsedModule(**mocked_data["main_module"])
    modules = [ParsedModule(**module) for module in mocked_data["modules"]]
    packages = [ParsedPackage(**package) for package in mocked_data["packages"]]
    modules_in_go_sum = frozenset(
        (name, version) for name, version in mocked_data["modules_in_go_sum"]
    )

    return ResolvedGoModule(main_module, modules, packages, modules_in_go_sum)


@pytest.mark.parametrize("cgo_disable", [False, True])
@pytest.mark.parametrize("force_gomod_tidy", [False, True])
@mock.patch("cachi2.core.package_managers.gomod._get_golang_version")
@mock.patch("cachi2.core.package_managers.gomod._validate_local_replacements")
@mock.patch("subprocess.run")
def test_resolve_gomod(
    mock_run: mock.Mock,
    mock_validate_local_replacements: mock.Mock,
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
    module_dir.path.mkdir(parents=True)
    module_dir.join_within_root("go.sum").path.write_text(
        get_mocked_data(data_dir, "non-vendored/go.sum")
    )

    resolve_result = _resolve_gomod(module_dir, gomod_request, tmp_path)

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

    expect_result = _parse_mocked_data(data_dir, "expected-results/resolve_gomod.json")

    assert resolve_result.parsed_main_module == expect_result.parsed_main_module
    assert list(resolve_result.parsed_modules) == expect_result.parsed_modules
    assert list(resolve_result.parsed_packages) == expect_result.parsed_packages
    assert resolve_result.modules_in_go_sum == expect_result.modules_in_go_sum

    mock_validate_local_replacements.assert_called_once_with(
        resolve_result.parsed_modules, module_dir
    )


@pytest.mark.parametrize("force_gomod_tidy", [False, True])
@mock.patch("cachi2.core.package_managers.gomod._get_golang_version")
@mock.patch("cachi2.core.package_managers.gomod._validate_local_replacements")
@mock.patch("subprocess.run")
def test_resolve_gomod_vendor_dependencies(
    mock_run: mock.Mock,
    mock_validate_local_replacements: mock.Mock,
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
    module_dir.join_within_root("vendor").path.mkdir(parents=True)
    module_dir.join_within_root("vendor/modules.txt").path.write_text(
        get_mocked_data(data_dir, "vendored/modules.txt")
    )
    module_dir.join_within_root("go.sum").path.write_text(
        get_mocked_data(data_dir, "vendored/go.sum")
    )

    resolve_result = _resolve_gomod(module_dir, gomod_request, tmp_path)

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

    expect_result = _parse_mocked_data(data_dir, "expected-results/resolve_gomod_vendored.json")

    assert resolve_result.parsed_main_module == expect_result.parsed_main_module
    assert list(resolve_result.parsed_modules) == expect_result.parsed_modules
    assert list(resolve_result.parsed_packages) == expect_result.parsed_packages
    assert resolve_result.modules_in_go_sum == expect_result.modules_in_go_sum


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
    main_module, modules, packages, _ = _resolve_gomod(module_path, gomod_request, tmp_path)
    packages_list = list(packages)

    assert main_module == ParsedModule(
        path="github.com/release-engineering/retrodep/v2",
        version="v2.1.1",
        main=True,
    )

    assert not modules
    assert len(packages_list) == 1
    assert packages_list[0] == ParsedPackage(
        import_path="github.com/release-engineering/retrodep/v2",
        module=ParsedModule(
            path="github.com/release-engineering/retrodep/v2",
            main=True,
        ),
    )


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


@pytest.mark.parametrize(
    "go_sum_content, expect_modules",
    [
        (None, set()),
        ("", set()),
        (
            dedent(
                """
                github.com/creack/pty v1.1.18 h1:n56/Zwd5o6whRC5PMGretI4IdRLlmBXYNjScPaBgsbY=

                github.com/davecgh/go-spew v1.1.0/go.mod h1:J7Y8YcW2NihsgmVo/mv3lAwl/skON4iLHjSsI+c5H38=

                github.com/davecgh/go-spew v1.1.1 h1:vj9j/u1bqnvCEfJOwUhtlOARqs3+rkHYY13jYWTU97c=
                github.com/davecgh/go-spew v1.1.1/go.mod h1:J7Y8YcW2NihsgmVo/mv3lAwl/skON4iLHjSsI+c5H38=

                github.com/moby/term v0.0.0-20221205130635-1aeaba878587 h1:HfkjXDfhgVaN5rmueG8cL8KKeFNecRCXFhaJ2qZ5SKA=
                github.com/moby/term v0.0.0-20221205130635-1aeaba878587/go.mod h1:8FzsFHVUBGZdbDsJw/ot+X+d5HLUbvklYLJ9uGfcI3Y=
                """
            ),
            {
                ("github.com/creack/pty", "v1.1.18"),  # has the .zip checksum => include it
                # ("github.com/davecgh/go-spew", "v1.1.0"),  # only the .mod checksum => exclude it
                ("github.com/davecgh/go-spew", "v1.1.1"),
                ("github.com/moby/term", "v0.0.0-20221205130635-1aeaba878587"),
            },
        ),
    ],
)
def test_parse_go_sum(
    go_sum_content: Optional[str],
    expect_modules: set[ModuleID],
    rooted_tmp_path: RootedPath,
) -> None:
    if go_sum_content is not None:
        rooted_tmp_path.join_within_root("go.sum").path.write_text(go_sum_content)

    parsed_modules = _parse_go_sum(rooted_tmp_path)
    assert frozenset(expect_modules) == parsed_modules


def test_parse_broken_go_sum(rooted_tmp_path: RootedPath, caplog: pytest.LogCaptureFixture) -> None:
    go_sum_content = dedent(
        """\
        github.com/creack/pty v1.1.18 h1:n56/Zwd5o6whRC5PMGretI4IdRLlmBXYNjScPaBgsbY=
        github.com/davecgh/go-spew v1.1.0/go.mod
        github.com/davecgh/go-spew v1.1.1 h1:vj9j/u1bqnvCEfJOwUhtlOARqs3+rkHYY13jYWTU97c=
        github.com/davecgh/go-spew v1.1.1/go.mod h1:J7Y8YcW2NihsgmVo/mv3lAwl/skON4iLHjSsI+c5H38=
        github.com/moby/term v0.0.0-20221205130635-1aeaba878587 h1:HfkjXDfhgVaN5rmueG8cL8KKeFNecRCXFhaJ2qZ5SKA=
        github.com/moby/term v0.0.0-20221205130635-1aeaba878587/go.mod h1:8FzsFHVUBGZdbDsJw/ot+X+d5HLUbvklYLJ9uGfcI3Y=
        """
    )
    expect_modules = frozenset([("github.com/creack/pty", "v1.1.18")])

    submodule = rooted_tmp_path.join_within_root("submodule")
    submodule.path.mkdir()
    submodule.join_within_root("go.sum").path.write_text(go_sum_content)

    assert _parse_go_sum(submodule) == expect_modules
    assert caplog.messages == [
        "submodule/go.sum:2: malformed line, skipping the rest of the file: 'github.com/davecgh/go-spew v1.1.0/go.mod'",
    ]


@mock.patch("cachi2.core.package_managers.gomod._get_golang_version")
def test_create_modules_from_parsed_data(
    mock_get_golang_version: mock.Mock, tmp_path: Path
) -> None:
    main_module_dir = RootedPath(tmp_path).join_within_root("target-module")
    mock_get_golang_version.return_value = "v1.5.0"

    main_module = Module(
        name="github.com/my-org/my-repo/target-module",
        version="v1.5.0",
        original_name="github.com/my-org/my-repo/target-module",
        real_path="github.com/my-org/my-repo/target-module",
        main=True,
    )

    parsed_modules = [
        # simple module
        ParsedModule(
            path="golang.org/a/standard-module",
            version="v0.0.0-20190311183353-d8887717615a",
        ),
        # replaced module
        ParsedModule(
            path="github.com/a-neat-org/useful-module",
            version="v1.0.0",
            replace=ParsedModule(
                path="github.com/another-org/useful-module",
                version="v2.0.0",
            ),
        ),
        # locally replaced module, child folder
        ParsedModule(
            path="github.com/some-org/this-other-module",
            version="v0.0.1",
            replace=ParsedModule(
                path="./local-path",
            ),
        ),
        # locally replaced module, sibling folder
        ParsedModule(
            path="github.com/some-org/yet-another-module",
            version="v0.1.0",
            replace=ParsedModule(
                path="../sibling-path",
            ),
        ),
    ]

    expect_modules = [
        Module(
            name="golang.org/a/standard-module",
            version="v0.0.0-20190311183353-d8887717615a",
            original_name="golang.org/a/standard-module",
            real_path="golang.org/a/standard-module",
        ),
        Module(
            name="github.com/another-org/useful-module",
            version="v2.0.0",
            original_name="github.com/a-neat-org/useful-module",
            real_path="github.com/another-org/useful-module",
        ),
        Module(
            name="github.com/some-org/this-other-module",
            version="v1.5.0",
            original_name="github.com/some-org/this-other-module",
            real_path="github.com/my-org/my-repo/target-module/local-path",
        ),
        Module(
            name="github.com/some-org/yet-another-module",
            version="v1.5.0",
            original_name="github.com/some-org/yet-another-module",
            real_path="github.com/my-org/my-repo/sibling-path",
        ),
    ]

    modules = _create_modules_from_parsed_data(main_module, main_module_dir, parsed_modules)

    assert modules == expect_modules


def test_module_to_component() -> None:
    expected_component = Component(
        name="github.com/another-org/nice-repo",
        version="v0.0.1",
        purl="pkg:golang/github.com/another-org/nice-repo@v0.0.1?type=module",
    )

    component = Module(
        name="github.com/another-org/nice-repo",
        version="v0.0.1",
        original_name="github.com/my-org/nice-repo",
        real_path="github.com/another-org/nice-repo",
    ).to_component()

    assert component == expected_component


def test_create_packages_from_parsed_data() -> None:
    # modules as they'd be resolved from _create_modules_from_parsed_data
    modules = [
        Module(
            name="github.com/my-org/my-repo",
            version="v1.5.0",
            original_name="github.com/my-org/my-repo",
            real_path="github.com/my-org/my-repo",
            main=True,
        ),
        Module(
            name="github.com/my-org/my-repo/child-module",
            version="v1.0.1",
            original_name="github.com/my-org/my-repo/child-module",
            real_path="github.com/my-org/my-repo/child-module",
        ),
        Module(
            name="github.com/stretchr/testify",
            version="v1.7.1",
            original_name="github.com/stretchr/testify",
            real_path="github.com/stretchr/testify",
        ),
        Module(
            name="github.com/cachito-testing/retrodep/v2",
            version="v2.0.0",
            original_name="github.com/containerbuildsystem/retrodep/v2",
            real_path="github.com/cachito-testing/retrodep/v2",
        ),
    ]

    parsed_packages = [
        # std pkg
        ParsedPackage(
            import_path="internal/cpu",
            standard=True,
        ),
        # normal pkg
        ParsedPackage(
            import_path="github.com/stretchr/testify/assert",
            module=ParsedModule(path="github.com/stretchr/testify", version="v1.7.1"),
        ),
        # main module package
        ParsedPackage(
            import_path="github.com/my-org/my-repo",
            module=ParsedModule(path="github.com/my-org/my-repo", version="v1.5.0"),
        ),
        # package from a replaced module
        ParsedPackage(
            import_path="github.com/containerbuildsystem/retrodep/v2",
            module=ParsedModule(
                path="github.com/containerbuildsystem/retrodep/v2", version="v2.0.0"
            ),
        ),
        # package from a child module, with module reference missing
        ParsedPackage(
            import_path="github.com/my-org/my-repo/child-module/child-pkg",
        ),
    ]

    expect_packages = [
        StandardPackage(name="internal/cpu"),
        Package(
            relative_path="assert",
            module=Module(
                name="github.com/stretchr/testify",
                version="v1.7.1",
                original_name="github.com/stretchr/testify",
                real_path="github.com/stretchr/testify",
            ),
        ),
        Package(
            relative_path="",
            module=Module(
                name="github.com/my-org/my-repo",
                version="v1.5.0",
                original_name="github.com/my-org/my-repo",
                real_path="github.com/my-org/my-repo",
                main=True,
            ),
        ),
        Package(
            relative_path="",
            module=Module(
                name="github.com/cachito-testing/retrodep/v2",
                version="v2.0.0",
                original_name="github.com/containerbuildsystem/retrodep/v2",
                real_path="github.com/cachito-testing/retrodep/v2",
            ),
        ),
        Package(
            relative_path="child-pkg",
            module=Module(
                name="github.com/my-org/my-repo/child-module",
                version="v1.0.1",
                original_name="github.com/my-org/my-repo/child-module",
                real_path="github.com/my-org/my-repo/child-module",
            ),
        ),
    ]

    packages = _create_packages_from_parsed_data(modules, parsed_packages)

    assert packages == expect_packages


@pytest.mark.parametrize(
    "package, expected_component",
    (
        # package is also the main module
        (
            Package(
                relative_path="",
                module=Module(
                    name="github.com/my-org/some-repo",
                    version="v0.0.3",
                    original_name="github.com/my-org/some-repo",
                    real_path="github.com/my-org/some-repo",
                ),
            ),
            Component(
                name="github.com/my-org/some-repo",
                version="v0.0.3",
                purl="pkg:golang/github.com/my-org/some-repo@v0.0.3?type=package",
            ),
        ),
        # package is from a replaced module
        (
            Package(
                relative_path="this-pkg",
                module=Module(
                    name="github.com/another-org/nice-repo",
                    version="v0.0.1",
                    original_name="github.com/my-org/nice-repo",
                    real_path="github.com/another-org/nice-repo",
                ),
            ),
            Component(
                name="github.com/another-org/nice-repo/this-pkg",
                version="v0.0.1",
                purl="pkg:golang/github.com/another-org/nice-repo/this-pkg@v0.0.1?type=package",
            ),
        ),
        # main module is from a forked repo
        (
            Package(
                relative_path="this-pkg",
                module=Module(
                    name="github.com/my-org/nice-repo",
                    version="v0.0.2",
                    original_name="github.com/my-org/nice-repo",
                    real_path="github.com/another-org/forked-repo",
                ),
            ),
            Component(
                name="github.com/my-org/nice-repo/this-pkg",
                version="v0.0.2",
                purl="pkg:golang/github.com/another-org/forked-repo/this-pkg@v0.0.2?type=package",
            ),
        ),
    ),
)
def test_package_to_component(package: Package, expected_component: Component) -> None:
    assert package.to_component() == expected_component


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


def test_deduplicate_resolved_modules() -> None:
    # as reported by "go list -deps all"
    package_modules = [
        # local replacement
        ParsedModule(
            path="github.com/my-org/local-replacement",
            version="v1.0.0",
            replace=ParsedModule(path="./local-folder"),
        ),
        # dependency replacement
        ParsedModule(
            path="github.com/my-org/my-dep",
            version="v2.0.0",
            replace=ParsedModule(path="github.com/another-org/another-dep", version="v2.0.1"),
        ),
        # common dependency
        ParsedModule(
            path="github.com/awesome-org/neat-dep",
            version="v2.0.1",
        ),
    ]

    # as reported by "go mod download -json"
    downloaded_modules = [
        # duplicate of dependency replacement
        ParsedModule(
            path="github.com/another-org/another-dep",
            version="v2.0.1",
        ),
        # duplicate of common dependency
        ParsedModule(
            path="github.com/awesome-org/neat-dep",
            version="v2.0.1",
        ),
    ]

    dedup_modules = _deduplicate_resolved_modules(package_modules, downloaded_modules)

    expect_dedup_modules = [
        ParsedModule(
            path="github.com/my-org/local-replacement",
            version="v1.0.0",
            replace=ParsedModule(path="./local-folder"),
        ),
        ParsedModule(
            path="github.com/my-org/my-dep",
            version="v2.0.0",
            replace=ParsedModule(path="github.com/another-org/another-dep", version="v2.0.1"),
        ),
        ParsedModule(
            path="github.com/awesome-org/neat-dep",
            version="v2.0.1",
        ),
    ]

    assert list(dedup_modules) == expect_dedup_modules


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


def test_validate_local_replacements(tmpdir: Path) -> None:
    app_path = RootedPath(tmpdir).join_within_root("subpath")

    modules = [
        ParsedModule(
            path="example.org/foo", version="v1.0.0", replace=ParsedModule(path="./another-foo")
        ),
        ParsedModule(
            path="example.org/foo", version="v1.0.0", replace=ParsedModule(path="../sibling-foo")
        ),
    ]

    _validate_local_replacements(modules, app_path)


def test_invalid_local_replacements(tmpdir: Path) -> None:
    app_path = RootedPath(tmpdir)

    modules = [
        ParsedModule(
            path="example.org/foo", version="v1.0.0", replace=ParsedModule(path="../outside-repo")
        ),
    ]

    expect_error = f"Joining path '../outside-repo' to '{tmpdir}': target is outside '{tmpdir}'"

    with pytest.raises(PathOutsideRoot, match=expect_error):
        _validate_local_replacements(modules, app_path)


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
def test_should_vendor_deps(
    flags: list[str],
    vendor_exists: bool,
    expect_result: tuple[bool, bool],
    rooted_tmp_path: RootedPath,
) -> None:
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
def test_should_vendor_deps_strict(
    flags: list[str], vendor_exists: bool, expect_error: bool, rooted_tmp_path: RootedPath
) -> None:
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
        ParsedModule(
            path="github.com/Azure/go-ansiterm", version="v0.0.0-20210617225240-d185dfc1b5a1"
        ),
        ParsedModule(path="github.com/Masterminds/semver", version="v1.4.2"),
        ParsedModule(path="github.com/Microsoft/go-winio", version="v0.6.0"),
        ParsedModule(
            path="github.com/cachito-testing/gomod-pandemonium/terminaltor",
            version="v0.0.0",
            replace=ParsedModule(path="./terminaltor"),
        ),
        ParsedModule(
            path="github.com/cachito-testing/gomod-pandemonium/weird",
            version="v0.0.0",
            replace=ParsedModule(path="./weird"),
        ),
        ParsedModule(path="github.com/go-logr/logr", version="v1.2.3"),
        ParsedModule(
            path="github.com/go-task/slim-sprig", version="v0.0.0-20230315185526-52ccab3ef572"
        ),
        ParsedModule(path="github.com/google/go-cmp", version="v0.5.9"),
        ParsedModule(path="github.com/google/pprof", version="v0.0.0-20210407192527-94a9f03dee38"),
        ParsedModule(path="github.com/moby/term", version="v0.0.0-20221205130635-1aeaba878587"),
        ParsedModule(path="github.com/onsi/ginkgo/v2", version="v2.9.2"),
        ParsedModule(path="github.com/onsi/gomega", version="v1.27.4"),
        ParsedModule(path="github.com/op/go-logging", version="v0.0.0-20160315200505-970db520ece7"),
        ParsedModule(path="github.com/pkg/errors", version="v0.8.1"),
        ParsedModule(
            path="github.com/release-engineering/retrodep/v2",
            version="v2.1.0",
            replace=ParsedModule(path="github.com/cachito-testing/retrodep/v2", version="v2.1.1"),
        ),
        ParsedModule(path="golang.org/x/mod", version="v0.9.0"),
        ParsedModule(path="golang.org/x/net", version="v0.8.0"),
        ParsedModule(path="golang.org/x/sys", version="v0.6.0"),
        ParsedModule(path="golang.org/x/text", version="v0.8.0"),
        ParsedModule(path="golang.org/x/tools", version="v0.7.0"),
        ParsedModule(path="gopkg.in/yaml.v2", version="v2.2.2"),
        ParsedModule(path="gopkg.in/yaml.v3", version="v3.0.1"),
    ]
    assert list(_parse_vendor(rooted_tmp_path)) == expect_modules


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
def test_run_download_cmd_success(
    mock_sleep: Any,
    mock_run: Any,
    mock_config: Any,
    tries_needed: int,
    caplog: pytest.LogCaptureFixture,
) -> None:
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
def test_run_download_cmd_failure(
    mock_sleep: Any, mock_run: Any, mock_config: Any, caplog: pytest.LogCaptureFixture
) -> None:
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
def test_missing_gomod_file(file_tree: dict[str, Any], tmp_path: Path) -> None:
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
    "gomod_input_packages, packages_output_by_path, expect_components",
    (
        (
            [{"type": "gomod", "path": "."}],
            {
                ".": ResolvedGoModule(
                    ParsedModule(
                        path="github.com/my-org/my-repo",
                        version="v1.0.0",
                    ),
                    [
                        ParsedModule(
                            path="golang.org/x/net",
                            version="v0.0.0-20190311183353-d8887717615a",
                        ),
                    ],
                    [
                        ParsedPackage(
                            import_path="github.com/my-org/my-repo",
                            module=ParsedModule(
                                path="github.com/my-org/my-repo",
                                version="v1.0.0",
                            ),
                        ),
                        ParsedPackage(
                            import_path="golang.org/x/net/http",
                            module=ParsedModule(
                                path="golang.org/x/net",
                                version="v0.0.0-20190311183353-d8887717615a",
                            ),
                        ),
                    ],
                    frozenset(),
                ),
            },
            [
                Component(
                    name="github.com/my-org/my-repo",
                    purl="pkg:golang/github.com/my-org/my-repo@v1.0.0?type=module",
                    version="v1.0.0",
                ),
                Component(
                    name="golang.org/x/net",
                    purl="pkg:golang/golang.org/x/net@v0.0.0-20190311183353-d8887717615a?type=module",
                    version="v0.0.0-20190311183353-d8887717615a",
                ),
                Component(
                    name="github.com/my-org/my-repo",
                    purl="pkg:golang/github.com/my-org/my-repo@v1.0.0?type=package",
                    version="v1.0.0",
                ),
                Component(
                    name="golang.org/x/net/http",
                    purl="pkg:golang/golang.org/x/net/http@v0.0.0-20190311183353-d8887717615a?type=package",
                    version="v0.0.0-20190311183353-d8887717615a",
                ),
            ],
        ),
        (
            [{"type": "gomod", "path": "."}, {"type": "gomod", "path": "./path"}],
            {
                ".": ResolvedGoModule(
                    ParsedModule(
                        path="github.com/my-org/my-repo",
                        version="v1.0.0",
                    ),
                    [],
                    [],
                    frozenset(),
                ),
                "path": ResolvedGoModule(
                    ParsedModule(
                        path="github.com/my-org/my-repo/path",
                        version="v1.0.0",
                    ),
                    [],
                    [],
                    frozenset(),
                ),
            },
            [
                Component(
                    name="github.com/my-org/my-repo",
                    purl="pkg:golang/github.com/my-org/my-repo@v1.0.0?type=module",
                    version="v1.0.0",
                ),
                Component(
                    name="github.com/my-org/my-repo/path",
                    purl="pkg:golang/github.com/my-org/my-repo/path@v1.0.0?type=module",
                    version="v1.0.0",
                ),
            ],
        ),
    ),
)
@mock.patch("cachi2.core.package_managers.gomod._get_repository_name")
@mock.patch("cachi2.core.package_managers.gomod._find_missing_gomod_files")
@mock.patch("cachi2.core.package_managers.gomod._resolve_gomod")
@mock.patch("cachi2.core.package_managers.gomod.GoCacheTemporaryDirectory")
def test_fetch_gomod_source(
    mock_tmp_dir: mock.Mock,
    mock_resolve_gomod: mock.Mock,
    mock_find_missing_gomod_files: mock.Mock,
    mock_get_repository_name: mock.Mock,
    gomod_request: Request,
    packages_output_by_path: dict[str, ResolvedGoModule],
    expect_components: list[Component],
    env_variables: list[dict[str, Any]],
) -> None:
    def resolve_gomod_mocked(
        app_dir: RootedPath, request: Request, tmp_dir: Path
    ) -> ResolvedGoModule:
        # Find package output based on the path being processed
        return packages_output_by_path[
            app_dir.path.relative_to(gomod_request.source_dir).as_posix()
        ]

    mock_resolve_gomod.side_effect = resolve_gomod_mocked
    mock_find_missing_gomod_files.return_value = []
    mock_get_repository_name.return_value = "github.com/my-org/my-repo"

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
            components=expect_components,
            build_config=BuildConfig(environment_variables=env_variables),
        )

    assert output == expected_output


@pytest.mark.parametrize(
    "input_url",
    (
        "ssh://github.com/cachito-testing/gomod-pandemonium",
        "ssh://username@github.com/cachito-testing/gomod-pandemonium",
        "github.com:cachito-testing/gomod-pandemonium.git",
        "username@github.com:cachito-testing/gomod-pandemonium.git/",
        "https://github.com/cachito-testing/gomod-pandemonium",
        "https://github.com/cachito-testing/gomod-pandemonium.git",
        "https://github.com/cachito-testing/gomod-pandemonium.git/",
    ),
)
@mock.patch("cachi2.core.scm.Repo")
def test_get_repository_name(mock_git_repo: Any, input_url: str) -> None:
    expected_url = "github.com/cachito-testing/gomod-pandemonium"

    mocked_repo = mock.Mock()
    mocked_repo.remote.return_value.url = input_url
    mocked_repo.head.commit.hexsha = "f" * 40
    mock_git_repo.return_value = mocked_repo

    resolved_url = _get_repository_name(RootedPath("/my-folder/cloned-repo"))

    assert resolved_url == expected_url
