import json
from contextlib import suppress
from itertools import chain
from pathlib import Path
from typing import Any, Iterable

import pydantic

from cachi2.core.errors import PackageRejected
from cachi2.core.models.input import YarnClassicPackageInput
from cachi2.core.rooted_path import RootedPath


class Workspace(pydantic.BaseModel):
    """Workspace model."""

    path: Path  # path to a workspace.
    package_contents: dict  # package data extracted from path/"package.json".
    # package reference for potential nested workspace extraction:
    package: YarnClassicPackageInput


def ensure_no_path_leads_out(
    paths: Iterable[Path],
    source_dir: RootedPath,
) -> None:
    """Ensure no path leads out of source directory.

    Raises an exception when any path is not relative to source directory.
    Does nothing when path does not exist in the file system.
    """
    for path in paths:
        if not path.is_relative_to(source_dir.path):
            raise PackageRejected(
                f"Found a workspace path which is not relative to package: {path}",
                solution=(
                    "Avoid using packages which try to access your filesystem "
                    "outside of package directory."
                ),
            )


def ensure_workspaces_are_well_formed(
    paths: Iterable[Path],
) -> None:
    """Ensure that every workspace contains package.json.

    Reject the package otherwise.
    """
    for p in paths:
        if not Path(p, "package.json").is_file():
            raise PackageRejected(
                reason=f"Workspace {p} does not contain 'package.json'",
                solution=None,
            )


def get_workspace_paths(
    workspaces_globs: list[str],
    source_dir: RootedPath,
) -> Iterable[Path]:
    """Resolve globs within source directory."""

    def all_paths_matching(glob: str) -> list[Path]:
        return [pth.resolve() for pth in source_dir.path.glob(glob)]

    return chain.from_iterable(all_paths_matching(g) for g in workspaces_globs)


def extract_workspaces_globs(
    package: dict[str, Any],
) -> list[str]:
    """Extract globs from workspaces entry in package dict."""
    workspaces_globs = package.get("workspaces", [])
    # This could be a list or a list in a dictionary. If it is not a dictionary
    # then it is already a list that we need:
    with suppress(AttributeError):
        workspaces_globs = workspaces_globs.get("packages", [])
    return workspaces_globs


def read_package_from(path: RootedPath) -> dict[str, Any]:
    """Read package.json from a path."""
    return json.loads(path.join_within_root("package.json").path.read_text())


def extract_workspace_metadata(
    package: YarnClassicPackageInput,
    source_dir: RootedPath,
) -> list[Workspace]:
    """Extract workspace metadata from a package.

    Currently does not deal with nested workspaces, however the way the code
    is structured it would be trivial to make component generation recursive.
    It is left non-recursive until it is clear that nested workspaces appear in
    the wild.
    """
    processed_package = read_package_from(source_dir.join_within_root(package.path))
    workspaces_globs = extract_workspaces_globs(processed_package)
    workspaces_paths = get_workspace_paths(workspaces_globs, source_dir)
    ensure_no_path_leads_out(workspaces_paths, source_dir)
    ensure_workspaces_are_well_formed(workspaces_paths)
    parsed_workspaces = []
    for wp in workspaces_paths:
        parsed_workspaces.append(
            Workspace(
                path=wp,
                package=YarnClassicPackageInput(
                    type="yarn-classic", path=wp.relative_to(source_dir.path)
                ),
                package_contents=read_package_from(source_dir.join_within_root(wp)),
            )
        )
    return parsed_workspaces
