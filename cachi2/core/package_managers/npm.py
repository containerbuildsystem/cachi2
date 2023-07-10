import asyncio
import copy
import fnmatch
import functools
import json
import logging
import os.path
from pathlib import Path
from typing import Any, Dict, Iterator, Literal, NewType, Optional, TypedDict
from urllib.parse import urlparse

from packageurl import PackageURL

from cachi2.core.checksum import ChecksumInfo, must_match_any_checksum
from cachi2.core.config import get_config
from cachi2.core.errors import PackageRejected, UnexpectedFormat, UnsupportedFeature
from cachi2.core.models.input import Request
from cachi2.core.models.output import Component, ProjectFile, RequestOutput
from cachi2.core.package_managers.general import async_download_files
from cachi2.core.rooted_path import RootedPath
from cachi2.core.scm import RepoID, clone_as_tarball, get_repo_id

DEPENDENCY_TYPES = (
    "dependencies",
    "devDependencies",
    "optionalDependencies",
    "peerDependencies",
)
log = logging.getLogger(__name__)

# Known CNAMEs for the official npm registry server.
# In rare cases, package-lock.json may contain resolved urls with the yarn CNAME.
# This most likely happens when converting a yarn.lock to package-lock.json
# ("importing" one with npm or "exporting" with yarn).
NPM_REGISTRY_CNAMES = ("registry.npmjs.org", "registry.yarnpkg.com")


class ResolvedNpmPackage(TypedDict):
    """Contains all of the data for a resolved npm package."""

    package: dict[str, str]
    dependencies: list[dict[str, str]]
    projectfiles: list[ProjectFile]


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
    def integrity(self) -> Optional[str]:
        """Get the package integrity."""
        return self._package_dict.get("integrity")

    @integrity.setter
    def integrity(self, integrity: str) -> None:
        """Set the package integrity."""
        self._package_dict["integrity"] = integrity

    @property
    def link(self) -> Optional[Any]:
        """Get the package link."""
        return self._package_dict.get("link")

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
    def semver_version(self) -> Optional[str]:
        """Get the semver version, if available.

        For v1/v2 `dependencies`, the semver version is only available for registry dependencies
        and bundled dependencies.

        For v2+ `packages`, the semver version is always available.
        """
        # v2+
        if self.path:
            return self.version
        # v1 registry or bundled
        elif "resolved" in self._package_dict or self._package_dict.get("bundled"):
            return self.version
        else:
            return None

    @property
    def dependencies(self) -> Optional[Any]:
        """Get the dict of package dependencies, if available."""
        return self._package_dict.get("dependencies") or None

    @property
    def resolved_url(self) -> Optional[str]:
        """Get the location where the package was resolved from.

        For v1/v2 package-lock.json `dependencies`, this will be the "resolved"
        key for registry deps and the "version" key for non-registry deps.

        For v2+ package-lock.json `packages`, this will be the "resolved" key
        unless it is a file dep, in which case it will be the path to the file.

        For bundled dependencies, this will be None. Such dependencies are included
        in the tarball of a different dependency (the dependency that bundles them).
        """
        if "resolved" not in self._package_dict:
            # indirect bundled dependency, does not have a resolved url
            if self._package_dict.get("bundled") or self._package_dict.get("inBundle"):
                return None
            # v2+ file dependency (or a workspace)
            elif self.path:
                return f"file:{self.path}"
            # v1 non-registry dependency
            else:
                return self.version

        return self._package_dict["resolved"]

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
        self._workspaces: list[str] = []
        self._lockfile_path = lockfile_path
        self._lockfile_data = lockfile_data
        self._packages = self._get_packages()
        self._dependencies = self._get_dependencies()

    @property
    def lockfile_version(self) -> int:
        """Get the lockfileVersion from package-lock.json data."""
        return self._lockfile_data["lockfileVersion"]

    def check_if_package_is_workspace(self, resolved_url: str) -> bool:
        """Test if package is workspace based on main package workspaces."""
        if (
            "packages" not in self._lockfile_data
            or "" not in self._lockfile_data["packages"]
            or "workspaces" not in self._lockfile_data["packages"][""]
        ):
            return False

        main_package_workspaces = self._lockfile_data["packages"][""]["workspaces"]

        for main_package_workspace in main_package_workspaces:
            if fnmatch.fnmatch(resolved_url, main_package_workspace.removeprefix("./")):
                return True
        return False

    @functools.cached_property
    def _purlifier(self) -> "_Purlifier":
        pkg_path = self._lockfile_path.join_within_root("..")
        return _Purlifier(pkg_path)

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
            if package_data.get("link"):
                if self.check_if_package_is_workspace(package_data.get("resolved")):
                    self._workspaces.append(package_data.get("resolved"))
                continue

            if package_path == "":
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

    def get_main_package(self) -> dict[str, str]:
        """Return a dict with sbom component data for the main package."""
        name = self._lockfile_data["name"]
        version = self._lockfile_data["version"]
        purl = self._purlifier.get_purl(name, version, "file:.", integrity=None)
        return {"name": name, "version": version, "purl": purl.to_string()}

    def get_sbom_components(self) -> list[dict[str, str]]:
        """Return a list of dicts with sbom component data."""
        packages = self._dependencies if self.lockfile_version == 1 else self._packages

        def to_component(package: Package) -> dict[str, str]:
            name = package.name
            version = package.semver_version
            purl = self._purlifier.get_purl(name, version, package.resolved_url, package.integrity)
            if version:
                return {"name": name, "version": version, "purl": purl.to_string()}
            else:
                return {"name": name, "purl": purl.to_string()}

        return list(map(to_component, packages))

    def get_dependencies_to_download(self) -> Dict[str, Dict[str, Optional[str]]]:
        """Return a Dict of URL dependencies to download."""
        packages = self._dependencies if self.lockfile_version == 1 else self._packages
        return {
            resolved_url: {
                "version": package.version,
                "name": package.name,
                "integrity": package.integrity,
            }
            for package in packages
            if (resolved_url := package.resolved_url) and not resolved_url.startswith("file:")
        }

    @property
    def workspaces(self) -> list:
        """Return list of workspaces."""
        return self._workspaces


class _Purlifier:
    """Generates purls for npm packages."""

    def __init__(self, pkg_path: RootedPath) -> None:
        """Init a purlifier for the package at pkg_path."""
        self._pkg_path = pkg_path

    @functools.cached_property
    def _repo_id(self) -> RepoID:
        return get_repo_id(self._pkg_path.root)

    def get_purl(
        self,
        name: str,
        version: Optional[str],
        resolved_url: Optional[str],
        integrity: Optional[str],
    ) -> PackageURL:
        """Get the purl for an npm package.

        https://github.com/package-url/purl-spec/blob/master/PURL-TYPES.rst#npm
        """
        if not resolved_url:
            # bundled dependency, same purl as a registry dependency
            # (differentiation between bundled and registry should be done elsewhere)
            return PackageURL(type="npm", name=name.lower(), version=version)

        qualifiers: Optional[dict[str, str]] = None
        subpath: Optional[str] = None

        resolved_url = _normalize_resolved_url(resolved_url)
        dep_type = _classify_resolved_url(resolved_url)

        if dep_type == "registry":
            pass
        elif dep_type == "git":
            info = _extract_git_info_npm(resolved_url)
            repo_id = RepoID(origin_url=info["url"], commit_id=info["ref"])
            qualifiers = {"vcs_url": repo_id.as_vcs_url_qualifier()}
        elif dep_type == "file":
            qualifiers = {"vcs_url": self._repo_id.as_vcs_url_qualifier()}
            path = urlparse(resolved_url).path
            subpath_from_root = self._pkg_path.join_within_root(path).subpath_from_root
            if subpath_from_root != Path():
                subpath = subpath_from_root.as_posix()
        else:  # dep_type == "https"
            qualifiers = {"download_url": resolved_url}
            if integrity:
                algorithm, digest = ChecksumInfo.from_sri(integrity)
                qualifiers["checksum"] = f"{algorithm}:{digest}"

        return PackageURL(
            type="npm",
            name=name.lower(),
            version=version,
            qualifiers=qualifiers,
            subpath=subpath,
        )


NormalizedUrl = NewType("NormalizedUrl", str)


def _normalize_resolved_url(resolved_url: str) -> NormalizedUrl:
    if resolved_url.startswith(("github:", "gitlab:", "bitbucket:")):
        resolved_url = _update_vcs_url_with_full_hostname(resolved_url)
    return NormalizedUrl(resolved_url)


def _classify_resolved_url(
    resolved_url: NormalizedUrl,
) -> Literal["registry", "git", "file", "https"]:
    url = urlparse(resolved_url)
    if url.hostname in NPM_REGISTRY_CNAMES:
        return "registry"
    if url.scheme == "git" or url.scheme.startswith("git+"):
        return "git"
    if url.scheme == "file":
        return "file"
    return "https"


def _update_vcs_url_with_full_hostname(vcs: str) -> str:
    """Update VCS URL with full hostname.

    Transform github:kevva/is-positive#97edff6
    into git+ssh://github.com/kevva/is-positive.git#97edff6

    :param vcs: VCS URL to be modified with full hostname and file extension
    :return: Updated VCS URL
    """
    host, _, path = vcs.partition(":")
    namespace_repo, _, ref = path.partition("#")
    suffix_domain = "org" if host == "bitbucket" else "com"

    vcs = f"git+ssh://git@{host}.{suffix_domain}/{namespace_repo}.git"
    if ref:
        vcs = f"{vcs}#{ref}"
    return vcs


def _extract_git_info_npm(vcs_url: NormalizedUrl) -> Dict[str, str]:
    """
    Extract important info from a VCS requirement URL.

    Given a URL such as git+ssh://user@host/namespace/repo.git#9e164b970

    this function will extract:
    - the "clean" URL: ssh://user@host/namespace/repo.git
    - the git ref: 9e164b970

    The clean URL and ref can be passed straight to scm.Git to fetch the repo.
    The host, namespace and repo will be used to construct the file path under deps/npm.

    :param vcs_url: The URL of a VCS requirement, must be valid (have git ref in path)
    :return: Dict with url, ref, host, namespace and repo keys
    """
    clean_url, _, ref = vcs_url.partition("#")
    # if scheme is git+protocol://, keep only protocol://
    clean_url = clean_url.removeprefix("git+")

    url = urlparse(clean_url)
    namespace_repo = url.path.strip("/").removesuffix(".git")

    # Everything up to the last '/' is namespace, the rest is repo
    namespace, _, repo = namespace_repo.partition("/")

    vcs_url_info = {
        "url": clean_url,
        "ref": ref.lower(),
        "namespace": namespace,
        "repo": repo,
    }

    for key, value in vcs_url_info.items():
        if not value:
            raise UnexpectedFormat(f"{vcs_url} is not valid VCS url. {key} is missing.")

    if url.hostname:
        vcs_url_info["host"] = url.hostname
    else:
        raise UnexpectedFormat(f"{vcs_url} is not valid VCS url. Host is missing.")

    return vcs_url_info


def _clone_repo_pack_archive(
    vcs: NormalizedUrl,
    download_dir: RootedPath,
) -> RootedPath:
    """
    Clone a repository and pack its content as tar.

    :param url: URL for file download
    :param download_dir: Output folder where dependencies will be downloaded
    :raise FetchError: If download failed
    """
    info = _extract_git_info_npm(vcs)
    download_path = download_dir.join_within_root(
        info["host"],  # host
        info["namespace"],
        info["repo"],
        f'{info["repo"]}-external-gitcommit-{info["ref"]}.tgz',
    )

    # Create missing directories
    directory = os.path.dirname(download_path)
    os.makedirs(directory, exist_ok=True)
    clone_as_tarball(info["url"], info["ref"], download_path.path)

    return download_path


def _get_npm_dependencies(
    download_dir: RootedPath, deps_to_download: Dict[str, Dict[str, Optional[str]]]
) -> Dict[NormalizedUrl, RootedPath]:
    """
    Download npm dependencies.

    Receives the destination directory (download_dir)
    and the dependencies to be downloaded (deps_to_download).

    :param download_dir: Destination directory path where deps will be downloaded
    :param deps_to_download: Dict of dependencies to be downloaded.
    :return: Dictionary of Resolved URL dependencies with downloaded paths
    """
    files_to_download: dict[str, dict[str, Any]] = {}
    download_paths = {}
    for url, info in deps_to_download.items():
        url = _normalize_resolved_url(url)
        dep_type = _classify_resolved_url(url)

        if dep_type == "file":
            continue
        elif dep_type == "git":
            download_paths[url] = _clone_repo_pack_archive(url, download_dir)
        else:
            if dep_type == "registry":
                archive_name = f'{info["name"]}-{info["version"]}.tgz'.removeprefix("@").replace(
                    "/", "-"
                )
                download_paths[url] = download_dir.join_within_root(archive_name)
            else:  # dep_type == "https"
                if info["integrity"]:
                    algorithm, digest = ChecksumInfo.from_sri(info["integrity"])
                else:
                    raise PackageRejected(
                        f"{info['name']} is missing integrity checksum. It is mandatory"
                        f"for https dependencies.",
                        solution="Please double-check provided package-lock.json that"
                        " your dependencies specify integrity. Try to "
                        "rerun `npm install` on your repository.",
                    )
                download_paths[url] = download_dir.join_within_root(
                    f"external-{info['name']}",
                    f"{info['name']}-external-{algorithm}-{digest}.tgz",
                )

                # Create missing directories
                directory = os.path.dirname(download_paths[url])
                os.makedirs(directory, exist_ok=True)

            files_to_download[url] = {
                "download_path": download_paths[url],
                "integrity": info["integrity"],
            }

    # Asynchronously download tar files
    asyncio.run(
        async_download_files(
            {url: item["download_path"] for (url, item) in files_to_download.items()},
            get_config().concurrency_limit,
        )
    )

    # Check integrity of downloaded packages
    for url, item in files_to_download.items():
        if item["integrity"]:
            must_match_any_checksum(
                item["download_path"], [ChecksumInfo.from_sri(str(item["integrity"]))]
            )
        else:
            log.warning("Missing integrity for %s, integrity check skipped.", url)

    return download_paths


def replace_dependency(dependency_version: str) -> bool:
    """Check if dependency must be updated in package(-lock).json.

    package(-lock).json files require to replace dependency URLs for
    empty string in git and https dependencies in V2+ and V1 dependency URLs
    should be replaced for local paths to fetched dependencies.
    """
    url = urlparse(dependency_version)
    if url.scheme == "file":
        return False
    return not (url.scheme == "" and "/" not in dependency_version)


def update_package_lock_with_local_paths(
    download_paths: Dict[NormalizedUrl, RootedPath],
    package_lock: PackageLock,
) -> Optional[Dict[str, str]]:
    """Replace packages resolved URLs with local paths.

    Update package-lock.json file in a way it can be used in isolated environment (container)
    without internet connection. All package/dependency URLs will be replaced for
    local paths to downloaded dependencies.

    :param download_paths:
    :param package_lock: PackageLock instance which holds package-lock.json content
    """
    if package_lock.lockfile_version > 1:
        for package in package_lock._get_packages():
            # Remove integrity for git sources, their integrity checksum will change when
            # constructing tar archive from cloned repository
            if package.resolved_url:
                url = _normalize_resolved_url(str(package.resolved_url))
            else:
                continue
            if _classify_resolved_url(url) == "git":
                if package.integrity:
                    package.integrity = ""

            # Update all type of dependencies except file:
            if _classify_resolved_url(url) != "file":
                templated_abspath = Path("${output_dir}", download_paths[url].subpath_from_root)
                package.resolved_url = f"file://{templated_abspath}"

            for dep_type in DEPENDENCY_TYPES:
                if package._package_dict.get(dep_type):
                    for dependency, dependency_version in package._package_dict[dep_type].items():
                        if replace_dependency(dependency_version):
                            package._package_dict[dep_type].update({dependency: ""})

        main_package = package_lock._lockfile_data["packages"][""]
        for dep_type in DEPENDENCY_TYPES:
            if main_package.get(dep_type):
                for dependency, dependency_version in main_package[dep_type].items():
                    if replace_dependency(dependency_version):
                        main_package[dep_type].update({dependency: ""})
        return {}
    else:
        # TODO: This part for V1 packages is still in development <--
        replace_deps = {}
        for package in package_lock._get_dependencies():
            if package.resolved_url:
                url = _normalize_resolved_url(str(package.resolved_url))
            else:
                continue

            if _classify_resolved_url(url) == "git":
                if package.integrity:
                    package.integrity = ""

            # Update all type of dependencies except file:
            if _classify_resolved_url(url) != "file":
                templated_abspath = Path("${output_dir}", download_paths[url].subpath_from_root)
                package.resolved_url = f"file://{templated_abspath}"
                replace_deps[package.name] = package.resolved_url

            # requires item needs to be removed, otherwise npm will try to download all required dependencies and
            # hermetic build will fail
            if package._package_dict.get("requires"):
                del package._package_dict["requires"]

            for dep_type in DEPENDENCY_TYPES:
                if package._package_dict.get(
                    dep_type
                ):  # TODO: Recursively update dependencies for V1, check if it's needed??
                    for dependency, dependency_dict in package._package_dict[dep_type].items():
                        key = "resolved" if "resolved" in dependency_dict else "version"
                        if replace_dependency(dependency_dict[key]):
                            templated_abspath = Path(
                                "${output_dir}",
                                download_paths[dependency_dict[key]].subpath_from_root,
                            )
                            package._package_dict[dep_type][dependency].update(
                                {key: f"file://{templated_abspath}"}
                            )
        # TODO: This part for V1 packages is still in development -->
        return replace_deps


def update_package_json_files(
    workspaces: list[str],
    pkg_dir: RootedPath,
    replace_deps: Optional[Dict[str, str]],
    lockfile_version: int,
) -> list[ProjectFile]:
    """Set dependencies to empty string in package.json files.

    :param workspaces: list of workspaces paths
    :param pkg_dir: Package subdirectory
    """
    package_json_paths = []
    if lockfile_version > 1:
        for workspace in workspaces:
            package_json_paths.append(pkg_dir.join_within_root(workspace, "package.json"))
    package_json_paths.append(pkg_dir.join_within_root("package.json"))

    package_json_projectfiles = []
    for package_json_path in package_json_paths:
        with open(package_json_path, "r") as f:
            package_json_content = json.load(f)

        for dep_type in DEPENDENCY_TYPES:
            if package_json_content.get(dep_type):
                for dependency, url in package_json_content[dep_type].items():
                    if lockfile_version > 1:
                        if replace_dependency(url):
                            package_json_content[dep_type].update({dependency: ""})
                    else:
                        if urlparse(url).scheme != "file":
                            if replace_deps:
                                package_json_content[dep_type].update(
                                    {dependency: replace_deps.get(dependency, "")}
                                )

        package_json_projectfiles.append(
            ProjectFile(
                abspath=package_json_path.path,
                template=json.dumps(package_json_content, indent=2) + "\n",
            )
        )
    return package_json_projectfiles


def fetch_npm_source(request: Request) -> RequestOutput:
    """Resolve and fetch npm dependencies for the given request.

    :param request: the request to process
    :return: A RequestOutput object with content for all npm packages in the request
    """
    components: list[Component] = []
    project_files: list[ProjectFile] = []

    npm_deps_dir = request.output_dir.join_within_root("deps", "npm")
    npm_deps_dir.path.mkdir(parents=True, exist_ok=True)

    for package in request.npm_packages:
        info = _resolve_npm(package.path, request.source_dir, request.output_dir, npm_deps_dir)
        components.append(Component.from_package_dict(info["package"]))

        for dependency in info["dependencies"]:
            components.append(Component.from_package_dict(dependency))

        for projectfile in info["projectfiles"]:
            project_files.append(projectfile)

    return RequestOutput.from_obj_list(
        components=components,
        environment_variables=[],
        project_files=project_files,
    )


def _resolve_npm(
    pkg_subpath: Path, source_dir: RootedPath, output_dir: RootedPath, npm_deps_dir: RootedPath
) -> ResolvedNpmPackage:
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
    pkg_path = source_dir.join_within_root(pkg_subpath)

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
    original_package_lock = PackageLock.from_file(package_lock_path)
    package_lock = copy.deepcopy(original_package_lock)

    # Download dependencies via resolved URLs and return download_paths for updating
    # package-lock.json with local file paths
    download_paths = _get_npm_dependencies(
        npm_deps_dir, package_lock.get_dependencies_to_download()
    )

    # Update package-lock.json, package.json(s) files with local paths to dependencies and store them as ProjectFiles
    replace_deps = update_package_lock_with_local_paths(download_paths, package_lock)
    projectfiles = update_package_json_files(
        package_lock.workspaces, source_dir, replace_deps, package_lock.lockfile_version
    )
    projectfiles.append(package_lock.get_project_file())

    return {
        "package": original_package_lock.get_main_package(),
        "dependencies": original_package_lock.get_sbom_components(),
        "projectfiles": projectfiles,
    }
