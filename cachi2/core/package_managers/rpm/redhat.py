import logging
import uuid
from functools import cached_property
from typing import Optional

from pydantic import BaseModel, PositiveInt, field_validator, model_validator

log = logging.getLogger(__name__)


class LockfilePackage(BaseModel):
    """Package item; represents RPM or SRPM file."""

    repoid: Optional[str] = None
    url: str
    checksum: Optional[str] = None
    size: Optional[int] = None


class LockfileArch(BaseModel):
    """Architecture structure."""

    arch: str
    packages: list[LockfilePackage] = []
    source: list[LockfilePackage] = []

    @model_validator(mode="after")
    def _arch_empty(self) -> "LockfileArch":
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
    arches: list[LockfileArch]

    @cached_property
    def cachi2_repoid(self) -> str:
        """
        Generate a short random repoid string.

        'repoid' key is not mandatory in the lockfile format. When not present,
        we fallback to a (partly) random string based on a UUID.
        """
        return f"cachi2-{uuid.uuid4().hex[:6]}"

    @cached_property
    def cachi2_source_repoid(self) -> str:
        """Generate a short random source repoid string."""
        return self.cachi2_repoid + "-source"

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
