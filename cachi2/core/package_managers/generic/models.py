from typing import Literal, Optional

from pydantic import BaseModel, field_validator


class LockfileMetadata(BaseModel):
    """Defines format of the metadata section in the lockfile."""

    version: Literal["1.0"]


class LockfileArtifact(BaseModel):
    """Defines format of a single artifact in the lockfile."""

    download_url: str
    target: Optional[str] = None
    checksums: dict[str, str]

    @field_validator("checksums")
    @classmethod
    def no_empty_checksums(cls, value: dict[str, str]) -> dict[str, str]:
        """
        Validate that at least one checksum is present for an artifact.

        :param value: the checksums dict to validate
        :return: the validated checksum dict
        """
        if len(value) == 0:
            raise ValueError("At least one checksum must be provided.")
        return value


class GenericLockfileV1(BaseModel):
    """Defines format of the cachi2 generic lockfile, version 1.0."""

    metadata: LockfileMetadata
    artifacts: list[LockfileArtifact]
