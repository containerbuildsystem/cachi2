from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Callable, ClassVar, Literal, Optional, TypeVar, Union

import pydantic

from cachi2.core.errors import InvalidInput
from cachi2.core.models.validators import check_sane_relpath, unique
from cachi2.core.safepath import NotSubpath, SafePath

if TYPE_CHECKING:
    from pydantic.error_wrappers import ErrorDict

T = TypeVar("T")
ModelT = TypeVar("ModelT", bound=pydantic.BaseModel)


def parse_user_input(to_model: Callable[[T], ModelT], input_obj: T) -> ModelT:
    """Parse user input into a model, re-raise validation errors as InvalidInput."""
    try:
        return to_model(input_obj)
    except pydantic.ValidationError as e:
        raise InvalidInput(_present_user_input_error(e)) from e


def _present_user_input_error(validation_error: pydantic.ValidationError) -> str:
    """Make a slightly nicer representation of a pydantic.ValidationError.

    Compared to pydantic's default message:
    - don't show the model name, just say "user input"
    - don't show the underlying error type (e.g. "type=value_error.const")
    """
    errors = validation_error.errors()
    n_errors = len(errors)

    def show_error(error: "ErrorDict") -> str:
        location = " -> ".join(map(str, error["loc"]))
        context = "; ".join(f"{k}={v}" for k, v in error.get("ctx", {}).items())
        message = error["msg"]

        if context:
            message = f"{message} ({context})"

        if location != "__root__":
            message = f"{location}\n  {message}"

        return message

    header = f"{n_errors} validation error{'' if n_errors == 1 else 's'} for user input"
    details = "\n".join(map(show_error, errors))
    return f"{header}\n{details}"


# Supported package managers
PackageManagerType = Literal["gomod", "pip"]

Flag = Literal["cgo-disable", "force-gomod-tidy", "gomod-vendor", "gomod-vendor-check"]


class _PackageInputBase(pydantic.BaseModel, extra="forbid"):
    """Common input attributes accepted for all package types."""

    type: PackageManagerType
    path: Path = Path(".")

    @pydantic.validator("path")
    def _path_is_relative(cls, path: Path) -> Path:
        return check_sane_relpath(path)


class GomodPackageInput(_PackageInputBase):
    """Accepted input for a gomod package."""

    type: Literal["gomod"]


class PipPackageInput(_PackageInputBase):
    """Accepted input for a pip package."""

    type: Literal["pip"]
    requirements_files: Optional[list[Path]] = None
    requirements_build_files: Optional[list[Path]] = None

    @pydantic.validator("requirements_files", "requirements_build_files")
    def _no_explicit_none(cls, paths: Optional[list[Path]]) -> list[Path]:
        """Fail if the user explicitly passes None."""
        if paths is None:
            # Note: same error message as pydantic's default
            raise TypeError("none is not an allowed value")
        return paths

    @pydantic.validator("requirements_files", "requirements_build_files", each_item=True)
    def _requirements_file_path_is_relative(cls, path: Path) -> Path:
        return check_sane_relpath(path)


PackageInput = Annotated[
    Union[GomodPackageInput, PipPackageInput],
    # https://pydantic-docs.helpmanual.io/usage/types/#discriminated-unions-aka-tagged-unions
    pydantic.Field(discriminator="type"),
]


class Request(pydantic.BaseModel):
    """Holds all data needed for the processing of a single request."""

    source_dir: SafePath
    output_dir: SafePath
    packages: list[PackageInput]
    flags: frozenset[Flag] = frozenset()
    dep_replacements: tuple[dict, ...] = ()  # TODO: do we want dep replacements at all?

    @pydantic.validator("source_dir", "output_dir")
    def _make_path_safe(cls, path: Path) -> SafePath:
        """Check that the path is absolute, fully resolve it and convert to SafePath."""
        if not path.is_absolute():
            raise ValueError(f"path must be absolute: {path}")
        # Needs to be explicitly converted to SafePath - otherwise, the directories
        # would be regular Paths despite being annotated as SafePath
        return SafePath(path.resolve())

    @pydantic.validator("packages")
    def _unique_packages(cls, packages: list[PackageInput]) -> list[PackageInput]:
        """De-duplicate the packages to be processed."""
        return unique(packages, by=lambda pkg: (pkg.type, pkg.path))

    @pydantic.validator("packages", each_item=True)
    def _check_package_paths(cls, package: PackageInput, values: dict) -> PackageInput:
        """Check that package paths are existing subdirectories."""
        source_dir = values.get("source_dir")
        # Don't run validation if source_dir failed to validate
        if source_dir is not None:
            try:
                abspath = source_dir / package.path
            except NotSubpath:
                raise ValueError(
                    f"package path (a symlink?) leads outside source directory: {package.path}"
                )
            if not abspath.is_dir():
                raise ValueError(
                    f"package path does not exist (or is not a directory): {package.path}"
                )
        return package

    @pydantic.validator("packages")
    def _packages_not_empty(cls, packages: list[PackageInput]) -> list[PackageInput]:
        """Check that the packages list is not empty."""
        if len(packages) == 0:
            raise ValueError("at least one package must be defined, got an empty list")
        return packages

    @property
    def gomod_packages(self) -> list[GomodPackageInput]:
        """Get the gomod packages specified for this request."""
        return self._packages_by_type(GomodPackageInput)

    @property
    def pip_packages(self) -> list[PipPackageInput]:
        """Get the pip packages specified for this request."""
        return self._packages_by_type(PipPackageInput)

    def _packages_by_type(self, pkgtype: type[T]) -> list[T]:
        return [package for package in self.packages if isinstance(package, pkgtype)]

    # This is kept here temporarily, should be refactored
    go_mod_cache_download_part: ClassVar[Path] = Path("pkg", "mod", "cache", "download")

    # This is kept here temporarily, should be refactored
    @property
    def gomod_download_dir(self):
        """Directory where the fetched dependencies will be placed."""
        return self.output_dir / "deps" / "gomod" / self.go_mod_cache_download_part
