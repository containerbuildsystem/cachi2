import string
from pathlib import Path
from typing import Annotated, Literal, Optional, Union

import pydantic

from cachi2.core.models.validators import check_sane_relpath, unique_sorted

# Supported package types (a superset of the supported package *manager* types)
PackageType = Literal["gomod", "go-package", "pip"]


class _DependencyBase(pydantic.BaseModel):
    """Common attributes for all dependency types."""

    type: PackageType
    name: str


class GomodDependency(_DependencyBase):
    """Metadata about a gomod dependency."""

    type: Literal["gomod"]
    version: str


class GoPackageDependency(_DependencyBase):
    """Metadata about a go-package dependency.

    Unlike other dependency types, go-package dependencies may come from the standard library,
    in which case their version is null.
    """

    type: Literal["go-package"]
    version: Optional[str]


class PipDependency(_DependencyBase):
    """Metadata about a pip dependency.

    Pip dependencies have a 'dev' value to indicate whether the dependency is used at runtime
    or at build time (requirements.txt X requirements-build.txt).
    """

    type: Literal["pip"]
    version: str
    dev: bool


Dependency = Annotated[
    Union[GomodDependency, GoPackageDependency, PipDependency],
    pydantic.Field(discriminator="type"),
]


def _dependency_sorting_key(dep: Dependency) -> tuple[str, bool, str, str]:
    # should return all the attributes a Dependency (the whole Union) can have
    return dep.type, getattr(dep, "dev", False), dep.name, dep.version or ""


class Package(pydantic.BaseModel):
    """Metadata about a resolved package and its dependencies."""

    type: PackageType
    path: Path  # relative from source directory
    name: str
    version: str
    dependencies: list[Dependency]

    @pydantic.validator("path")
    def _path_is_relative(cls, path: Path) -> Path:
        return check_sane_relpath(path)

    @pydantic.validator("dependencies")
    def _unique_deps(cls, dependencies: list[Dependency]) -> list[Dependency]:
        """Sort and de-duplicate dependencies."""
        return unique_sorted(dependencies, by=_dependency_sorting_key)


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


class RequestOutput(pydantic.BaseModel):
    """Results of processing one or more package managers."""

    packages: list[Package]
    environment_variables: list[EnvironmentVariable]
    project_files: list[ProjectFile]

    @pydantic.validator("packages")
    def _unique_packages(cls, packages: list[Package]) -> list[Package]:
        """Sort packages and check that there are no duplicates."""
        return unique_sorted(
            packages,
            by=lambda pkg: (pkg.type, pkg.name, pkg.version),
            dedupe=False,  # de-duplicating could be quite expensive with many dependencies
        )

    @pydantic.validator("environment_variables")
    def _unique_env_vars(cls, env_vars: list[EnvironmentVariable]) -> list[EnvironmentVariable]:
        """Sort and de-duplicate environment variables by name."""
        return unique_sorted(env_vars, by=lambda env_var: env_var.name)

    @pydantic.validator("project_files")
    def _unique_project_files(cls, project_files: list[ProjectFile]) -> list[ProjectFile]:
        """Sort and de-duplicate project files by path."""
        return unique_sorted(project_files, by=lambda f: f.abspath)

    @classmethod
    def empty(cls):
        """Return an empty RequestOutput."""
        return cls(packages=[], environment_variables=[], project_files=[])
