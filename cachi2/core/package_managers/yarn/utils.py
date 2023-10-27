import json
import os
import subprocess  # nosec
from typing import Optional

from cachi2.core.errors import YarnCommandError
from cachi2.core.rooted_path import RootedPath
from cachi2.core.utils import run_cmd


def run_yarn_cmd(
    cmd: list[str], source_dir: RootedPath, env: Optional[dict[str, str]] = None
) -> str:
    """Run a yarn command on a source directory.

    :param cmd: the command that will be executed, split in a list of strings in every space.
    :param source_dir: the directory in the repository containing the yarn source files.
    :param env: environment variables to be set during the command's execution
    :raises YarnCommandError: if the command fails.
    """
    env = env or {}
    # if the caller doesn't specify a PATH variable, then pass the PATH from the current
    # process to the subprocess
    if "PATH" not in env and (self_path := os.environ.get("PATH")):
        env = env | {"PATH": self_path}
    try:
        stdout = run_cmd(cmd=["yarn", *cmd], params={"cwd": source_dir, "env": env})

        # Fix Yarn's JSON output
        if "--json" in cmd:
            return _jsonify(stdout)
        return stdout
    except subprocess.CalledProcessError:
        raise YarnCommandError(f"Yarn command failed: {' '.join(cmd)}")


def _jsonify(yarn_output: str) -> str:
    """Return a properly serialized JSON array.

    Yarn's --json command line option doesn't actually return a valid JSON,
    instead it returns a sequence of (hopefully valid) JSON objects delimited
    by line breaks. We'll accept this output and convert it to a properly
    serialized JSON array.

    :param yarn_output: this is the Yarn command's raw output
    :raises json.JSONDecodeError: if JSON fails to deserialize Yarn's
                                  representation of an object
    :returns: properly formatted JSON array
    """
    try:
        _ = json.loads(yarn_output)
        if isinstance(_, list):
            return yarn_output

        # Yarn can return a single JSON object in which case we need to convert it to an array
        return json.dumps([_])
    except json.JSONDecodeError:
        # fall back to fixing Yarn's newline delimited JSON objects
        objs = [json.loads(line) for line in yarn_output.splitlines()]
        return json.dumps(objs)
