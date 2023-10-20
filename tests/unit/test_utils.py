import subprocess
from typing import Optional
from unittest import mock

import pytest

from cachi2.core.errors import Cachi2Error
from cachi2.core.utils import run_cmd


@mock.patch("subprocess.run")
@mock.patch("shutil.which")
@pytest.mark.parametrize(
    "stdout, stderr, expect_logs",
    [
        # when stderr is empty, log that fact and log the stdout
        ("failed", None, ["STDERR: <empty>", "STDOUT:\nfailed"]),
        ("failed", "", ["STDERR: <empty>", "STDOUT:\nfailed"]),
        # when stderr is not empty, don't log stdout no matter what
        (None, "failed", ["STDERR:\nfailed"]),
        ("", "failed", ["STDERR:\nfailed"]),
        ("some info", "failed", ["STDERR:\nfailed"]),
        # when both are empty, log that fact and be sad :(
        ("", "", ["STDERR: <empty>", "STDOUT: <empty>"]),
        # test that newlines are stripped
        ("", "failed\n", ["STDERR:\nfailed"]),
        ("failed", "", ["STDERR: <empty>", "STDOUT:\nfailed"]),
    ],
)
def test_run_cmd_logs_stdouterr_on_failure(
    mock_shutil_which: mock.Mock,
    mock_subprocess_run: mock.Mock,
    stdout: Optional[str],
    stderr: Optional[str],
    expect_logs: list[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    mock_shutil_which.return_value = "/usr/local/bin/some"
    mock_subprocess_run.return_value = subprocess.CompletedProcess(
        ["some", "command"], returncode=1, stdout=stdout, stderr=stderr
    )

    with pytest.raises(subprocess.CalledProcessError):
        run_cmd(["some", "command"], {})

    assert caplog.messages == ['The command "some command" failed', *expect_logs]


@mock.patch("subprocess.run")
@mock.patch("shutil.which")
@pytest.mark.parametrize("extra_args", [True, False])
def test_run_cmd_execute_by_abspath(
    mock_shutil_which: mock.Mock,
    mock_subprocess_run: mock.Mock,
    extra_args: bool,
) -> None:
    mock_shutil_which.return_value = "/usr/local/bin/yarn"
    mock_subprocess_run.return_value = subprocess.CompletedProcess([], returncode=0)

    if extra_args:
        cmd = ["yarn", "--version"]
        expect_cmd = ["/usr/local/bin/yarn", "--version"]
    else:
        cmd = ["yarn"]
        expect_cmd = ["/usr/local/bin/yarn"]

    run_cmd(cmd, params={})

    mock_subprocess_run.assert_called_once()
    call = mock_subprocess_run.call_args_list[0]
    assert call.args[0] == expect_cmd


@mock.patch("shutil.which")
def test_run_cmd_executable_not_found(
    mock_shutil_which: mock.Mock,
) -> None:
    mock_shutil_which.return_value = None

    with pytest.raises(Cachi2Error, match="'foo' executable not found in PATH"):
        run_cmd(["foo"], params={})
