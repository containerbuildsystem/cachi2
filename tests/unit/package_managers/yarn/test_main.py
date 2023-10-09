from typing import Optional
from unittest import mock

import pytest
import semver

from cachi2.core.errors import PackageRejected, UnexpectedFormat
from cachi2.core.package_managers.yarn.main import _configure_yarn_version


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
    mock_yarn_path_semver.return_value = yarn_path_version
    mock_package_manager_semver.return_value = package_manager_version

    _configure_yarn_version(mock_project)

    if package_manager_version is None:
        assert mock_project.package_json.package_manager == f"yarn@{yarn_path_version}"
        mock_project.package_json.to_file.assert_called_once()


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
                "Unable to determine the yarn version to use to process the request",
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
    package_manager_version: Optional[semver.version.Version],
    expected_error: Exception,
) -> None:
    mock_project = mock.Mock()
    mock_yarn_path_semver.return_value = yarn_path_version
    mock_package_manager_semver.side_effect = [package_manager_version]

    with pytest.raises(type(expected_error), match=str(expected_error)):
        _configure_yarn_version(mock_project)
