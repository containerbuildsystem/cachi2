import os
import subprocess  # nosec
from typing import Optional

from cachi2.core.errors import PackageManagerError
from cachi2.core.rooted_path import RootedPath
from cachi2.core.utils import run_cmd


def run_yarn_cmd(
    cmd: list[str], source_dir: RootedPath, env: Optional[dict[str, str]] = None
) -> str:
    """Run a yarn command on a source directory.

    :param cmd: the command that will be executed, split in a list of strings in every space.
    :param source_dir: the directory in the repository containing the yarn source files.
    :param env: environment variables to be set during the command's execution
    :raises PackageManagerError: if the command fails.
    """
    env = env or {}
    # if the caller doesn't specify a PATH variable, then pass the PATH from the current
    # process to the subprocess
    if "PATH" not in env and (self_path := os.environ.get("PATH")):
        env = env | {"PATH": self_path}
    try:
        return run_cmd(cmd=["yarn", *cmd], params={"cwd": source_dir, "env": env})
    except subprocess.CalledProcessError as e:
        # the yarn command writes the errors to stdout
        raise PackageManagerError(f"Yarn command failed: {' '.join(cmd)}", stderr=e.stdout)
