from unittest import mock

import pytest

from cachi2.core.errors import PackageRejected
from cachi2.core.models.input import GenericPackageInput
from cachi2.core.models.sbom import Component
from cachi2.core.package_managers.generic import (
    DEFAULT_LOCKFILE_NAME,
    _resolve_generic_lockfile,
    fetch_generic_source,
)
from cachi2.core.rooted_path import RootedPath


@pytest.mark.parametrize(
    ["model_input", "components"],
    [
        pytest.param(GenericPackageInput.model_construct(type="generic"), [], id="single_input"),
    ],
)
@mock.patch("cachi2.core.package_managers.rpm.main.RequestOutput.from_obj_list")
@mock.patch("cachi2.core.package_managers.generic._resolve_generic_lockfile")
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


def test_resolve_generic_no_lockfile(rooted_tmp_path: RootedPath) -> None:
    with pytest.raises(PackageRejected) as exc_info:
        _resolve_generic_lockfile(rooted_tmp_path, rooted_tmp_path)
    assert (
        f"Cachi2 generic lockfile '{DEFAULT_LOCKFILE_NAME}' missing, refusing to continue"
        in str(exc_info.value)
    )
