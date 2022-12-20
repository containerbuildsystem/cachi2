# SPDX-License-Identifier: GPL-3.0-or-later

import json
import logging
import os
from pathlib import Path

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
                check_output_json=True,
                check_deps_checksums=True,
                expected_rc=0,
                expected_output="All dependencies fetched successfully",
            ),
            id="gomod_with_deps",
        ),
        pytest.param(
            utils.TestParameters(
                repo="https://github.com/cachito-testing/cachito-gomod-without-deps.git",
                ref="a888f7261b9a9683972fbd77da2d12fe86faef5e",
                packages=({"path": ".", "type": "gomod"},),
                check_output_json=True,
                check_deps_checksums=True,
                expected_rc=0,
                expected_output="All dependencies fetched successfully",
            ),
            id="gomod_without_deps",
        ),
        pytest.param(
            utils.TestParameters(
                repo="https://github.com/cachito-testing/gomod-vendored.git",
                ref="ff1960095dd158d3d2a4f31d15b244c24930248b",
                packages=({"path": ".", "type": "gomod"},),
                expected_rc=2,
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
                check_output_json=True,
                check_deps_checksums=True,
                check_vendor_checksums=True,
                flags=["--gomod-vendor"],
                expected_rc=0,
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
                check_output_json=True,
                check_deps_checksums=True,
                check_vendor_checksums=True,
                flags=["--gomod-vendor-check"],
                expected_rc=0,
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
                check_output_json=True,
                check_deps_checksums=True,
                check_vendor_checksums=True,
                flags=["--gomod-vendor-check"],
                expected_rc=0,
                expected_output="All dependencies fetched successfully",
            ),
            id="gomod_vendor_check_correct_vendor",
        ),
    ],
)
def test_packages(
    test_params: utils.TestParameters,
    cachi2_image: utils.ContainerImage,
    tmpdir: Path,
    test_data_dir: Path,
    request,
):
    """
    Test fetched dependencies for package managers.

    :param test_params: Test case arguments
    :param tmpdir: Temp directory for pytest
    """
    test_case = request.node.callspec.id

    source_folder = utils.clone_repository(
        test_params.repo, test_params.ref, f"{test_case}-source", tmpdir
    )

    output_folder = os.path.join(tmpdir, f"{test_case}-output")
    cmd = [
        "fetch-deps",
        "--source",
        source_folder,
        "--output",
        output_folder,
    ]
    if test_params.flags:
        cmd += test_params.flags

    for package in test_params.packages:
        cmd += ["--package", json.dumps(package).encode("utf-8")]

    (output, rc) = cachi2_image.run_cmd_on_image(cmd, tmpdir)
    assert rc == test_params.expected_rc, (
        f"Fetching deps ended with unexpected exitcode: {rc} != {test_params.expected_rc}, "
        f"output-cmd: {output}"
    )
    assert test_params.expected_output in str(
        output
    ), f"Expected msg {test_params.expected_output} was not found in cmd output: {output}"

    if test_params.check_output_json:
        output_json = utils.load_json(os.path.join(output_folder, "output.json"))
        expected_output_json = utils.load_json(
            os.path.join(test_data_dir, test_case, "output.json")
        )
        log.info("Compare output.json files")
        assert output_json == expected_output_json

    if test_params.check_deps_checksums:
        files_checksums = utils.calculate_files_sha256sum_in_dir(
            os.path.join(output_folder, "deps")
        )
        expected_files_checksums = utils.load_json(
            os.path.join(test_data_dir, test_case, "fetch_deps_sha256sums.json")
        )
        log.info("Compare checksums of fetched deps files")
        assert files_checksums == expected_files_checksums

    if test_params.check_vendor_checksums:
        files_checksums = utils.calculate_files_sha256sum_in_dir(
            os.path.join(source_folder, "vendor")
        )
        expected_files_checksums = utils.load_json(
            os.path.join(test_data_dir, test_case, "vendor_sha256sums.json")
        )
        log.info("Compare checksums of files in source vendor folder")
        assert files_checksums == expected_files_checksums
