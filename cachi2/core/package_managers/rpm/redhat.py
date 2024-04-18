import logging
import uuid
from functools import cached_property
from typing import Optional

from pydantic import BaseModel, PositiveInt, field_validator, model_validator

log = logging.getLogger(__name__)


class Package(BaseModel):
    """Package item; represents RPM or SRPM file."""

    repoid: Optional[str] = None
    url: str
    checksum: Optional[str] = None
    size: Optional[int] = None


class Arch(BaseModel):
    """Architecture structure."""

    arch: str
    packages: list[Package] = []
    source: list[Package] = []

    @model_validator(mode="after")
    def _arch_empty(self) -> "Arch":
        """Validate arch."""
        if self.packages == [] and self.source == []:
            raise ValueError("At least one field ('packages', 'source') must be set in every arch.")
        return self


class RedhatRpmsLock(BaseModel):
    """
    The class implements basic operations with specific lockfile format.

    Input data comes from raw yaml stored as a dictionary.
    """

    # Top of the structure of the lockfile. Model is used for parsing the lockfile.
    lockfileVersion: PositiveInt
    lockfileVendor: str
    arches: list[Arch]

    @cached_property
    def _uuid(self) -> str:
        """
        Generate short random string for internal repoid.

        'repoid' key is not mandatory in the lockfile format. When not present,
        fallback is set as (partly) random string containing _uuid.
        """
        return uuid.uuid4().hex[:6]

    @property
    def internal_repoid(self) -> str:
        """Internal_repoid getter."""
        return f"cachi2-{self._uuid}"

    @property
    def internal_source_repoid(self) -> str:
        """Internal_source_repoid getter."""
        return f"cachi2-{self._uuid}-source"

    @field_validator("lockfileVersion")
    def _version_redhat(cls, version: PositiveInt) -> PositiveInt:
        """Evaluate whether the lockfile header matches the format specification."""
        if version != 1:
            raise ValueError(f"Unexpected value for 'lockfileVersion': '{version}'.")
        return version

    @field_validator("lockfileVendor")
    def _vendor_redhat(cls, vendor: str) -> str:
        """Evaluate whether the lockfile header matches the format specification."""
        if vendor != "redhat":
            raise ValueError(f"Unexpected value for 'lockfileVendor': '{vendor}'.")
        return vendor
