import os
from typing import Optional
from unittest import mock

import pytest

from cachi2.core.package_managers.yarn.utils import run_yarn_cmd
from cachi2.core.rooted_path import RootedPath


@pytest.mark.parametrize(
    "env, expect_path",
    [
        (None, os.environ["PATH"]),
        ({}, os.environ["PATH"]),
        ({"yarn_global_folder": "/tmp/yarnberry"}, os.environ["PATH"]),
        ({"PATH": "/bin"}, "/bin"),
    ],
)
@mock.patch("subprocess.run")
def test_run_yarn_cmd(
    mock_subprocess_run: mock.Mock,
    env: Optional[dict[str, str]],
    expect_path: str,
    rooted_tmp_path: RootedPath,
) -> None:
    run_yarn_cmd(["info", "--json"], rooted_tmp_path, env)

    mock_subprocess_run.assert_called_once()

    call = mock_subprocess_run.call_args_list[0]
    assert call.args[0] == ["yarn", "info", "--json"]
    assert call.kwargs["cwd"] == rooted_tmp_path
    assert call.kwargs["env"] == (env or {}) | {"PATH": expect_path}
