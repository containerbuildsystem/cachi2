import pytest

from cachi2.core.models.output import EnvironmentVariable
from cachi2.core.package_managers.yarn_classic.main import _generate_build_environment_variables


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
