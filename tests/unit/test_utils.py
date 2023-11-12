import shutil
import subprocess
from pathlib import Path
from typing import Callable, Optional
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

    mock_shutil_copytree.assert_called_with(
        origin, destination, copy_function=copy_function, dirs_exist_ok=True, symlinks=True
    )


@mock.patch("shutil.copytree")
@mock.patch("reflink.supported_at")
def test_copy_directory_with_reflink_failure(
    mock_reflink_supported_at: mock.Mock,
    mock_shutil_copytree: mock.Mock,
) -> None:
    def raise_reflink_error(
        origin: Path,
        destination: Path,
        copy_function: Callable,
        dirs_exist_ok: bool,
        symlinks: bool,
    ) -> None:
        raise reflink.ReflinkImpossibleError()

    mock_reflink_supported_at.return_value = True
    mock_shutil_copytree.side_effect = raise_reflink_error

    origin = Path("/fake")
    destination = Path("/phony")

    with pytest.raises(reflink.ReflinkImpossibleError):
        copy_directory(origin, destination)

    mock_shutil_copytree.assert_has_calls(
        [
            mock.call(
                origin,
                destination,
                copy_function=reflink.reflink,
                dirs_exist_ok=True,
                symlinks=True,
            ),
            mock.call(
                origin,
                destination,
                copy_function=shutil.copy2,
                dirs_exist_ok=True,
                symlinks=True,
            ),
        ]
    )
