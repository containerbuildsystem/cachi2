import json
import logging
import re
import subprocess  # nosec
from typing import Iterator

from cachi2.core.config import get_worker_config

log = logging.getLogger(__name__)


def run_cmd(cmd, params):
    """
    Run the given command with provided parameters.

    :param iter cmd: iterable representing command to be executed
    :param dict params: keyword parameters for command execution
    :returns: the command output
    :rtype: str
    :raises SubprocessCallError: if the command fails
    """
    params.setdefault("capture_output", True)
    params.setdefault("universal_newlines", True)
    params.setdefault("encoding", "utf-8")

    conf = get_worker_config()
    params.setdefault("timeout", conf.subprocess_timeout)

    response = subprocess.run(cmd, **params)  # nosec

    try:
        response.check_returncode()
    except subprocess.CalledProcessError:
        log.error('The command "%s" failed with: %s', " ".join(cmd), response.stderr)
        raise

    return response.stdout


def load_json_stream(s: str) -> Iterator:
    """
    Load all JSON objects from input string.

    The objects can be separated by one or more whitespace characters. The return value is
    a generator that will yield the parsed objects one by one.
    """
    decoder = json.JSONDecoder()
    non_whitespace = re.compile(r"\S")
    i = 0

    while match := non_whitespace.search(s, i):
        obj, i = decoder.raw_decode(s, match.start())
        yield obj
