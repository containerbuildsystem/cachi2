import json
import os
from typing import Optional
from unittest import mock

import pytest

from cachi2.core.package_managers.yarn.utils import _jsonify, run_yarn_cmd
from cachi2.core.rooted_path import RootedPath

YARN_SAMPLE_OUTPUT_SINGLE_JSON_OBJ = '{"foo":"bar", "bar":["baz", "foobar"]}'
YARN_SAMPLE_JSON_OUTPUT_MULTI_JSON_OBJ = """\
{"foo":"bar", "bar":["baz", "foobar"]}
{"foo":"baz", "bar":{"foo": "bar"}}
{"foo":null}
"""

SINGLE_JSON_OBJ_EXPECTED_OUTPUT = '[{"foo": "bar", "bar": ["baz", "foobar"]}]'
MULTI_JSON_OBJ_EXPECTED_OUTPUT = """\
[\
{"foo": "bar", "bar": ["baz", "foobar"]}, \
{"foo": "baz", "bar": {"foo": "bar"}}, \
{"foo": null}\
]\
"""

INVALID_JSON = "definitely not JSON"


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


@pytest.mark.parametrize(
    "input_, expected",
    [
        pytest.param(
            YARN_SAMPLE_OUTPUT_SINGLE_JSON_OBJ,
            SINGLE_JSON_OBJ_EXPECTED_OUTPUT,
            id="yarn_single_json_obj",
        ),
        pytest.param(
            YARN_SAMPLE_JSON_OUTPUT_MULTI_JSON_OBJ,
            MULTI_JSON_OBJ_EXPECTED_OUTPUT,
            id="yarn_multiple_json_objs",
        ),
        pytest.param(
            MULTI_JSON_OBJ_EXPECTED_OUTPUT, MULTI_JSON_OBJ_EXPECTED_OUTPUT, id="proper_json_array"
        ),
        pytest.param("", "[]", id="empty_json"),
    ],
)
def test_jsonify(input_: str, expected: str) -> None:
    assert _jsonify(input_) == expected


def test_jsonify_error() -> None:
    with pytest.raises(json.JSONDecodeError):
        _jsonify("invalid_json")
