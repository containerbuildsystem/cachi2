from cachi2.core.rooted_path import RootedPath
from cachi2.core.utils import run_cmd


def run_yarn_cmd(cmd: list[str], source_dir: RootedPath, env: dict[str, str]) -> str:
    """Run a yarn command on a source directory.

    :param cmd: the command that will be executed, split in a list of strings in every space.
    :param source_dir: the directory in the repository containing the yarn source files.
    :param env: environment variables to be set during the command's execution.

    :raises SubprocessCallError: if the command fails.
    """
    run_cmd(cmd=["yarn", *cmd], params={"cwd": source_dir, "env": env})
    return NotImplemented
