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
                repo="https://github.com/cachito-testing/cachi2-yarn-berry.git",
                ref="08f09b9340c85fbb84c8fb46fc19a235056a178b",
                packages=({"path": ".", "type": "yarn"},),
                check_output=False,
                check_deps_checksums=False,
                check_vendor_checksums=False,
                flags=["--dev-package-managers"],
                expected_exit_code=2,
                expected_output="PackageRejected: Yarn zero install detected, PnP zero installs are unsupported by cachi2",
            ),
            id="yarn_zero_installs",
        ),
        pytest.param(
            utils.TestParameters(
                repo="https://github.com/cachito-testing/cachi2-yarn-berry.git",
                ref="ea24d50fcc20f44f74fc0e7beb482c18349b1002",
                packages=({"path": ".", "type": "yarn"},),
                check_output=False,
                check_vendor_checksums=False,
                check_deps_checksums=False,
                flags=["--dev-package-managers"],
                expected_exit_code=2,
                expected_output="UnsupportedFeature: Found 8 unsupported dependencies, more details in the logs.",
            ),
            id="yarn_disallowed_protocols",
        ),
        pytest.param(
            utils.TestParameters(
                repo="https://github.com/cachito-testing/cachi2-yarn-berry.git",
                ref="712e2e1baff80f8ad6e493babf08318b9051b3c7",
                packages=({"path": ".", "type": "yarn"},),
                check_vendor_checksums=False,
                expected_exit_code=0,
                expected_output="Processing the request using yarn@3.6.1",
                flags=["--dev-package-managers"],
            ),
            id="yarn_correct_version_installed_by_corepack",
        ),
    ],
)
def test_yarn_packages(
    test_params: utils.TestParameters,
    cachi2_image: utils.ContainerImage,
    tmp_path: Path,
    test_data_dir: Path,
    request: pytest.FixtureRequest,
) -> None:
    """
    Test fetched dependencies for yarn berry.

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
