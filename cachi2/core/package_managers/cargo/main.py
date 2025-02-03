from cachi2.core.models.input import Request
from cachi2.core.models.output import Component, EnvironmentVariable, ProjectFile, RequestOutput


def fetch_cargo_source(request: Request) -> RequestOutput:
    """Fetch the source code for all cargo packages specified in a request."""
    components: list[Component] = []
    environment_variables: list[EnvironmentVariable] = []
    project_files: list[ProjectFile] = []

    return RequestOutput.from_obj_list(components, environment_variables, project_files)
