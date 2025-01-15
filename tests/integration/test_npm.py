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
                repo="https://github.com/cachito-testing/npm-cachi2-bundled.git",
                ref="de68ac6aa88a81272660b6d0f6d44ce157207799",
                packages=({"path": ".", "type": "npm"},),
                check_vendor_checksums=False,
            ),
            id="npm_bundled_lockfile3",
        ),
        pytest.param(
            utils.TestParameters(
                repo="https://github.com/cachito-testing/npm-cachi2-registry-yarnpkg.git",
                ref="f830b62780e75357c38abb7e1102871b51bfbcfe",
                packages=({"path": ".", "type": "npm"},),
                check_vendor_checksums=False,
            ),
            id="npm_lockfile3_yarn_registry",
        ),
    ],
)
def test_npm_packages(
    test_params: utils.TestParameters,
    cachi2_image: utils.ContainerImage,
    tmp_path: Path,
    test_data_dir: Path,
    request: pytest.FixtureRequest,
) -> None:
    """
    Smoketest for npm offline install development.

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
    "test_params,check_cmd,expected_cmd_output",
    [
        pytest.param(
            utils.TestParameters(
                repo="https://github.com/cachito-testing/npm-cachi2-smoketest.git",
                ref="532dd79bde494e90fae261afbb7b464dae2d2e32",
                packages=({"path": ".", "type": "npm"},),
                check_vendor_checksums=False,
            ),
            [],
            [],
            id="npm_smoketest_lockfile2",
        ),
        pytest.param(
            utils.TestParameters(
                repo="https://github.com/cachito-testing/npm-cachi2-smoketest.git",
                ref="f1d31c2b051b218c84399b12461e0957d87bd0cd",
                packages=({"path": ".", "type": "npm"},),
                check_vendor_checksums=False,
            ),
            [],
            [],
            id="npm_smoketest_lockfile3",
        ),
        pytest.param(
            utils.TestParameters(
                repo="https://github.com/cachito-testing/cachito-npm-with-multiple-dep-versions.git",
                ref="97070a9eb06bad62eb581890731221660ade9ea3",
                packages=({"path": ".", "type": "npm"},),
                check_vendor_checksums=False,
            ),
            [],
            [],
            id="npm_lockfile3_multiple_dep_versions",
        ),
        pytest.param(
            utils.TestParameters(
                repo="https://github.com/cachito-testing/npm-with-aliased-deps.git",
                ref="48c5f156b43b8727b10bf464c00847b09e2f25f6",
                packages=({"path": ".", "type": "npm"},),
                check_vendor_checksums=False,
            ),
            [],
            [],
            id="npm_lockfile3_aliased_deps",
        ),
        pytest.param(
            utils.TestParameters(
                repo="https://github.com/cachito-testing/npm-dev-optional-peer-deps.git",
                ref="77018bf73295ef1248d24479da897d960576f933",
                packages=({"path": ".", "type": "npm"},),
                check_vendor_checksums=False,
            ),
            [],
            [],
            id="npm_lockfile3_dev_optional_peer_deps",
        ),
        pytest.param(
            utils.TestParameters(
                repo="https://github.com/cachito-testing/npm-cachi2-multiple-packages.git",
                ref="a721cb61d43d07b0d8276a5b8c4555b1ed75bd39",
                packages=(
                    {"path": "first_pkg", "type": "npm"},
                    {"path": "second_pkg", "type": "npm"},
                    {"path": "third_pkg", "type": "npm"},
                ),
                check_vendor_checksums=False,
            ),
            [],
            [],
            id="npm_multiple_packages_lockfile3",
        ),
    ],
)
def test_e2e_npm(
    test_params: utils.TestParameters,
    check_cmd: List[str],
    expected_cmd_output: str,
    cachi2_image: utils.ContainerImage,
    tmp_path: Path,
    test_data_dir: Path,
    request: pytest.FixtureRequest,
) -> None:
    """
    End to end test for npm.

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
