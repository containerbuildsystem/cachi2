import itertools
import re
from enum import Enum
from itertools import zip_longest
from pathlib import Path
from typing import List, Optional, Union
from unittest import mock

import pytest
import semver

from cachi2.core.errors import PackageManagerError, PackageRejected, UnexpectedFormat
from cachi2.core.models.input import Request
from cachi2.core.models.output import BuildConfig, Component, EnvironmentVariable, RequestOutput
from cachi2.core.package_managers.yarn.main import (
    _check_lockfile,
    _check_zero_installs,
    _configure_yarn_version,
    _fetch_dependencies,
    _generate_environment_variables,
    _set_yarnrc_configuration,
    _verify_corepack_yarn_version,
    _verify_yarnrc_paths,
    fetch_yarn_source,
)
from cachi2.core.package_managers.yarn.project import Plugin, YarnRc
from cachi2.core.rooted_path import RootedPath


@pytest.fixture
def yarn_input_packages(request: pytest.FixtureRequest) -> list[dict[str, str]]:
    return request.param


@pytest.fixture
def yarn_request(tmp_path: Path, yarn_input_packages: list[dict[str, str]]) -> Request:
    # Create folder in the specified path, otherwise Request validation would fail
    for package in yarn_input_packages:
        if "path" in package:
            (tmp_path / package["path"]).mkdir(exist_ok=True)

    return Request(
        source_dir=tmp_path,
        output_dir=tmp_path / "output",
        packages=yarn_input_packages,
    )


@pytest.fixture(scope="module")
def yarn_env_variables() -> list[EnvironmentVariable]:
    return [
        EnvironmentVariable(name="YARN_ENABLE_GLOBAL_CACHE", value="false"),
        EnvironmentVariable(name="YARN_ENABLE_IMMUTABLE_CACHE", value="false"),
        EnvironmentVariable(name="YARN_ENABLE_MIRROR", value="true"),
        EnvironmentVariable(name="YARN_GLOBAL_FOLDER", value="${output_dir}/deps/yarn"),
    ]


class YarnVersions(Enum):
    YARN_V1 = semver.VersionInfo(1, 0, 0)
    YARN_V2 = semver.VersionInfo(2, 0, 0)

    YARN_V3_RC1 = semver.VersionInfo(3, 0, 0, prerelease="rc1")
    YARN_V3 = semver.VersionInfo(3, 0, 0)
    YARN_V36_RC1 = semver.VersionInfo(3, 6, 0, prerelease="rc1")

    YARN_V4_RC1 = semver.VersionInfo(4, 0, 0, prerelease="rc1")
    YARN_V4 = semver.VersionInfo(4, 0, 0)

    @classmethod
    def supported(cls) -> List["YarnVersions"]:
        return [cls.YARN_V3, cls.YARN_V36_RC1]

    @classmethod
    def unsupported(cls) -> List["YarnVersions"]:
        return list(set(cls.__members__.values()).difference(set(cls.supported())))


SAMPLE_PLUGINS = """
plugins:
  - path: .yarn/plugins/@yarnpkg/plugin-typescript.cjs
    spec: "@yarnpkg/plugin-typescript"
  - path: .yarn/plugins/@yarnpkg/plugin-exec.cjs
    spec: "@yarnpkg/plugin-exec"
"""


@pytest.mark.parametrize(
    "yarn_path_version, package_manager_version",
    [
        pytest.param(YarnVersions.YARN_V3.value, None, id="valid-yarnpath-no-packagemanager"),
        pytest.param(YarnVersions.YARN_V36_RC1.value, None, id="minor-version-with-prerelease"),
        pytest.param(None, YarnVersions.YARN_V3.value, id="no-yarnpath-valid-packagemanager"),
        pytest.param(
            YarnVersions.YARN_V3.value,
            YarnVersions.YARN_V3.value,
            id="matching-yarnpath-and-packagemanager",
        ),
        pytest.param(
            semver.VersionInfo(3, 0, 0),
            semver.VersionInfo(
                3, 0, 0, build="sha224.953c8233f7a92884eee2de69a1b92d1f2ec1655e66d08071ba9a02fa"
            ),
            id="matching-yarnpath-and-packagemanager-with-build",
        ),
    ],
)
@mock.patch("cachi2.core.package_managers.yarn.main._verify_corepack_yarn_version")
@mock.patch("cachi2.core.package_managers.yarn.main.get_semver_from_package_manager")
@mock.patch("cachi2.core.package_managers.yarn.main.get_semver_from_yarn_path")
def test_configure_yarn_version(
    mock_yarn_path_semver: mock.Mock,
    mock_package_manager_semver: mock.Mock,
    mock_verify_corepack: mock.Mock,
    yarn_path_version: Optional[semver.version.Version],
    package_manager_version: Optional[semver.version.Version],
) -> None:
    mock_project = mock.Mock()
    mock_project.package_json.package_manager = None
    mock_yarn_path_semver.return_value = yarn_path_version
    mock_package_manager_semver.return_value = package_manager_version

    _configure_yarn_version(mock_project)

    if package_manager_version is None:
        assert mock_project.package_json.package_manager == f"yarn@{yarn_path_version}"
        mock_project.package_json.write.assert_called_once()
    else:
        assert mock_project.package_json.package_manager is None
        mock_project.package_json.write.assert_not_called()

    mock_verify_corepack.assert_called_once_with(
        yarn_path_version or package_manager_version, mock_project.source_dir
    )


@pytest.mark.parametrize(
    "corepack_yarn_version",
    [
        pytest.param("1.0.0", id="yarn_versions_match"),
        pytest.param("1.0.0\n", id="yarn_versions_match_with_whitespace"),
    ],
)
@mock.patch("cachi2.core.package_managers.yarn.main.run_yarn_cmd")
def test_corepack_installed_correct_yarn_version(
    mock_run_yarn_cmd: mock.Mock,
    corepack_yarn_version: str,
    rooted_tmp_path: RootedPath,
) -> None:
    expected_yarn_version = YarnVersions.YARN_V1.value
    mock_run_yarn_cmd.return_value = corepack_yarn_version

    _verify_corepack_yarn_version(expected_yarn_version, rooted_tmp_path)
    mock_run_yarn_cmd.assert_called_once_with(["--version"], rooted_tmp_path)


@pytest.mark.parametrize(
    "corepack_yarn_version",
    [
        pytest.param("2.0.0", id="yarn_versions_do_not_match"),
        pytest.param("2", id="invalid_semver"),
    ],
)
@mock.patch("cachi2.core.package_managers.yarn.main.run_yarn_cmd")
def test_corepack_installed_correct_yarn_version_fail(
    mock_run_yarn_cmd: mock.Mock,
    corepack_yarn_version: str,
    rooted_tmp_path: RootedPath,
) -> None:
    expected_yarn_version = YarnVersions.YARN_V1.value
    mock_run_yarn_cmd.return_value = corepack_yarn_version

    with pytest.raises(PackageManagerError):
        _verify_corepack_yarn_version(expected_yarn_version, rooted_tmp_path)

    mock_run_yarn_cmd.assert_called_once_with(["--version"], rooted_tmp_path)


@pytest.mark.parametrize(
    "yarn_path_version, package_manager_version, expected_error",
    [
        pytest.param(
            None,
            None,
            PackageRejected(
                "Unable to determine the yarn version to use to process the request",
                solution="Ensure that either yarnPath is defined in .yarnrc or that packageManager is defined in package.json",
            ),
            id="no-yarnpath-no-packagemanager",
        ),
        pytest.param(
            None,
            UnexpectedFormat("some error about packageManager formatting"),
            UnexpectedFormat("some error about packageManager formatting"),
            id="exception-parsing-packagemanager",
        ),
        pytest.param(
            semver.VersionInfo(3, 0, 1),
            semver.VersionInfo(3, 0, 0),
            PackageRejected(
                "Mismatch between the yarn versions specified by yarnPath (yarn@3.0.1) and packageManager (yarn@3.0.0)",
                solution="Ensure that the yarnPath version in .yarnrc and the packageManager version in package.json agree",
            ),
            id="yarnpath-packagemanager-mismatch",
        ),
    ],
)
@mock.patch("cachi2.core.package_managers.yarn.main.get_semver_from_package_manager")
@mock.patch("cachi2.core.package_managers.yarn.main.get_semver_from_yarn_path")
def test_configure_yarn_version_fail(
    mock_yarn_path_semver: mock.Mock,
    mock_package_manager_semver: mock.Mock,
    yarn_path_version: Optional[semver.version.Version],
    package_manager_version: Union[semver.version.Version, None, Exception],
    expected_error: Exception,
) -> None:
    mock_project = mock.Mock()
    mock_yarn_path_semver.return_value = yarn_path_version
    mock_package_manager_semver.side_effect = [package_manager_version]

    with pytest.raises(type(expected_error), match=re.escape(str(expected_error))):
        _configure_yarn_version(mock_project)


YARN_VERSIONS = [yarn_version.value for yarn_version in YarnVersions.unsupported()]


@pytest.mark.parametrize(
    "package_manager_version, yarn_path_version",
    [
        pytest.param(
            pkg_mgr_version,
            yarn_path_version,
            id=f"package_manager,yarn_path-({str(pkg_mgr_version)}, {str(yarn_path_version)})",
        )
        for pkg_mgr_version, yarn_path_version in zip_longest(YARN_VERSIONS, YARN_VERSIONS[:1])
    ],
)
@mock.patch("cachi2.core.package_managers.yarn.main.get_semver_from_package_manager")
@mock.patch("cachi2.core.package_managers.yarn.main.get_semver_from_yarn_path")
def test_yarn_unsupported_version_fail(
    mock_yarn_path_semver: mock.Mock,
    mock_package_manager_semver: mock.Mock,
    package_manager_version: Union[semver.version.Version, None, Exception],
    yarn_path_version: semver.version.Version,
) -> None:
    mock_project = mock.Mock()
    mock_yarn_path_semver.return_value = None
    mock_package_manager_semver.return_value = package_manager_version

    with pytest.raises(
        PackageRejected, match=f"Unsupported Yarn version '{package_manager_version}'"
    ):
        _configure_yarn_version(mock_project)


@mock.patch("cachi2.core.package_managers.yarn.main.run_yarn_cmd")
def test_fetch_dependencies(mock_yarn_cmd: mock.Mock, rooted_tmp_path: RootedPath) -> None:
    mock_yarn_cmd.side_effect = PackageManagerError("berryscary")

    with pytest.raises(PackageManagerError):
        _fetch_dependencies(rooted_tmp_path)

    mock_yarn_cmd.assert_called_once_with(["install", "--mode", "skip-build"], rooted_tmp_path)


def test_resolve_zero_installs_fail() -> None:
    project = mock.Mock()
    project.is_zero_installs = True

    with pytest.raises(
        PackageRejected,
        match=("Yarn zero install detected, PnP zero installs are unsupported by cachi2"),
    ):
        _check_zero_installs(project)


@pytest.mark.parametrize(
    "yarn_rc_content, expected_plugins",
    [
        pytest.param("", [], id="empty_yarn_rc"),
        pytest.param(
            SAMPLE_PLUGINS,
            [
                {
                    "path": ".yarn/plugins/@yarnpkg/plugin-exec.cjs",
                    "spec": "@yarnpkg/plugin-exec",
                },
            ],
            id="yarn_rc_with_default_plugins",
        ),
    ],
)
@mock.patch("cachi2.core.package_managers.yarn.project.YarnRc.write")
def test_set_yarnrc_configuration(
    mock_write: mock.Mock,
    yarn_rc_content: str,
    expected_plugins: list[Plugin],
    rooted_tmp_path: RootedPath,
) -> None:
    yarn_rc_path = rooted_tmp_path.join_within_root(".yarnrc.yml")
    with open(yarn_rc_path, "w") as f:
        f.write(yarn_rc_content)
    yarn_rc = YarnRc.from_file(yarn_rc_path)

    project = mock.Mock()
    project.yarn_rc = yarn_rc
    output_dir = RootedPath("/tmp/output")

    _set_yarnrc_configuration(project, output_dir)

    expected_data = {
        "checksumBehavior": "throw",
        "enableGlobalCache": True,
        "enableImmutableInstalls": True,
        "enableMirror": False,
        "enableScripts": False,
        "enableStrictSsl": True,
        "enableTelemetry": False,
        "globalFolder": "/tmp/output/deps/yarn",
        "ignorePath": True,
        "unsafeHttpWhitelist": [],
        "pnpMode": "strict",
        "plugins": expected_plugins,
    }

    assert yarn_rc._data == expected_data
    assert mock_write.called_once()


def test_verify_yarnrc_paths() -> None:
    output_dir = RootedPath("/tmp/output")
    yarn_rc = YarnRc(RootedPath("/tmp/.yarnrc.yml"), {})
    project = mock.Mock()
    project.yarn_rc = yarn_rc

    _set_yarnrc_configuration(project, output_dir)
    _verify_yarnrc_paths(project)


def test_check_missing_lockfile(rooted_tmp_path: RootedPath) -> None:
    project = mock.Mock()
    project.source_dir = rooted_tmp_path
    project.yarn_rc = YarnRc(project.source_dir.join_within_root(".yarnrc.yml"), {})

    with pytest.raises(
        PackageRejected,
        match=f"Yarn lockfile '{project.yarn_rc.lockfilename}' missing, refusing to continue",
    ):
        _check_lockfile(project)


@pytest.mark.parametrize(
    "opt_path",
    [
        pytest.param("/custom/path", id="installStatePath"),
        pytest.param("/custom/path", id="patchFolder"),
        pytest.param("/custom/path", id="pnpDataPath"),
        pytest.param("/custom/path", id="pnpUnpluggedFolder"),
        pytest.param("/custom/path", id="virtualFolder"),
    ],
)
def test_verify_yarnrc_paths_fail(
    request: pytest.FixtureRequest, tmp_path: Path, opt_path: str
) -> None:
    project = mock.Mock()
    project.source_dir = tmp_path
    project.yarn_rc = YarnRc(
        RootedPath(tmp_path / ".yarnrc.yml"), {request.node.callspec.id: opt_path}
    )

    with pytest.raises(PackageRejected):
        _verify_yarnrc_paths(project)


def test_generate_environment_variables(yarn_env_variables: list[EnvironmentVariable]) -> None:
    result = _generate_environment_variables()
    assert result == yarn_env_variables


@pytest.mark.parametrize(
    "yarn_input_packages, package_components",
    (
        pytest.param(
            [{"type": "yarn", "path": "."}],
            [
                [
                    Component(
                        name="foo",
                        purl="pkg:npm/foo@1.0.0",
                        version="1.0.0",
                    ),
                    Component(
                        name="bar",
                        purl="pkg:npm/bar@2.0.0",
                        version="2.0.0",
                    ),
                ],
            ],
            id="single_input_package",
        ),
        pytest.param(
            [{"type": "yarn", "path": "."}, {"type": "yarn", "path": "./path"}],
            [
                [
                    Component(
                        name="foo",
                        purl="pkg:npm/foo@1.0.0",
                        version="1.0.0",
                    ),
                ],
                [
                    Component(
                        name="bar",
                        purl="pkg:npm/bar@2.0.0",
                        version="2.0.0",
                    ),
                    Component(
                        name="baz",
                        purl="pkg:npm/baz@3.0.0",
                        version="3.0.0",
                    ),
                ],
            ],
            id="multiple_input_packages",
        ),
    ),
    indirect=["yarn_input_packages"],
)
@mock.patch("cachi2.core.package_managers.yarn.main._resolve_yarn_project")
@mock.patch("cachi2.core.package_managers.yarn.project.Project.from_source_dir")
def test_fetch_yarn_source(
    mock_project_from_source_dir: mock.Mock,
    mock_resolve_yarn: mock.Mock,
    package_components: list[Component],
    yarn_request: Request,
    yarn_env_variables: list[EnvironmentVariable],
) -> None:
    mock_project = [mock.Mock() for _ in yarn_request.packages]
    mock_project_from_source_dir.side_effect = mock_project
    mock_resolve_yarn.side_effect = package_components

    output = fetch_yarn_source(yarn_request)

    calls = [
        mock.call(
            yarn_request.source_dir.join_within_root(package.path),
        )
        for package in yarn_request.packages
    ]
    mock_project_from_source_dir.assert_has_calls(calls)

    calls = [
        mock.call(
            project,
            yarn_request.output_dir,
        )
        for project in mock_project
    ]
    mock_resolve_yarn.assert_has_calls(calls)

    expected_output = RequestOutput(
        components=list(itertools.chain.from_iterable(package_components)),
        build_config=BuildConfig(environment_variables=yarn_env_variables),
    )
    assert output == expected_output
