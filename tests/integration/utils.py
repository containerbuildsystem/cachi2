# SPDX-License-Identifier: GPL-3.0-or-later
import hashlib
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from subprocess import PIPE, Popen
from typing import Dict, List, Tuple

from git import Repo

log = logging.getLogger(__name__)


@dataclass
class TestParameters:
    repo: str
    ref: str
    packages: Tuple[Dict]
    check_output_json: bool = True
    check_deps_checksums: bool = True
    check_vendor_checksums: bool = True
    expected_rc: int = 0
    expected_output: str = ""
    flags: List[str] = field(default_factory=list)


class ContainerImage:
    def __init__(self, repository: str):
        """Initialize ContainerImage object with associated repository."""
        self.repository = repository

    def pull_image(self):
        cmd = ["podman", "pull", self.repository]
        output, rc = run_cmd(cmd)
        if rc != 0:
            raise RuntimeError(f"Pulling {self.repository} failed. Output:{output}")
        log.info("Pulled image: %s.", self.repository)

    def run_cmd_on_image(self, cmd: List, tmpdir: Path) -> Tuple[str, int]:
        image_cmd = ["podman", "run", "--rm", "-v", f"{tmpdir}:{tmpdir}:z", self.repository] + cmd
        return run_cmd(image_cmd)


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


def calculate_files_sha256sum_in_dir(root_dir: str) -> Dict:
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
            files_checksums[rel_file] = calculate_sha256sum(os.path.join(root_dir, rel_file))
    return files_checksums


def calculate_sha256sum(file: str) -> str:
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
    return sha256_hash.hexdigest()


def load_json(file: str) -> Dict:
    """Load JSON file and return dict."""
    with open(file) as json_file:
        return json.load(json_file)
