from pathlib import Path
from typing import Optional, Union

from pydantic import BaseModel


class _BasePackage(BaseModel):
    """A base Yarn 1.x package."""

    name: str
    version: Optional[str] = None
    integrity: Optional[str] = None
    dev: bool = False


class _UrlMixin(BaseModel):
    url: str


class _RelpathMixin(BaseModel):
    relpath: Path


class RegistryPackage(_BasePackage):
    """A Yarn 1.x package from the registry."""


class GitPackage(_BasePackage, _UrlMixin):
    """A Yarn 1.x package from a git repo."""


class UrlPackage(_BasePackage, _UrlMixin):
    """A Yarn 1.x package from a http/https URL."""


class FilePackage(_BasePackage, _RelpathMixin):
    """A Yarn 1.x package from a local file path."""


class WorkspacePackage(_BasePackage, _RelpathMixin):
    """A Yarn 1.x local workspace package."""


class LinkPackage(_BasePackage, _RelpathMixin):
    """A Yarn 1.x local link package."""


YarnClassicPackage = Union[
    FilePackage,
    GitPackage,
    LinkPackage,
    RegistryPackage,
    UrlPackage,
    WorkspacePackage,
]
