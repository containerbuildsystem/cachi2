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
                ref="d8a0c2789446f4119604a0cc5e7eb97f30652f9f",
                packages=(
                    {"path": "first_pkg", "type": "pip"},
                    {
                        "path": "second_pkg",
                        "type": "pip",
                        "requirements_files": [
                            "requirements.txt",
                            "requirements-extra.txt",
                        ],
                    },
                    {"path": "third_pkg", "type": "pip"},
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
        pytest.param(
            utils.TestParameters(
                repo="https://github.com/cachito-testing/cachito-pip-without-metadata.git",
                ref="4fb61a80f9bb19fdd422a74602b108d405ede299",
                packages=(
                    {"path": ".", "type": "pip"},
                    {"path": "subpath1/subpath2", "type": "pip"},
                ),
                check_vendor_checksums=False,
                expected_exit_code=0,
                expected_output="All dependencies fetched successfully",
            ),
            id="pip_without_metadata",
        ),
        pytest.param(
            utils.TestParameters(
                repo="https://github.com/cachito-testing/cachi2-pip-wheels.git",
                ref="331dfac94a9112a3e5d6f667567a02c0d9718ef1",
                packages=({"path": ".", "type": "pip"},),
                check_output=False,
                check_deps_checksums=False,
                check_vendor_checksums=False,
                expected_exit_code=2,
                expected_output="Error: PackageRejected: No distributions found",
            ),
            id="pip_no_sdists_error",
        ),
        # Test case fixes the previous one by adding the `allow_binary` option
        pytest.param(
            utils.TestParameters(
                repo="https://github.com/cachito-testing/cachi2-pip-wheels.git",
                ref="331dfac94a9112a3e5d6f667567a02c0d9718ef1",
                packages=({"path": ".", "type": "pip", "allow_binary": "true"},),
                check_vendor_checksums=False,
                expected_exit_code=0,
                expected_output="All dependencies fetched successfully",
            ),
            id="pip_no_sdists",
        ),
        pytest.param(
            utils.TestParameters(
                repo="https://github.com/cachito-testing/cachi2-pip-wheels.git",
                ref="3697d63affaec82985f1d9b4035d5305e58c91d6",
                packages=({"path": ".", "type": "pip", "allow_binary": "true"},),
                check_vendor_checksums=False,
                expected_exit_code=0,
                expected_output="All dependencies fetched successfully",
            ),
            id="pip_no_wheels",
        ),
    ],
)
def test_pip_packages(
    test_params: utils.TestParameters,
    cachi2_image: utils.ContainerImage,
    tmp_path: Path,
    test_data_dir: Path,
    request: pytest.FixtureRequest,
) -> None:
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
            ["registry.fedoraproject.org/fedora-minimal:37"],
            id="pip_e2e_test",
        ),
        # Same as above, but with wheel distributions - allow binary option is set to true
        pytest.param(
            utils.TestParameters(
                repo="https://github.com/cachito-testing/cachi2-pip-wheels",
                ref="b3dea71a1ad51da90e1161cf71c85e0f7c3e292b",
                packages=(
                    {
                        "type": "pip",
                        "requirements_files": ["requirements.txt"],
                        "requirements_build_files": ["requirements-build.txt"],
                        "allow_binary": "true",
                    },
                ),
                check_vendor_checksums=False,
                expected_exit_code=0,
                expected_output="All dependencies fetched successfully",
            ),
            ["python3", "/opt/package"],
            ["Hello, world!"],
            id="pip_e2e_test_wheels",
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
) -> None:
    """
    End to end test for pip.

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
