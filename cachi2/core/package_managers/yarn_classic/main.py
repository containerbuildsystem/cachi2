from cachi2.core.models.input import Request
from cachi2.core.models.output import Component, EnvironmentVariable, RequestOutput


def fetch_yarn_source(request: Request) -> RequestOutput:
    """Process all the yarn source directories in a request."""
    components: list[Component] = []
    env_vars: list[EnvironmentVariable] = []

    return RequestOutput.from_obj_list(components, env_vars, project_files=[])


def _generate_build_environment_variables() -> list[EnvironmentVariable]:
    """Generate environment variables that will be used for building the project.

    These ensure that yarnv1 will
    - YARN_YARN_OFFLINE_MIRROR: Maintain offline copies of packages for repeatable and reliable
        builds. Defines the cache location.
    - YARN_YARN_OFFLINE_MIRROR_PRUNING: Control automatic pruning of the offline mirror. We
        disable this, as we need to retain the cache.
    """
    env_vars = {
        "YARN_YARN_OFFLINE_MIRROR": "${output_dir}/deps/yarn-classic",
        "YARN_YARN_OFFLINE_MIRROR_PRUNING": "false",
    }

    return [EnvironmentVariable(name=key, value=value) for key, value in env_vars.items()]
