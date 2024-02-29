import pytest

from cachi2.core.models.input import Request
from cachi2.core.models.output import BuildConfig, EnvironmentVariable, RequestOutput
from cachi2.core.models.sbom import Component
from cachi2.core.package_managers.yarn_classic.main import (
    _generate_build_environment_variables,
    fetch_yarn_source,
)


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
    ],
    indirect=["input_request"],
)
def test_fetch_yarn_source(input_request: Request, components: list[Component]) -> None:
    output = fetch_yarn_source(input_request)
    expected_output = RequestOutput(
        components=components,
        build_config=BuildConfig(environment_variables=[]),
    )
    assert output == expected_output
