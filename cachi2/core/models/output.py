import logging
import string
from pathlib import Path
from typing import Literal, Optional

import pydantic

from cachi2.core.models.sbom import Component, Sbom
from cachi2.core.models.validators import unique_sorted

log = logging.getLogger(__name__)


class EnvironmentVariable(pydantic.BaseModel):
    """An environment variable."""

    name: str
    value: str
    kind: Literal["literal", "path"]

    def resolve_value(self, relative_to_path: Path) -> str:
        """Return the resolved value of this environment variable.

        For "literal" variables, the resolved value is simply the value it was created with.
        For "path" variables, the value is joined to the specified path.
        """
        if self.kind == "path":
            value = str(relative_to_path / self.value)
        else:
            value = self.value
        return value


class ProjectFile(pydantic.BaseModel):
    """A file to be written into the user's project directory.

    Typically should be used to inject configuration files (e.g. .npmrc) or to modify lockfiles
    (e.g. requirements.txt).

    The content of the file is interpreted as a string.Template. The following placeholders will
    be replaced:
        * ${output_dir} - the absolute path to the output directory
    """

    abspath: Path
    template: str

    def resolve_content(self, output_dir: Path) -> str:
        """Return the resolved content of this file.

        Uses Template.safe_substitute, so if the template contains invalid placeholders,
        they will simply stay unresolved rather than causing errors.

        Example:
            foo @ file://${output_dir}/deps/pip/...
            bar==1.0.0  # comment with $placeholder
            baz==1.0.0  # comment with $ invalid placeholder

            =>
            foo @ file:///cachi2/output/deps/pip/...
            bar==1.0.0  # comment with $placeholder
            baz==1.0.0  # comment with $ invalid placeholder
        """
        template = string.Template(self.template)
        return template.safe_substitute(output_dir=output_dir)


class BuildConfig(pydantic.BaseModel):
    """Holds output used to configure a repository for a build."""

    environment_variables: list[EnvironmentVariable] = []
    project_files: list[ProjectFile] = []

    @pydantic.validator("environment_variables")
    def _unique_env_vars(cls, env_vars: list[EnvironmentVariable]) -> list[EnvironmentVariable]:
        """Sort and de-duplicate environment variables by name."""
        return unique_sorted(env_vars, by=lambda env_var: env_var.name)

    @pydantic.validator("project_files")
    def _unique_project_files(cls, project_files: list[ProjectFile]) -> list[ProjectFile]:
        """Sort and de-duplicate project files by path."""
        return unique_sorted(project_files, by=lambda f: f.abspath)


class RequestOutput(pydantic.BaseModel):
    """Results of processing one or more package managers."""

    components: list[Component]
    build_config: BuildConfig

    def generate_sbom(self) -> Sbom:
        """Generate the SBOM for this RequestOutput.

        Note that RequestOutput may contain duplicated components, the Sbom model will de-duplicate
        them automatically.
        """
        return Sbom(components=self.components)

    @classmethod
    def empty(cls) -> "RequestOutput":
        """Return an empty RequestOutput."""
        return cls(components=[], build_config=BuildConfig())

    @classmethod
    def from_obj_list(
        cls,
        components: list[Component],
        environment_variables: Optional[list[EnvironmentVariable]] = None,
        project_files: Optional[list[ProjectFile]] = None,
    ) -> "RequestOutput":
        """Create a RequestOutput from components, environment variables and project files."""
        if environment_variables is None:
            environment_variables = []

        if project_files is None:
            project_files = []

        return RequestOutput(
            components=components,
            build_config=BuildConfig(
                environment_variables=environment_variables,
                project_files=project_files,
            ),
        )
