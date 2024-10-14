from typing import Type
from unittest import mock

import pytest

from cachi2.core.errors import Cachi2Error, PackageManagerError, PackageRejected
from cachi2.core.models.input import GenericPackageInput
from cachi2.core.models.sbom import Component
from cachi2.core.package_managers.generic.main import (
    DEFAULT_LOCKFILE_NAME,
    _load_lockfile,
    _resolve_generic_lockfile,
    fetch_generic_source,
)
from cachi2.core.package_managers.generic.models import GenericLockfileV1
from cachi2.core.rooted_path import RootedPath

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
      checksums:
        md5: 3a18656e1cea70504b905836dee14db0
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
            LOCKFILE_WRONG_VERSION, PackageManagerError, "Input should be '1.0'", id="wrong_version"
        ),
        pytest.param(
            LOCKFILE_CHECKSUM_MISSING, PackageManagerError, "Field required", id="checksum_missing"
        ),
        pytest.param(
            LOCKFILE_CHECKSUM_EMPTY,
            PackageManagerError,
            "At least one checksum must be provided",
            id="checksum_empty",
        ),
    ],
)
def test_resolve_generic_lockfile_invalid(
    lockfile: str,
    expected_exception: Type[Cachi2Error],
    expected_err: str,
    rooted_tmp_path: RootedPath,
) -> None:
    # setup lockfile
    with open(rooted_tmp_path.join_within_root(DEFAULT_LOCKFILE_NAME), "w") as f:
        f.write(lockfile)

    with pytest.raises(expected_exception) as exc_info:
        _resolve_generic_lockfile(rooted_tmp_path, rooted_tmp_path)

    assert expected_err in str(exc_info.value)


@pytest.mark.parametrize(
    ["lockfile", "expected_lockfile"],
    [
        pytest.param(
            LOCKFILE_VALID,
            GenericLockfileV1.model_validate(
                {
                    "metadata": {"version": "1.0"},
                    "artifacts": [
                        {
                            "download_url": "https://example.com/artifact",
                            "checksums": {"md5": "3a18656e1cea70504b905836dee14db0"},
                        }
                    ],
                }
            ),
        ),
    ],
)
def test_resolve_generic_lockfile_valid(
    lockfile: str,
    expected_lockfile: GenericLockfileV1,
    rooted_tmp_path: RootedPath,
) -> None:
    # setup lockfile
    with open(rooted_tmp_path.join_within_root(DEFAULT_LOCKFILE_NAME), "w") as f:
        f.write(lockfile)

    assert (
        _load_lockfile(rooted_tmp_path.join_within_root(DEFAULT_LOCKFILE_NAME)) == expected_lockfile
    )
