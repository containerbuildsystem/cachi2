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
            ),
            id="yarn_correct_version_installed_by_corepack",
        ),
        pytest.param(
            utils.TestParameters(
                repo="https://github.com/cachito-testing/cachi2-yarn-berry.git",
                ref="9d6a941220a1dfb14a6bdb6f3c52d7204a939688",
                packages=({"path": ".", "type": "yarn"},),
                check_output=False,
                check_vendor_checksums=False,
                check_deps_checksums=False,
                expected_exit_code=1,
                expected_output="The lockfile would have been modified by this install, which is explicitly forbidden.",
            ),
            id="yarn_immutable_installs",
        ),
        pytest.param(
            utils.TestParameters(
                repo="https://github.com/cachito-testing/cachi2-yarn-berry.git",
                ref="c5268f91f0a0b68fa72d4f2c3a570d348d194241",
                packages=({"path": ".", "type": "yarn"},),
                check_output=False,
                check_deps_checksums=False,
                check_vendor_checksums=False,
                expected_exit_code=1,
                expected_output="typescript@npm:5.3.3: The remote archive doesn't match the expected checksum",
            ),
            id="yarn_incorrect_checksum",
        ),
        pytest.param(
            utils.TestParameters(
                repo="https://github.com/cachito-testing/cachi2-yarn-berry.git",
                ref="c1da60842aa94aaab8ed48122dc44522bd2a5ab1",
                packages=({"path": ".", "type": "yarn"},),
                check_output=False,
                check_deps_checksums=False,
                check_vendor_checksums=False,
                expected_exit_code=2,
                expected_output="Yarn lockfile 'yarn_non_existent.lock' missing, refusing to continue",
            ),
            id="yarn_no_lockfile",
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


@pytest.mark.parametrize(
    "test_params, check_cmd, expected_cmd_output",
    [
        pytest.param(
            utils.TestParameters(
                repo="https://github.com/cachito-testing/cachi2-yarn-berry.git",
                ref="70515793108df42547d3320c7ea4cd6b6e505c46",
                packages=({"path": ".", "type": "yarn"},),
                check_vendor_checksums=False,
                expected_exit_code=0,
                expected_output="All dependencies fetched successfully",
            ),
            ["yarn", "berryscary"],
            "Hello, World!",
            id="yarn_e2e_test",
        ),
    ],
)
def test_e2e_yarn(
    test_params: utils.TestParameters,
    check_cmd: list[str],
    expected_cmd_output: str,
    cachi2_image: utils.ContainerImage,
    tmp_path: Path,
    test_data_dir: Path,
    request: pytest.FixtureRequest,
) -> None:
    """End to end test for yarn berry."""
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
