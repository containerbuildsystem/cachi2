import json
import logging
from pathlib import Path
from typing import Any, Iterator, TypedDict

from cachi2.core.errors import PackageRejected, UnsupportedFeature
from cachi2.core.models.input import Request
from cachi2.core.models.output import Component, ProjectFile, RequestOutput
from cachi2.core.rooted_path import RootedPath

log = logging.getLogger(__name__)


class ResolvedNpmPackage(TypedDict):
    """Contains all of the data for a resolved npm package."""

    package: dict[str, str]
    dependencies: list[dict[str, str]]
    package_lock_file: ProjectFile


class Package:
    """A npm package."""

    def __init__(self, name: str, path: str, package_dict: dict[str, Any]) -> None:
        """Initialize a Package.

        :param name: the package name, which should correspond to the name in it's package.json
        :param path: the relative path to the package from the root project dir. This is set for
                     for package-lock.json `packages` and falsy for `dependencies`.
        :param package_dict: the raw dict for a package-lock.json `package` or `dependency`
        """
        self.name = name
        self.path = path
        self._package_dict = package_dict

    @property
    def version(self) -> str:
        """Get the package version.

        For v1/v2 package-lock.json `dependencies`, this will be a semver
        for registry dependencies and a url for git/https/filepath sources.
        https://docs.npmjs.com/cli/v6/configuring-npm/package-lock-json#dependencies

        For v2+ package-lock.json `packages`, this will be a semver from the package.json file.
        https://docs.npmjs.com/cli/v7/configuring-npm/package-lock-json#packages
        """
        return self._package_dict["version"]

    @property
    def resolved_url(self) -> str:
        """Get the location where the package was resolved from.

        For v1/v2 package-lock.json `dependencies`, this will be the "resolved"
        key for registry deps and the "version" key for non-registry deps.

        For v2+ package-lock.json `packages`, this will be the "resolved" key
        unless it is a file dep, in which case it will be the path to the file.
        """
        if self.path and "resolved" not in self._package_dict:
            return f"file:{self.path}"

        return self._package_dict.get("resolved") or self.version

    @resolved_url.setter
    def resolved_url(self, resolved_url: str) -> None:
        """Set the location where the package should be resolved from.

        For v1/v2 package-lock.json `dependencies`, this will be the "resolved"
        key for registry deps and the "version" key for non-registry deps.

        For v2+ package-lock.json `packages`, this will be the "resolved" key.
        """
        key = "resolved" if "resolved" in self._package_dict else "version"
        self._package_dict[key] = resolved_url

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, Package):
            return (
                self.name == other.name
                and self.path == other.path
                and self._package_dict == other._package_dict
            )
        return False


class PackageLock:
    """A npm package-lock.json file."""

    def __init__(self, lockfile_path: RootedPath, lockfile_data: dict[str, Any]) -> None:
        """Initialize a PackageLock."""
        self._lockfile_path = lockfile_path
        self._lockfile_data = lockfile_data
        self._packages = self._get_packages()
        self._dependencies = self._get_dependencies()

    @property
    def lockfile_version(self) -> int:
        """Get the lockfileVersion from package-lock.json data."""
        return self._lockfile_data["lockfileVersion"]

    @property
    def main_package(self) -> dict[str, str]:
        """Return a dict with sbom component data for the main package."""
        return {"name": self._lockfile_data["name"], "version": self._lockfile_data["version"]}

    @classmethod
    def from_file(cls, lockfile_path: RootedPath) -> "PackageLock":
        """Create a PackageLock from a package-lock.json file."""
        with lockfile_path.path.open("r") as f:
            lockfile_data = json.load(f)

        lockfile_version = lockfile_data.get("lockfileVersion")
        if lockfile_version not in (1, 2, 3):
            raise UnsupportedFeature(
                f"lockfileVersion {lockfile_version} from {lockfile_path} is not supported",
                solution="Please use a supported lockfileVersion, which are versions 1, 2, and 3",
            )

        return cls(lockfile_path, lockfile_data)

    def get_project_file(self) -> ProjectFile:
        """Return a ProjectFile for the npm package-lock.json data."""
        return ProjectFile(
            abspath=self._lockfile_path.path.resolve(),
            template=json.dumps(self._lockfile_data, indent=2) + "\n",
        )

    def _get_packages(self) -> list[Package]:
        """Return a flat list of Packages from a v2+ package-lock.json file.

        Use the "packages" key in the lockfile.
        """

        def get_package_name_from_path(package_path: str) -> str:
            """Get the package name from the path in v2+ package-lock.json file."""
            path = Path(package_path)
            parent_name = Path(package_path).parents[0].name
            is_scoped = parent_name.startswith("@")
            return (Path(parent_name) / path.name).as_posix() if is_scoped else path.name

        packages = []
        for package_path, package_data in self._lockfile_data.get("packages", {}).items():
            # ignore links and the main package, since they're already accounted
            # for elsewhere in the lockfile
            if package_data.get("link") or package_path == "":
                continue
            # if there is no name key, derive it from the package path
            if not (package_name := package_data.get("name")):
                package_name = get_package_name_from_path(package_path)

            packages.append(Package(package_name, package_path, package_data))

        return packages

    def _get_dependencies(self) -> list[Package]:
        """Return a flat list of Packages from a v1/v2 package-lock.json file.

        Use the "dependencies" key in the lockfile.
        """

        def get_dependencies_iter(dependencies: dict[str, dict[str, Any]]) -> Iterator[Package]:
            for dependency_name, dependency_data in dependencies.items():
                yield Package(dependency_name, "", dependency_data)
                # v1 lockfiles can have nested dependencies
                if "dependencies" in dependency_data:
                    yield from get_dependencies_iter(dependency_data["dependencies"])

        return list(get_dependencies_iter(self._lockfile_data.get("dependencies", {})))

    def get_sbom_components(self) -> list[dict[str, str]]:
        """Return a list of dicts with sbom component data."""
        packages = self._dependencies if self.lockfile_version == 1 else self._packages
        return [{"name": package.name, "version": package.version} for package in packages]


def fetch_npm_source(request: Request) -> RequestOutput:
    """Resolve and fetch npm dependencies for the given request.

    :param request: the request to process
    :return: A RequestOutput object with content for all npm packages in the request
    """
    components: list[Component] = []
    project_files: list[ProjectFile] = []

    for package in request.npm_packages:
        info = _resolve_npm(request.source_dir.join_within_root(package.path))

        components.append(Component.from_package_dict(info["package"]))
        project_files.append(info["package_lock_file"])

        for dependency in info["dependencies"]:
            components.append(Component.from_package_dict(dependency))

    return RequestOutput.from_obj_list(
        components=components,
        environment_variables=[],
        project_files=project_files,
    )


def _resolve_npm(pkg_path: RootedPath) -> ResolvedNpmPackage:
    """Resolve and fetch npm dependencies for the given package.

    :param pkg_path: the path to the directory containing npm-shrinkwrap.json or package-lock.json
    :return: a dictionary that has the following keys:
        ``package`` which is the dict representing the main Package,
        ``dependencies`` which is a list of dicts representing the package Dependencies
        ``package_lock_file`` which is the (updated) package-lock.json as a ProjectFile
    :raises PackageRejected: if the npm package is not cachi2 compatible
    """
    # npm-shrinkwrap.json and package-lock.json share the same format but serve slightly
    # different purposes. See the following documentation for more information:
    # https://docs.npmjs.com/files/package-lock.json.
    for lock_file in ("npm-shrinkwrap.json", "package-lock.json"):
        package_lock_path = pkg_path.join_within_root(lock_file)
        if package_lock_path.path.exists():
            break
    else:
        raise PackageRejected(
            "The npm-shrinkwrap.json or package-lock.json file must be present for the npm "
            "package manager",
            solution="Please double-check that you have specified the correct path to the package directory containing one of those two files",
        )

    package_lock = PackageLock.from_file(package_lock_path)

    return {
        "package": package_lock.main_package,
        "dependencies": package_lock.get_sbom_components(),
        "package_lock_file": package_lock.get_project_file(),
    }
