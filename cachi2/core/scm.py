# SPDX-License-Identifier: GPL-3.0-or-later
import logging
import tarfile
import tempfile
from pathlib import Path

import git

from cachi2._compat.errors import InvalidRequestData, RepositoryAccessError

log = logging.getLogger(__name__)


def clone_as_tarball(url: str, ref: str, to_path: Path) -> None:
    """Clone a git repository, check out the specified revision and create a compressed tarball.

    The repository content will be under the app/ directory in the tarball.

    :param url: the URL of the repository
    :param ref: the revision to check out
    :param to_path: create the tarball at this path
    """
    with tempfile.TemporaryDirectory(prefix="cachito-") as temp_dir:
        log.debug("Cloning the Git repository from %s", url)
        try:
            repo = git.repo.Repo.clone_from(
                url,
                temp_dir,
                no_checkout=True,
                filter="blob:none",
                # Don't allow git to prompt for a username if we don't have access
                env={"GIT_TERMINAL_PROMPT": "0"},
            )
        except Exception as ex:
            log.exception(
                "Failed cloning the Git repository from %s, ref: %s, exception: %s",
                url,
                ref,
                type(ex).__name__,
            )
            raise RepositoryAccessError("Failed cloning the Git repository")

        _reset_git_head(repo, ref)

        with tarfile.open(to_path, mode="w:gz") as archive:
            # GitPython wrongly annotates working_dir as Optional, it cannot be None
            assert repo.working_dir is not None  # nosec assert_used
            archive.add(repo.working_dir, "app")


def _reset_git_head(repo: git.repo.Repo, ref: str) -> None:
    try:
        repo.head.reference = repo.commit(ref)  # type: ignore # 'reference' is a weird property
        repo.head.reset(index=True, working_tree=True)

    except Exception as ex:
        log.exception(
            "Failed on checking out the Git ref %s, exception: %s",
            ref,
            type(ex).__name__,
        )
        raise InvalidRequestData(
            "Failed on checking out the Git repository. Please verify the supplied reference "
            f'of "{ref}" is valid.'
        )
