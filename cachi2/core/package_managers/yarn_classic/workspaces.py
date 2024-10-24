import json
from itertools import chain
from pathlib import Path
from typing import Any, Generator, Iterable

import pydantic

from cachi2.core.errors import PackageRejected
from cachi2.core.rooted_path import PathOutsideRoot, RootedPath


class Workspace(pydantic.BaseModel):
    """Workspace model."""

    path: Path  # path to a workspace.
    package_contents: dict  # package data extracted from path/"package.json".

    @pydantic.field_validator("package_contents")
    def _ensure_package_is_named(cls, package_contents: dict) -> dict:
        if "name" not in package_contents:
            raise ValueError("Workspaces must contain 'name' field.")
        return package_contents


def ensure_no_path_leads_out(
    paths: Iterable[Path],
    source_dir: RootedPath,
) -> None:
    """Ensure no path leads out of source directory.

    Raises an exception when any path is not relative to source directory.
    Does nothing when path does not exist in the file system.
    """
    for path in paths:
        try:
            source_dir.join_within_root(path)
        except PathOutsideRoot:
            raise PackageRejected(
                f"Found a workspace path which is not relative to package: {path}",
                solution=(
                    "Avoid using packages which try to access your filesystem "
                    "outside of package directory."
                ),
            )


def _ensure_workspaces_are_well_formed(
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


def _get_workspace_paths(
    workspaces_globs: list[str],
    source_dir: RootedPath,
) -> Iterable[Path]:
    """Resolve globs within source directory."""

    def all_paths_matching(glob: str) -> Generator[Path, None, None]:
        return (pth.resolve() for pth in source_dir.path.glob(glob))

    return chain.from_iterable(map(all_paths_matching, workspaces_globs))


def _extract_workspaces_globs(
    package: dict[str, Any],
) -> list[str]:
    """Extract globs from workspaces entry in package dict."""
    # This could be an Array or an Array nested in an Object.
    # Official docs mentioning the former:
    #   https://classic.yarnpkg.com/lang/en/docs/workspaces/
    # Official blog containing a hint about the latter:
    #   https://classic.yarnpkg.com/lang/en/docs/workspaces/
    workspaces_globs = package.get("workspaces", [])
    if isinstance(workspaces_globs, dict):
        workspaces_globs = workspaces_globs.get("packages", [])
    return workspaces_globs


def _read_package_from(path: RootedPath) -> dict[str, Any]:
    """Read package.json from a path."""
    return json.loads(path.join_within_root("package.json").path.read_text())


def extract_workspace_metadata(
    package_path: RootedPath,
) -> list[Workspace]:
    """Extract workspace metadata from a package."""
    processed_package = _read_package_from(package_path)
    workspaces_globs = _extract_workspaces_globs(processed_package)
    workspaces_paths = _get_workspace_paths(workspaces_globs, package_path)
    ensure_no_path_leads_out(workspaces_paths, package_path)
    _ensure_workspaces_are_well_formed(workspaces_paths)
    parsed_workspaces = []
    for wp in workspaces_paths:
        parsed_workspaces.append(
            Workspace(
                path=wp,
                package_contents=_read_package_from(package_path.join_within_root(wp)),
            )
        )
    return parsed_workspaces
