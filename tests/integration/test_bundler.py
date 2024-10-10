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
                repo="https://github.com/cachito-testing/cachi2-bundler.git",
                ref="malformed_ruby_missing_gemfile",
                packages=({"path": ".", "type": "bundler"},),
                flags=["--dev-package-managers"],
                check_output=False,
                check_deps_checksums=False,
                check_vendor_checksums=False,
                expected_exit_code=2,
                expected_output="Gemfile and Gemfile.lock must be present in the package directory",
            ),
            id="bundler_no_gemfile",
        ),
        pytest.param(
            utils.TestParameters(
                repo="https://github.com/cachito-testing/cachi2-bundler.git",
                ref="malformed_ruby_missing_gemfile_lock",
                packages=({"path": ".", "type": "bundler"},),
                flags=["--dev-package-managers"],
                check_output=False,
                check_deps_checksums=False,
                check_vendor_checksums=False,
                expected_exit_code=2,
                expected_output="Gemfile and Gemfile.lock must be present in the package directory",
            ),
            id="bundler_no_lockfile",
        ),
        pytest.param(
            utils.TestParameters(
                repo="https://github.com/cachito-testing/cachi2-bundler.git",
                ref="malformed_ruby_missing_git_revision",
                packages=({"path": ".", "type": "bundler"},),
                flags=["--dev-package-managers"],
                check_output=False,
                check_deps_checksums=False,
                check_vendor_checksums=False,
                expected_exit_code=1,
                expected_output="Failed to parse",
            ),
            id="bundler_malformed_lockfile",
        ),
        pytest.param(
            utils.TestParameters(
                repo="https://github.com/cachito-testing/cachi2-bundler.git",
                ref="well_formed_ruby_all_features",
                packages=({"path": ".", "type": "bundler"},),
                flags=["--dev-package-managers"],
                check_output=False,
                check_deps_checksums=False,
                check_vendor_checksums=False,
                expected_exit_code=0,
                expected_output="",
            ),
            id="bundler_everything_present",
        ),
        pytest.param(
            utils.TestParameters(
                repo="https://github.com/cachito-testing/cachi2-bundler.git",
                ref="well_formed_ruby_without_gemspec",
                packages=({"path": ".", "type": "bundler"},),
                flags=["--dev-package-managers"],
                check_output=False,
                check_deps_checksums=False,
                check_vendor_checksums=False,
                expected_exit_code=0,
                expected_output="",
            ),
            id="bundler_everything_present_except_gemspec",
        ),
    ],
)
def test_bundler_packages(
    test_params: utils.TestParameters,
    cachi2_image: utils.ContainerImage,
    tmp_path: Path,
    test_data_dir: Path,
    request: pytest.FixtureRequest,
) -> None:
    """Integration tests for bundler package manager."""
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
                repo="https://github.com/cachito-testing/cachi2-bundler.git",
                ref="well_formed_ruby_all_features",
                packages=({"path": ".", "type": "bundler", "allow_binary": "true"},),
                flags=["--dev-package-managers"],
                check_output=False,
                check_deps_checksums=False,
                check_vendor_checksums=False,
                expected_exit_code=0,
                expected_output="",
            ),
            [],  # No additional commands are run to verify the build
            [],
            id="bundler_everything_present",
        ),
        pytest.param(
            utils.TestParameters(
                repo="https://github.com/cachito-testing/cachi2-bundler.git",
                ref="well_formed_ruby_without_gemspec",
                packages=({"path": ".", "type": "bundler", "allow_binary": "true"},),
                flags=["--dev-package-managers"],
                check_output=False,
                check_deps_checksums=False,
                check_vendor_checksums=False,
                expected_exit_code=0,
                expected_output="",
            ),
            [],  # No additional commands are run to verify the build
            [],
            id="bundler_everything_present_except_gemspec",
        ),
    ],
)
def test_e2e_bundler(
    test_params: utils.TestParameters,
    check_cmd: list[str],
    expected_cmd_output: str,
    cachi2_image: utils.ContainerImage,
    tmp_path: Path,
    test_data_dir: Path,
    request: pytest.FixtureRequest,
) -> None:
    """
    End to end test for bundler.

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
