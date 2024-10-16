from pathlib import Path
from typing import Type
from unittest import mock

import pytest
from pydantic_core import Url

from cachi2.core.errors import Cachi2Error, PackageRejected
from cachi2.core.models.input import GenericPackageInput
from cachi2.core.models.sbom import Component
from cachi2.core.package_managers.generic.main import (
    DEFAULT_DEPS_DIR,
    DEFAULT_LOCKFILE_NAME,
    _load_lockfile,
    _resolve_generic_lockfile,
    fetch_generic_source,
)
from cachi2.core.rooted_path import PathOutsideRoot, RootedPath

LOCKFILE_WRONG_VERSION = """
metadata:
    version: '0.42'
artifacts:
    - download_url: https://example.com/artifact
      checksums:
        md5: 3a18656e1cea70504b905836dee14db0
"""

LOCKFILE_CHECKSUM_MISSING = """
metadata:
    version: '1.0'
artifacts:
    - download_url: https://example.com/artifact
"""

LOCKFILE_CHECKSUM_EMPTY = """
metadata:
    version: '1.0'
artifacts:
    - download_url: https://example.com/artifact
      checksums: {}
"""

LOCKFILE_VALID = """
metadata:
    version: '1.0'
artifacts:
    - download_url: https://example.com/artifact
      target: archive.zip
      checksums:
        md5: 3a18656e1cea70504b905836dee14db0
    - download_url: https://example.com/more/complex/path/file.tar.gz?foo=bar#fragment
      checksums:
        md5: 32112bed1914cfe3799600f962750b1d
"""

LOCKFILE_INVALID_TARGET = """
metadata:
    version: '1.0'
artifacts:
    - download_url: https://example.com/artifact
      target: ./../../../archive.zip
      checksums:
        md5: 3a18656e1cea70504b905836dee14db0
"""

LOCKFILE_TARGET_OVERLAP = """
metadata:
    version: '1.0'
artifacts:
    - download_url: https://example.com/artifact
      target: archive.zip
      checksums:
        md5: 3a18656e1cea70504b905836dee14db0
    - download_url: https://example.com/artifact2
      target: archive.zip
      checksums:
        md5: 3a18656e1cea70504b905836dee14db0
"""

LOCKFILE_URL_OVERLAP = """
metadata:
    version: '1.0'
artifacts:
    - download_url: https://example.com/artifact
      checksums:
        md5: 3a18656e1cea70504b905836dee14db0
    - download_url: https://example.com/artifact
      target: archive.zip
      checksums:
        md5: 3a18656e1cea70504b905836dee14db0
"""

LOCKFILE_WRONG_CHECKSUM = """
metadata:
    version: '1.0'
artifacts:
    - download_url: https://example.com/artifact
      target: archive.zip
      checksums:
        md5: 32112bed1914cfe3799600f962750b1d
"""


@pytest.mark.parametrize(
    ["model_input", "components"],
    [
        pytest.param(GenericPackageInput.model_construct(type="generic"), [], id="single_input"),
    ],
)
@mock.patch("cachi2.core.package_managers.generic.main.RequestOutput.from_obj_list")
@mock.patch("cachi2.core.package_managers.generic.main._resolve_generic_lockfile")
def test_fetch_generic_source(
    mock_resolve_generic_lockfile: mock.Mock,
    mock_from_obj_list: mock.Mock,
    model_input: GenericPackageInput,
    components: list[Component],
) -> None:

    mock_resolve_generic_lockfile.return_value = components

    mock_request = mock.Mock()
    mock_request.generic_packages = [model_input]

    fetch_generic_source(mock_request)

    mock_resolve_generic_lockfile.assert_called()
    mock_from_obj_list.assert_called_with(components=components)


@mock.patch("cachi2.core.package_managers.generic.main._load_lockfile")
def test_resolve_generic_no_lockfile(mock_load: mock.Mock, rooted_tmp_path: RootedPath) -> None:
    with pytest.raises(PackageRejected) as exc_info:
        _resolve_generic_lockfile(rooted_tmp_path, rooted_tmp_path)
    assert (
        f"Cachi2 generic lockfile '{DEFAULT_LOCKFILE_NAME}' missing, refusing to continue"
        in str(exc_info.value)
    )
    mock_load.assert_not_called()


@pytest.mark.parametrize(
    ["lockfile", "expected_exception", "expected_err"],
    [
        pytest.param("{", PackageRejected, "yaml format is not correct", id="invalid_yaml"),
        pytest.param(
            LOCKFILE_WRONG_VERSION, PackageRejected, "Input should be '1.0'", id="wrong_version"
        ),
        pytest.param(
            LOCKFILE_CHECKSUM_MISSING, PackageRejected, "Field required", id="checksum_missing"
        ),
        pytest.param(
            LOCKFILE_CHECKSUM_EMPTY,
            PackageRejected,
            "At least one checksum must be provided",
            id="checksum_empty",
        ),
        pytest.param(
            LOCKFILE_INVALID_TARGET,
            PathOutsideRoot,
            "target is outside",
            id="invalid_target",
        ),
        pytest.param(
            LOCKFILE_TARGET_OVERLAP,
            PackageRejected,
            "Duplicate targets",
            id="conflicting_targets",
        ),
        pytest.param(
            LOCKFILE_URL_OVERLAP,
            PackageRejected,
            "Duplicate download_urls",
            id="conflicting_urls",
        ),
        pytest.param(
            LOCKFILE_WRONG_CHECKSUM,
            PackageRejected,
            "Failed to verify archive.zip against any of the provided checksums.",
            id="wrong_checksum",
        ),
    ],
)
@mock.patch("cachi2.core.package_managers.generic.main.asyncio.run")
@mock.patch("cachi2.core.package_managers.generic.main.async_download_files")
def test_resolve_generic_lockfile_invalid(
    mock_download: mock.Mock,
    mock_asyncio_run: mock.Mock,
    lockfile: str,
    expected_exception: Type[Cachi2Error],
    expected_err: str,
    rooted_tmp_path: RootedPath,
) -> None:
    # setup lockfile
    with open(rooted_tmp_path.join_within_root(DEFAULT_LOCKFILE_NAME), "w") as f:
        f.write(lockfile)

    # setup testing downloaded dependency
    deps_path = rooted_tmp_path.join_within_root(DEFAULT_DEPS_DIR)
    Path.mkdir(deps_path.path, parents=True, exist_ok=True)
    with open(deps_path.join_within_root("archive.zip"), "w") as f:
        f.write("Testfile")

    with pytest.raises(expected_exception) as exc_info:
        _resolve_generic_lockfile(rooted_tmp_path, rooted_tmp_path)

    assert expected_err in str(exc_info.value)


def test_load_generic_lockfile_valid(rooted_tmp_path: RootedPath) -> None:
    expected_lockfile = {
        "metadata": {"version": "1.0"},
        "artifacts": [
            {
                "download_url": Url("https://example.com/artifact"),
                "target": str(rooted_tmp_path.join_within_root("archive.zip")),
                "checksums": {"md5": "3a18656e1cea70504b905836dee14db0"},
            },
            {
                "checksums": {"md5": "32112bed1914cfe3799600f962750b1d"},
                "download_url": Url(
                    "https://example.com/more/complex/path/file.tar.gz?foo=bar#fragment"
                ),
                "target": str(rooted_tmp_path.join_within_root("file.tar.gz")),
            },
        ],
    }

    # setup lockfile
    with open(rooted_tmp_path.join_within_root(DEFAULT_LOCKFILE_NAME), "w") as f:
        f.write(LOCKFILE_VALID)

    assert (
        _load_lockfile(
            rooted_tmp_path.join_within_root(DEFAULT_LOCKFILE_NAME), rooted_tmp_path
        ).model_dump()
        == expected_lockfile
    )
