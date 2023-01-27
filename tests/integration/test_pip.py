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
                check_output_json=False,
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
    tmpdir: Path,
    test_data_dir: Path,
    request: pytest.FixtureRequest,
):
    """
    Test fetched dependencies for pip.

    :param test_params: Test case arguments
    :param tmpdir: Temp directory for pytest
    """
    test_case = request.node.callspec.id

    source_folder = utils.clone_repository(
        test_params.repo, test_params.ref, f"{test_case}-source", tmpdir
    )

    _ = utils.fetch_deps_and_check_output(
        tmpdir, test_case, test_params, source_folder, test_data_dir, cachi2_image
    )
