import json
from itertools import chain
from pathlib import Path
from typing import Any, Generator, Iterable

import pydantic

from cachi2.core.errors import PackageRejected
from cachi2.core.models.input import YarnClassicPackageInput
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
