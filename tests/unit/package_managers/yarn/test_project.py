import re
from typing import Optional

import pytest
import semver

from cachi2.core.errors import PackageRejected, UnexpectedFormat
from cachi2.core.package_managers.yarn.project import (
    PackageJson,
    Project,
    YarnRc,
    get_semver_from_package_manager,
    get_semver_from_yarn_path,
)
from cachi2.core.rooted_path import PathOutsideRoot, RootedPath

VALID_YARNRC_FILE = """
plugins:
  - path: .yarn/plugins/@yarnpkg/plugin-typescript.cjs
    spec: "@yarnpkg/plugin-typescript"
  - path: .yarn/plugins/@yarnpkg/plugin-exec.cjs
    spec: "@yarnpkg/plugin-exec"

yarnPath: .custom/path/yarn-3.6.1.cjs

enableInlineBuilds: true

supportedArchitectures:
  os:
    - "linux"

cacheFolder: ./.custom/cache

npmRegistryServer: https://registry.alternative.com

npmScopes:
    foobar:
        npmRegistryServer: https://registry.foobar.com
"""

EMPTY_YML_FILE = ""

INVALID_YML = "this: is: not: valid: yaml"

VALID_PACKAGE_JSON_FILE = """
{
  "name": "camelot",
  "packageManager": "yarn@3.6.1"
}
"""

EMPTY_JSON_FILE = "{}"

INVALID_JSON = "totally not json"


# --- YarnRc tests ---


def _prepare_yarnrc_file(rooted_tmp_path: RootedPath, data: str) -> YarnRc:
    path = rooted_tmp_path.join_within_root(".yarnrc.yml")

    with open(path, "w") as f:
        f.write(data)

    return YarnRc.from_file(path)


def test_parse_yarnrc(rooted_tmp_path: RootedPath) -> None:
    yarn_rc = _prepare_yarnrc_file(rooted_tmp_path, VALID_YARNRC_FILE)

    assert yarn_rc.cache_folder == "./.custom/cache"
    assert yarn_rc.registry_server == "https://registry.alternative.com"
    assert yarn_rc.registry_server_for_scope("foobar") == "https://registry.foobar.com"
    assert yarn_rc.registry_server_for_scope("barfoo") == "https://registry.alternative.com"
    assert yarn_rc.yarn_path == ".custom/path/yarn-3.6.1.cjs"


def test_parse_empty_yarnrc(rooted_tmp_path: RootedPath) -> None:
    yarn_rc = _prepare_yarnrc_file(rooted_tmp_path, EMPTY_YML_FILE)

    assert yarn_rc.cache_folder == "./.yarn/cache"
    assert yarn_rc.registry_server == "https://registry.yarnpkg.com"
    assert yarn_rc.registry_server_for_scope("foobar") == "https://registry.yarnpkg.com"
    assert yarn_rc.yarn_path is None


def test_parse_invalid_yarnrc(rooted_tmp_path: RootedPath) -> None:
    with pytest.raises(PackageRejected, match="Can't parse the .yarnrc.yml file"):
        _prepare_yarnrc_file(rooted_tmp_path, INVALID_YML)


# --- PackageJson tests ---


def _prepare_package_json_file(rooted_tmp_path: RootedPath, data: str) -> PackageJson:
    path = rooted_tmp_path.join_within_root("package.json")

    with open(path, "w") as f:
        f.write(data)

    return PackageJson.from_file(path)


def test_parse_package_json(rooted_tmp_path: RootedPath) -> None:
    package_json = _prepare_package_json_file(rooted_tmp_path, VALID_PACKAGE_JSON_FILE)
    assert package_json.package_manager == "yarn@3.6.1"


def test_parse_empty_package_json_file(rooted_tmp_path: RootedPath) -> None:
    package_json = _prepare_package_json_file(rooted_tmp_path, EMPTY_JSON_FILE)
    assert package_json.package_manager is None


def test_parse_invalid_package_json_file(rooted_tmp_path: RootedPath) -> None:
    with pytest.raises(PackageRejected, match="Can't parse the package.json file"):
        _prepare_package_json_file(rooted_tmp_path, INVALID_JSON)


# --- Project tests ---


def _add_mock_yarn_cache_file(cache_path: RootedPath) -> None:
    cache_path.path.mkdir(parents=True)
    file = cache_path.join_within_root("mock-package-0.0.1.zip")
    file.path.touch()


@pytest.mark.parametrize(
    "is_zero_installs",
    (
        pytest.param(True, id="zero-installs-project"),
        pytest.param(False, id="regular-workflow-project"),
    ),
)
def test_parse_project_folder(rooted_tmp_path: RootedPath, is_zero_installs: bool) -> None:
    _prepare_package_json_file(rooted_tmp_path, VALID_PACKAGE_JSON_FILE)
    _prepare_yarnrc_file(rooted_tmp_path, VALID_YARNRC_FILE)

    cache_path = "./.custom/cache"

    if is_zero_installs:
        _add_mock_yarn_cache_file(rooted_tmp_path.join_within_root(cache_path))

    project = Project.from_source_dir(rooted_tmp_path)

    assert project.is_zero_installs == is_zero_installs
    assert project.yarn_cache == rooted_tmp_path.join_within_root(cache_path)

    assert project.yarn_rc is not None
    assert project.yarn_rc._path == rooted_tmp_path.join_within_root(".yarnrc.yml")
    assert project.package_json._path == rooted_tmp_path.join_within_root("package.json")


@pytest.mark.parametrize(
    "is_zero_installs",
    (
        pytest.param(True, id="zero-installs-project"),
        pytest.param(False, id="regular-workflow-project"),
    ),
)
def test_parse_project_folder_without_yarnrc(
    rooted_tmp_path: RootedPath, is_zero_installs: bool
) -> None:
    _prepare_package_json_file(rooted_tmp_path, VALID_PACKAGE_JSON_FILE)

    if is_zero_installs:
        _add_mock_yarn_cache_file(rooted_tmp_path.join_within_root("./.yarn/cache"))

    project = Project.from_source_dir(rooted_tmp_path)

    assert project.is_zero_installs == is_zero_installs
    assert project.yarn_cache == rooted_tmp_path.join_within_root("./.yarn/cache")

    assert project.yarn_rc._data == {}
    assert project.yarn_rc._path == rooted_tmp_path.join_within_root(".yarnrc.yml")
    assert project.package_json._path == rooted_tmp_path.join_within_root("package.json")


def test_parse_empty_folder(rooted_tmp_path: RootedPath) -> None:
    message = "The package.json file must be present for the yarn package manager"
    with pytest.raises(PackageRejected, match=message):
        Project.from_source_dir(rooted_tmp_path)


def test_parsing_cache_folder_that_resolves_outside_of_the_repository(
    rooted_tmp_path: RootedPath,
) -> None:
    yarn_rc = VALID_YARNRC_FILE.replace("./.custom/cache", "../.custom/cache")

    _prepare_yarnrc_file(rooted_tmp_path, yarn_rc)
    _prepare_package_json_file(rooted_tmp_path, VALID_PACKAGE_JSON_FILE)

    project = Project.from_source_dir(rooted_tmp_path)

    with pytest.raises(PathOutsideRoot):
        project.yarn_cache


# --- Semver parsing tests ---


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
