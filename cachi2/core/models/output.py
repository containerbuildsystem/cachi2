import logging
import re
import string
from pathlib import Path
from typing import Any, Literal, Optional

import pydantic

from cachi2.core.models.validators import unique_sorted

log = logging.getLogger(__name__)


class Component(pydantic.BaseModel):
    """A software component such as a dependency or a package.

    Compliant to the CycloneDX specification:
    https://cyclonedx.org/docs/1.4/json/#components
    """

    name: str
    version: Optional[str]
    purl: Optional[str]  # optional while it is not implemented for Pip
    type: Literal["library"] = "library"

    def key(self) -> str:
        """Uniquely identifies a package.

        Used mainly for sorting and deduplication.
        """
        if self.purl:
            return self.purl

        return f"{self.name}:{self.version}"

    @pydantic.validator("version")
    def _valid_semver(cls, version: Optional[str]) -> Optional[str]:
        """Ignore invalid versions.

        For now, versions for the following types of dependencies will be ignored:
            * Direct files (starting with http|https)
            * VCS dependencies (starting with git+)
            * Gomod local replacements (starting with ./)

        This behavior is meant to be temporary, proper version output should be handled at package
        manager level.
        """
        regex = re.compile(r"^(git\+|https?://|\./|file:).*$")

        if version is None or regex.match(version):
            return None

        return version

    @classmethod
    def from_package_dict(cls, package: dict[str, Any]) -> "Component":
        """Create a Component from a Cachi2 package dictionary.

        A Cachi2 package has extra fields which are unnecessary and can cause validation errors.
        """
        return Component(name=package.get("name", None), version=package.get("version", None))


class Sbom(pydantic.BaseModel):
    """Software bill of materials in the CycloneDX format.

    See full specification at:
    https://cyclonedx.org/docs/1.4/json
    """

    bom_format: Literal["CycloneDX"] = pydantic.Field(alias="bomFormat", default="CycloneDX")
    components: list[Component] = []
    spec_version: str = pydantic.Field(alias="specVersion", default="1.4")
    version: int = 1

    @pydantic.validator("components")
    def _unique_components(cls, components: list[Component]) -> list[Component]:
        """Sort and de-duplicate components."""
        return unique_sorted(components, by=lambda component: component.key())


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

    build_config: BuildConfig
    sbom: Sbom

    @classmethod
    def empty(cls) -> "RequestOutput":
        """Return an empty RequestOutput."""
        return cls(sbom=Sbom(), build_config=BuildConfig())

    @classmethod
    def from_obj_list(
        cls,
        components: list[Component],
        environment_variables: Optional[list[EnvironmentVariable]] = None,
        project_files: Optional[list[ProjectFile]] = None,
    ) -> "RequestOutput":
        """Create a RequestOutput from internal Sbom and BuildConfig contents."""
        if environment_variables is None:
            environment_variables = []

        if project_files is None:
            project_files = []

        return RequestOutput(
            sbom=Sbom(components=components),
            build_config=BuildConfig(
                environment_variables=environment_variables, project_files=project_files
            ),
        )
