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
@mock.patch("cachi2.core.package_managers.yarn.utils.run_cmd")
def test_run_yarn_cmd(
    mock_run_cmd: mock.Mock,
    env: Optional[dict[str, str]],
    expect_path: str,
    rooted_tmp_path: RootedPath,
) -> None:
    run_yarn_cmd(["info", "--json"], rooted_tmp_path, env)

    expect_env = (env or {}) | {"PATH": expect_path}
    mock_run_cmd.assert_called_once_with(
        cmd=["yarn", "info", "--json"], params={"cwd": rooted_tmp_path, "env": expect_env}
    )
