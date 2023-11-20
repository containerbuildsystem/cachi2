import re
from enum import Enum
from itertools import zip_longest
from typing import List, Optional, Union
from unittest import mock

import pytest
import semver

from cachi2.core.errors import PackageRejected, UnexpectedFormat, YarnCommandError
from cachi2.core.package_managers.yarn.main import (
    _configure_yarn_version,
    _fetch_dependencies,
    _resolve_yarn_project,
    _set_yarnrc_configuration,
)
from cachi2.core.package_managers.yarn.project import YarnRc
from cachi2.core.rooted_path import RootedPath


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
@mock.patch("cachi2.core.package_managers.yarn.main.get_semver_from_package_manager")
@mock.patch("cachi2.core.package_managers.yarn.main.get_semver_from_yarn_path")
def test_configure_yarn_version(
    mock_yarn_path_semver: mock.Mock,
    mock_package_manager_semver: mock.Mock,
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
    source_dir = rooted_tmp_path
    output_dir = rooted_tmp_path.join_within_root("cachi2-output")

    mock_yarn_cmd.side_effect = YarnCommandError("berryscary")

    with pytest.raises(YarnCommandError) as exc_info:
        _fetch_dependencies(source_dir, output_dir)

    mock_yarn_cmd.assert_called_once_with(
        ["install", "--mode", "skip-build"],
        source_dir,
        {"YARN_GLOBAL_FOLDER": str(output_dir.join_within_root("deps", "yarn"))},
    )

    assert str(exc_info.value) == "berryscary"


@mock.patch("cachi2.core.package_managers.yarn.main._configure_yarn_version")
def test_resolve_zero_installs_fail(
    mock_configure_yarn_version: mock.Mock, rooted_tmp_path: RootedPath
) -> None:
    mock_configure_yarn_version.return_value = None
    project = mock.Mock()
    project.is_zero_installs = True
    output_dir = rooted_tmp_path.join_within_root("cachi2-output")

    with pytest.raises(
        PackageRejected,
        match=("Yarn zero install detected, PnP zero installs are unsupported by cachi2"),
    ):
        _resolve_yarn_project(project, output_dir)


@mock.patch("cachi2.core.package_managers.yarn.project.YarnRc.write")
def test_set_yarnrc_configuration(mock_write: mock.Mock) -> None:
    yarn_rc = YarnRc(RootedPath("/tmp/.yarnrc.yml"), {})

    project = mock.Mock()
    project.yarn_rc = yarn_rc

    output_dir = RootedPath("/tmp/output")

    _set_yarnrc_configuration(project, output_dir)

    expected_data = {
        "checksumBehavior": "throw",
        "enableImmutableInstalls": True,
        "enableMirror": True,
        "enableScripts": False,
        "enableStrictSsl": True,
        "enableTelemetry": False,
        "globalFolder": "/tmp/output/deps/yarn",
        "ignorePath": True,
        "unsafeHttpWhitelist": [],
        "pnpMode": "strict",
        "plugins": [],
    }

    assert yarn_rc._data == expected_data
    assert mock_write.called_once()
