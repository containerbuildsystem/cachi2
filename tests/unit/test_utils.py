import shutil
import subprocess
from pathlib import Path
from typing import Optional
from unittest import mock

import pytest
import reflink  # type: ignore

from cachi2.core.errors import Cachi2Error
from cachi2.core.utils import copy_directory, run_cmd


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


@mock.patch("shutil.copytree")
@mock.patch("reflink.supported_at")
@pytest.mark.parametrize(
    "reflink_supported",
    (True, False),
)
def test_copy_directory(
    mock_reflink_supported_at: mock.Mock, mock_shutil_copytree: mock.Mock, reflink_supported: bool
) -> None:
    mock_reflink_supported_at.return_value = reflink_supported

    origin = Path("/fake")
    destination = Path("/phony")

    copy_directory(origin, destination)

    if reflink_supported:
        copy_function = reflink.reflink
    else:
        copy_function = shutil.copy2

    assert mock_shutil_copytree.call_args.kwargs["copy_function"] == copy_function


@mock.patch("shutil.copy2")
@mock.patch("reflink.reflink")
@mock.patch("reflink.supported_at")
def test_copy_directory_fallback_on_reflink_fail(
    mock_reflink_supported_at: mock.Mock,
    mock_reflink: mock.Mock,
    mock_shutil_copy2: mock.Mock,
    tmp_path: Path,
) -> None:
    mock_reflink_supported_at.return_value = True
    mock_reflink.side_effect = reflink.ReflinkImpossibleError
    mock_shutil_copy2.return_value = None

    # prepare dummy copy data
    destination = tmp_path.joinpath("dst")
    origin = tmp_path.joinpath("src")
    origin.mkdir()
    origin.joinpath("foo").touch()

    copy_directory(origin, destination)

    # check we called both copy_functions (reflink, copy2)
    mock_reflink.assert_called_once()
    mock_shutil_copy2.assert_called_once()
