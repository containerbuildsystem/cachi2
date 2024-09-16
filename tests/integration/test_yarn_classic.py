import logging
from pathlib import Path

import pytest

from . import utils

log = logging.getLogger(__name__)


@pytest.mark.parametrize(
    "test_params",
    [
        pytest.param(
            utils.TestParameters(
                repo="https://github.com/cachito-testing/cachi2-yarn.git",
                ref="3d596bd12839bff7ca8965895f4ce70c00bc3c7f",
                packages=({"path": ".", "type": "yarn-classic"},),
                flags=["--dev-package-managers"],
                check_output=False,
                check_deps_checksums=False,
                check_vendor_checksums=False,
                expected_exit_code=0,
                expected_output="Processing the request using yarn@1.22.",
            ),
            id="yarn_classic_corepack_packagemanager_ignored",
        ),
        pytest.param(
            utils.TestParameters(
                repo="https://github.com/cachito-testing/cachi2-yarn.git",
                ref="e02f9f5ba278ad412e2823acf6f68a521acabfab",
                packages=({"path": ".", "type": "yarn-classic"},),
                flags=["--dev-package-managers"],
                check_output=False,
                check_deps_checksums=False,
                check_vendor_checksums=False,
                expected_exit_code=0,
                expected_output="Processing the request using yarn@1.22.",
            ),
            id="yarn_classic_yarnpath_ignored",
        ),
    ],
)
def test_yarn_classic_packages(
    test_params: utils.TestParameters,
    cachi2_image: utils.ContainerImage,
    tmp_path: Path,
    test_data_dir: Path,
    request: pytest.FixtureRequest,
) -> None:
    """
    Test fetched dependencies for yarn classic.

    :param test_params: Test case arguments
    :param tmp_path: Temp directory for pytest
    """
    test_case = request.node.callspec.id

    source_folder = utils.clone_repository(
        test_params.repo, test_params.ref, f"{test_case}-source", tmp_path
    )

    utils.fetch_deps_and_check_output(
        tmp_path, test_case, test_params, source_folder, test_data_dir, cachi2_image
    )
