# SPDX-License-Identifier: GPL-3.0-or-later

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
                repo="https://github.com/cachito-testing/cachito-gomod-with-deps.git",
                ref="4c65d49cae6bfbada4d479b321d8c0109fa1aa97",
                packages=({"path": ".", "type": "gomod"},),
                check_vendor_checksums=False,
                expected_exit_code=0,
                expected_output="All dependencies fetched successfully",
            ),
            id="gomod_with_deps",
        ),
        pytest.param(
            utils.TestParameters(
                repo="https://github.com/cachito-testing/cachito-gomod-without-deps.git",
                ref="a888f7261b9a9683972fbd77da2d12fe86faef5e",
                packages=({"path": ".", "type": "gomod"},),
                check_vendor_checksums=False,
                expected_exit_code=0,
                expected_output="All dependencies fetched successfully",
            ),
            id="gomod_without_deps",
        ),
        pytest.param(
            utils.TestParameters(
                repo="https://github.com/cachito-testing/gomod-vendored.git",
                ref="ff1960095dd158d3d2a4f31d15b244c24930248b",
                packages=({"path": ".", "type": "gomod"},),
                check_output=False,
                check_deps_checksums=False,
                check_vendor_checksums=False,
                expected_exit_code=2,
                expected_output='The "gomod-vendor" or "gomod-vendor-check" flag'
                " must be set when your repository has vendored dependencies",
            ),
            id="gomod_vendored_without_flag",
        ),
        # Test case checks if vendor folder with dependencies will remain unchanged in cloned
        # source repo, deps folder in output folder should be empty.
        pytest.param(
            utils.TestParameters(
                repo="https://github.com/cachito-testing/gomod-vendored.git",
                ref="ff1960095dd158d3d2a4f31d15b244c24930248b",
                packages=({"path": ".", "type": "gomod"},),
                flags=["--gomod-vendor"],
                expected_exit_code=0,
                expected_output="All dependencies fetched successfully",
            ),
            id="gomod_vendored_with_flag",
        ),
        # Test case checks if vendor folder will be created with dependencies in cloned
        # source repo, deps folder in output folder should be empty.
        pytest.param(
            utils.TestParameters(
                repo="https://github.com/cachito-testing/gomod-vendor-check-no-vendor.git",
                ref="7ba383d5592910edbf7f287d4b5a00c5ababf751",
                packages=({"path": ".", "type": "gomod"},),
                flags=["--gomod-vendor-check"],
                expected_exit_code=0,
                expected_output="All dependencies fetched successfully",
            ),
            id="gomod_vendor_check_no_vendor",
        ),
        # Test case checks if vendor folder with dependencies will remain unchanged in cloned
        # source repo, deps folder in output folder should be empty.
        pytest.param(
            utils.TestParameters(
                repo="https://github.com/cachito-testing/gomod-vendor-check-pass.git",
                ref="0543a5034b687df174c6b12b7b6b9c04770a856f",
                packages=({"path": ".", "type": "gomod"},),
                flags=["--gomod-vendor-check"],
                expected_exit_code=0,
                expected_output="All dependencies fetched successfully",
            ),
            id="gomod_vendor_check_correct_vendor",
        ),
        # Test case checks if request will fail when source provided wrong vendor.
        pytest.param(
            utils.TestParameters(
                repo="https://github.com/cachito-testing/gomod-vendor-check-fail.git",
                ref="8553df6498705b2b36614320ca0c65bc24a1d9e6",
                packages=({"path": ".", "type": "gomod"},),
                flags=["--gomod-vendor-check"],
                check_output=False,
                check_deps_checksums=False,
                check_vendor_checksums=False,
                expected_exit_code=2,
                expected_output=(
                    "PackageRejected: The content of the vendor directory is not "
                    "consistent with go.mod. Please check the logs for more details"
                ),
            ),
            id="gomod_vendor_check_wrong_vendor",
        ),
        # Test case checks if request will fail when source provided empty vendor.
        pytest.param(
            utils.TestParameters(
                repo="https://github.com/cachito-testing/gomod-vendor-check-empty-vendor.git",
                ref="9989e210ac2993196e22d0a23fe18ce460012058",
                packages=({"path": ".", "type": "gomod"},),
                flags=["--gomod-vendor-check"],
                check_output=False,
                check_deps_checksums=False,
                check_vendor_checksums=False,
                expected_exit_code=2,
                expected_output=(
                    "PackageRejected: The content of the vendor directory is not "
                    "consistent with go.mod. Please check the logs for more details"
                ),
            ),
            id="gomod_vendor_check_empty_vendor",
        ),
        # Test case checks if package can be replaced with local dependency
        pytest.param(
            utils.TestParameters(
                repo="https://github.com/cachito-testing/cachito-gomod-local-deps.git",
                ref="b2e465b91a6a272540c77d4dde1e317773ed700b",
                packages=({"path": ".", "type": "gomod"},),
                check_vendor_checksums=False,
                expected_exit_code=0,
                expected_output="All dependencies fetched successfully",
            ),
            id="gomod_local_deps",
        ),
        # Test case checks if fetching dependencies will not fail if non-existent package is
        # imported. main.go imports foobar here as a dependency, but foobar was not generated
        # on the source repository with `go generate`. Cachi2 should recognize here `main` as
        # a package and `foobar` as its dependency.
        pytest.param(
            utils.TestParameters(
                repo="https://github.com/cachito-testing/go-generate-imported.git",
                ref="56659413f7db4f5feed9bbde4560cb55fbb85d67",
                packages=({"path": ".", "type": "gomod"},),
                check_vendor_checksums=False,
                expected_exit_code=0,
                expected_output="All dependencies fetched successfully",
            ),
            id="gomod_go_generate_imported",
        ),
        # Test the handling of missing checksums. Cachi2 should report them via
        # cachi2:missing_hash:in_file properties in the SBOM.
        # See also https://github.com/cachito-testing/gomod-multiple-modules/tree/missing-checksums
        pytest.param(
            utils.TestParameters(
                repo="https://github.com/cachito-testing/gomod-multiple-modules.git",
                ref="5a8c00ce49210e4b42a02003ef9ed0d1574abdae",
                packages=(
                    {"path": ".", "type": "gomod"},
                    {"path": "spam-module", "type": "gomod"},
                    {"path": "eggs-module", "type": "gomod"},
                ),
                check_vendor_checksums=False,
                expected_exit_code=0,
                expected_output="All dependencies fetched successfully",
            ),
            id="gomod_multiple_modules_missing_checksums",
        ),
    ],
)
def test_gomod_packages(
    test_params: utils.TestParameters,
    cachi2_image: utils.ContainerImage,
    tmp_path: Path,
    test_data_dir: Path,
    request: pytest.FixtureRequest,
) -> None:
    """
    Test fetched dependencies for gomod.

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
        # Test case checks fetching retrodep dependencies, generating environment vars file,
        # building image with all prepared prerequisites and printing help message for retrodep
        # app in built image
        pytest.param(
            utils.TestParameters(
                repo="https://github.com/cachito-testing/retrodep.git",
                ref="c3496edd5d45523a1ed300de1575a212b86d00d3",
                packages=({"path": ".", "type": "gomod"},),
                check_vendor_checksums=False,
                expected_exit_code=0,
                expected_output="All dependencies fetched successfully",
            ),
            ["retrodep", "--help"],
            ["retrodep: help requested"],
            id="gomod_1.18_e2e_test",
        ),
        # Test case checks fetching retrodep dependencies, generating environment vars file,
        # building image with all prepared prerequisites and printing help message for retrodep
        # app in built image. The retrodep module specifies minimum go version 1.21.
        pytest.param(
            utils.TestParameters(
                repo="https://github.com/cachito-testing/retrodep.git",
                ref="d0c316edef82e527fed5713f9960cfe7f7c29945",
                packages=({"path": ".", "type": "gomod"},),
                check_vendor_checksums=False,
                expected_exit_code=0,
                expected_output="All dependencies fetched successfully",
            ),
            ["retrodep", "--help"],
            ["retrodep: help requested"],
            id="gomod_1.21_e2e_test",
        ),
        # Check handling of multiple Go modules in one repository. See the README in the testing
        # repository for more details.
        pytest.param(
            utils.TestParameters(
                repo="https://github.com/cachito-testing/gomod-multiple-modules.git",
                ref="d909c337ffc82c7b92a8efa1281a7b6e8152b4a7",
                packages=(
                    {"path": ".", "type": "gomod"},
                    {"path": "spam-module", "type": "gomod"},
                    {"path": "eggs-module", "type": "gomod"},
                ),
                check_vendor_checksums=False,
                expected_exit_code=0,
                expected_output="All dependencies fetched successfully",
            ),
            [],  # check using CMD defined in Dockerfile
            [""],
            id="gomod_e2e_multiple_modules",
        ),
    ],
)
def test_e2e_gomod(
    test_params: utils.TestParameters,
    check_cmd: List[str],
    expected_cmd_output: str,
    cachi2_image: utils.ContainerImage,
    tmp_path: Path,
    test_data_dir: Path,
    request: pytest.FixtureRequest,
) -> None:
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
