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
        pytest.param(
            utils.TestParameters(
                repo="https://github.com/cachito-testing/cachi2-yarn.git",
                ref="ab0e1befff22af6fe92b75c8a75cb024fa7d8c33",
                packages=({"path": ".", "type": "yarn-classic"},),
                flags=["--dev-package-managers"],
                check_output=False,
                check_deps_checksums=False,
                check_vendor_checksums=False,
                expected_exit_code=1,
                expected_output='Integrity check failed for "@colors/colors"',
            ),
            id="yarn_classic_invalid_checksum",
        ),
        pytest.param(
            utils.TestParameters(
                repo="https://github.com/cachito-testing/cachi2-yarn.git",
                ref="invalid_frozen_lockfile_add_dependency",
                packages=({"path": ".", "type": "yarn-classic"},),
                flags=["--dev-package-managers"],
                check_output=False,
                check_deps_checksums=False,
                check_vendor_checksums=False,
                expected_exit_code=1,
                expected_output="Your lockfile needs to be updated, but yarn was run with `--frozen-lockfile`.",
            ),
            id="yarn_invalid_frozen_lockfile_add_dependency",
        ),
        pytest.param(
            utils.TestParameters(
                repo="https://github.com/cachito-testing/cachi2-yarn.git",
                ref="200cc9423b1df173c12b61f951e463d8a18d9e19",
                packages=({"path": ".", "type": "yarn-classic"},),
                flags=["--dev-package-managers"],
                check_output=False,
                check_deps_checksums=False,
                check_vendor_checksums=False,
                expected_exit_code=0,
                expected_output="All dependencies fetched successfully",
            ),
            id="yarn_classic_lifecycle_scripts",
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


@pytest.mark.parametrize(
    "test_params, check_cmd, expected_cmd_output",
    [
        pytest.param(
            utils.TestParameters(
                repo="https://github.com/cachito-testing/cachi2-yarn.git",
                ref="4fe0919c4b2fb9a0f6fb98999ceaeb732f4b1d9d",
                packages=({"path": ".", "type": "yarn-classic"},),
                flags=["--dev-package-managers"],
                check_vendor_checksums=False,
                expected_exit_code=0,
                expected_output="All dependencies fetched successfully",
            ),
            ["yarn", "node", "index.js"],
            "Hello world!",
            id="yarn_classic_e2e_test",
        ),
        pytest.param(
            utils.TestParameters(
                repo="https://github.com/cachito-testing/cachi2-yarn.git",
                ref="db27afd28d5b5fdc349f3ffb12b0f58140f6be32",
                packages=(
                    {"path": "first-pkg", "type": "yarn-classic"},
                    {"path": "second-pkg", "type": "yarn-classic"},
                ),
                flags=["--dev-package-managers"],
                check_vendor_checksums=False,
                expected_exit_code=0,
                expected_output="All dependencies fetched successfully",
            ),
            ["yarn", "node", "index.js"],
            "Hello from first package!",
            id="yarn_classic_e2e_test_multiple_packages",
        ),
    ],
)
def test_e2e_yarn_classic(
    test_params: utils.TestParameters,
    check_cmd: list[str],
    expected_cmd_output: str,
    cachi2_image: utils.ContainerImage,
    tmp_path: Path,
    test_data_dir: Path,
    request: pytest.FixtureRequest,
) -> None:
    """End to end test for yarn classic."""
    test_case = request.node.callspec.id

    source_folder = utils.clone_repository(
        test_params.repo, test_params.ref, f"{test_case}-source", tmp_path
    )

    output_folder = utils.fetch_deps_and_check_output(
        tmp_path, test_case, test_params, source_folder, test_data_dir, cachi2_image
    )

    utils.build_image_and_check_cmd(
        tmp_path,
        output_folder,
        test_data_dir,
        test_case,
        check_cmd,
        expected_cmd_output,
        cachi2_image,
    )
