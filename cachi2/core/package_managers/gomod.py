import functools
import logging
import os
import re
import shutil
import subprocess  # nosec
import tempfile
from datetime import datetime
from itertools import chain
from pathlib import Path, PureWindowsPath
from typing import Any, Dict, Iterable, Iterator, List, Literal, NoReturn, Optional, Tuple, Union

import backoff
import git
import git.objects
import pydantic
import semver

from cachi2.core.config import get_config
from cachi2.core.errors import (
    FetchError,
    GoModError,
    PackageRejected,
    UnexpectedFormat,
    UnsupportedFeature,
)
from cachi2.core.models.input import Request
from cachi2.core.models.output import Component, EnvironmentVariable, RequestOutput
from cachi2.core.rooted_path import PathOutsideRoot, RootedPath
from cachi2.core.utils import load_json_stream, run_cmd

log = logging.getLogger(__name__)


GOMOD_DOC = "https://github.com/containerbuildsystem/cachi2/blob/main/docs/gomod.md"
GOMOD_INPUT_DOC = f"{GOMOD_DOC}#specifying-modules-to-process"
VENDORING_DOC = f"{GOMOD_DOC}#vendoring"


class _GolangModel(pydantic.BaseModel):
    """Attributes automatically get PascalCase aliases to make parsing Golang JSON easier.

    >>> class SomeModel(_GolangModel):
            some_attribute: str

    >>> SomeModel.parse_obj({"SomeAttribute": "hello"})
    SomeModel(some_attribute="hello")
    """

    class Config:
        @staticmethod
        def alias_generator(attr_name: str) -> str:
            return "".join(word.capitalize() for word in attr_name.split("_"))

        # allow SomeModel(some_attribute="hello"), not just SomeModel(SomeAttribute="hello")
        allow_population_by_field_name = True


class GoModule(_GolangModel):
    """A Go module as returned by the -json option of various commands (relevant fields only).

    See:
        go help mod download    (Module struct)
        go help list            (Module struct)
    """

    path: str
    version: Optional[str] = None
    main: bool = False
    replace: Optional["GoModule"] = None


class GoPackage(_GolangModel):
    """A Go package as returned by the -json option of go list (relevant fields only).

    See:
        go help list    (Package struct)
    """

    import_path: str
    standard: bool = False
    module: Optional[GoModule]


def _run_gomod_cmd(cmd: Iterable[str], params: dict[str, Any]) -> str:
    try:
        return run_cmd(cmd, params)
    except subprocess.CalledProcessError as e:
        rc = e.returncode
        raise GoModError(
            f"Processing gomod dependencies failed: `{' '.join(cmd)}` failed with {rc=}"
        ) from e


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

    with GoCacheTemporaryDirectory(prefix="cachito-") as tmp_dir:
        request.gomod_download_dir.path.mkdir(exist_ok=True, parents=True)
        for i, subpath in enumerate(subpaths):
            log.info("Fetching the gomod dependencies at subpath %s", subpath)

            log.info(f'Fetching the gomod dependencies at the "{subpath}" directory')

            gomod_source_path = request.source_dir.join_within_root(subpath)
            try:
                resolve_result = _resolve_gomod(gomod_source_path, request, Path(tmp_dir))
            except GoModError:
                log.error("Failed to fetch gomod dependencies")
                raise

            main_module, modules, packages = resolve_result

            components.append(Component(name=main_module.path, version=main_module.version))

            modules_names_and_versions = (_get_name_and_version(module) for module in modules)

            components.extend(
                Component(name=name_version[0], version=name_version[1])
                for name_version in modules_names_and_versions
            )

            for package in packages:
                if package.standard:
                    version = None
                elif package.module:
                    version = package.module.version
                else:
                    raise RuntimeError("Non-stdlib package does not have a parent module")

                components.append(Component(name=package.import_path, version=version))

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


def _protect_against_symlinks(app_dir: RootedPath) -> None:
    """Try to prevent go subcommands from following suspicious symlinks.

    The go command doesn't particularly care if the files it reads are subpaths of the directory
    where it is executed. Check some of the common paths that the subcommands may read.

    :raises PathOutsideRoot: if go.mod, go.sum, vendor/modules.txt or any **/*.go file is a symlink
        that leads outside the source directory
    """

    def check_potential_symlink(relative_path: Union[str, Path]) -> None:
        try:
            app_dir.join_within_root(relative_path)
        except PathOutsideRoot as e:
            e.solution = (
                "Found a potentially harmful symlink, which would make the go command read "
                "a file outside of your source repository. Refusing to proceed."
            )
            raise

    check_potential_symlink("go.mod")
    check_potential_symlink("go.sum")
    check_potential_symlink("vendor/modules.txt")
    for go_file in app_dir.path.rglob("*.go"):
        check_potential_symlink(go_file.relative_to(app_dir))


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


def _resolve_gomod(
    app_dir: RootedPath, request: Request, tmp_dir: Path
) -> tuple[GoModule, Iterable[GoModule], Iterable[GoPackage]]:
    """
    Resolve and fetch gomod dependencies for given app source archive.

    :param app_dir: the full path to the application source code
    :param request: the Cachi2 request this is for
    :param tmp_dir: one temporary directory for all go modules
    :return: a dict containing the Go module itself ("module" key), the list of dictionaries
        representing the dependencies ("module_deps" key), the top package level dependency
        ("pkg" key), and a list of dictionaries representing the package level dependencies
        ("pkg_deps" key)
    :raises GoModError: if fetching dependencies fails
    """
    _protect_against_symlinks(app_dir)

    config = get_config()

    env = {
        "GOPATH": tmp_dir,
        "GO111MODULE": "on",
        "GOCACHE": tmp_dir,
        "PATH": os.environ.get("PATH", ""),
        "GOMODCACHE": "{}/pkg/mod".format(tmp_dir),
    }

    if config.goproxy_url:
        env["GOPROXY"] = config.goproxy_url

    if "cgo-disable" in request.flags:
        env["CGO_ENABLED"] = "0"

    run_params = {"env": env, "cwd": app_dir}

    for dep_replacement in request.dep_replacements:
        name = dep_replacement["name"]
        new_name = dep_replacement.get("new_name", name)
        version = dep_replacement["version"]
        log.info("Applying the gomod replacement %s => %s@%s", name, new_name, version)
        _run_gomod_cmd(
            ("go", "mod", "edit", "-replace", f"{name}={new_name}@{version}"),
            run_params,
        )

    # Vendor dependencies if the gomod-vendor flag is set
    flags = request.flags
    should_vendor, can_make_changes = _should_vendor_deps(
        flags, app_dir, config.gomod_strict_vendor
    )
    if should_vendor:
        downloaded_modules = _vendor_deps(app_dir, can_make_changes, run_params)
    else:
        log.info("Downloading the gomod dependencies")
        download_cmd = ["go", "mod", "download", "-json"]
        downloaded_modules = (
            GoModule.parse_obj(obj)
            for obj in load_json_stream(_run_download_cmd(download_cmd, run_params))
        )

    if "force-gomod-tidy" in flags or request.dep_replacements:
        _run_gomod_cmd(("go", "mod", "tidy"), run_params)

    go_list = ["go", "list", "-e"]
    if not should_vendor:
        # Make Go ignore the vendor dir even if there is one
        go_list.extend(["-mod", "readonly"])

    main_module_name = _run_gomod_cmd([*go_list, "-m"], run_params).rstrip()
    main_module_version = _get_golang_version(main_module_name, app_dir, update_tags=True)
    main_module = GoModule(path=main_module_name, version=main_module_version, main=True)

    def go_list_deps(pattern: Literal["./...", "all"]) -> Iterator[GoPackage]:
        """Run go list -deps -json and return the parsed list of packages.

        The "./..." pattern returns the list of packages compiled into the final binary.

        The "all" pattern includes dependencies needed only for tests. Use it to get a more
        complete module list (roughly matching the list of downloaded modules).
        """
        cmd = [*go_list, "-deps", "-json=ImportPath,Module,Standard,Deps", pattern]
        return map(GoPackage.parse_obj, load_json_stream(_run_gomod_cmd(cmd, run_params)))

    package_modules = (
        module for pkg in go_list_deps("all") if (module := pkg.module) and not module.main
    )

    all_modules = _deduplicate_resolved_modules(package_modules, downloaded_modules)

    log.info("Retrieving the list of packages")
    all_packages = list(go_list_deps("./..."))

    _validate_local_replacements(all_modules, app_dir)

    return main_module, all_modules, all_packages


def _deduplicate_resolved_modules(
    package_modules: Iterable[GoModule],
    downloaded_modules: Iterable[GoModule],
) -> Iterable[GoModule]:
    def get_unique_key(module: GoModule) -> tuple[str, Optional[str]]:
        if not (replace := module.replace):
            return module.path, module.version
        elif replace.version:
            # module/name v1.0.0 => replace/name v1.2.3
            return replace.path, replace.version
        else:
            # module/name v1.0.0 => ./local/path
            return module.path, replace.path

    modules_by_name_and_version: dict[tuple[str, Optional[str]], GoModule] = {}

    # package_modules have the replace data, so they should take precedence in the deduplication
    for module in chain(package_modules, downloaded_modules):
        # get the module for this name+version or create a new one
        modules_by_name_and_version.setdefault(get_unique_key(module), module)

    return modules_by_name_and_version.values()


def _get_name_and_version(module: GoModule) -> tuple[str, str]:
    if not (replace := module.replace):
        name = module.path
        version = module.version
    elif replace.version:
        # module/name v1.0.0 => replace/name v1.2.3
        name = replace.path
        version = replace.version
    else:
        # module/name v1.0.0 => ./local/path
        name = module.path
        version = replace.path
    if not version:
        # should be impossible for modules other than the main module
        # (don't call this function on the main module)
        raise RuntimeError(f"versionless module: {module}")
    return name, version


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
            _run_gomod_cmd(("go", "clean", "-modcache"), {"env": env})
        finally:
            super().__exit__(exc, value, tb)


def _run_download_cmd(cmd: Iterable[str], params: Dict[str, Any]) -> str:
    """Run gomod command that downloads dependencies.

    Such commands may fail due to network errors (go is bad at retrying), so the entire operation
    will be retried a configurable number of times.

    Cachi2 will reuse the same cache directory between retries, so Go will not have to download
    the same dependency twice. The backoff is exponential, Cachi2 will wait 1s -> 2s -> 4s -> ...
    before retrying.
    """
    n_tries = get_config().gomod_download_max_tries

    @backoff.on_exception(
        backoff.expo,
        GoModError,
        jitter=None,  # use deterministic backoff, do not apply jitter
        max_tries=n_tries,
        logger=log,
    )
    def run_go(_cmd: Iterable[str], _params: Dict[str, Any]) -> str:
        log.debug(f"Running {_cmd}")
        return _run_gomod_cmd(_cmd, _params)

    try:
        return run_go(cmd, params)
    except GoModError:
        err_msg = (
            f"Processing gomod dependencies failed. Cachi2 tried the {' '.join(cmd)} command "
            f"{n_tries} times."
        )
        raise GoModError(err_msg) from None


def _should_vendor_deps(
    flags: Iterable[str], app_dir: RootedPath, strict: bool
) -> Tuple[bool, bool]:
    """
    Determine if Cachi2 should vendor dependencies and if it is allowed to make changes.

    This is based on the presence of flags:
    - gomod-vendor-check => should vendor, can only make changes if vendor dir does not exist
    - gomod-vendor => should vendor, can make changes

    :param flags: flags from the Cachi2 request
    :param app_dir: absolute path to the app directory
    :param strict: fail the request if the vendor dir is present but the flags are not used?
    :return: (should vendor: bool, allowed to make changes in the vendor directory: bool)
    :raise PackageRejected: if the vendor dir is present, the flags are not used and we are strict
    """
    vendor = app_dir.join_within_root("vendor").path

    if "gomod-vendor-check" in flags:
        return True, not vendor.exists()
    if "gomod-vendor" in flags:
        return True, True

    if strict and vendor.is_dir():
        raise PackageRejected(
            reason=(
                'The "gomod-vendor" or "gomod-vendor-check" flag must be set when your repository '
                "has vendored dependencies."
            ),
            solution=(
                "Consider removing the vendor/ directory and letting Cachi2 download dependencies "
                "instead.\n"
                "If you do want to keep using vendoring, please pass one of the required flags."
            ),
            docs=VENDORING_DOC,
        )

    return False, False


def _get_golang_version(
    module_name: str,
    app_dir: RootedPath,
    commit_sha: Optional[str] = None,
    update_tags: bool = False,
) -> str:
    """
    Get the version of the Go module in the input Git repository in the same format as `go list`.

    If commit doesn't point to a commit with a semantically versioned tag, a pseudo-version
    will be returned.

    :param module_name: the Go module's name
    :param app_dir: the path to the module directory
    :param commit_sha: the Git commit SHA1 of the Go module to get the version for
    :param update_tags: determines if `git fetch --tags --force` should be run before
        determining the version. If this fails, it will be logged as a warning.
    :return: a version as `go list` would provide
    :raises FetchError: if failed to fetch the tags on the Git repository
    """
    # If the module is version v2 or higher, the major version of the module is included as /vN at
    # the end of the module path. If the module is version v0 or v1, the major version is omitted
    # from the module path.
    module_major_version = None
    match = re.match(r"(?:.+/v)(?P<major_version>\d+)$", module_name)
    if match:
        module_major_version = int(match.groupdict()["major_version"])

    repo = git.Repo(app_dir.root)
    if update_tags:
        try:
            repo.remote().fetch(force=True, tags=True)
        except Exception as ex:
            raise FetchError(
                f"Failed to fetch the tags on the Git repository ({type(ex).__name__}) "
                f"for {module_name}"
            )

    if module_major_version:
        major_versions_to_try: tuple[int, ...] = (module_major_version,)
    else:
        # Prefer v1.x.x tags but fallback to v0.x.x tags if both are present
        major_versions_to_try = (1, 0)

    if commit_sha is None:
        commit_sha = repo.rev_parse("HEAD").hexsha

    if app_dir.path == app_dir.root:
        subpath = None
    else:
        subpath = app_dir.path.relative_to(app_dir.root).as_posix()

    commit = repo.commit(commit_sha)
    for major_version in major_versions_to_try:
        # Get the highest semantic version tag on the commit with a matching major version
        tag_on_commit = _get_highest_semver_tag(repo, commit, major_version, subpath=subpath)
        if not tag_on_commit:
            continue

        log.debug(
            "Using the semantic version tag of %s for commit %s",
            tag_on_commit.name,
            commit_sha,
        )

        # We want to preserve the version in the "v0.0.0" format, so the subpath is not needed
        return tag_on_commit.name if not subpath else tag_on_commit.name.replace(f"{subpath}/", "")

    log.debug("No semantic version tag was found on the commit %s", commit_sha)

    # This logic is based on:
    # https://github.com/golang/go/blob/a23f9afd9899160b525dbc10d01045d9a3f072a0/src/cmd/go/internal/modfetch/coderepo.go#L511-L521
    for major_version in major_versions_to_try:
        # Get the highest semantic version tag before the commit with a matching major version
        pseudo_base_tag = _get_highest_semver_tag(
            repo, commit, major_version, all_reachable=True, subpath=subpath
        )
        if not pseudo_base_tag:
            continue

        log.debug(
            "Using the semantic version tag of %s as the pseudo-base for the commit %s",
            pseudo_base_tag.name,
            commit_sha,
        )
        pseudo_version = _get_golang_pseudo_version(
            commit, pseudo_base_tag, major_version, subpath=subpath
        )
        log.debug("Using the pseudo-version %s for the commit %s", pseudo_version, commit_sha)
        return pseudo_version

    log.debug("No valid semantic version tag was found")
    # Fall-back to a vX.0.0-yyyymmddhhmmss-abcdefabcdef pseudo-version
    return _get_golang_pseudo_version(
        commit, module_major_version=module_major_version, subpath=subpath
    )


def _get_highest_semver_tag(
    repo: git.Repo,
    target_commit: git.objects.Commit,
    major_version: int,
    all_reachable: bool = False,
    subpath: Optional[str] = None,
) -> Optional[git.Tag]:
    """
    Get the highest semantic version tag related to the input commit.

    :param repo: the Git repository object to search
    :param major_version: the major version of the Go module as in the go.mod file to use as a
        filter for major version tags
    :param all_reachable: if False, the search is constrained to the input commit. If True,
        then the search is constrained to the input commit and preceding commits.
    :param subpath: path to the module, relative to the root repository folder
    :return: the highest semantic version tag if one is found
    """
    try:
        if all_reachable:
            # Get all the tags on the input commit and all that precede it.
            # This is based on:
            # https://github.com/golang/go/blob/0ac8739ad5394c3fe0420cf53232954fefb2418f/src/cmd/go/internal/modfetch/codehost/git.go#L659-L695
            cmd = [
                "git",
                "for-each-ref",
                "--format",
                "%(refname:lstrip=2)",
                "refs/tags",
                "--merged",
                target_commit.hexsha,
            ]
        else:
            # Get the tags that point to this commit
            cmd = ["git", "tag", "--points-at", target_commit.hexsha]

        tag_names = repo.git.execute(
            cmd,
            # these args are the defaults, but are required to let mypy know which override to match
            # (the one that returns a string)
            with_extended_output=False,
            as_process=False,
            stdout_as_string=True,
        ).splitlines()
    except git.GitCommandError:
        msg = f"Failed to get the tags associated with the reference {target_commit.hexsha}"
        log.error(msg)
        raise

    # Keep only semantic version tags related to the path being processed
    prefix = f"{subpath}/v" if subpath else "v"
    filtered_tags = [tag_name for tag_name in tag_names if tag_name.startswith(prefix)]

    not_semver_tag_msg = "%s is not a semantic version tag"
    highest: Optional[dict[str, Any]] = None

    for tag_name in filtered_tags:
        try:
            semantic_version = _get_semantic_version_from_tag(tag_name, subpath)
        except ValueError:
            log.debug(not_semver_tag_msg, tag_name)
            continue

        # If the major version of the semantic version tag doesn't match the Go module's major
        # version, then ignore it
        if semantic_version.major != major_version:
            continue

        if highest is None or semantic_version > highest["semver"]:
            highest = {"tag": tag_name, "semver": semantic_version}

    if highest:
        return repo.tags[highest["tag"]]

    return None


def _get_golang_pseudo_version(
    commit: git.objects.Commit,
    tag: Optional[git.Tag] = None,
    module_major_version: Optional[int] = None,
    subpath: Optional[str] = None,
) -> str:
    """
    Get the Go module's pseudo-version when a non-version commit is used.

    For a description of the algorithm, see https://tip.golang.org/cmd/go/#hdr-Pseudo_versions.

    :param commit: the commit object of the Go module
    :param tag: the highest semantic version tag with a matching major version before the
        input commit. If this isn't specified, it is assumed there was no previous valid tag.
    :param module_major_version: the Go module's major version as stated in its go.mod file. If
        this and "tag" are not provided, 0 is assumed.
    :param subpath: path to the module, relative to the root repository folder
    :return: the Go module's pseudo-version as returned by `go list`
    :rtype: str
    """
    # Use this instead of commit.committed_datetime so that the datetime object is UTC
    committed_dt = datetime.utcfromtimestamp(commit.committed_date)
    commit_timestamp = committed_dt.strftime(r"%Y%m%d%H%M%S")
    commit_hash = commit.hexsha[0:12]

    # vX.0.0-yyyymmddhhmmss-abcdefabcdef is used when there is no earlier versioned commit with an
    # appropriate major version before the target commit
    if tag is None:
        # If the major version isn't in the import path and there is not a versioned commit with the
        # version of 1, the major version defaults to 0.
        return f'v{module_major_version or "0"}.0.0-{commit_timestamp}-{commit_hash}'

    tag_semantic_version = _get_semantic_version_from_tag(tag.name, subpath)

    # An example of a semantic version with a prerelease is v2.2.0-alpha
    if tag_semantic_version.prerelease:
        # vX.Y.Z-pre.0.yyyymmddhhmmss-abcdefabcdef is used when the most recent versioned commit
        # before the target commit is vX.Y.Z-pre
        version_seperator = "."
        pseudo_semantic_version = tag_semantic_version
    else:
        # vX.Y.(Z+1)-0.yyyymmddhhmmss-abcdefabcdef is used when the most recent versioned commit
        # before the target commit is vX.Y.Z
        version_seperator = "-"
        pseudo_semantic_version = tag_semantic_version.bump_patch()

    return f"v{pseudo_semantic_version}{version_seperator}0.{commit_timestamp}-{commit_hash}"


def _vet_local_deps(dependencies: List[dict]) -> None:
    """Fail if any local dependency path is absolute or outside repository."""
    for dep in dependencies:
        version = dep["version"]

        if not version:
            continue  # go stdlib
        if version.startswith(".") and ".." in Path(version).parts:
            raise UnsupportedFeature(f"Path to gomod dependency contains '..': {version}.")
        elif version.startswith("/") or PureWindowsPath(version).root:
            # This will disallow paths starting with '/', '\' or '<drive letter>:\'
            raise UnsupportedFeature(
                f"Absolute paths to gomod dependencies are not supported: {version}"
            )


def _validate_local_replacements(modules: Iterable[GoModule], app_path: RootedPath) -> None:
    replaced_paths = [
        (module.path, module.replace.path)
        for module in modules
        if module.replace and module.replace.path.startswith(".")
    ]

    for name, path in replaced_paths:
        try:
            app_path.join_within_root(path)
        except PathOutsideRoot as e:
            e.solution = (
                f"The module '{name}' is being replaced by the local path '{path}', "
                "which falls outside of the repository root. Refusing to proceed."
            )
            raise


def _set_full_local_dep_relpaths(pkg_deps: List[dict], main_module_deps: List[dict]) -> None:
    """
    Set full relative paths for all local go-package dependencies.

    The path that you see in the go list -deps output points only to the module that contains
    the package. To get the full path to the package, take the relative path from the module
    to the package (based on the package name relative to the module name) and join it with the
    module path.
    """
    locally_replaced_mod_names = [
        module["name"] for module in main_module_deps if module["version"].startswith(".")
    ]

    for dep in pkg_deps:
        dep_name = dep["name"]
        dep_path = dep["version"]

        if not dep_path or not dep_path.startswith("."):
            continue

        # The gomod module that contains this go-package dependency
        dep_module_name = _match_parent_module(dep_name, locally_replaced_mod_names)
        if dep_module_name is None:
            # This should be impossible
            raise RuntimeError(f"Could not find parent Go module for local dependency: {dep_name}")

        path_from_module_to_pkg = _path_to_subpackage(dep_module_name, dep_name)
        if path_from_module_to_pkg:
            dep["version"] = os.path.join(dep_path, path_from_module_to_pkg)


def _path_to_subpackage(parent_name: str, subpackage_name: str) -> str:
    """
    Get relative path from parent module/package to subpackage inside the parent.

    If the subpackage and parent names are identical, returns empty string.
    The subpackage name must start with the parent name.

    :param parent_name: name of parent module or package
    :param subpackage_name: name of subpackage inside the parent module/package
    :return: relative path from parent to subpackage
    :raises ValueError: if subpackage name does not start with parent name
    """
    if not _contains_package(parent_name, subpackage_name):
        raise ValueError(f"Package {subpackage_name} does not belong to {parent_name}")
    return subpackage_name[len(parent_name) :].lstrip("/")


def _contains_package(parent_name: str, package_name: str) -> bool:
    """
    Check that parent module/package contains specified package.

    :param parent_name: name of parent module or package
    :param package_name: name of package to check
    :return: True if package belongs to parent, False otherwise
    """
    if not package_name.startswith(parent_name):
        return False
    if len(package_name) > len(parent_name):
        # Check that the subpackage is {parent_name}/* and not {parent_name}*/*
        return package_name[len(parent_name)] == "/"
    # At this point package_name == parent_name, every package contains itself
    return True


def _get_semantic_version_from_tag(
    tag_name: str, subpath: Optional[str] = None
) -> semver.version.Version:
    """
    Parse a version tag to a semantic version.

    A Go version follows the format "v0.0.0", but it needs to have the "v" removed in
    order to be properly parsed by the semver library.

    In case `subpath` is defined, it will be removed from the tag_name, e.g. `subpath/v0.1.0`
    will be parsed as `0.1.0`.

    :param tag_name: tag to be converted into a semver object
    :param subpath: path to the module, relative to the root repository folder
    """
    if subpath:
        semantic_version = tag_name.replace(f"{subpath}/v", "")
    else:
        semantic_version = tag_name[1:]

    return semver.version.Version.parse(semantic_version)


def _parse_vendor(module_dir: RootedPath) -> Iterable[GoModule]:
    """Parse modules from vendor/modules.txt."""
    modules_txt = module_dir.join_within_root("vendor", "modules.txt")
    if not modules_txt.path.exists():
        return []

    def fail_for_unexpected_format(msg: str) -> NoReturn:
        solution = (
            "Does `go mod vendor` make any changes to modules.txt?\n"
            "If not, please let the maintainers know that Cachi2 fails to parse valid modules.txt"
        )
        raise UnexpectedFormat(f"vendor/modules.txt: {msg}", solution=solution)

    def parse_module_line(line: str) -> GoModule:
        parts = line.removeprefix("# ").split()
        # name version
        if len(parts) == 2:
            name, version = parts
            return GoModule(path=name, version=version)
        # name => path
        if len(parts) == 3 and parts[1] == "=>":
            name, _, path = parts
            return GoModule(path=name, replace=GoModule(path=path))
        # name => new_name new_version
        if len(parts) == 4 and parts[1] == "=>":
            name, _, new_name, new_version = parts
            return GoModule(path=name, replace=GoModule(path=new_name, version=new_version))
        # name version => path
        if len(parts) == 4 and parts[2] == "=>":
            name, version, _, path = parts
            return GoModule(path=name, version=version, replace=GoModule(path=path))
        # name version => new_name new_version
        if len(parts) == 5 and parts[2] == "=>":
            name, version, _, new_name, new_version = parts
            return GoModule(
                path=name,
                version=version,
                replace=GoModule(path=new_name, version=new_version),
            )
        fail_for_unexpected_format(f"unexpected module line format: {line!r}")

    modules: list[GoModule] = []
    module_has_packages: list[bool] = []

    for line in modules_txt.path.read_text().splitlines():
        if line.startswith("# "):  # module line
            modules.append(parse_module_line(line))
            module_has_packages.append(False)
        elif not line.startswith("#"):  # package line
            if not modules:
                fail_for_unexpected_format(f"package has no parent module: {line}")
            module_has_packages[-1] = True
        elif not line.startswith("##"):  # marker line
            fail_for_unexpected_format(f"unexpected format: {line!r}")

    return (module for module, has_packages in zip(modules, module_has_packages) if has_packages)


def _vendor_deps(
    app_dir: RootedPath, can_make_changes: bool, run_params: dict[str, Any]
) -> Iterable[GoModule]:
    """
    Vendor golang dependencies.

    If Cachi2 is not allowed to make changes, it will verify that the vendor directory already
    contained the correct content.

    :param app_dir: path to the module directory
    :param can_make_changes: is Cachi2 allowed to make changes?
    :param run_params: common params for the subprocess calls to `go`
    :return: the list of Go modules parsed from vendor/modules.txt
    :raise PackageRejected: if vendor directory changed and Cachi2 is not allowed to make changes
    :raise UnexpectedFormat: if Cachi2 fails to parse vendor/modules.txt
    """
    log.info("Vendoring the gomod dependencies")
    _run_download_cmd(("go", "mod", "vendor"), run_params)
    if not can_make_changes and _vendor_changed(app_dir):
        raise PackageRejected(
            reason=(
                "The content of the vendor directory is not consistent with go.mod. "
                "Please check the logs for more details."
            ),
            solution=(
                "Please try running `go mod vendor` and committing the changes.\n"
                "Note that you may need to `git add --force` ignored files in the vendor/ dir.\n"
                "Also consider whether you really want the -check variant of the flag."
            ),
            docs=VENDORING_DOC,
        )
    return _parse_vendor(app_dir)


def _match_parent_module(package_name: str, module_names: Iterable[str]) -> Optional[str]:
    """
    Find parent module for package in iterable of module names.

    Picks the longest module name that matches the package name
    (the package name must start with the module name).

    :param package_name: name of package
    :param module_names: iterable of module names
    :return: longest matching module name or None (no module matches)
    """
    contains_this_package = functools.partial(_contains_package, package_name=package_name)
    return max(
        filter(contains_this_package, module_names),
        key=len,  # type: ignore
        default=None,
    )


def _vendor_changed(app_dir: RootedPath) -> bool:
    """Check for changes in the vendor directory."""
    repo_root = app_dir.root
    vendor = app_dir.path.relative_to(repo_root).joinpath("vendor")
    modules_txt = vendor / "modules.txt"

    repo = git.Repo(repo_root)
    # Add untracked files but do not stage them
    repo.git.add("--intent-to-add", "--force", "--", app_dir)

    try:
        # Diffing modules.txt should catch most issues and produce relatively useful output
        modules_txt_diff = repo.git.diff("--", str(modules_txt))
        if modules_txt_diff:
            log.error("%s changed after vendoring:\n%s", modules_txt, modules_txt_diff)
            return True

        # Show only if files were added/deleted/modified, not the full diff
        vendor_diff = repo.git.diff("--name-status", "--", str(vendor))
        if vendor_diff:
            log.error("%s directory changed after vendoring:\n%s", vendor, vendor_diff)
            return True
    finally:
        repo.git.reset("--", app_dir)

    return False
