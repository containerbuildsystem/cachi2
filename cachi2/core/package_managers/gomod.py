import fnmatch
import functools
import logging
import os
import re
import shutil
import subprocess  # nosec
import tempfile
from datetime import datetime
from pathlib import Path, PureWindowsPath
from typing import Any, Dict, Iterable, List, Optional, Tuple

import backoff
import git
import semver

from cachi2.core.config import get_worker_config
from cachi2.core.errors import (
    FetchError,
    GoModError,
    PackageRejected,
    UnexpectedFormat,
    UnsupportedFeature,
)
from cachi2.core.models.input import Request
from cachi2.core.models.output import RequestOutput
from cachi2.core.utils import load_json_stream, run_cmd

log = logging.getLogger(__name__)


_MODULE_VERSION_RE = re.compile(r"/v\d+$")

GOMOD_DOC = "https://github.com/containerbuildsystem/cachi2/blob/main/docs/gomod.md"
GOMOD_INPUT_DOC = f"{GOMOD_DOC}#specifying-modules-to-process"
VENDORING_DOC = f"{GOMOD_DOC}#vendoring"


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

    config = get_worker_config()
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
    env_vars.update(config.cachito_default_environment_variables.get("gomod", {}))

    packages = []

    for i, subpath in enumerate(subpaths):
        log.info("Fetching the gomod dependencies at subpath %s", subpath)

        log.info(f'Fetching the gomod dependencies at the "{subpath}" directory')

        gomod_source_path = request.source_dir / subpath
        try:
            gomod = _resolve_gomod(gomod_source_path, request)
        except GoModError:
            log.error("Failed to fetch gomod dependencies")
            raise

        module_info = gomod["module"]

        packages.append({**module_info, "path": subpath, "dependencies": gomod["module_deps"]})

        # add package deps
        for package in gomod["packages"]:
            pkg_info = package["pkg"]
            package_subpath = _package_subpath(module_info["name"], pkg_info["name"], subpath)
            packages.append(
                {**pkg_info, "path": package_subpath, "dependencies": package.get("pkg_deps", [])}
            )

    return RequestOutput(
        packages=packages,
        environment_variables=[{"name": name, **obj} for name, obj in env_vars.items()],
        project_files=[],
    )


def _find_missing_gomod_files(source_path: Path, subpaths: list[str]) -> list[Path]:
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
        package_gomod_path = source_path / subpath / "go.mod"
        log.debug("Testing for go mod file in {}".format(package_gomod_path))
        if not package_gomod_path.exists():
            invalid_gomod_files.append(package_gomod_path)

    return invalid_gomod_files


def _resolve_gomod(path: Path, request: Request, git_dir_path=None):
    """
    Resolve and fetch gomod dependencies for given app source archive.

    :param str path: the full path to the application source code
    :param dict request: the Cachi2 request this is for
    :param list dep_replacements: dependency replacements with the keys "name" and "version"; this
        results in a series of `go mod edit -replace` commands
    :param RequestBundleDir git_dir_path: the full path to the application's git repository
    :return: a dict containing the Go module itself ("module" key), the list of dictionaries
        representing the dependencies ("module_deps" key), the top package level dependency
        ("pkg" key), and a list of dictionaries representing the package level dependencies
        ("pkg_deps" key)
    :rtype: dict
    :raises GoModError: if fetching dependencies fails
    """
    if git_dir_path is None:
        git_dir_path = request.source_dir

    worker_config = get_worker_config()

    with GoCacheTemporaryDirectory(prefix="cachito-") as temp_dir:
        env = {
            "GOPATH": temp_dir,
            "GO111MODULE": "on",
            "GOCACHE": temp_dir,
            "PATH": os.environ.get("PATH", ""),
            "GOMODCACHE": "{}/pkg/mod".format(temp_dir),
        }

        if worker_config.cachito_goproxy_url:
            env["GOPROXY"] = worker_config.cachito_goproxy_url

        if "cgo-disable" in request.flags:
            env["CGO_ENABLED"] = "0"

        run_params = {"env": env, "cwd": path}

        # Collect all the dependency names that are being replaced to later verify if they were
        # all used
        replaced_dep_names = set()
        for dep_replacement in request.dep_replacements:
            name = dep_replacement["name"]
            replaced_dep_names.add(name)
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
            flags, path, worker_config.cachito_gomod_strict_vendor
        )
        if should_vendor:
            _vendor_deps(run_params, can_make_changes, git_dir_path)
        else:
            log.info("Downloading the gomod dependencies")
            _run_download_cmd(("go", "mod", "download"), run_params)
        if "force-gomod-tidy" in flags or request.dep_replacements:
            _run_gomod_cmd(("go", "mod", "tidy"), run_params)

        # main module
        module_name = _run_gomod_cmd(["go", "list", "-m"], run_params).rstrip()

        # module level dependencies
        if should_vendor:
            module_lines = _module_lines_from_modules_txt(path)
        else:
            # .String formats the module as <name> <version> [=> <replace>],
            #   where <replace> is <name> <version> or <path>
            output_format = "{{ if not .Main }}{{ .String }}{{ end }}"
            go_list_output = _run_gomod_cmd(
                ("go", "list", "-mod", "readonly", "-m", "-f", output_format, "all"),
                run_params,
            )
            module_lines = go_list_output.splitlines()

        module_level_deps = []
        # Keep track of which dependency replacements were actually applied to verify they were all
        # used later
        used_replaced_dep_names = set()
        for line in module_lines:
            parts = line.split(" ")

            replaces = None
            if len(parts) == 4 and parts[2] == "=>":
                # If a Go module uses a "replace" directive to a local path, it will be shown as:
                # k8s.io/metrics v0.0.0 => ./staging/src/k8s.io/metrics
                # In this case, take the module name and the relative path, since that is the
                # actual dependency being used.
                parts = [parts[0], parts[-1]]
            elif len(parts) == 5 and parts[2] == "=>":
                # If a Go module uses a "replace" directive, then it will be in the format:
                # github.com/pkg/errors v0.8.0 => github.com/pkg/errors v0.8.1
                # In this case, just take the right side since that is the actual
                # dependency being used
                old_name, old_version = parts[:2]
                # Only keep track of user provided replaces. There could be existing "replace"
                # directives in the go.mod file, but they are an implementation detail specific to
                # Go and they don't need to be recorded in Cachi2.
                if old_name in replaced_dep_names:
                    used_replaced_dep_names.add(old_name)
                    replaces = {
                        "type": "gomod",
                        "name": old_name,
                        "version": old_version,
                    }
                parts = parts[3:]

            if len(parts) == 2:
                module_level_deps.append(
                    {
                        "name": parts[0],
                        "replaces": replaces,
                        "type": "gomod",
                        "version": parts[1],
                    }
                )
            else:
                log.warning("Unexpected go module output: %s", line)

        unused_dep_replacements = replaced_dep_names - used_replaced_dep_names
        if unused_dep_replacements:
            raise PackageRejected(
                reason=(
                    "The following gomod dependency replacements don't apply: "
                    f'{", ".join(unused_dep_replacements)}'
                ),
                solution="Dependency replacements are deprecated! Please don't use them.",
            )

        # In case a submodule is being processed, we need to determine its path
        subpath = None if path == git_dir_path else path.relative_to(f"{git_dir_path}/", "")

        # NOTE: If there are multiple go modules in a single git repo, they will
        #   all be versioned identically.
        module_version = _get_golang_version(
            module_name, git_dir_path, update_tags=True, subpath=subpath
        )
        module = {"name": module_name, "type": "gomod", "version": module_version}

        if should_vendor:
            # Create an empty gomod cache in the bundle directory so that any Cachi2
            # user does not have to guard against this directory not existing
            request.gomod_download_dir.mkdir(exist_ok=True, parents=True)
        else:
            # Add the gomod cache to the bundle the user will later download
            tmp_download_cache_dir = os.path.join(temp_dir, request.go_mod_cache_download_part)
            if not os.path.exists(tmp_download_cache_dir):
                os.makedirs(tmp_download_cache_dir, exist_ok=True)

            log.debug(
                "Adding dependencies from %s to %s",
                tmp_download_cache_dir,
                request.gomod_download_dir,
            )
            _merge_bundle_dirs(tmp_download_cache_dir, str(request.gomod_download_dir))

        if not should_vendor:
            # Make Go ignore the vendor dir even if there is one
            go_list = ["go", "list", "-mod", "readonly"]
        else:
            go_list = ["go", "list"]

        log.info("Retrieving the list of packages")
        package_list = _run_gomod_cmd([*go_list, "-find", "./..."], run_params).splitlines()

        log.info("Retrieving the list of package level dependencies")
        package_info = _load_list_deps(
            _run_gomod_cmd([*go_list, "-e", "-deps", "-json", "./..."], run_params)
        )

        packages: list[dict] = []
        processed_pkg_deps = set()
        for pkg_name in package_list:
            if pkg_name in processed_pkg_deps:
                # Go searches for packages in directories through a top-down approach. If a toplevel
                # package is already listed as a dependency, we do not list it here, since its
                # dependencies would also be listed in the parent package
                log.debug(
                    "Package %s is already listed as a package dependency. Skipping...",
                    pkg_name,
                )
                continue

            pkg_level_deps = []
            for dep_name in package_info[pkg_name].get("Deps", []):
                dep_info = package_info[dep_name]

                processed_pkg_deps.add(dep_name)
                if "Standard" in dep_info:
                    version = None
                else:
                    # If the dependency does not have a version, we'll use the module version
                    version = _get_dep_version(dep_info) or module_version

                pkg_level_deps.append({"name": dep_name, "type": "go-package", "version": version})

            # Top-level packages always use the module version
            pkg = {"name": pkg_name, "type": "go-package", "version": module_version}
            packages.append({"pkg": pkg, "pkg_deps": pkg_level_deps})

        allowlist = _get_allowed_local_deps(module_name)
        log.debug("Allowed local dependencies for %s: %s", module_name, allowlist)
        _vet_local_deps(module_level_deps, module_name, allowlist)
        for pkg in packages:
            # Local dependencies are always relative to the main module, even for subpackages
            _vet_local_deps(pkg["pkg_deps"], module_name, allowlist)
            _set_full_local_dep_relpaths(pkg["pkg_deps"], module_level_deps)

        # import time
        # time.sleep(1000)

        return {
            "module": module,
            "module_deps": module_level_deps,
            "packages": packages,
        }


class GoCacheTemporaryDirectory(tempfile.TemporaryDirectory):
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
    n_tries = get_worker_config().cachito_gomod_download_max_tries

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


def _should_vendor_deps(flags: Iterable[str], app_dir: Path, strict: bool) -> Tuple[bool, bool]:
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
    vendor = app_dir.joinpath("vendor")

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


def _get_golang_version(module_name, git_path, commit_sha=None, update_tags=False, subpath=None):
    """
    Get the version of the Go module in the input Git repository in the same format as `go list`.

    If commit doesn't point to a commit with a semantically versioned tag, a pseudo-version
    will be returned.

    :param str module_name: the Go module's name
    :param str git_path: the path to the Git repository
    :param str commit_sha: the Git commit SHA1 of the Go module to get the version for
    :param bool update_tags: determines if `git fetch --tags --force` should be run before
        determining the version. If this fails, it will be logged as a warning.
    :param str subpath: path to the module, relative to the root repository folder
    :return: a version as `go list` would provide
    :rtype: str
    :raises FetchError: if failed to fetch the tags on the Git repository
    """
    # If the module is version v2 or higher, the major version of the module is included as /vN at
    # the end of the module path. If the module is version v0 or v1, the major version is omitted
    # from the module path.
    module_major_version = None
    match = re.match(r"(?:.+/v)(?P<major_version>\d+)$", module_name)
    if match:
        module_major_version = int(match.groupdict()["major_version"])

    repo = git.Repo(git_path)
    if update_tags:
        try:
            repo.remote().fetch(force=True, tags=True)
        except Exception as ex:
            raise FetchError(
                "Failed to fetch the tags on the Git repository (%s) for %s",
                type(ex).__name__,
                module_name,
            )

    if module_major_version:
        major_versions_to_try = (module_major_version,)
    else:
        # Prefer v1.x.x tags but fallback to v0.x.x tags if both are present
        major_versions_to_try = (1, 0)

    if commit_sha is None:
        commit_sha = repo.rev_parse("HEAD").hexsha

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


def _get_highest_semver_tag(repo, target_commit, major_version, all_reachable=False, subpath=None):
    """
    Get the highest semantic version tag related to the input commit.

    :param Git.Repo repo: the Git repository object to search
    :param int major_version: the major version of the Go module as in the go.mod file to use as a
        filter for major version tags
    :param bool all_reachable: if False, the search is constrained to the input commit. If True,
        then the search is constrained to the input commit and preceding commits.
    :param str subpath: path to the module, relative to the root repository folder
    :return: the highest semantic version tag if one is found
    :rtype: git.Tag
    """
    try:
        g = git.Git(repo.working_dir)
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
        tag_names = g.execute(cmd).splitlines()
    except git.GitCommandError:
        msg = f"Failed to get the tags associated with the reference {target_commit.hexsha}"
        log.error(msg)
        raise

    # Keep only semantic version tags related to the path being processed
    prefix = f"{subpath}/v" if subpath else "v"
    filtered_tags = [tag_name for tag_name in tag_names if tag_name.startswith(prefix)]

    not_semver_tag_msg = "%s is not a semantic version tag"
    highest = None

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


def _get_golang_pseudo_version(commit, tag=None, module_major_version=None, subpath=None):
    """
    Get the Go module's pseudo-version when a non-version commit is used.

    For a description of the algorithm, see https://tip.golang.org/cmd/go/#hdr-Pseudo_versions.

    :param git.Commit commit: the commit object of the Go module
    :param git.Tag tag: the highest semantic version tag with a matching major version before the
        input commit. If this isn't specified, it is assumed there was no previous valid tag.
    :param int module_major_version: the Go module's major version as stated in its go.mod file. If
        this and "tag" are not provided, 0 is assumed.
    :param str subpath: path to the module, relative to the root repository folder
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


def _merge_bundle_dirs(root_src_dir: str, root_dst_dir: str):
    """
    Merge two bundle directories together.

    The contents of root_src_dir will be copied into root_dst_dir, overwriting any files
    that might already be present. For a description of the algorithm, see
    https://lukelogbook.tech/2018/01/25/merging-two-folders-in-python/

    In addition to that merge algorithm, however, we also need to make sure that we merge
    the list file to ensure all versions are represented. In order to protect against merging
    extra files, we are also checking for the presence of the list.lock file since it should
    be present according to https://github.com/golang/go/issues/29434

    :param str root_src_dir: the root path to the source directory
    :param str root_dst_dir: the root path to the destination directory
    :return: None
    """
    for src_dir, dirs, files in os.walk(root_src_dir):
        dst_dir = src_dir.replace(root_src_dir, root_dst_dir, 1)
        if not os.path.exists(dst_dir):
            os.makedirs(dst_dir)
        for file_ in files:
            src_file = os.path.join(src_dir, file_)
            dst_file = os.path.join(dst_dir, file_)
            if os.path.exists(dst_file):
                # check to see if we are trying to merge the `list` file
                # since we have to treat that seperately. We don't want to
                # delete it or overwrite it -- we need to merge it.
                if (
                    file_ == "list"
                    and os.path.isfile(src_file)
                    and os.path.exists("{}.lock".format(src_file))
                ):
                    _merge_files(src_file, dst_file)
                continue
            shutil.copy2(src_file, dst_dir)


def _merge_files(src_file, dst_file):
    """
    Merge two files so that we ensure that all packages are represented.

    The dst_file will be updated by inserting the lines from the src_file,
    sorting all lines, and removing duplicate lines.

    :param str src_file: the source file (to be merged)
    :param str dst_file: the destination file (to be merged into)
    :return: None
    """
    with open(src_file, "r") as file1:
        source_content = [line.rstrip() for line in file1.readlines()]
    with open(dst_file, "r") as file2:
        dest_content = [line.rstrip() for line in file2.readlines()]

    with open(dst_file, "w") as target:
        for line in sorted(set(source_content + dest_content)):
            if line == "":
                continue
            target.write(str(line) + "\n")


def _load_list_deps(list_deps_output: str) -> Dict[str, dict]:
    """Load go list -deps -json output, return relevant data as a dict of {name: data}."""
    package_info = {}

    for pkg in load_json_stream(list_deps_output):
        info = {}
        for k in ("Module", "Deps", "Standard"):
            v = pkg.get(k)
            if v is not None:
                info[k] = v

        package_info[pkg["ImportPath"]] = info

    return package_info


def _get_allowed_local_deps(module_name: str) -> List[str]:
    """
    Get allowed local dependencies for module.

    If module name contains a version and is not present in the allowlist, also try matching
    without the version. E.g. if example.org/module/v2 is not present in the allowlist, return
    allowed deps for example.org/module.
    """
    allowlist = get_worker_config().cachito_gomod_file_deps_allowlist
    allowed_deps = allowlist.get(module_name)
    if allowed_deps is None:
        versionless_module_name = _MODULE_VERSION_RE.sub("", module_name)
        allowed_deps = allowlist.get(versionless_module_name)
    return allowed_deps or []


def _vet_local_deps(dependencies: List[dict], module_name: str, allowed_patterns: List[str]):
    """
    Fail if any dependency is replaced by a local path unless the module is allowlisted.

    Also fail if the module is allowlisted but the path is absolute or outside repository.
    """
    for dep in dependencies:
        name = dep["name"]
        version = dep["version"]

        if not version:
            continue  # go stdlib

        if version.startswith("."):
            log.debug(
                "Module %s wants to replace %s with a local dependency: %s",
                module_name,
                name,
                version,
            )
            if ".." in Path(version).parts:
                raise UnsupportedFeature(f"Path to gomod dependency contains '..': {version}.")
            _fail_unless_allowed(module_name, name, allowed_patterns)
        elif version.startswith("/") or PureWindowsPath(version).root:
            # This will disallow paths starting with '/', '\' or '<drive letter>:\'
            raise UnsupportedFeature(
                f"Absolute paths to gomod dependencies are not supported: {version}"
            )


def _set_full_local_dep_relpaths(pkg_deps: List[dict], main_module_deps: List[dict]):
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


def _package_subpath(module_name: str, package_name: str, module_subpath: str) -> str:
    """Get path from repository root to a package inside a module."""
    subpath = _path_to_subpackage(module_name, package_name)
    return os.path.normpath(os.path.join(module_subpath, subpath))


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


def _get_dep_version(dep_info: dict) -> Optional[str]:
    """Get dependency version (if present) from the corresponding object in go list -deps -json."""
    module = dep_info.get("Module")
    if not module:
        return None

    replace = module.get("Replace")
    if replace:
        # Replacements must specify a version or a relative path
        #   (in which case we report the relative path)
        return replace.get("Version") or replace.get("Path")

    return module.get("Version")


def _get_semantic_version_from_tag(tag_name, subpath=None):
    """
    Parse a version tag to a semantic version.

    A Go version follows the format "v0.0.0", but it needs to have the "v" removed in
    order to be properly parsed by the semver library.

    In case `subpath` is defined, it will be removed from the tag_name, e.g. `subpath/v0.1.0`
    will be parsed as `0.1.0`.

    :param str tag_name: tag to be converted into a semver object
    :param str subpath: path to the module, relative to the root repository folder
    :rtype: semver.VersionInfo
    """
    if subpath:
        semantic_version = tag_name.replace(f"{subpath}/v", "")
    else:
        semantic_version = tag_name[1:]

    return semver.VersionInfo.parse(semantic_version)


def _module_lines_from_modules_txt(app_dir: Path) -> List[str]:
    """
    Read module lines from vendor/modules.txt.

    Exclude modules that do not have any packages, as those will not actually be downloaded by
    go mod vendor.

    Note that vendor/modules.txt is fully managed by go. After you call go mod vendor, this file
    is guaranteed to contain only the content written in it by go.
    """
    modules_txt = app_dir / "vendor" / "modules.txt"
    module_lines: List[str] = []
    has_packages = {}

    log.debug("Parsing modules from vendor/modules.txt")
    unexpected_format_solution = (
        "Does `go mod vendor` make any changes to modules.txt?\n"
        "If not, please let the maintainers know that Cachi2 fails to parse valid modules.txt"
    )

    for line in modules_txt.read_text().splitlines():
        # modules.txt contains lines in one of 4 formats:
        #   1) # <module_name> <version> [=> <replace>]
        #   2) ## <markers>
        #   3) <package_name>
        #   4) # <module_name> => <replace>

        # the lines always appear in the order of 1, 2, 3 (2 and 3 are optional)
        # 4 can only appear at the end of the file and is never followed by package lines (3)
        # see https://github.com/golang/go/blob/master/src/cmd/go/internal/modcmd/vendor.go

        if not line.startswith("#"):  # this is a package line
            if not module_lines:
                raise UnexpectedFormat(
                    f"vendor/modules.txt: package has no parent module: {line}",
                    solution=unexpected_format_solution,
                )
            has_packages[module_lines[-1]] = True
        elif line.startswith("# "):  # this is a module line or a wildcard replacement (4)
            module_lines.append(line[2:])
        elif not line.startswith("##"):
            # at this point, the line must be a marker, otherwise we don't know what it is
            raise UnexpectedFormat(
                f"vendor/modules.txt: unexpected format: {line!r}",
                solution=unexpected_format_solution,
            )

    return list(filter(has_packages.get, module_lines))


def _vendor_deps(run_params: dict, can_make_changes: bool, git_dir: str):
    """
    Vendor golang dependencies.

    If Cachi2 is not allowed to make changes, it will verify that the vendor directory already
    contained the correct content.

    :param run_params: common params for the subprocess calls to `go`
    :param can_make_changes: is Cachi2 allowed to make changes?
    :param git_dir: path to the repository root
    :raise PackageRejected: if vendor directory changed and Cachi2 is not allowed to make changes
    """
    log.info("Vendoring the gomod dependencies")
    _run_download_cmd(("go", "mod", "vendor"), run_params)
    app_dir = run_params["cwd"]
    if not can_make_changes and _vendor_changed(git_dir, app_dir):
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


def _fail_unless_allowed(module_name: str, package_name: str, allowed_patterns: List[str]):
    """
    Fail unless the module is allowed to replace the package with a local dependency.

    When packages are allowed to be replaced:
    * package_name is a submodule of module_name
    * package_name replacement is allowed according to allowed_patterns
    """
    versionless_module_name = _MODULE_VERSION_RE.sub("", module_name)
    is_submodule = _contains_package(versionless_module_name, package_name)
    if not is_submodule and not any(fnmatch.fnmatch(package_name, pat) for pat in allowed_patterns):
        raise UnsupportedFeature(
            reason=(
                f"The module {module_name} is not allowed to replace {package_name} with a local "
                "dependency."
            ),
            solution=(
                "Please allow the replacement in Cachi2's configuration.\n"
                "If you're using Cachi2 in a managed environment, please contact the "
                "administrators."
            ),
        )


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


def _vendor_changed(git_dir: str, app_dir: str) -> bool:
    """Check for changes in the vendor directory."""
    vendor = Path(app_dir).relative_to(git_dir).joinpath("vendor")
    modules_txt = vendor / "modules.txt"

    repo = git.Repo(git_dir)
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
