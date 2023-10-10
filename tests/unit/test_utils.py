import subprocess
from typing import Optional
from unittest import mock

import pytest

from cachi2.core.utils import run_cmd


@mock.patch("subprocess.run")
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
    mock_subprocess_run: mock.Mock,
    stdout: Optional[str],
    stderr: Optional[str],
    expect_logs: list[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    mock_subprocess_run.return_value = subprocess.CompletedProcess(
        ["some", "command"], returncode=1, stdout=stdout, stderr=stderr
    )

    with pytest.raises(subprocess.CalledProcessError):
        run_cmd(["some", "command"], {})

    assert caplog.messages == ['The command "some command" failed', *expect_logs]
