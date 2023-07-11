import logging
from pathlib import Path

import pytest

from . import utils

log = logging.getLogger(__name__)


@pytest.mark.parametrize(
    "test_params",
    [
        # Test case checks loading npm dependencies in SBOM format for source repo
        # Plus fetching the dependencies
        pytest.param(
            utils.TestParameters(
                repo="https://github.com/cachito-testing/npm-cachi2-smoketest.git",
                ref="e5bd11ca3a7aacd81aa195275d679d954848c71c",
                packages=({"path": ".", "type": "npm"},),
                check_vendor_checksums=False,
            ),
            id="npm_smoketest_lockfile1",
        ),
        pytest.param(
            utils.TestParameters(
                repo="https://github.com/cachito-testing/npm-cachi2-smoketest.git",
                ref="b9a264fb7244f2cefa782feb1fd8c51ead9fb88b",
                packages=({"path": ".", "type": "npm"},),
                check_vendor_checksums=False,
            ),
            id="npm_smoketest_lockfile2",
        ),
        pytest.param(
            utils.TestParameters(
                repo="https://github.com/cachito-testing/npm-cachi2-smoketest.git",
                ref="f229b5b9c9085dabf71622cc1204c5deef97fbe8",
                packages=({"path": ".", "type": "npm"},),
                check_vendor_checksums=False,
            ),
            id="npm_smoketest_lockfile3",
        ),
        # bundled dependencies, see the repo README for more details
        pytest.param(
            utils.TestParameters(
                repo="https://github.com/cachito-testing/npm-cachi2-bundled.git",
                ref="87937b938d5c737bc4d62f3759478dd5e3e9ebb6",
                packages=({"path": ".", "type": "npm"},),
                check_vendor_checksums=False,
            ),
            id="npm_bundled_lockfile1",
        ),
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
                ref="666e85812266bdad8795e75025ce053ecbb060d9",
                packages=({"path": ".", "type": "npm"},),
                check_vendor_checksums=False,
            ),
            id="npm_lockfile1_yarn_registry",
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
def test_npm_smoketest(
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
