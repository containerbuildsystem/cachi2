from pathlib import Path

import pytest

from . import utils


@pytest.mark.parametrize(
    "test_params",
    [
        pytest.param(
            utils.TestParameters(
                repo="https://github.com/cachito-testing/cachi2-generic",
                ref="51714e766c7cfed139fb4927a5b6b6499545f47c",
                packages=({"path": ".", "type": "generic"},),
                flags=["--dev-package-managers"],
                check_output=True,
                check_deps_checksums=True,
                check_vendor_checksums=False,
                expected_exit_code=0,
            ),
            id="generic_e2e",
        ),
        pytest.param(
            utils.TestParameters(
                repo="https://github.com/cachito-testing/cachi2-generic",
                ref="adbc0250695e91b01283550eebcfe648cddcb983",
                packages=({"path": ".", "type": "generic"},),
                flags=["--dev-package-managers"],
                check_output=False,
                check_deps_checksums=False,
                check_vendor_checksums=False,
                expected_exit_code=2,
                expected_output="format is not valid: '('metadata', 'version'): Input should be '1.0'",
            ),
            id="generic_bad_lockfile",
        ),
        pytest.param(
            utils.TestParameters(
                repo="https://github.com/cachito-testing/cachi2-generic",
                ref="04cc5aa38a937ffe64fc15dbf069aef371539875",
                packages=({"path": ".", "type": "generic"},),
                flags=["--dev-package-managers"],
                check_output=False,
                check_deps_checksums=False,
                check_vendor_checksums=False,
                expected_exit_code=2,
                expected_output="PathOutsideRoot",
            ),
            id="generic_bad_target",
        ),
        pytest.param(
            utils.TestParameters(
                repo="https://github.com/cachito-testing/cachi2-generic",
                ref="68cb051f8fbe26bf7deaef4a950bf10d35de7105",
                packages=({"path": ".", "type": "generic"},),
                flags=["--dev-package-managers"],
                check_output=False,
                check_deps_checksums=False,
                check_vendor_checksums=False,
                expected_exit_code=1,
                expected_output="Unsuccessful download",
            ),
            id="generic_file_not_reachable",
        ),
        pytest.param(
            utils.TestParameters(
                repo="https://github.com/cachito-testing/cachi2-generic",
                ref="f8f4963c663d5c2019db1f6bfb4cbae6cc6be330",
                packages=({"path": ".", "type": "generic"},),
                flags=["--dev-package-managers"],
                check_output=False,
                check_deps_checksums=False,
                check_vendor_checksums=False,
                expected_exit_code=2,
                expected_output="Make sure that all targets are unique.",
            ),
            id="generic_target_collision",
        ),
        pytest.param(
            utils.TestParameters(
                repo="https://github.com/cachito-testing/cachi2-generic",
                ref="a20f7196d896ed1fd7956ed76ebff310965627f5",
                packages=({"path": ".", "type": "generic"},),
                flags=["--dev-package-managers"],
                check_output=False,
                check_deps_checksums=False,
                check_vendor_checksums=False,
                expected_exit_code=2,
                expected_output="Failed to verify v1.0.0.zip against any of the provided checksums.",
            ),
            id="generic_checksum_mismatch",
        ),
    ],
)
def test_generic_fetcher(
    test_params: utils.TestParameters,
    cachi2_image: utils.ContainerImage,
    tmp_path: Path,
    test_data_dir: Path,
    top_level_test_dir: Path,
    request: pytest.FixtureRequest,
) -> None:
    """
    Test fetched dependencies for the generic fetcher.

    :param test_params: Test case arguments
    :param tmp_path: Temp directory for pytest
    """
    test_case = request.node.callspec.id

    source_folder = utils.clone_repository(
        test_params.repo, test_params.ref, f"{test_case}-source", tmp_path
    )

    utils.fetch_deps_and_check_output(
        tmp_path,
        test_case,
        test_params,
        source_folder,
        test_data_dir,
        cachi2_image,
    )
