from pathlib import Path
from textwrap import dedent

import pytest

from cachi2.core.errors import UnsupportedFeature
from cachi2.core.extras.envfile import EnvFormat, generate_envfile
from cachi2.core.models.output import BuildConfig


@pytest.mark.parametrize(
    "filename, expect_format",
    [
        ("cachito.env", EnvFormat.env),
        ("cachito.sh", EnvFormat.env),
        ("cachito.json", EnvFormat.json),
    ],
)
def test_format_based_on_suffix(filename: str, expect_format: EnvFormat):
    assert EnvFormat.based_on_suffix(Path(filename)) == expect_format


@pytest.mark.parametrize(
    "filename, expect_reason",
    [
        (".env", "file has no suffix: .env"),
        ("cachi2.", "file has no suffix: cachi2."),
        ("cachi2.yaml", "unsupported suffix: yaml"),
    ],
)
def test_cannot_determine_format(filename: str, expect_reason: str):
    expect_error = f"Cannot determine envfile format, {expect_reason}"
    with pytest.raises(UnsupportedFeature, match=expect_error) as exc_info:
        EnvFormat.based_on_suffix(Path(filename))

    expect_friendly_msg = dedent(
        f"""
        Cannot determine envfile format, {expect_reason}
          Please use one of the supported suffixes: json, env, sh[==env]
          You can also define the format explicitly instead of letting Cachi2 choose.
        """
    ).strip()
    assert exc_info.value.friendly_msg() == expect_friendly_msg


def test_generate_env_as_json():
    env_vars = [
        {"name": "GOCACHE", "value": "deps/gomod", "kind": "path"},
        {"name": "GOSUMDB", "value": "off", "kind": "literal"},
    ]
    build_config = BuildConfig(environment_variables=env_vars, project_files=[])

    gocache = '{"name": "GOCACHE", "value": "/output/dir/deps/gomod"}'
    gosumdb = '{"name": "GOSUMDB", "value": "off"}'
    expect_content = f"[{gocache}, {gosumdb}]"

    content = generate_envfile(build_config, EnvFormat.json, relative_to_path=Path("/output/dir"))
    assert content == expect_content


def test_generate_env_as_env():
    env_vars = [
        {"name": "GOCACHE", "value": "deps/gomod", "kind": "path"},
        {"name": "GOSUMDB", "value": "off", "kind": "literal"},
        {"name": "SNEAKY", "value": "foo; echo hello there", "kind": "literal"},
    ]
    build_config = BuildConfig(environment_variables=env_vars, project_files=[])

    expect_content = dedent(
        """
        export GOCACHE=/output/dir/deps/gomod
        export GOSUMDB=off
        export SNEAKY='foo; echo hello there'
        """
    ).strip()

    content = generate_envfile(build_config, EnvFormat.env, relative_to_path=Path("/output/dir"))
    assert content == expect_content
