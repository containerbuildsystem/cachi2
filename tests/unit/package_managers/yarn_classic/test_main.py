from pathlib import Path
from unittest import mock

import pytest

from cachi2.core.models.input import Request
from cachi2.core.models.output import BuildConfig, EnvironmentVariable, RequestOutput
from cachi2.core.models.sbom import Component
from cachi2.core.package_managers.yarn_classic.main import (
    _fetch_dependencies,
    _generate_build_environment_variables,
    _get_prefetch_environment_variables,
    fetch_yarn_source,
)
from cachi2.core.rooted_path import RootedPath


@pytest.fixture(scope="module")
def yarn_classic_env_variables() -> list[EnvironmentVariable]:
    return [
        EnvironmentVariable(
            name="YARN_YARN_OFFLINE_MIRROR", value="${output_dir}/deps/yarn-classic"
        ),
        EnvironmentVariable(name="YARN_YARN_OFFLINE_MIRROR_PRUNING", value="false"),
    ]


def test_generate_build_environment_variables(
    yarn_classic_env_variables: list[EnvironmentVariable],
) -> None:
    result = _generate_build_environment_variables()
    assert result == yarn_classic_env_variables


@pytest.mark.parametrize(
    "input_request, components",
    [
        pytest.param(
            [{"type": "yarn-classic", "path": "."}],
            [],
            id="single_input_package",
        ),
        pytest.param(
            [{"type": "yarn-classic", "path": "."}, {"type": "yarn-classic", "path": "./path"}],
            [],
            id="multiple_input_packages",
        ),
    ],
    indirect=["input_request"],
)
@mock.patch("cachi2.core.package_managers.yarn_classic.main._get_prefetch_environment_variables")
@mock.patch("cachi2.core.package_managers.yarn_classic.main._fetch_dependencies")
def test_fetch_yarn_source(
    mock_fetch_dependencies: mock.Mock,
    mock_prefetch_env_vars: mock.Mock,
    input_request: Request,
    yarn_classic_env_variables: list[EnvironmentVariable],
    components: list[Component],
) -> None:
    expected_output = RequestOutput(
        components=components,
        build_config=BuildConfig(environment_variables=yarn_classic_env_variables),
    )

    output = fetch_yarn_source(input_request)

    mock_prefetch_env_vars.assert_has_calls(
        [mock.call(input_request.output_dir) for _ in input_request.packages]
    )

    calls = []
    for package in input_request.packages:
        package_path = input_request.source_dir.join_within_root(package.path)
        calls.append(mock.call(package_path, mock_prefetch_env_vars(input_request.output_dir)))
    mock_fetch_dependencies.assert_has_calls(calls)

    assert input_request.output_dir.join_within_root("deps/yarn-classic").path.exists()
    assert output == expected_output


@mock.patch("cachi2.core.package_managers.yarn_classic.main.run_yarn_cmd")
def test_fetch_dependencies(mock_run_yarn_cmd: mock.Mock, tmp_path: Path) -> None:
    env = {"foo": "bar"}
    rooted_tmp_path = RootedPath(tmp_path)

    _fetch_dependencies(rooted_tmp_path, env)

    mock_run_yarn_cmd.assert_called_with(
        [
            "install",
            "--disable-pnp",
            "--frozen-lockfile",
            "--ignore-engines",
            "--no-default-rc",
            "--non-interactive",
        ],
        rooted_tmp_path,
        env,
    )


def test_get_prefetch_environment_variables(tmp_path: Path) -> None:
    request_output_dir = RootedPath(tmp_path).join_within_root("output")
    yarn_deps_dir = request_output_dir.join_within_root("deps/yarn-classic")
    expected_output = {
        "COREPACK_ENABLE_DOWNLOAD_PROMPT": "0",
        "COREPACK_ENABLE_PROJECT_SPEC": "0",
        "YARN_IGNORE_PATH": "true",
        "YARN_IGNORE_SCRIPTS": "true",
        "YARN_YARN_OFFLINE_MIRROR": str(yarn_deps_dir),
        "YARN_YARN_OFFLINE_MIRROR_PRUNING": "false",
    }

    output = _get_prefetch_environment_variables(request_output_dir)

    assert output == expected_output
