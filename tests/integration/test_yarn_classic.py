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
                branch="yarn-classic/corepack-ignored",
                packages=({"path": ".", "type": "yarn"},),
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
                branch="yarn-classic/yarn-path-ignored",
                packages=({"path": ".", "type": "yarn"},),
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
                branch="yarn-classic/invalid-checksum",
                packages=({"path": ".", "type": "yarn"},),
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
                branch="yarn-classic/frozen-lockfile",
                packages=({"path": ".", "type": "yarn"},),
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
                branch="yarn-classic/lifecycle-scripts",
                packages=({"path": ".", "type": "yarn"},),
                check_output=False,
                check_deps_checksums=False,
                check_vendor_checksums=False,
                expected_exit_code=0,
                expected_output="All dependencies fetched successfully",
            ),
            id="yarn_classic_lifecycle_scripts",
        ),
        pytest.param(
            utils.TestParameters(
                branch="yarn-classic/offline-mirror-collision",
                packages=({"path": ".", "type": "yarn"},),
                check_output=False,
                check_deps_checksums=False,
                check_vendor_checksums=False,
                expected_exit_code=1,
                expected_output="Duplicate tarballs detected",
            ),
            id="yarn_classic_offline_mirror_collision",
        ),
    ],
)
def test_yarn_classic_packages(
    test_params: utils.TestParameters,
    cachi2_image: utils.ContainerImage,
    tmp_path: Path,
    test_repo_dir: Path,
    test_data_dir: Path,
    request: pytest.FixtureRequest,
) -> None:
    """
    Test fetched dependencies for yarn classic.

    :param test_params: Test case arguments
    :param tmp_path: Temp directory for pytest
    """
    test_case = request.node.callspec.id

    utils.fetch_deps_and_check_output(
        tmp_path, test_case, test_params, test_repo_dir, test_data_dir, cachi2_image
    )


@pytest.mark.parametrize(
    "test_params, check_cmd, expected_cmd_output",
    [
        pytest.param(
            utils.TestParameters(
                branch="yarn-classic/e2e",
                packages=({"path": ".", "type": "yarn"},),
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
                branch="yarn-classic/e2e-multiple-packages",
                packages=(
                    {"path": "first-pkg", "type": "yarn"},
                    {"path": "second-pkg", "type": "yarn"},
                ),
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
    test_repo_dir: Path,
    test_data_dir: Path,
    request: pytest.FixtureRequest,
) -> None:
    """End to end test for yarn classic."""
    test_case = request.node.callspec.id

    utils.fetch_deps_and_check_output(
        tmp_path, test_case, test_params, test_repo_dir, test_data_dir, cachi2_image
    )

    utils.build_image_and_check_cmd(
        tmp_path,
        test_repo_dir,
        test_data_dir,
        test_case,
        check_cmd,
        expected_cmd_output,
        cachi2_image,
    )
