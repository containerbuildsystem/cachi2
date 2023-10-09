import re
from typing import Optional

import pytest
import semver

from cachi2.core.errors import UnexpectedFormat
from cachi2.core.package_managers.yarn.project import (
    get_semver_from_package_manager,
    get_semver_from_yarn_path,
)


@pytest.mark.parametrize(
    "yarn_path, expected_result",
    [
        (
            None,
            None,
        ),
        (
            "",
            None,
        ),
        (
            "/some/path/yarn-1.0.cjs",
            None,
        ),
        (
            "/some/path/yarn-1.0.0.cjs",
            semver.VersionInfo(1, 0, 0),
        ),
        (
            "/some/path/yarn-1.0.0-rc.cjs",
            semver.VersionInfo(1, 0, 0, prerelease="rc"),
        ),
        (
            "/some/path/yarn.cjs",
            None,
        ),
    ],
)
def test_get_semver_from_yarn_path(
    yarn_path: str, expected_result: Optional[semver.version.Version]
) -> None:
    yarn_semver = get_semver_from_yarn_path(yarn_path)

    if yarn_semver is None:
        assert expected_result is None
    else:
        assert expected_result is not None
        assert yarn_semver == expected_result


@pytest.mark.parametrize(
    "package_manager, expected_result",
    [
        (
            None,
            None,
        ),
        (
            "",
            None,
        ),
        (
            "yarn@1.0.0",
            semver.VersionInfo(1, 0, 0),
        ),
        (
            "yarn@1.0.0-rc",
            semver.VersionInfo(1, 0, 0, prerelease="rc"),
        ),
        (
            "yarn@1.0.0+sha224.953c8233f7a92884eee2de69a1b92d1f2ec1655e66d08071ba9a02fa",
            semver.VersionInfo(
                1, 0, 0, build="sha224.953c8233f7a92884eee2de69a1b92d1f2ec1655e66d08071ba9a02fa"
            ),
        ),
        (
            "yarn@1.0.0-rc+sha224.953c8233f7a92884eee2de69a1b92d1f2ec1655e66d08071ba9a02fa",
            semver.VersionInfo(
                1,
                0,
                0,
                prerelease="rc",
                build="sha224.953c8233f7a92884eee2de69a1b92d1f2ec1655e66d08071ba9a02fa",
            ),
        ),
    ],
)
def test_get_semver_from_package_manager(
    package_manager: str, expected_result: Optional[semver.version.Version]
) -> None:
    yarn_semver = get_semver_from_package_manager(package_manager)

    if yarn_semver is None:
        assert expected_result is None
    else:
        assert expected_result is not None
        assert yarn_semver == expected_result


@pytest.mark.parametrize(
    "package_manager, expected_error",
    [
        (
            "no-one-expected-it",
            "could not parse packageManager spec in package.json (expected name@semver)",
        ),
        (
            "yarn@1.0",
            "1.0 is not a valid semver for packageManager in package.json",
        ),
        (
            "npm@1.0.0",
            "packageManager in package.json must be yarn",
        ),
    ],
)
def test_get_semver_from_package_manager_fail(package_manager: str, expected_error: str) -> None:
    with pytest.raises(UnexpectedFormat, match=re.escape(expected_error)):
        get_semver_from_package_manager(package_manager)
