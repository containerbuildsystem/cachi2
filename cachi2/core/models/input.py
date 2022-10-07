import os.path
from pathlib import Path
from typing import ClassVar, Literal

import pydantic

from cachi2.core.models.validators import unique

# Supported package managers
PackageManagerType = Literal["gomod"]

Flag = Literal["cgo-disable", "force-gomod-tidy", "gomod-vendor", "gomod-vendor-check"]


class PackageInput(pydantic.BaseModel, extra="forbid"):
    """Specification of a package to process, as received from the user."""

    type: PackageManagerType
    path: Path = Path(".")

    @pydantic.validator("path")
    def check_path(cls, path: Path) -> Path:
        """Check that the path is relative and looks sane."""
        if path.is_absolute():
            raise ValueError(f"package path must be relative: {path}")
        if os.path.pardir in path.parts:
            raise ValueError(f"package path contains {os.path.pardir}: {path}")
        return path


class Request(pydantic.BaseModel):
    """Holds all data needed for the processing of a single request."""

    source_dir: Path
    output_dir: Path
    packages: list[PackageInput]
    flags: frozenset[Flag] = frozenset()
    dep_replacements: tuple[dict, ...] = ()  # TODO: do we want dep replacements at all?

    @pydantic.validator("source_dir", "output_dir")
    def resolve_path(cls, path: Path) -> Path:
        """Check that path is absolute and fully resolve it."""
        if not path.is_absolute():
            raise ValueError(f"path must be absolute: {path}")
        return path.resolve()

    @pydantic.validator("packages")
    def unique_packages(cls, packages: list[PackageInput]) -> list[PackageInput]:
        """De-duplicate the packages to be processed."""
        return unique(packages, by=lambda pkg: (pkg.type, pkg.path))

    @pydantic.validator("packages", each_item=True)
    def check_package_paths(cls, package: PackageInput, values: dict) -> PackageInput:
        """Check that package paths are existing subdirectories."""
        source_dir = values.get("source_dir")
        # Don't run validation if source_dir failed to validate
        if source_dir is not None:
            abspath = source_dir.joinpath(package.path).resolve()
            if not abspath.is_relative_to(source_dir):
                raise ValueError(
                    f"package path (a symlink?) leads outside source directory: {package.path}"
                )
            if not abspath.is_dir():
                raise ValueError(
                    f"package path does not exist (or is not a directory): {package.path}"
                )
        return package

    # This is kept here temporarily, should be refactored
    go_mod_cache_download_part: ClassVar[Path] = Path("pkg", "mod", "cache", "download")

    # This is kept here temporarily, should be refactored
    @property
    def gomod_download_dir(self):
        """Directory where the fetched dependencies will be placed."""
        return self.output_dir / "deps" / "gomod" / self.go_mod_cache_download_part
