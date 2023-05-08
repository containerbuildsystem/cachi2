import logging
import re

from datetime import datetime
from typing import (
    Any,
    Optional,
)

import git
import semver

from cachi2.core.errors import (
    FetchError,
)
from cachi2.core.rooted_path import RootedPath

log = logging.getLogger(__name__)


def get_golang_version(
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
