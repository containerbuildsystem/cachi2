# SPDX-License-Identifier: GPL-3.0-or-later
import hashlib
import json
import logging
import os
import shutil
import string
from dataclasses import dataclass, field
from pathlib import Path
from subprocess import PIPE, Popen
from tarfile import ExtractError, TarFile
from typing import Any, Dict, List, Tuple

from git import Repo

log = logging.getLogger(__name__)


@dataclass
class TestParameters:
    repo: str
    ref: str
    packages: Tuple[Dict[str, Any], ...]
    check_output_json: bool = True
    check_deps_checksums: bool = True
    check_vendor_checksums: bool = True
    expected_exit_code: int = 0
    expected_output: str = ""
    flags: List[str] = field(default_factory=list)


class ContainerImage:
    def __init__(self, repository: str):
        """Initialize ContainerImage object with associated repository."""
        self.repository = repository

    def __enter__(self):
        return self

    def pull_image(self):
        cmd = ["podman", "pull", self.repository]
        output, exit_code = run_cmd(cmd)
        if exit_code != 0:
            raise RuntimeError(f"Pulling {self.repository} failed. Output:{output}")
        log.info("Pulled image: %s.", self.repository)

    def run_cmd_on_image(self, cmd: List, tmpdir: Path) -> Tuple[str, int]:
        image_cmd = ["podman", "run", "--rm", "-v", f"{tmpdir}:{tmpdir}:z", self.repository] + cmd
        return run_cmd(image_cmd)

    def __exit__(self, exc_type, exc_value, exc_traceback):
        image_cmd = ["podman", "rmi", "--force", self.repository]
        (output, exit_code) = run_cmd(image_cmd)
        if exit_code != 0:
            raise RuntimeError(f"Image deletion failed. Output:{output}")


def build_image(tmpdir: Path, containerfile: str, test_case: str) -> ContainerImage:
    image_cmd = [
        "podman",
        "build",
        "-f",
        containerfile,
        "-v",
        f"{tmpdir}:/tmp:Z",
        "--no-cache",
        "--network",
        "none",
        "--tag",
        test_case,
    ]
    (output, exit_code) = run_cmd(image_cmd)
    if exit_code != 0:
        raise RuntimeError(f"Building image failed. Output:{output}")
    return ContainerImage(f"localhost/{test_case}")


def clone_repository(repo_url: str, ref: str, folder_name: str, tmpdir: Path) -> Path:
    """
    Clone repository and checkout specific commit.

    :param repo_url: Git repository URL
    :param ref: Git reference
    :param folder_name: Name of folder where content will be cloned
    :param tmpdir: Temp directory for pytest
    :return: Absolute path to cloned repository
    :rtype: str
    """
    folder = tmpdir / folder_name

    repo = Repo.clone_from(repo_url, folder)
    repo.git.checkout(ref)
    log.info("Cloned repository path: %s", folder)
    return folder


def run_cmd(cmd: List[str]) -> Tuple[str, int]:
    """
    Run command via subprocess.

    :param cmd: command to be executed
    :return: Command output and exitcode
    :rtype: Tuple
    """
    log.info("Run command: %s.", cmd)

    process = Popen(cmd, stdout=PIPE, stderr=PIPE)
    out, err = process.communicate()
    return (out + err).decode("utf-8"), process.returncode


def _calculate_files_checksums_in_dir(root_dir: str) -> Dict:
    """
    Calculate files sha256sum in provided directory.

    Method lists all files in provided directory and calculates their checksums.
    :param root_dir: path to root directory
    :return: Dictionary with relative paths to files in dir and their checksums
    :rtype: Dict
    """
    files_checksums = {}

    for dir_, _, files in os.walk(root_dir):
        for file_name in files:
            rel_dir = os.path.relpath(dir_, root_dir)
            rel_file = os.path.join(rel_dir, file_name)
            if "-external-gitcommit-" in file_name:
                files_checksums[rel_file] = _get_git_commit_from_tarball(
                    os.path.join(root_dir, rel_file)
                )
            else:
                files_checksums[rel_file] = _calculate_sha256sum(os.path.join(root_dir, rel_file))
    return files_checksums


def _get_git_commit_from_tarball(tarball: str) -> str:
    with TarFile.open(tarball, "r:gz") as tarfile:
        extract_path = tarball.replace(".tar.gz", "")
        _safe_extract(tarfile, extract_path)

    repo = Repo(path=f"{extract_path}/app")
    commit = f"gitcommit:{repo.commit().hexsha}"

    shutil.rmtree(extract_path)

    return commit


def _calculate_sha256sum(file: str) -> str:
    """
    Calculate sha256sum of file.

    :param file: path to file
    :return: file's sha256sum
    :rtype: str
    """
    sha256_hash = hashlib.sha256()
    with open(file, "rb") as f:
        # Read and update hash string value in blocks of 4K
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return f"sha256:{sha256_hash.hexdigest()}"


def _load_json(file: str) -> Dict:
    """Load JSON file and return dict."""
    with open(file) as json_file:
        return json.load(json_file)


def _safe_extract(tar: TarFile, path: str = ".", *, numeric_owner: bool = False):
    """
    CVE-2007-4559 replacement for extract() or extractall().

    By using extract() or extractall() on a tarfile object without sanitizing input,
    a maliciously crafted .tar file could perform a directory path traversal attack.
    The patch essentially checks to see if all tarfile members will be
    extracted safely and throws an exception otherwise.

    :param tarfile tar: the tarfile to be extracted.
    :param str path: specifies a different directory to extract to.
    :param numeric_owner: if True, only the numbers for user/group names are used and not the names.
    :raise ExtractError: if there is a Traversal Path Attempt in the Tar File.
    """
    abs_path = Path(path).resolve()
    for member in tar.getmembers():

        member_path = Path(path).joinpath(member.name)
        abs_member_path = member_path.resolve()

        if not abs_member_path.is_relative_to(abs_path):
            raise ExtractError("Attempted Path Traversal in Tar File")

    tar.extractall(path, numeric_owner=numeric_owner)


def fetch_deps_and_check_output(
    tmpdir: Path,
    test_case: str,
    test_params: TestParameters,
    source_folder: Path,
    test_data_dir: Path,
    cachi2_image: ContainerImage,
) -> str:
    """
    Fetch dependencies for source repo and check expected output.

    :param tmpdir: Temp directory for pytest
    :param test_case: Test case name retrieved from pytest id
    :param test_params: Test case arguments
    :param source_folder: Folder path to source repository content
    :param test_data_dir: Relative path to expected output test data
    :param cachi2_image: ContainerImage instance with Cachi2 image
    :return: Path to output folder with fetched dependencies and output.json
    """
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

    cmd.append(json.dumps(test_params.packages).encode("utf-8"))

    (output, exit_code) = cachi2_image.run_cmd_on_image(cmd, tmpdir)
    assert exit_code == test_params.expected_exit_code, (
        f"Fetching deps ended with unexpected exitcode: {exit_code} != "
        f"{test_params.expected_exit_code}, output-cmd: {output}"
    )
    assert test_params.expected_output in str(
        output
    ), f"Expected msg {test_params.expected_output} was not found in cmd output: {output}"

    if test_params.check_output_json:
        output_json = _load_json(os.path.join(output_folder, "output.json"))
        expected_output_json = _load_json(os.path.join(test_data_dir, test_case, "output.json"))

        if "project_files" in expected_output_json:
            _set_tmpdir_path(expected_output_json["project_files"], tmpdir)

        log.info("Compare output.json files")
        assert output_json == expected_output_json

    if test_params.check_deps_checksums:
        files_checksums = _calculate_files_checksums_in_dir(os.path.join(output_folder, "deps"))
        expected_files_checksums = _load_json(
            os.path.join(test_data_dir, test_case, "fetch_deps_sha256sums.json")
        )
        log.info("Compare checksums of fetched deps files")
        assert files_checksums == expected_files_checksums

    if test_params.check_vendor_checksums:
        files_checksums = _calculate_files_checksums_in_dir(os.path.join(source_folder, "vendor"))
        expected_files_checksums = _load_json(
            os.path.join(test_data_dir, test_case, "vendor_sha256sums.json")
        )
        log.info("Compare checksums of files in source vendor folder")
        assert files_checksums == expected_files_checksums

    return output_folder


def _set_tmpdir_path(project_files: list[dict[str, str]], path: Path) -> None:
    for item in project_files:
        template = string.Template(item.get("abspath", ""))
        item["abspath"] = template.safe_substitute(test_case_tmpdir=str(path))
