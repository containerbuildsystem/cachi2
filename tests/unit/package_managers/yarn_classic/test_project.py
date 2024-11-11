import json

import pytest

from cachi2.core.errors import PackageRejected
from cachi2.core.package_managers.yarn_classic.project import ConfigFile, PackageJson
from cachi2.core.rooted_path import RootedPath

VALID_PACKAGE_JSON_FILE = """
{
  "name": "camelot",
  "packageManager": "yarn@3.6.1"
}
"""

PNP_PACKAGE_JSON_FILE = """
{
  "name": "camelot",
  "packageManager": "yarn@3.6.1",
  "installConfig": {
    "pnp": true
  }
}
"""

INVALID_JSON_FILE = "totally not json"


def _prepare_config_file(
    rooted_tmp_path: RootedPath, config_file_class: ConfigFile, filename: str, content: str
) -> ConfigFile:
    path = rooted_tmp_path.join_within_root(filename)

    with open(path, "w") as f:
        f.write(content)

    return config_file_class.from_file(path)


@pytest.mark.parametrize(
    "config_file_class, config_file_name, config_file_content, config_kind",
    [
        pytest.param(
            PackageJson, "package.json", VALID_PACKAGE_JSON_FILE, "package_json", id="package_json"
        ),
    ],
)
def test_config_file_attributes(
    rooted_tmp_path: RootedPath,
    config_file_class: ConfigFile,
    config_file_name: str,
    config_file_content: str,
    config_kind: str,
) -> None:
    found_config = _prepare_config_file(
        rooted_tmp_path,
        config_file_class,
        config_file_name,
        config_file_content,
    )
    assert found_config.path.root == rooted_tmp_path.root
    assert found_config.config_kind == config_kind


@pytest.mark.parametrize(
    "config_file_class, config_file_name, config_file_content, content_kind",
    [
        pytest.param(
            PackageJson, "package.json", VALID_PACKAGE_JSON_FILE, "json", id="package_json"
        ),
    ],
)
def test_find_and_open_config_file(
    rooted_tmp_path: RootedPath,
    config_file_class: ConfigFile,
    config_file_name: str,
    config_file_content: str,
    content_kind: str,
) -> None:
    found_config = _prepare_config_file(
        rooted_tmp_path,
        config_file_class,
        config_file_name,
        config_file_content,
    )

    if content_kind == "json":
        assert found_config.data == json.loads(config_file_content)


@pytest.mark.parametrize(
    "config_file_class, config_file_name, config_file_content",
    [
        pytest.param(
            PackageJson,
            "package.json",
            INVALID_JSON_FILE,
            id="invalid_package_json",
        ),
    ],
)
def test_from_file_bad(
    rooted_tmp_path: RootedPath,
    config_file_class: ConfigFile,
    config_file_name: str,
    config_file_content: str,
) -> None:
    with pytest.raises(PackageRejected):
        _prepare_config_file(
            rooted_tmp_path,
            config_file_class,
            config_file_name,
            config_file_content,
        )


@pytest.mark.parametrize(
    "config_file_class, config_file_name",
    [
        pytest.param(
            PackageJson,
            "package.json",
            id="missing_package_json",
        ),
    ],
)
def test_from_file_missing(
    rooted_tmp_path: RootedPath,
    config_file_class: ConfigFile,
    config_file_name: str,
) -> None:
    with pytest.raises(PackageRejected):
        path = rooted_tmp_path.join_within_root(config_file_name)
        config_file_class.from_file(path)
