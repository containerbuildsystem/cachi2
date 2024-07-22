# SPDX-License-Identifier: GPL-3.0-or-later
import json
import os
import re
import subprocess
import textwrap
from pathlib import Path
from string import Template
from textwrap import dedent
from typing import Any, Iterator, Optional, Tuple, Union
from unittest import mock

import git
import pytest
from packaging import version

from cachi2.core.errors import FetchError, PackageManagerError, PackageRejected, UnexpectedFormat
from cachi2.core.models.input import Flag, Request
from cachi2.core.models.output import BuildConfig, EnvironmentVariable, RequestOutput
from cachi2.core.models.sbom import Component, Property
from cachi2.core.package_managers import gomod
from cachi2.core.package_managers.gomod import (
    Go,
    Module,
    ModuleDict,
    ModuleID,
    ModuleVersionResolver,
    Package,
    ParsedModule,
    ParsedPackage,
    ResolvedGoModule,
    StandardPackage,
    _create_modules_from_parsed_data,
    _create_packages_from_parsed_data,
    _deduplicate_resolved_modules,
    _get_go_sum_files,
    _get_go_work_path,
    _get_gomod_version,
    _get_repository_name,
    _parse_go_sum,
    _parse_local_modules,
    _parse_vendor,
    _parse_workspace_module,
    _process_modules_json_stream,
    _resolve_gomod,
    _setup_go_toolchain,
    _should_vendor_deps,
    _validate_local_replacements,
    _vendor_changed,
    _vendor_deps,
    fetch_gomod_source,
)
from cachi2.core.rooted_path import PathOutsideRoot, RootedPath
from tests.common_utils import write_file_tree

GO_CMD_PATH = "/usr/bin/go"


def setup_module() -> None:
    """Re-enable logging that was disabled at some point in previous tests."""
    gomod.log.disabled = False
    gomod.log.setLevel("DEBUG")


@pytest.fixture(scope="module")
def env_variables() -> list[EnvironmentVariable]:
    return [
        EnvironmentVariable(name="GOCACHE", value="${output_dir}/deps/gomod"),
        EnvironmentVariable(name="GOMODCACHE", value="${output_dir}/deps/gomod/pkg/mod"),
        EnvironmentVariable(name="GOPATH", value="${output_dir}/deps/gomod"),
        EnvironmentVariable(name="GOPROXY", value="file://${GOMODCACHE}/cache/download"),
    ]


@pytest.fixture(scope="module", autouse=True)
def mock_which_go() -> Iterator[None]:
    """Make shutil.which return GO_CMD_PATH for all the tests in this file.

    Whenever we execute a command, we use shutil.which to look for it first. To ensure
    that these tests don't depend on the state of the developer's machine, the returned
    go path must be mocked.
    """
    with mock.patch("shutil.which") as mock_which:
        mock_which.return_value = GO_CMD_PATH
        yield


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
def go_mod_file(tmp_path: Path, request: pytest.FixtureRequest) -> None:
    output_file = tmp_path / "go.mod"

    with open(output_file, "w") as f:
        f.write(request.param)


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


@pytest.mark.parametrize(
    "cgo_disable, force_gomod_tidy, has_workspaces",
    (
        pytest.param(False, False, False, id="cgo_disabled__dont_force_tidy"),
        pytest.param(True, False, False, id="cgo_enabled__dont_force_tidy"),
        pytest.param(False, True, False, id="cgo_disabled__force_tidy"),
        pytest.param(True, True, False, id="cgo_enabled__force_tidy"),
        pytest.param(False, False, True, id="has_workspaces"),
    ),
)
@mock.patch("cachi2.core.package_managers.gomod._get_go_work_path")
@mock.patch("cachi2.core.package_managers.gomod.Go.release", new_callable=mock.PropertyMock)
@mock.patch("cachi2.core.package_managers.gomod._get_gomod_version")
@mock.patch("cachi2.core.package_managers.gomod.ModuleVersionResolver")
@mock.patch("cachi2.core.package_managers.gomod._validate_local_replacements")
@mock.patch("subprocess.run")
def test_resolve_gomod(
    mock_run: mock.Mock,
    mock_validate_local_replacements: mock.Mock,
    mock_version_resolver: mock.Mock,
    mock_get_gomod_version: mock.Mock,
    mock_go_release: mock.PropertyMock,
    mock_get_go_work: mock.Mock,
    cgo_disable: bool,
    force_gomod_tidy: bool,
    has_workspaces: bool,
    tmp_path: Path,
    data_dir: Path,
    gomod_request: Request,
) -> None:
    module_dir = gomod_request.source_dir.join_within_root("path/to/module")
    mocked_data_folder = "non-vendored" if not has_workspaces else "workspaces"

    # Mock the "subprocess.run" calls
    run_side_effects = []

    if has_workspaces:
        run_side_effects.append(
            proc_mock(
                "go work edit -json",
                returncode=0,
                stdout=get_mocked_data(data_dir, "workspaces/go_work.json"),
            )
        )

    run_side_effects.append(
        proc_mock(
            "go mod download -json",
            returncode=0,
            stdout=get_mocked_data(data_dir, f"{mocked_data_folder}/go_mod_download.json"),
        )
    )

    if force_gomod_tidy:
        run_side_effects.append(proc_mock("go mod tidy", returncode=0, stdout=None))

    run_side_effects.append(
        proc_mock(
            "go list -e -mod readonly -m",
            returncode=0,
            stdout=get_mocked_data(data_dir, f"{mocked_data_folder}/go_list_modules.json").replace(
                "{repo_dir}", str(module_dir)
            ),
        )
    )
    run_side_effects.append(
        proc_mock(
            "go list -e -mod readonly -deps -json all",
            returncode=0,
            stdout=get_mocked_data(data_dir, f"{mocked_data_folder}/go_list_deps_all.json"),
        )
    )
    run_side_effects.append(
        proc_mock(
            "go list -e -mod readonly -deps -json ./...",
            returncode=0,
            stdout=get_mocked_data(data_dir, f"{mocked_data_folder}/go_list_deps_threedot.json"),
        )
    )
    mock_run.side_effect = run_side_effects

    mock_version_resolver.get_golang_version.return_value = "v0.1.0"
    mock_go_release.return_value = "go0.1.0"
    mock_get_gomod_version.return_value = ("0.1.1", "0.1.2")

    flags: list[Flag] = []
    if cgo_disable:
        flags.append("cgo-disable")
    if force_gomod_tidy:
        flags.append("force-gomod-tidy")

    gomod_request.flags = frozenset(flags)

    mock_get_go_work.return_value = None
    module_dir.path.mkdir(parents=True)
    module_dir.join_within_root("go.sum").path.write_text(
        get_mocked_data(data_dir, f"{mocked_data_folder}/go.sum")
    )

    go_work_path = None
    if has_workspaces:
        go_work_path = module_dir.join_within_root("workspace_root")
        go_work_path.path.mkdir(parents=True)
        go_work_path.join_within_root("go.sum").path.write_text(
            get_mocked_data(data_dir, "workspaces/go.sum")
        )

    resolve_result = _resolve_gomod(
        module_dir, gomod_request, tmp_path, mock_version_resolver, go_work_path
    )

    if has_workspaces:
        assert mock_run.call_args_list[0][0][0] == [GO_CMD_PATH, "work", "edit", "-json"]
    if force_gomod_tidy:
        assert mock_run.call_args_list[1][0][0] == [GO_CMD_PATH, "mod", "tidy"]

    # when not vendoring, go list should be called with -mod readonly
    listdeps_cmd = [
        GO_CMD_PATH,
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

    if has_workspaces:
        expect_result = _parse_mocked_data(
            data_dir, "expected-results/resolve_gomod_workspaces.json"
        )
    else:
        expect_result = _parse_mocked_data(data_dir, "expected-results/resolve_gomod.json")

    assert resolve_result.parsed_main_module == expect_result.parsed_main_module
    assert list(resolve_result.parsed_modules) == expect_result.parsed_modules
    assert list(resolve_result.parsed_packages) == expect_result.parsed_packages
    assert resolve_result.modules_in_go_sum == expect_result.modules_in_go_sum

    mock_validate_local_replacements.assert_called_once_with(
        resolve_result.parsed_modules, module_dir
    )


@pytest.mark.parametrize("force_gomod_tidy", [False, True])
@mock.patch("cachi2.core.package_managers.gomod.Go.release", new_callable=mock.PropertyMock)
@mock.patch("cachi2.core.package_managers.gomod._get_gomod_version")
@mock.patch("cachi2.core.package_managers.gomod.ModuleVersionResolver")
@mock.patch("cachi2.core.package_managers.gomod._validate_local_replacements")
@mock.patch("subprocess.run")
def test_resolve_gomod_vendor_dependencies(
    mock_run: mock.Mock,
    mock_validate_local_replacements: mock.Mock,
    mock_version_resolver: mock.Mock,
    mock_get_gomod_version: mock.Mock,
    mock_go_release: mock.PropertyMock,
    force_gomod_tidy: bool,
    tmp_path: Path,
    data_dir: Path,
    gomod_request: Request,
) -> None:
    module_dir = gomod_request.source_dir.join_within_root("path/to/module")

    # Mock the "subprocess.run" calls
    run_side_effects = []
    run_side_effects.append(proc_mock("go mod vendor", returncode=0, stdout=None))
    if force_gomod_tidy:
        run_side_effects.append(proc_mock("go mod tidy", returncode=0, stdout=None))
    run_side_effects.append(
        proc_mock(
            "go list -e -m -json",
            returncode=0,
            stdout=get_mocked_data(data_dir, "non-vendored/go_list_modules.json").replace(
                "{repo_dir}", str(module_dir)
            ),
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

    mock_version_resolver.get_golang_version.return_value = "v0.1.0"
    mock_go_release.return_value = "go0.1.0"
    mock_get_gomod_version.return_value = ("0.1.1", "0.1.2")

    flags: list[Flag] = ["gomod-vendor"]
    if force_gomod_tidy:
        flags.append("force-gomod-tidy")

    gomod_request.flags = frozenset(flags)

    module_dir.join_within_root("vendor").path.mkdir(parents=True)
    module_dir.join_within_root("vendor/modules.txt").path.write_text(
        get_mocked_data(data_dir, "vendored/modules.txt")
    )
    module_dir.join_within_root("go.sum").path.write_text(
        get_mocked_data(data_dir, "vendored/go.sum")
    )

    resolve_result = _resolve_gomod(module_dir, gomod_request, tmp_path, mock_version_resolver)

    assert mock_run.call_args_list[0][0][0] == [GO_CMD_PATH, "mod", "vendor"]
    # when vendoring, go list should be called without -mod readonly
    assert mock_run.call_args_list[-2][0][0] == [
        GO_CMD_PATH,
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


@mock.patch("cachi2.core.package_managers.gomod.Go.release", new_callable=mock.PropertyMock)
@mock.patch("cachi2.core.package_managers.gomod._get_gomod_version")
def test_resolve_gomod_vendor_without_flag(
    mock_get_gomod_version: mock.Mock,
    mock_go_release: mock.PropertyMock,
    tmp_path: Path,
    gomod_request: Request,
) -> None:
    module_dir = gomod_request.source_dir.join_within_root("path/to/module")
    module_dir.path.joinpath("vendor").mkdir(parents=True)
    version_resolver = mock.Mock()
    mock_go_release.return_value = "go0.1.0"
    mock_get_gomod_version.return_value = ("0.1.1", "0.1.2")

    expected_error = (
        'The "gomod-vendor" or "gomod-vendor-check" flag must be set when your repository has '
        "vendored dependencies."
    )
    with pytest.raises(PackageRejected, match=expected_error):
        _resolve_gomod(module_dir, gomod_request, tmp_path, version_resolver)


@pytest.mark.parametrize("force_gomod_tidy", [False, True])
@mock.patch("cachi2.core.package_managers.gomod.Go.release", new_callable=mock.PropertyMock)
@mock.patch("cachi2.core.package_managers.gomod.Go._install")
@mock.patch("cachi2.core.package_managers.gomod.Go._locate_toolchain")
@mock.patch("cachi2.core.package_managers.gomod._get_gomod_version")
@mock.patch("cachi2.core.package_managers.gomod.ModuleVersionResolver")
@mock.patch("subprocess.run")
def test_resolve_gomod_no_deps(
    mock_run: mock.Mock,
    mock_version_resolver: mock.Mock,
    mock_get_gomod_version: mock.Mock,
    mock_go_locate_toolchain: mock.Mock,
    mock_go_install: mock.Mock,
    mock_go_release: mock.PropertyMock,
    force_gomod_tidy: bool,
    tmp_path: Path,
    gomod_request: Request,
) -> None:
    module_path = gomod_request.source_dir.join_within_root("path/to/module")

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

    mock_go_list_modules = Template(
        """
        {
            "Path": "github.com/release-engineering/retrodep/v2",
            "Main": true,
            "Dir": "$repo_dir",
            "GoMod": "$repo_dir/go.mod",
            "GoVersion": "1.19"
        }
        """
    ).substitute({"repo_dir": str(module_path)})

    # Mock the "subprocess.run" calls
    run_side_effects = []
    run_side_effects.append(proc_mock("go mod download -json", returncode=0, stdout=""))
    if force_gomod_tidy:
        run_side_effects.append(proc_mock("go mod tidy", returncode=0, stdout=None))
    run_side_effects.append(
        proc_mock(
            "go list -e -mod readonly -m",
            returncode=0,
            stdout=mock_go_list_modules,
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

    mock_version_resolver.get_golang_version.return_value = "v1.21.4"
    mock_go_release.return_value = "go1.21.0"
    mock_go_install.return_value = "/usr/bin/go"
    mock_get_gomod_version.return_value = ("1.21.4", None)

    if force_gomod_tidy:
        gomod_request.flags = frozenset({"force-gomod-tidy"})

    main_module, modules, packages, _ = _resolve_gomod(
        module_path, gomod_request, tmp_path, mock_version_resolver
    )
    packages_list = list(packages)

    assert main_module == ParsedModule(
        path="github.com/release-engineering/retrodep/v2",
        version="v1.21.4",
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
    version_resolver = mock.Mock()

    app_dir = gomod_request.source_dir

    expect_err_msg = re.escape(f"Joining path '{symlinked_file}' to '{app_dir}'")
    with pytest.raises(PathOutsideRoot, match=expect_err_msg) as exc_info:
        _resolve_gomod(app_dir, gomod_request, tmp_path, version_resolver)

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
    go_sum_file = rooted_tmp_path.join_within_root("go.sum")

    if go_sum_content is not None:
        go_sum_file.path.write_text(go_sum_content)

    parsed_modules = _parse_go_sum(go_sum_file)
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
    go_sum_file = submodule.join_within_root("go.sum")
    go_sum_file.path.write_text(go_sum_content)

    assert _parse_go_sum(go_sum_file) == expect_modules
    assert caplog.messages == [
        "submodule/go.sum:2: malformed line, skipping the rest of the file: 'github.com/davecgh/go-spew v1.1.0/go.mod'",
    ]


@mock.patch("cachi2.core.package_managers.gomod.Go")
@mock.patch("cachi2.core.package_managers.gomod.ModuleVersionResolver")
def test_parse_local_modules(go: mock.Mock, version_resolver: mock.Mock) -> None:
    go.return_value = """
    {
        "Path": "myorg.com/my-project",
        "Main": true,
        "Dir": "/path/to/project"
    }
    {
        "Path": "myorg.com/my-project/workspace",
        "Main": true,
        "Dir": "/path/to/project/workspace"
    }
    """

    app_dir = RootedPath("/path/to/project")
    version_resolver.get_golang_version.return_value = "1.0.0"

    main_module, workspace_modules = _parse_local_modules(go, [], {}, app_dir, version_resolver)

    assert main_module == ParsedModule(
        path="myorg.com/my-project",
        version="1.0.0",
        main=True,
    )

    assert workspace_modules[0] == ParsedModule(
        path="myorg.com/my-project/workspace",
        replace=ParsedModule(path="./workspace"),
    )


@pytest.mark.parametrize(
    "project_path, stream, expected_modules",
    (
        pytest.param(
            "/home/my-projects/simple-project",
            dedent(
                """
                {
                    "Path": "github.com/my-org/simple-project",
                    "Main": true,
                    "Dir": "/home/my-projects/simple-project",
                    "GoMod": "/home/my-projects/simple-project/go.mod",
                    "GoVersion": "1.19"
                }
                """
            ),
            (
                {
                    "Path": "github.com/my-org/simple-project",
                    "Main": True,
                    "Dir": "/home/my-projects/simple-project",
                    "GoMod": "/home/my-projects/simple-project/go.mod",
                    "GoVersion": "1.19",
                },
                [],
            ),
            id="no_workspaces",
        ),
        pytest.param(
            "/home/my-projects/project-with-workspaces",
            dedent(
                """
                {
                    "Path": "github.com/my-org/project-with-workspaces",
                    "Main": true,
                    "Dir": "/home/my-projects/project-with-workspaces",
                    "GoMod": "/home/my-projects/project-with-workspaces/go.mod",
                    "GoVersion": "1.19"
                }
                {
                    "Path": "github.com/my-org/work",
                    "Main": true,
                    "Dir": "/home/my-projects/project-with-workspaces/work",
                    "GoMod": "/home/my-projects/project-with-workspaces/work/go.mod"
                }
                {
                    "Path": "github.com/my-org/space",
                    "Main": true,
                    "Dir": "/home/my-projects/project-with-workspaces/space",
                    "GoMod": "/home/my-projects/project-with-workspaces/space/go.mod"
                }
                """
            ),
            (
                {
                    "Path": "github.com/my-org/project-with-workspaces",
                    "Main": True,
                    "Dir": "/home/my-projects/project-with-workspaces",
                    "GoMod": "/home/my-projects/project-with-workspaces/go.mod",
                    "GoVersion": "1.19",
                },
                [
                    {
                        "Path": "github.com/my-org/work",
                        "Main": True,
                        "Dir": "/home/my-projects/project-with-workspaces/work",
                        "GoMod": "/home/my-projects/project-with-workspaces/work/go.mod",
                    },
                    {
                        "Path": "github.com/my-org/space",
                        "Main": True,
                        "Dir": "/home/my-projects/project-with-workspaces/space",
                        "GoMod": "/home/my-projects/project-with-workspaces/space/go.mod",
                    },
                ],
            ),
            id="with_workspaces",
        ),
    ),
)
def test_process_modules_json_stream(
    project_path: str,
    stream: str,
    expected_modules: tuple[ModuleDict, list[ModuleDict]],
) -> None:
    app_dir = RootedPath(project_path)
    result = _process_modules_json_stream(app_dir, stream)

    assert result == expected_modules


@pytest.mark.parametrize(
    "relative_app_dir, module, expected_module",
    (
        # main module is also the workspace root:
        pytest.param(
            ".",
            {"Dir": "workspace", "Path": "example.com/myproject/workspace"},
            ParsedModule(
                path="example.com/myproject/workspace",
                replace=ParsedModule(path="./workspace"),
            ),
            id="workspace_root_is_a_go_module",
        ),
        # main module and workspace are inside the workspace root:
        pytest.param(
            "mainmod",
            {"Dir": "workspace", "Path": "example.com/myproject/workspace"},
            ParsedModule(
                path="example.com/myproject/workspace",
                replace=ParsedModule(path="../workspace"),
            ),
            id="only_nested_workspaces",
        ),
    ),
)
def test_parse_workspace_modules(
    relative_app_dir: str, module: dict[str, Any], expected_module: ParsedModule, tmp_path: Path
) -> None:
    app_dir = RootedPath(tmp_path).join_within_root(relative_app_dir)
    # makes Dir an absolute path based on tmp_path
    module["Dir"] = str(tmp_path.joinpath(module["Dir"]))

    parsed_workspace = _parse_workspace_module(app_dir, module, "0.0.1")
    assert parsed_workspace == expected_module


@pytest.mark.parametrize(
    "go_work_edit_json, relative_file_paths",
    [
        pytest.param(
            # main module is the same as the source dir, there's one nested workspace
            """
            {
                "Use": [
                    {"DiskPath": "."},
                    {"DiskPath": "./workspace"}
                ]
            }
            """,
            ["./go.sum", "./workspace/go.sum", "./go.work.sum"],
            id="main_module_is_repo_root",
        ),
        pytest.param(
            # go.work is in the source dir, main module and a workspace are nested
            """
            {
                "Use": [
                    {"DiskPath": "./app"},
                    {"DiskPath": "./workspace"}
                ]
            }
            """,
            ["./app/go.sum", "./workspace/go.sum", "./go.work.sum"],
            id="nested_main_module",
        ),
    ],
)
@mock.patch("subprocess.run")
def test_get_go_sum_files(
    mock_run: mock.Mock, go_work_edit_json: str, relative_file_paths: list[str], tmp_path: Path
) -> None:
    mock_run.side_effect = [
        proc_mock("go work -edit -json", returncode=0, stdout=go_work_edit_json)
    ]
    go_work_path = RootedPath(tmp_path)

    files = _get_go_sum_files(go_work_path, Go(), {})

    expected_files = [go_work_path.join_within_root(path) for path in relative_file_paths]
    assert files == expected_files


@pytest.mark.parametrize(
    "path_to_go_work_file, should_return_none",
    (
        pytest.param(Template("$tmp_path/project"), False, id="go_work_exists"),
        pytest.param(Template(""), True, id="go_work_does_not_exist"),
    ),
)
@mock.patch("cachi2.core.package_managers.gomod.Go.__call__")
def test_get_go_work_path(
    mock_run: mock.Mock,
    path_to_go_work_file: Template,
    should_return_none: bool,
    tmp_path: Path,
) -> None:
    mock_run.return_value = path_to_go_work_file.substitute({"tmp_path": tmp_path})

    repo_root = RootedPath(tmp_path)

    go_work_path = _get_go_work_path(repo_root)

    if should_return_none:
        assert go_work_path is None
    else:
        assert go_work_path == repo_root


@mock.patch("cachi2.core.package_managers.gomod.Go.__call__")
def test_get_go_work_path_when_go_work_is_outside_of_repo(
    mock_run: mock.Mock, rooted_tmp_path: RootedPath
) -> None:
    mock_run.return_value = "/a/random/path/go.work"

    error_message = f"Joining path '/a/random/path' to '{rooted_tmp_path}': target is outside '{rooted_tmp_path}'"

    with pytest.raises(PathOutsideRoot, match=error_message):
        _get_go_work_path(rooted_tmp_path)


@pytest.mark.parametrize("has_workspaces", (False, True))
@mock.patch("cachi2.core.package_managers.gomod.ModuleVersionResolver")
def test_create_modules_from_parsed_data(
    mock_version_resolver: mock.Mock,
    has_workspaces: bool,
    tmp_path: Path,
) -> None:
    main_module_dir = RootedPath(tmp_path).join_within_root("target-module")
    mock_version_resolver.get_golang_version.return_value = "v1.5.0"
    go_work_path = None

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

    modules_in_go_sum = frozenset(
        [
            ("golang.org/a/standard-module", "v0.0.0-20190311183353-d8887717615a"),
            # another-org/useful-module is missing
        ]
    )

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
            missing_hash_in_file=Path("target-module/go.sum"),
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

    if has_workspaces:
        go_work_path = RootedPath(tmp_path).join_within_root("workspace_dir")
        expect_modules[1] = Module(
            name="github.com/another-org/useful-module",
            version="v2.0.0",
            original_name="github.com/a-neat-org/useful-module",
            real_path="github.com/another-org/useful-module",
            missing_hash_in_file=Path("workspace_dir/go.work.sum"),
        )

    modules = _create_modules_from_parsed_data(
        main_module,
        main_module_dir,
        parsed_modules,
        modules_in_go_sum,
        mock_version_resolver,
        go_work_path,
    )

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
@mock.patch("cachi2.core.package_managers.gomod.Go.release", new_callable=mock.PropertyMock)
@mock.patch("cachi2.core.package_managers.gomod._get_gomod_version")
@mock.patch("cachi2.core.package_managers.gomod.get_config")
@mock.patch("subprocess.run")
def test_go_list_cmd_failure(
    mock_run: mock.Mock,
    mock_config: mock.Mock,
    mock_get_gomod_version: mock.Mock,
    mock_go_release: mock.PropertyMock,
    tmp_path: Path,
    go_mod_rc: int,
    go_list_rc: int,
    gomod_request: Request,
) -> None:
    module_path = gomod_request.source_dir.join_within_root("path/to/module")
    version_resolver = mock.Mock()

    mock_config.return_value.gomod_download_max_tries = 1
    mock_go_release.return_value = "go0.1.0"
    mock_get_gomod_version.return_value = ("0.1.1", "0.1.2")

    # Mock the "subprocess.run" calls
    mock_run.side_effect = [
        proc_mock("go mod download", returncode=go_mod_rc, stdout=""),
        proc_mock(
            "go list -e -mod readonly -m",
            returncode=go_list_rc,
            stdout="",
        ),
    ]

    expect_error = "Go execution failed: "
    if go_mod_rc == 0:
        expect_error += "`go list -e -mod readonly -m -json` failed with rc=1"
    else:
        expect_error += "Cachi2 re-tried running `go mod download -json` command 1 times."

    with pytest.raises(PackageManagerError, match=expect_error):
        _resolve_gomod(module_path, gomod_request, tmp_path, version_resolver)


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
    golang_repo_path: Path,
    module_suffix: str,
    ref: str,
    expected: str,
    subpath: Optional[str],
) -> None:
    module_name = f"github.com/mprahl/test-golang-pseudo-versions{module_suffix}"

    module_dir = RootedPath(golang_repo_path)
    repo = git.Repo(golang_repo_path)
    repo.git.checkout(ref)
    version_resolver = ModuleVersionResolver(repo, repo.commit(ref))

    if subpath:
        module_dir = module_dir.join_within_root(subpath)

    version = version_resolver.get_golang_version(module_name, module_dir)
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
@mock.patch("cachi2.core.package_managers.gomod.Go._run")
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
            _vendor_deps(Go(), app_dir, can_make_changes, run_params)
    else:
        _vendor_deps(Go(), app_dir, can_make_changes, run_params)

    mock_run_cmd.assert_called_once_with(["go", "mod", "vendor"], **run_params)
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


@pytest.mark.parametrize(
    "file_tree",
    (
        {".": {}},
        {"foo": {}, "bar": {}},
        {"foo": {}, "bar": {"go.mod": ""}},
    ),
)
@mock.patch("cachi2.core.package_managers.gomod.run_cmd")
def test_missing_gomod_file(
    mock_run_cmd: mock.Mock, file_tree: dict[str, Any], tmp_path: Path
) -> None:
    mock_run_cmd.return_value = "go version go0.0.1"
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
                        ParsedModule(
                            path="golang.org/x/tools",
                            version="v0.7.0",
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
                    frozenset([("golang.org/x/tools", "v0.7.0")]),
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
                    properties=[Property(name="cachi2:missing_hash:in_file", value="go.sum")],
                ),
                Component(
                    name="golang.org/x/tools",
                    purl="pkg:golang/golang.org/x/tools@v0.7.0?type=module",
                    version="v0.7.0",
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
                    [
                        ParsedModule(
                            path="golang.org/x/net",
                            version="v0.0.0-20190311183353-d8887717615a",
                        ),
                        ParsedModule(
                            path="golang.org/x/tools",
                            version="v0.7.0",
                        ),
                    ],
                    [],
                    frozenset([("golang.org/x/tools", "v0.7.0")]),
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
                Component(
                    name="golang.org/x/net",
                    purl="pkg:golang/golang.org/x/net@v0.0.0-20190311183353-d8887717615a?type=module",
                    version="v0.0.0-20190311183353-d8887717615a",
                    properties=[Property(name="cachi2:missing_hash:in_file", value="path/go.sum")],
                ),
                Component(
                    name="golang.org/x/tools",
                    purl="pkg:golang/golang.org/x/tools@v0.7.0?type=module",
                    version="v0.7.0",
                ),
            ],
        ),
    ),
)
@mock.patch("cachi2.core.package_managers.gomod._get_repository_name")
@mock.patch("cachi2.core.package_managers.gomod._find_missing_gomod_files")
@mock.patch("cachi2.core.package_managers.gomod._resolve_gomod")
@mock.patch("cachi2.core.package_managers.gomod.GoCacheTemporaryDirectory")
@mock.patch("cachi2.core.package_managers.gomod.ModuleVersionResolver.from_repo_path")
@mock.patch("cachi2.core.package_managers.gomod._get_go_work_path")
def test_fetch_gomod_source(
    mock_get_go_work_path: mock.Mock,
    mock_version_resolver: mock.Mock,
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
        app_dir: RootedPath,
        request: Request,
        tmp_dir: Path,
        version_resolver: ModuleVersionResolver,
        go_work_path: Optional[RootedPath],
    ) -> ResolvedGoModule:
        # Find package output based on the path being processed
        return packages_output_by_path[
            app_dir.path.relative_to(gomod_request.source_dir).as_posix()
        ]

    mock_get_go_work_path.return_value = None
    mock_resolve_gomod.side_effect = resolve_gomod_mocked
    mock_find_missing_gomod_files.return_value = []
    mock_get_repository_name.return_value = "github.com/my-org/my-repo"

    output = fetch_gomod_source(gomod_request)

    tmp_dir = Path(mock_tmp_dir.return_value.__enter__.return_value)
    calls = [
        mock.call(
            gomod_request.source_dir.join_within_root(package.path),
            gomod_request,
            tmp_dir,
            mock_version_resolver.return_value,
            None,
        )
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


@pytest.fixture
def repo_remote_with_tag(rooted_tmp_path: RootedPath) -> tuple[RootedPath, RootedPath]:
    """
    Return the Paths to two Repos, with the first configured as the remote of the second.

    There are different git tags applied to the first and second commits of the README file
    """
    local_repo_path = rooted_tmp_path.join_within_root("local")
    remote_repo_path = rooted_tmp_path.join_within_root("remote")
    readme_file_path = remote_repo_path.join_within_root("README.md")

    local_repo_path.path.mkdir()
    remote_repo_path.path.mkdir()
    remote_repo = git.Repo.init(remote_repo_path)

    with open(readme_file_path, "wb"):
        pass
    remote_repo.index.add([readme_file_path])
    initial_commit = remote_repo.index.commit("Add README")

    with open(readme_file_path, "w") as f:
        f.write("This is a README")
    remote_repo.index.add([readme_file_path])
    remote_repo.index.commit("Update README")

    git.Repo.clone_from(remote_repo_path, local_repo_path)

    remote_repo.create_tag("v1.0.0", ref=initial_commit)
    remote_repo.create_tag("v2.0.0")

    return remote_repo_path, local_repo_path


def test_fetch_tags(repo_remote_with_tag: tuple[RootedPath, RootedPath]) -> None:
    _, local_repo_path = repo_remote_with_tag
    assert git.Repo(local_repo_path).tags == []
    version_resolver = ModuleVersionResolver.from_repo_path(local_repo_path)
    assert version_resolver._commit_tags == ["v2.0.0"]
    assert version_resolver._all_tags == ["v1.0.0", "v2.0.0"]


def test_fetch_tags_fail(repo_remote_with_tag: tuple[RootedPath, RootedPath]) -> None:
    # The remote_repo itself has no remote configured, so will fail when fetching tags
    remote_repo_path, _ = repo_remote_with_tag
    error_msg = re.escape(
        f"Failed to fetch the tags on the Git repository (ValueError) for {remote_repo_path}"
    )
    with pytest.raises(FetchError, match=error_msg):
        ModuleVersionResolver.from_repo_path(remote_repo_path)


@pytest.mark.parametrize(
    "go_mod_file, go_mod_version, go_toolchain_version",
    [
        pytest.param("go 1.21", "1.21", None, id="go_minor"),
        pytest.param("go 1.21.0", "1.21.0", None, id="go_micro"),
        pytest.param("    go    1.21.4    ", "1.21.4", None, id="go_spaces"),
        pytest.param("go 1.21rc4", "1.21rc4", None, id="go_minor_rc"),
        pytest.param("go 1.21.0rc4", "1.21.0rc4", None, id="go_micro_rc"),
        pytest.param("go 1.21.0  // comment", "1.21.0", None, id="go_commentary"),
        pytest.param("go 1.21.0//commentary", "1.21.0", None, id="go_commentary_no_spaces"),
        pytest.param("go 1.21.0beta2//comment", "1.21.0beta2", None, id="go_rc_commentary"),
        pytest.param("   toolchain   go1.21.4  ", None, "1.21.4", id="toolchain_spaces"),
        pytest.param("go 1.21\ntoolchain go1.21.6", "1.21", "1.21.6", id="go_and_toolchain"),
    ],
    indirect=["go_mod_file"],
)
def test_get_gomod_version(
    rooted_tmp_path: RootedPath, go_mod_file: Path, go_mod_version: str, go_toolchain_version: str
) -> None:
    assert _get_gomod_version(rooted_tmp_path.join_within_root("go.mod")) == (
        go_mod_version,
        go_toolchain_version,
    )


INVALID_VERSION_STRINGS = [
    "go1.21",  # missing space between go and version number
    "go 1.21.0.100",  # non-conforming to the X.Y(.Z)? versioning template
    "1.21",  # missing 'go' at the beginning
    "go 1.21 foo",  # extra characters after version string
    "go 1.21prerelease",  # pre-release with no number
    "go 1.21prerelease_4",  # pre-release with non-alphanum character
    "toolchain 1.21",  # missing 'go' prefix for the toolchain spec
]


@pytest.mark.parametrize(
    "go_mod_file",
    [pytest.param(_, id=_) for _ in INVALID_VERSION_STRINGS],
    indirect=True,
)
def test_get_gomod_version_fail(rooted_tmp_path: RootedPath, go_mod_file: Path) -> None:
    assert _get_gomod_version(rooted_tmp_path.join_within_root("go.mod")) == (None, None)


@pytest.mark.parametrize(
    "go_mod_file, go_base_release, expected_toolchain",
    [
        pytest.param("", "go1.20.4", "1.20.4", id="mod_too_old_fallback_to_1.20"),
        pytest.param("go 1.19", "go1.21.4", "1.20", id="mod_older_than_base_fallback_to_1.20"),
        pytest.param("go 1.21.4", "go1.20.4", "1.21.0", id="base_older_than_mod"),
        pytest.param("go 1.21.4", "go1.21.6", "1.21.0", id="mod_older_than_base_use_1.21.0"),
        pytest.param("toolchain go1.21.4", "go1.21.6", "1.21.0", id="decide_based_on_toolchain"),
    ],
    indirect=["go_mod_file"],
)
@mock.patch("cachi2.core.package_managers.gomod.Go._locate_toolchain")
@mock.patch("cachi2.core.package_managers.gomod.Go.__call__")
def test_setup_go_toolchain(
    mock_go_call: mock.Mock,
    mock_go_locate_toolchain: mock.Mock,
    rooted_tmp_path: RootedPath,
    go_mod_file: Path,
    go_base_release: str,
    expected_toolchain: str,
) -> None:
    mock_go_call.return_value = f"Go release: {go_base_release}"
    mock_go_locate_toolchain.return_value = None

    go = _setup_go_toolchain(rooted_tmp_path.join_within_root("go.mod"))
    assert str(go.version) == expected_toolchain


@pytest.mark.parametrize(
    "unsupported_version",
    [
        pytest.param(("1.23.0", None), id="go_version_higher_than_max"),
        pytest.param((None, "1.23.0"), id="toolchain_version_higher_than_max"),
    ],
)
@mock.patch("cachi2.core.package_managers.gomod._get_gomod_version")
@mock.patch("cachi2.core.package_managers.gomod.Go.version", new_callable=mock.PropertyMock)
def test_setup_go_toolchain_failure(
    mock_go_version: mock.Mock,
    mock_get_gomod_version: mock.Mock,
    rooted_tmp_path: RootedPath,
    unsupported_version: Tuple[Optional[str], Optional[str]],
) -> None:
    mock_go_version.return_value = version.Version("1.21.0")
    mock_get_gomod_version.return_value = unsupported_version
    unsupported = unsupported_version[0] if unsupported_version[0] else unsupported_version[1]

    error_msg = f"Required/recommended Go toolchain version '{unsupported}' is not supported yet."
    with pytest.raises(PackageManagerError, match=error_msg):
        _setup_go_toolchain(rooted_tmp_path.join_within_root("go.mod"))


class TestGo:
    @pytest.mark.parametrize(
        "bin_, params",
        [
            pytest.param(None, {}, id="bundled_go_no_params"),
            pytest.param("/usr/bin/go1.21", {}, id="custom_go_no_params"),
            pytest.param(None, {"cwd": "/foo/bar"}, id="bundled_go_params"),
            pytest.param(
                "/usr/bin/go1.21",
                {
                    "env": {"GOCACHE": "/foo", "GOTOOLCHAIN": "local"},
                    "cwd": "/foo/bar",
                    "text": True,
                },
                id="custom_go_params",
            ),
        ],
    )
    @mock.patch("cachi2.core.package_managers.gomod.run_cmd")
    def test_run(
        self,
        mock_run: mock.Mock,
        bin_: str,
        params: dict,
    ) -> None:
        if not bin_:
            go = Go(bin_)
        else:
            go = Go()

        cmd = [go._bin, "mod", "download"]
        go._run(cmd, **params)
        mock_run.assert_called_once_with(cmd, params)

    @pytest.mark.parametrize(
        "bin_, params, tries_needed",
        [
            pytest.param(None, {}, 1, id="bundled_go_1_try"),
            pytest.param("/usr/bin/go1.21", {}, 2, id="custom_go_2_tries"),
            pytest.param(
                None,
                {
                    "env": {"GOCACHE": "/foo", "GOTOOLCHAIN": "local"},
                    "cwd": "/foo/bar",
                    "text": True,
                },
                5,
                id="bundled_go_params_5_tries",
            ),
        ],
    )
    @mock.patch("cachi2.core.package_managers.gomod.get_config")
    @mock.patch("cachi2.core.package_managers.gomod.run_cmd")
    @mock.patch("time.sleep")
    def test_retry(
        self,
        mock_sleep: mock.Mock,
        mock_run: mock.Mock,
        mock_config: mock.Mock,
        bin_: str,
        params: dict,
        tries_needed: int,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        mock_config.return_value.gomod_download_max_tries = 5

        # We don't want to mock subprocess.run here, because:
        # 1) the call chain looks like this: Go()._retry->run_go->self._run->run_cmd->subprocess.run
        # 2) we wouldn't be able to check if params are propagated correctly since run_cmd adds some too
        failure = subprocess.CalledProcessError(returncode=1, cmd="foo")
        success = 1
        mock_run.side_effect = [failure for _ in range(tries_needed - 1)] + [success]

        if bin_:
            go = Go(bin_)
        else:
            go = Go()

        cmd = [go._bin, "mod", "download"]
        go._retry(cmd, **params)
        mock_run.assert_called_with(cmd, params)
        assert mock_run.call_count == tries_needed
        assert mock_sleep.call_count == tries_needed - 1

        for n in range(tries_needed - 1):
            wait = 2**n
            assert f"Backing off run_go(...) for {wait:.1f}s" in caplog.text

    @mock.patch("cachi2.core.package_managers.gomod.get_config")
    @mock.patch("cachi2.core.package_managers.gomod.run_cmd")
    @mock.patch("time.sleep")
    def test_retry_failure(
        self, mock_sleep: Any, mock_run: Any, mock_config: Any, caplog: pytest.LogCaptureFixture
    ) -> None:
        mock_config.return_value.gomod_download_max_tries = 5

        failure = subprocess.CalledProcessError(returncode=1, cmd="foo")
        mock_run.side_effect = [failure] * 5
        go = Go()

        error_msg = f"Go execution failed: Cachi2 re-tried running `{go._bin} mod download` command 5 times."

        with pytest.raises(PackageManagerError, match=error_msg):
            go._retry([go._bin, "mod", "download"])

        assert mock_run.call_count == 5
        assert mock_sleep.call_count == 4

        assert "Backing off run_go(...) for 1.0s" in caplog.text
        assert "Backing off run_go(...) for 2.0s" in caplog.text
        assert "Backing off run_go(...) for 4.0s" in caplog.text
        assert "Backing off run_go(...) for 8.0s" in caplog.text
        assert "Giving up run_go(...) after 5 tries" in caplog.text

    @pytest.mark.parametrize("release", ["go1.20", "go1.21.1"])
    @mock.patch("pathlib.Path.home")
    @mock.patch("cachi2.core.package_managers.gomod.Go._retry")
    @mock.patch("cachi2.core.package_managers.gomod.get_cache_dir")
    def test_install(
        self,
        mock_cache_dir: mock.Mock,
        mock_go_retry: mock.Mock,
        mock_path_home: mock.Mock,
        tmp_path: Path,
        release: str,
    ) -> None:
        dest_cache_dir = tmp_path / "cache"
        env_vars = ["PATH", "GOPATH", "GOCACHE"]

        mock_cache_dir.return_value = dest_cache_dir
        mock_go_retry.return_value = 0
        mock_path_home.return_value = tmp_path

        sdk_download_dir = tmp_path / f"sdk/{release}"
        sdk_bin_dir = sdk_download_dir / "bin"
        sdk_bin_dir.mkdir(parents=True)
        sdk_bin_dir.joinpath("go").touch()

        go = Go(release=release)
        binary = Path(go._install(release))
        assert mock_go_retry.call_args_list[0][0][0][1] == "install"
        assert mock_go_retry.call_args_list[0][0][0][2] == f"golang.org/dl/{release}@latest"
        assert mock_go_retry.call_args_list[0][1].get("env") is not None
        assert set(mock_go_retry.call_args_list[0][1]["env"].keys()) & set(env_vars)
        assert not sdk_download_dir.exists()
        assert dest_cache_dir.exists()
        assert binary.exists()
        assert str(binary) == f"{dest_cache_dir}/go/{release}/bin/go"

    @pytest.mark.parametrize(
        "release, needs_install, retry",
        [
            pytest.param(None, False, False, id="bundled_go"),
            pytest.param("go1.20", False, True, id="custom_release_installed"),
            pytest.param("go1.21.0", True, True, id="custom_release_needs_installation"),
        ],
    )
    @mock.patch("cachi2.core.package_managers.gomod.get_config")
    @mock.patch("cachi2.core.package_managers.gomod.Go._locate_toolchain")
    @mock.patch("cachi2.core.package_managers.gomod.Go._install")
    @mock.patch("cachi2.core.package_managers.gomod.Go._run")
    def test_call(
        self,
        mock_run: mock.Mock,
        mock_install: mock.Mock,
        mock_locate_toolchain: mock.Mock,
        mock_get_config: mock.Mock,
        tmp_path: Path,
        release: Optional[str],
        needs_install: bool,
        retry: bool,
    ) -> None:
        go_bin = tmp_path / f"go/{release}/bin/go"

        if not needs_install:
            mock_locate_toolchain.return_value = go_bin.as_posix()
        else:
            mock_locate_toolchain.return_value = None
            mock_install.return_value = go_bin.as_posix()

        env = {"env": {"GOTOOLCHAIN": "local", "GOCACHE": "foo", "GOPATH": "bar"}}
        opts = ["mod", "download"]
        go = Go(release=release)
        go(opts, retry=retry, params=env)

        cmd = [go._bin, *opts]
        if not retry:
            mock_run.assert_called_once_with(cmd, **env)
        else:
            mock_get_config.return_value.gomod_download_max_tries = 1
            mock_run.call_count = 1
            mock_run.assert_called_with(cmd, **env)

        if needs_install:
            assert go._install_toolchain is False

    @pytest.mark.parametrize("retry", [False, True])
    @mock.patch("cachi2.core.package_managers.gomod.get_config")
    @mock.patch("subprocess.run")
    def test_call_failure(
        self,
        mock_run: mock.Mock,
        mock_get_config: mock.Mock,
        retry: bool,
    ) -> None:
        tries = 1
        mock_get_config.return_value.gomod_download_max_tries = tries
        failure = proc_mock(returncode=1, stdout="")
        mock_run.side_effect = [failure]

        opts = ["mod", "download"]
        cmd = ["go", *opts]
        error_msg = "Go execution failed: "
        if retry:
            error_msg += f"Cachi2 re-tried running `{' '.join(cmd)}` command {tries} times."
        else:
            error_msg += f"`{' '.join(cmd)}` failed with rc=1"

        with pytest.raises(PackageManagerError, match=error_msg):
            go = Go()
            go(opts, retry=retry)

        assert mock_run.call_count == 1

    @pytest.mark.parametrize(
        "base_path",
        [
            pytest.param("usr/local", id="locate_in_system_path"),
            pytest.param("cachi2", id="locate_in_XDG_CACHE_HOME"),
        ],
    )
    @mock.patch("cachi2.core.package_managers.gomod.get_cache_dir")
    @mock.patch("cachi2.core.package_managers.gomod.Path")
    def test_locate_toolchain(
        self, mock_path: mock.Mock, mock_cache_dir: mock.Mock, tmp_path: Path, base_path: str
    ) -> None:
        def prefix_path(*args: Any) -> Path:
            # we have to mock Path creation to prevent tests touching real system paths

            my_args = list(args)
            if str(tmp_path) not in my_args[0] and my_args[0].startswith("/"):
                my_args[0] = my_args[0][1:]
            return Path(tmp_path, *my_args)

        mock_path.side_effect = prefix_path
        mock_cache_dir.return_value = "cachi2"

        release = "go1.20"
        go_bin_dir = tmp_path / f"{base_path}/go/{release}/bin"
        go_bin_dir.mkdir(parents=True)
        go_bin_dir.joinpath("go").touch()

        go = Go(release=release)

        assert Path(go._bin) == go_bin_dir / "go"
        assert go._install_toolchain is False

    @mock.patch("cachi2.core.package_managers.gomod.get_cache_dir")
    def test_locate_toolchain_failure(
        self,
        mock_cache_dir: mock.Mock,
    ) -> None:
        mock_cache_dir.return_value = "cachi2"

        release = "go1.20"
        go = Go(release=release)

        assert go._bin == "go"
        assert go._install_toolchain is True

    @pytest.mark.parametrize(
        "release, expect, go_output",
        [
            pytest.param("go1.20", "go1.20", None, id="explicit_release"),
            pytest.param(
                None, "go1.21.4", "go version go1.21.4 linux/amd64", id="parse_from_output"
            ),
            pytest.param(
                None,
                "go1.21.4",
                "go   version\tgo1.21.4 \t\t linux/amd64",
                id="parse_from_output_white_spaces",
            ),
        ],
    )
    @mock.patch("cachi2.core.package_managers.gomod.Go._run")
    def test_release(
        self,
        mock_run: mock.Mock,
        release: Optional[str],
        expect: str,
        go_output: str,
    ) -> None:
        mock_run.return_value = go_output

        go = Go(release=release)
        assert go.release == expect

    @mock.patch("cachi2.core.package_managers.gomod.Go._run")
    def test_release_failure(self, mock_run: mock.Mock) -> None:
        go_output = "go mangled version 1.21_4"
        mock_run.return_value = go_output

        error_msg = f"Could not extract Go toolchain version from Go's output: '{go_output}'"
        with pytest.raises(PackageManagerError, match=error_msg):
            Go(release=None).release
