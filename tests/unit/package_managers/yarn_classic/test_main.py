import json
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

from cachi2.core.errors import PackageManagerError
from cachi2.core.models.input import Request
from cachi2.core.models.output import BuildConfig, EnvironmentVariable, RequestOutput
from cachi2.core.models.sbom import Component
from cachi2.core.package_managers.yarn_classic.main import (
    _fetch_dependencies,
    _generate_build_environment_variables,
    _get_prefetch_environment_variables,
    _resolve_yarn_project,
    _verify_corepack_yarn_version,
    fetch_yarn_source,
)
from cachi2.core.package_managers.yarn_classic.project import Project
from cachi2.core.rooted_path import RootedPath


def _prepare_project(source_dir: RootedPath, package_json: dict[str, Any]) -> Project:
    package_json_path = source_dir.join_within_root("package.json")
    with open(package_json_path.path, "w") as f:
        json.dump(package_json, f)

    return Project.from_source_dir(source_dir)


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
@mock.patch("cachi2.core.package_managers.yarn_classic.main._resolve_yarn_project")
@mock.patch("cachi2.core.package_managers.yarn_classic.main.extract_workspace_metadata")
@mock.patch("cachi2.core.package_managers.yarn_classic.main.Project.from_source_dir")
def test_fetch_yarn_source(
    mock_create_project: mock.Mock,
    mock_extract_metadata: mock.Mock,
    mock_resolve_yarn: mock.Mock,
    input_request: Request,
    yarn_classic_env_variables: list[EnvironmentVariable],
    components: list[Component],
) -> None:
    expected_output = RequestOutput(
        components=components,
        build_config=BuildConfig(environment_variables=yarn_classic_env_variables),
    )
    package_dirs = [
        input_request.source_dir.join_within_root(p.path) for p in input_request.packages
    ]
    projects = [_prepare_project(path, {}) for path in package_dirs]
    mock_create_project.side_effect = projects

    output = fetch_yarn_source(input_request)

    mock_create_project.assert_has_calls([mock.call(path) for path in package_dirs])
    mock_resolve_yarn.assert_has_calls([mock.call(p, input_request.output_dir) for p in projects])

    assert input_request.output_dir.join_within_root("deps/yarn-classic").path.exists()
    assert output == expected_output


@mock.patch("cachi2.core.package_managers.yarn_classic.main._verify_corepack_yarn_version")
@mock.patch("cachi2.core.package_managers.yarn_classic.main._get_prefetch_environment_variables")
@mock.patch("cachi2.core.package_managers.yarn_classic.main._fetch_dependencies")
def test_resolve_yarn_project(
    mock_fetch_dependencies: mock.Mock,
    mock_prefetch_env_vars: mock.Mock,
    mock_verify_yarn_version: mock.Mock,
    rooted_tmp_path: RootedPath,
) -> None:
    project = _prepare_project(rooted_tmp_path, {})
    output_dir = rooted_tmp_path.join_within_root("output")

    _resolve_yarn_project(project, output_dir)

    mock_prefetch_env_vars.assert_called_once_with(output_dir)
    mock_verify_yarn_version.assert_called_once_with(
        project.source_dir, mock_prefetch_env_vars.return_value
    )
    mock_fetch_dependencies.assert_called_once_with(
        project.source_dir, mock_prefetch_env_vars.return_value
    )


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


@pytest.mark.parametrize(
    "yarn_version_output",
    [
        pytest.param("1.22.0", id="valid_version"),
        pytest.param("1.22.0\n", id="valid_version_with_whitespace"),
    ],
)
@mock.patch("cachi2.core.package_managers.yarn.utils.run_yarn_cmd")
def test_verify_corepack_yarn_version(
    mock_run_yarn_cmd: mock.Mock, yarn_version_output: str, tmp_path: Path
) -> None:
    rooted_tmp_path = RootedPath(tmp_path)
    env = {"foo": "bar"}
    mock_run_yarn_cmd.return_value = yarn_version_output

    _verify_corepack_yarn_version(RootedPath(tmp_path), env)
    mock_run_yarn_cmd.assert_called_once_with(["--version"], rooted_tmp_path, env=env)


@pytest.mark.parametrize(
    "yarn_version_output",
    [
        pytest.param("1.21.0", id="version_too_low"),
        pytest.param("2.0.0", id="version_too_high"),
    ],
)
@mock.patch("cachi2.core.package_managers.yarn.utils.run_yarn_cmd")
def test_verify_corepack_yarn_version_disallowed_version(
    mock_run_yarn_cmd: mock.Mock, yarn_version_output: str, tmp_path: Path
) -> None:
    mock_run_yarn_cmd.return_value = yarn_version_output
    error_message = (
        "Cachi2 expected corepack to install yarn >=1.22.0,<2.0.0, but "
        f"instead found yarn@{yarn_version_output}"
    )

    with pytest.raises(PackageManagerError, match=error_message):
        _verify_corepack_yarn_version(RootedPath(tmp_path), env={"foo": "bar"})


@mock.patch("cachi2.core.package_managers.yarn.utils.run_yarn_cmd")
def test_verify_corepack_yarn_version_invalid_version(
    mock_run_yarn_cmd: mock.Mock, tmp_path: Path
) -> None:
    mock_run_yarn_cmd.return_value = "foobar"
    error_message = "The command `yarn --version` did not return a valid semver."

    with pytest.raises(PackageManagerError, match=error_message):
        _verify_corepack_yarn_version(RootedPath(tmp_path), env={"foo": "bar"})
