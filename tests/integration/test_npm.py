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
                ref="cb56134a2543ba56c303b4cd8e7c174cef9de4ea",
                packages=({"path": ".", "type": "npm"},),
            ),
            id="npm_smoketest_lockfile1",
        ),
        pytest.param(
            utils.TestParameters(
                repo="https://github.com/cachito-testing/npm-cachi2-smoketest.git",
                ref="05f841a5b94fb447b4ed428a37d7395d66d9fc6a",
                packages=({"path": ".", "type": "npm"},),
            ),
            id="npm_smoketest_lockfile2",
        ),
        pytest.param(
            utils.TestParameters(
                repo="https://github.com/cachito-testing/npm-cachi2-smoketest.git",
                ref="4baf3d58db432752aa63156597b28a7e775fd862",
                packages=({"path": ".", "type": "npm"},),
            ),
            id="npm_smoketest_lockfile3",
        ),
    ],
)
def test_npm_smoketest(
    test_params: utils.TestParameters,
    cachi2_image: utils.ContainerImage,
    tmp_path: Path,
    test_data_dir: Path,
    request: pytest.FixtureRequest,
):
    """
    Smoketest for npm offline install development.

    :param test_params: Test case arguments
    :param tmp_path: Temp directory for pytest
    """
    test_case = request.node.callspec.id

    utils.clone_repository(test_params.repo, test_params.ref, f"{test_case}-source", tmp_path)

    # TODO: Load SBOM for package-lock.json - STONEBLD-1053

    # TODO: Fetch npm dependencies for source_repo - STONEBLD-1054
