from unittest import mock

import pytest

from cachi2.core.errors import YarnCommandError
from cachi2.core.package_managers.yarn.main import _fetch_dependencies
from cachi2.core.rooted_path import RootedPath


@mock.patch("cachi2.core.package_managers.yarn.main.run_yarn_cmd")
def test_fetch_dependencies(mock_yarn_cmd: mock.Mock, rooted_tmp_path: RootedPath) -> None:
    source_dir = rooted_tmp_path
    output_dir = rooted_tmp_path.join_within_root("cachi2-output")

    mock_yarn_cmd.side_effect = YarnCommandError("berryscary")

    with pytest.raises(YarnCommandError) as exc_info:
        _fetch_dependencies(source_dir, output_dir)

    mock_yarn_cmd.assert_called_once_with(
        ["install", "--mode", "skip-build"],
        source_dir,
        {"YARN_GLOBAL_FOLDER": str(output_dir.join_within_root("deps", "yarn"))},
    )

    assert str(exc_info.value) == "berryscary"
