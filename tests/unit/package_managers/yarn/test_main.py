import re
from typing import Optional, Union
from unittest import mock

import pytest
import semver

from cachi2.core.errors import PackageRejected, UnexpectedFormat, YarnCommandError
from cachi2.core.package_managers.yarn.main import (
    _configure_yarn_version,
    _fetch_dependencies,
    _set_yarnrc_configuration,
)
from cachi2.core.package_managers.yarn.project import YarnRc
from cachi2.core.rooted_path import RootedPath


@pytest.mark.parametrize(
    "yarn_path_version, package_manager_version",
    [
        pytest.param(semver.VersionInfo(1, 0, 0), None, id="valid-yarnpath-no-packagemanager"),
        pytest.param(None, semver.VersionInfo(1, 0, 0), id="no-yarnpath-valid-packagemanager"),
        pytest.param(
            semver.VersionInfo(1, 0, 0),
            semver.VersionInfo(1, 0, 0),
            id="matching-yarnpath-and-packagemanager",
        ),
        pytest.param(
            semver.VersionInfo(1, 0, 0),
            semver.VersionInfo(
                1, 0, 0, build="sha224.953c8233f7a92884eee2de69a1b92d1f2ec1655e66d08071ba9a02fa"
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
            semver.VersionInfo(1, 0, 1),
            semver.VersionInfo(1, 0, 0),
            PackageRejected(
                "Mismatch between the yarn versions specified by yarnPath (yarn@1.0.1) and packageManager (yarn@1.0.0)",
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


@pytest.mark.parametrize(
    "is_zero_installs",
    (
        pytest.param(True, id="zero-installs-project"),
        pytest.param(False, id="regular-workflow-project"),
    ),
)
@mock.patch("cachi2.core.package_managers.yarn.project.YarnRc.write")
def test_set_yarnrc_configuration(mock_write: mock.Mock, is_zero_installs: bool) -> None:
    yarn_rc = YarnRc(RootedPath("/tmp/.yarnrc.yml"), {})

    project = mock.Mock()
    project.is_zero_installs = is_zero_installs
    project.yarn_rc = yarn_rc

    output_dir = RootedPath("/tmp/output")

    _set_yarnrc_configuration(project, output_dir)

    expected_data = {
        "checksumBehavior": "throw",
        "enableImmutableInstalls": True,
        "enableStrictSsl": True,
        "enableTelemetry": False,
        "unsafeHttpWhitelist": [],
        "pnpMode": "strict",
        "plugins": [],
    }

    if project.is_zero_installs:
        expected_data["enableImmutableCache"] = True
    else:
        expected_data["enableMirror"] = True
        expected_data["globalFolder"] = "/tmp/output"

    assert yarn_rc._data == expected_data
    assert mock_write.called_once()
