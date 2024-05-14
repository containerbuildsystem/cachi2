import os
import re
from pathlib import Path
from typing import List

import pytest

from . import utils


@pytest.mark.parametrize(
    "test_params",
    [
        pytest.param(
            utils.TestParameters(
                repo="https://github.com/cachito-testing/cachi2-rpm",
                ref="3956e4d095920b3f06b861dbc778a520fdb89fd2",
                packages=({"path": ".", "type": "rpm"},),
                flags=["--dev-package-managers"],
                check_output=True,
                check_deps_checksums=False,
                check_vendor_checksums=False,
                expected_exit_code=0,
            ),
            id="rpm_missing_checksums",
        ),
        pytest.param(
            utils.TestParameters(
                repo="https://github.com/cachito-testing/cachi2-rpm",
                ref="a214ee8db55418ea1d0734cd2a401c97ad896390",
                packages=({"path": ".", "type": "rpm"},),
                flags=["--dev-package-managers"],
                check_output=False,
                check_deps_checksums=False,
                check_vendor_checksums=False,
                expected_exit_code=2,
                expected_output="Unmatched checksum",
            ),
            id="rpm_unmatched_checksum",
        ),
        pytest.param(
            utils.TestParameters(
                repo="https://github.com/cachito-testing/cachi2-rpm",
                ref="699bfad4030c97e3b62042ffc48149ef896164ec",
                packages=({"path": ".", "type": "rpm"},),
                flags=["--dev-package-managers"],
                check_output=False,
                check_deps_checksums=False,
                check_vendor_checksums=False,
                expected_exit_code=2,
                expected_output="Unexpected file size",
            ),
            id="rpm_unexpected_size",
        ),
        pytest.param(
            utils.TestParameters(
                repo="https://github.com/cachito-testing/cachi2-rpm",
                ref="12afdef45a07560303496217de0222c5f7a49cac",
                packages=(
                    {"path": "this-project", "type": "rpm"},
                    {"path": "another-project", "type": "rpm"},
                ),
                flags=["--dev-package-managers"],
                check_output=True,
                check_deps_checksums=False,
                check_vendor_checksums=False,
                expected_exit_code=0,
            ),
            id="rpm_multiple_packages",
        ),
        pytest.param(
            utils.TestParameters(
                repo="https://github.com/cachito-testing/cachi2-rpm",
                ref="22cb12ee0ba4f98d8a751e552c3caee8de5b0237",
                packages=({"path": ".", "type": "rpm"},),
                flags=["--dev-package-managers"],
                check_output=True,
                check_deps_checksums=False,
                check_vendor_checksums=False,
                expected_exit_code=0,
            ),
            id="rpm_multiple_archs",
        ),
    ],
)
def test_rpm_packages(
    test_params: utils.TestParameters,
    cachi2_image: utils.ContainerImage,
    tmp_path: Path,
    test_data_dir: Path,
    request: pytest.FixtureRequest,
) -> None:
    """
    Test fetched dependencies for RPMs.

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
    "test_params",
    [
        pytest.param(
            utils.TestParameters(
                repo="https://github.com/cachito-testing/cachi2-rpm",
                ref="ce7fed744fc8fc2fd5d8981027e519ecd50b8805",
                packages=({"path": ".", "type": "rpm"},),
                flags=["--dev-package-managers"],
                check_output=False,
                check_deps_checksums=False,
                check_vendor_checksums=False,
                expected_exit_code=0,
            ),
            id="rpm_test_repo_file",
        ),
    ],
)
def test_repo_files(
    test_params: utils.TestParameters,
    cachi2_image: utils.ContainerImage,
    tmp_path: Path,
    test_data_dir: Path,
    request: pytest.FixtureRequest,
) -> None:
    """Test if the contents of the generated .repo file are correct."""
    test_case = request.node.callspec.id
    output_folder = tmp_path.joinpath(f"{test_case}-output")

    source_folder = utils.clone_repository(
        test_params.repo, test_params.ref, f"{test_case}-source", tmp_path
    )

    utils.fetch_deps_and_check_output(
        tmp_path, test_case, test_params, source_folder, test_data_dir, cachi2_image
    )

    # call inject-files to create the .repo file
    cmd = [
        "inject-files",
        output_folder,
        "--for-output-dir",
        Path("/tmp", f"{test_case}-output"),
    ]
    (output, exit_code) = cachi2_image.run_cmd_on_image(cmd, tmp_path)
    assert exit_code == 0, f"Injecting project files failed. output-cmd: {output}"

    # load .repo file contents
    def read_and_normalize_repofile(path: Path) -> str:
        with open(path) as file:
            # whenever an RPM lacks a repoid in the lockfile, Cachi2 will resort to a randomly
            # generated internal repoid, which needs to be replaced by a constant string so it can
            # be tested consistently.
            return re.sub(r"cachi2-[a-f0-9]{6}", "cachi2-aaa000", file.read())

    repo_file_content = read_and_normalize_repofile(
        output_folder.joinpath("deps/rpm/x86_64/repos.d/cachi2.repo")
    )

    # update test data if needed
    expected_repo_file_path = test_data_dir.joinpath(test_case, "cachi2.repo")

    if os.getenv("CACHI2_GENERATE_TEST_DATA") == "true":
        expected_repo_file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(expected_repo_file_path, "w") as file:
            file.write(repo_file_content)

    # check if .repo file content matches the expected test data
    assert repo_file_content == read_and_normalize_repofile(expected_repo_file_path)


@pytest.mark.parametrize(
    "test_params, check_cmd, expected_cmd_output",
    [
        # Test case that checks fetching RPM files, generating repos and repofiles, building an
        # image that requires the RPM files to be installed and running the image to check if the
        # RPMs were properly installed
        pytest.param(
            utils.TestParameters(
                repo="https://github.com/cachito-testing/cachi2-rpm.git",
                ref="eef99f074a9abd288b421697d7e00cec77590d0d",
                packages=(
                    {
                        "type": "rpm",
                    },
                ),
                flags=["--dev-package-managers"],
                expected_exit_code=0,
                expected_output="All dependencies fetched successfully",
            ),
            ["vim", "--version"],
            ["VIM - Vi IMproved 9.0"],
            id="rpm_e2e_test",
        ),
    ],
)
def test_e2e_rpm(
    test_params: utils.TestParameters,
    check_cmd: List[str],
    expected_cmd_output: str,
    cachi2_image: utils.ContainerImage,
    tmp_path: Path,
    test_data_dir: Path,
    request: pytest.FixtureRequest,
) -> None:
    """
    End to end test for rpms.

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
