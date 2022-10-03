from pathlib import Path
from typing import Any, Callable, Iterable, Literal, Optional, TypeVar

import pydantic

T = TypeVar("T")


def unique(items: Iterable[T], by: Callable[[T], Any], dedupe: bool = True) -> list[T]:
    """Make sure input items are unique by the specified key.

    The 'by' function must return a hashable key (the uniqueness key).

    If item A and item B have the same key, then
        if dedupe is true (the default) and A == B, B is discarded
        if dedupe is false or A != B, raise an error
    """
    by_key = {}
    for item in items:
        key = by(item)
        if key not in by_key:
            by_key[key] = item
        elif not dedupe or by_key[key] != item:
            raise ValueError(f"conflict by {key}: {by_key[key]} X {item}")
    return list(by_key.values())


def unique_sorted(items: Iterable[T], by: Callable[[T], Any], dedupe: bool = True) -> list[T]:
    """Make sure input items are unique and sort them.

    Same as 'unique()' but the key returned from the 'by' function must support ordering.
    """
    unique_items = unique(items, by, dedupe)
    unique_items.sort(key=by)
    return unique_items


# Supported package types (a superset of the supported package *manager* types)
PackageType = Literal["gomod", "go-package"]


class Dependency(pydantic.BaseModel):
    """Metadata about a resolved dependency."""

    type: PackageType
    name: str
    version: Optional[str]  # go-package stdlib dependencies are allowed not to have versions

    @pydantic.validator("version")
    def check_version_vs_type(cls, version: Optional[str], values: dict) -> Optional[str]:
        """Check that the dependency has a version or is 'go-package'."""
        ptype = values.get("type")
        if ptype is not None and (version is None and ptype != "go-package"):
            raise TypeError(f"{values['type']} dependencies must have a version")
        return version


class Package(pydantic.BaseModel):
    """Metadata about a resolved package and its dependencies."""

    type: PackageType
    path: Path  # relative from source directory
    name: str
    version: str
    dependencies: list[Dependency]

    @pydantic.validator("path")
    def check_path(cls, path: Path) -> Path:
        """Check that the package path is relative."""
        if path.is_absolute():
            raise ValueError(f"package path must be relative: {path}")
        return path

    @pydantic.validator("dependencies")
    def unique_deps(cls, dependencies: list[Dependency]) -> list[Dependency]:
        """Sort and de-duplicate dependencies."""
        return unique_sorted(dependencies, by=lambda dep: (dep.type, dep.name, dep.version))


class EnvironmentVariable(pydantic.BaseModel):
    """An environment variable."""

    name: str
    value: str
    kind: Literal["literal", "path"]


class RequestOutput(pydantic.BaseModel):
    """Results of processing one or more package managers."""

    packages: list[Package]
    environment_variables: list[EnvironmentVariable]

    @pydantic.validator("packages")
    def unique_packages(cls, packages: list[Package]) -> list[Package]:
        """Sort packages and check that there are no duplicates."""
        return unique_sorted(
            packages,
            by=lambda pkg: (pkg.type, pkg.name, pkg.version),
            dedupe=False,  # de-duplicating could be quite expensive with many dependencies
        )

    @pydantic.validator("environment_variables")
    def unique_env_vars(cls, env_vars: list[EnvironmentVariable]) -> list[EnvironmentVariable]:
        """Sort and de-duplicate environment variables by name."""
        return unique_sorted(env_vars, by=lambda env_var: env_var.name)

    @classmethod
    def empty(cls):
        """Return an empty RequestOutput."""
        return cls(packages=[], environment_variables=[])
