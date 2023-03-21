import logging
from pathlib import Path
from typing import List

import pytest

from . import utils

log = logging.getLogger(__name__)


@pytest.mark.parametrize(
    "test_params",
    [
        pytest.param(
            utils.TestParameters(
                repo="https://github.com/cachito-testing/cachito-pip-without-deps.git",
                ref="3fe2fc3cb8ffa36317cacbd9d356e35e17af2824",
                packages=({"path": ".", "type": "pip"},),
                check_vendor_checksums=False,
                expected_exit_code=0,
                expected_output="All dependencies fetched successfully",
            ),
            id="pip_without_deps",
        ),
        pytest.param(
            utils.TestParameters(
                repo="https://github.com/cachito-testing/cachito-pip-with-deps.git",
                ref="56efa5f7eb4ff1b7ea1409dbad76f5bb378291e6",
                packages=({"path": ".", "type": "pip"},),
                check_vendor_checksums=False,
                expected_exit_code=0,
                expected_output="All dependencies fetched successfully",
            ),
            id="pip_with_deps",
        ),
        pytest.param(
            utils.TestParameters(
                repo="https://github.com/cachito-testing/cachito-pip-multiple.git",
                ref="93c6c44b36075454a509d595850b81be29e53db0",
                packages=(
                    {"path": "first_pkg", "type": "pip"},
                    {"path": "second_pkg", "type": "pip"},
                ),
                check_vendor_checksums=False,
                expected_exit_code=0,
                expected_output="All dependencies fetched successfully",
            ),
            id="pip_multiple",
        ),
        # Test case checks that an attempt to fetch a local file will result in failure.
        pytest.param(
            utils.TestParameters(
                repo="https://github.com/cachito-testing/cachito-pip-local-path.git",
                ref="d66f7e029a15e8dc96ced65865344e6088c3fdd5",
                packages=({"path": ".", "type": "pip"},),
                check_output=False,
                check_deps_checksums=False,
                check_vendor_checksums=False,
                expected_exit_code=2,
                expected_output=(
                    "UnsupportedFeature: Direct references with 'file' scheme are not supported, "
                    "'file:///tmp/packages.zip'\n  "
                    "If you need Cachi2 to support this feature, please contact the maintainers."
                ),
            ),
            id="pip_local_path",
        ),
    ],
)
def test_pip_packages(
    test_params: utils.TestParameters,
    cachi2_image: utils.ContainerImage,
    tmp_path: Path,
    test_data_dir: Path,
    request: pytest.FixtureRequest,
):
    """
    Test fetched dependencies for pip.

    :param test_params: Test case arguments
    :param tmp_path: Temp directory for pytest
    """
    test_case = request.node.callspec.id

    source_folder = utils.clone_repository(
        test_params.repo, test_params.ref, f"{test_case}-source", tmp_path
    )

    _ = utils.fetch_deps_and_check_output(
        tmp_path, test_case, test_params, source_folder, test_data_dir, cachi2_image
    )


@pytest.mark.parametrize(
    "test_params,check_cmd,expected_cmd_output",
    [
        # Test case checks fetching pip dependencies, generating environment vars file,
        # building image with all prepared prerequisites and testing if pip packages are present
        # in built image
        pytest.param(
            utils.TestParameters(
                repo="https://github.com/cachito-testing/pip-e2e-test.git",
                ref="bae083d57dc265a899b59859b769e88eb8319404",
                packages=(
                    {
                        "type": "pip",
                        "requirements_files": ["requirements.txt"],
                        "requirements_build_files": ["requirements-build.txt"],
                    },
                ),
                check_vendor_checksums=False,
                expected_exit_code=0,
                expected_output="All dependencies fetched successfully",
            ),
            ["python3", "/opt/test_package_cachi2"],
            "registry.fedoraproject.org/fedora-minimal:37",
            id="pip_e2e_test",
        ),
    ],
)
def test_e2e_pip(
    test_params: utils.TestParameters,
    check_cmd: List[str],
    expected_cmd_output: str,
    cachi2_image: utils.ContainerImage,
    tmp_path: Path,
    test_data_dir: Path,
    request: pytest.FixtureRequest,
):
    """
    End to end test for gomod.

    :param test_params: Test case arguments
    :param tmp_path: Temp directory for pytest
    """
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
