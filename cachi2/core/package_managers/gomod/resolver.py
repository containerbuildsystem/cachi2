import logging
import os
import re
import shutil

import tempfile
from pathlib import Path
from typing import (
    Iterable,
    NamedTuple,
    Optional,
    Union,
)

import git
import git.objects

from packageurl import PackageURL

from cachi2.core.config import get_config
from cachi2.core.errors import (
    GoModError,
    PackageRejected,
    UnsupportedFeature,
)
from cachi2.core.models.input import Request
from cachi2.core.models.output import Component, EnvironmentVariable, RequestOutput
from cachi2.core.rooted_path import RootedPath
from cachi2.core.utils import run_cmd
from cachi2.core.package_managers.gomod.parser import resolve_gomod, run_gomod_cmd, ParsedModule, ParsedPackage
from cachi2.core.package_managers.gomod.version import get_golang_version

log = logging.getLogger(__name__)


GOMOD_DOC = "https://github.com/containerbuildsystem/cachi2/blob/main/docs/gomod.md"
GOMOD_INPUT_DOC = f"{GOMOD_DOC}#specifying-modules-to-process"
VENDORING_DOC = f"{GOMOD_DOC}#vendoring"


class Module(NamedTuple):
    """A Go module with relevant data for the SBOM generation.

    name: the resolved name for this module
    original_name: module's name as written in go.mod, before any replacement
    real_path: real path to locate the package on the Internet, which might differ from its name
    version: the resolved version for this module
    main: if this is the main module in the repository subpath that is being processed
    """

    name: str
    original_name: str
    real_path: str
    version: str
    main: bool = False

    @property
    def purl(self) -> str:
        """Get the purl for this module."""
        purl = PackageURL(
            type="golang",
            name=self.real_path,
            version=self.version,
            qualifiers={"type": "module"},
        )
        return purl.to_string()

    def to_component(self) -> Component:
        """Create a SBOM component for this module."""
        return Component(name=self.name, version=self.version, purl=self.purl)


class Package(NamedTuple):
    """A Go package with relevant data for the SBOM generation.

    relative_path: the package path relative to its parent module's name
    module: parent module for this package
    """

    relative_path: Optional[str]
    module: Module

    @property
    def name(self) -> str:
        """Get the name for this package based on the parent module's name."""
        if self.relative_path:
            return f"{self.module.name}/{self.relative_path}"

        return self.module.name

    @property
    def real_path(self) -> str:
        """Get the real path to locate this package on the Internet."""
        if self.relative_path:
            return f"{self.module.real_path}/{self.relative_path}"

        return self.module.real_path

    @property
    def purl(self) -> str:
        """Get the purl for this package."""
        purl = PackageURL(
            type="golang",
            name=self.real_path,
            version=self.module.version,
            qualifiers={"type": "package"},
        )
        return purl.to_string()

    def to_component(self) -> Component:
        """Create a SBOM component for this package."""
        return Component(name=self.name, version=self.module.version, purl=self.purl)


class StandardPackage(NamedTuple):
    """A package from Go standard lib used in the SBOM generation.

    Standard lib packages lack a parent module and, consequentially, a version.
    """

    name: str

    @property
    def purl(self) -> str:
        """Get the purl for this package."""
        purl = PackageURL(type="golang", name=self.name, qualifiers={"type": "package"})
        return purl.to_string()

    def to_component(self) -> Component:
        """Create a SBOM component for this package."""
        return Component(name=self.name, purl=self.purl)


def _create_modules_from_parsed_data(
    main_module: Module, main_module_dir: RootedPath, parsed_modules: Iterable[ParsedModule]
) -> list[Module]:
    def _create_module(module: ParsedModule) -> Module:
        if not (replace := module.replace):
            name = module.path
            version = module.version or ""
            original_name = name
            real_path = name
        elif replace.version:
            # module/name v1.0.0 => replace/name v1.2.3
            name = replace.path
            version = replace.version
            original_name = module.path
            real_path = name
        else:
            # module/name v1.0.0 => ./local/path
            name = module.path
            resolved_replacement_path = main_module_dir.join_within_root(module.replace.path)
            version = get_golang_version(module.path, resolved_replacement_path)
            real_path = _resolve_path_for_local_replacement(module)
            original_name = name

        return Module(name=name, version=version, original_name=original_name, real_path=real_path)

    def _resolve_path_for_local_replacement(module: ParsedModule) -> str:
        """Resolve all instances of "." and ".." for a local replacement."""
        if not module.replace:
            # Should not happen, this function will only be called for replaced modules
            raise RuntimeError("Can't resolve path for a module that was not replaced")

        path = f"{main_module.real_path}/{module.replace.path}"

        platform_specific_path = os.path.normpath(path)
        return Path(platform_specific_path).as_posix()

    return [_create_module(module) for module in parsed_modules]


def _create_packages_from_parsed_data(
    modules: list[Module], parsed_packages: Iterable[ParsedPackage]
) -> list[Union[Package, StandardPackage]]:
    # in case of replacements, the packages still refer to their parent module by its original name
    indexed_modules = {module.original_name: module for module in modules}

    def _create_package(package: ParsedPackage) -> Union[Package, StandardPackage]:
        if package.standard:
            return StandardPackage(name=package.import_path)

        if package.module is None:
            module = _find_parent_module_by_name(package)
        else:
            module = indexed_modules[package.module.path]

        relative_path = _resolve_package_relative_path(package, module)

        return Package(relative_path=str(relative_path), module=module)

    def _find_parent_module_by_name(package: ParsedPackage) -> Module:
        """Return the longest module name that is contained in package's import_path."""
        path = Path(package.import_path)

        matched_name = max(
            filter(path.is_relative_to, indexed_modules.keys()),
            key=len,  # type: ignore
            default=None,
        )

        if not matched_name:
            # This should be impossible
            raise RuntimeError("Package parent module was not found")

        return indexed_modules[matched_name]

    def _resolve_package_relative_path(package: ParsedPackage, module: Module) -> str:
        """Return the path for a package relative to its parent module original name."""
        relative_path = Path(package.import_path).relative_to(module.original_name)
        return str(relative_path).removeprefix(".")

    return [_create_package(package) for package in parsed_packages]


def fetch_gomod_source(request: Request) -> RequestOutput:
    """
    Resolve and fetch gomod dependencies for a given request.

    :param request: the request to process
    :raises PackageRejected: if a file is not present for the gomod package manager
    :raises UnsupportedFeature: if dependency replacements are provided for
        a non-single go module path
    :raises GoModError: if failed to fetch gomod dependencies
    """
    version_output = run_cmd(["go", "version"], {})
    log.info(f"Go version: {version_output.strip()}")

    config = get_config()
    subpaths = [str(package.path) for package in request.gomod_packages]

    if not subpaths:
        return RequestOutput.empty()

    invalid_gomod_files = _find_missing_gomod_files(request.source_dir, subpaths)

    if invalid_gomod_files:
        invalid_files_print = "; ".join(str(file.parent) for file in invalid_gomod_files)

        raise PackageRejected(
            f"The go.mod file must be present for the Go module(s) at: {invalid_files_print}",
            solution="Please double-check that you have specified correct paths to your Go modules",
            docs=GOMOD_INPUT_DOC,
        )

    if len(subpaths) > 1 and request.dep_replacements:
        raise UnsupportedFeature(
            "Dependency replacements are only supported for a single go module path.",
            solution="Dependency replacements are deprecated! Please don't use them.",
        )

    env_vars = {
        "GOCACHE": {"value": "deps/gomod", "kind": "path"},
        "GOPATH": {"value": "deps/gomod", "kind": "path"},
        "GOMODCACHE": {"value": "deps/gomod/pkg/mod", "kind": "path"},
    }
    env_vars.update(config.default_environment_variables.get("gomod", {}))

    components: list[Component] = []

    repo_name = _get_repository_name(request.source_dir)

    with GoCacheTemporaryDirectory(prefix="cachito-") as tmp_dir:
        request.gomod_download_dir.path.mkdir(exist_ok=True, parents=True)
        for i, subpath in enumerate(subpaths):
            log.info("Fetching the gomod dependencies at subpath %s", subpath)

            log.info(f'Fetching the gomod dependencies at the "{subpath}" directory')

            main_module_dir = request.source_dir.join_within_root(subpath)
            try:
                resolve_result = resolve_gomod(main_module_dir, request, Path(tmp_dir))
            except GoModError:
                log.error("Failed to fetch gomod dependencies")
                raise

            parsed_main_module, parsed_modules, parsed_packages = resolve_result

            main_module = _create_main_module_from_parsed_data(
                main_module_dir, repo_name, parsed_main_module
            )

            modules = [main_module]
            modules.extend(
                _create_modules_from_parsed_data(main_module, main_module_dir, parsed_modules)
            )

            packages = _create_packages_from_parsed_data(modules, parsed_packages)

            components.extend(module.to_component() for module in modules)
            components.extend(package.to_component() for package in packages)

        if "gomod-vendor-check" not in request.flags and "gomod-vendor" not in request.flags:
            tmp_download_cache_dir = Path(tmp_dir).joinpath(request.go_mod_cache_download_part)
            if tmp_download_cache_dir.exists():
                log.debug(
                    "Adding dependencies from %s to %s",
                    tmp_download_cache_dir,
                    request.gomod_download_dir,
                )
                shutil.copytree(
                    tmp_download_cache_dir,
                    str(request.gomod_download_dir),
                    dirs_exist_ok=True,
                )

    return RequestOutput.from_obj_list(
        components=components,
        environment_variables=[
            EnvironmentVariable(name=name, **obj) for name, obj in env_vars.items()
        ],
        project_files=[],
    )


def _create_main_module_from_parsed_data(
    main_module_dir: RootedPath, repo_name: str, parsed_main_module: ParsedModule
) -> Module:
    resolved_subpath = main_module_dir.subpath_from_root

    if str(resolved_subpath) == ".":
        resolved_path = repo_name
    else:
        resolved_path = f"{repo_name}/{resolved_subpath}"

    if not parsed_main_module.version:
        # Should not happen, since the version is always resolved from the Git repo
        raise RuntimeError(f"Version was not identified for main module at {resolved_subpath}")

    return Module(
        name=parsed_main_module.path,
        original_name=parsed_main_module.path,
        version=parsed_main_module.version,
        real_path=resolved_path,
    )


def _get_repository_name(source_dir: RootedPath) -> str:
    """Return the name resolved from the Git origin URL.

    The name is a treated form of the URL, after stripping the scheme, user and .git extension.
    """
    repo = git.Repo(source_dir)
    url = repo.remote().url

    # strip scheme and ssh user
    path = re.sub(r"^(https|ssh)?(:\/\/)?(git@)?", "", url)
    # strip trailing .git
    path = re.sub(r"\.git$", "", path)
    # change colon from ssh urls into slash
    return path.replace(":", "/")


def _find_missing_gomod_files(source_path: RootedPath, subpaths: list[str]) -> list[Path]:
    """
    Find all go modules with missing gomod files.

    These files will need to be present in order for the package manager to proceed with
    fetching the package sources.

    :param RequestBundleDir bundle_dir: the ``RequestBundleDir`` object for the request
    :param list subpaths: a list of subpaths in the source repository of gomod packages
    :return: a list containing all non-existing go.mod files across subpaths
    :rtype: list
    """
    invalid_gomod_files = []
    for subpath in subpaths:
        package_gomod_path = source_path.join_within_root(subpath, "go.mod").path
        log.debug("Testing for go mod file in {}".format(package_gomod_path))
        if not package_gomod_path.exists():
            invalid_gomod_files.append(package_gomod_path)

    return invalid_gomod_files


class GoCacheTemporaryDirectory(tempfile.TemporaryDirectory[str]):
    """
    A wrapper around the TemporaryDirectory context manager to also run `go clean -modcache`.

    The files in the Go cache are read-only by default and cause the default clean up behavior of
    tempfile.TemporaryDirectory to fail with a permission error. A way around this is to run
    `go clean -modcache` before the default clean up behavior is run.
    """

    def __exit__(self, exc, value, tb):
        """Clean up the temporary directory by first cleaning up the Go cache."""
        try:
            env = {"GOPATH": self.name, "GOCACHE": self.name}
            run_gomod_cmd(("go", "clean", "-modcache"), {"env": env})
        finally:
            super().__exit__(exc, value, tb)
