from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Iterable, Literal, Optional

import pydantic

if TYPE_CHECKING:
    from typing_extensions import Self, assert_never


PropertyName = Literal[
    "cachi2:bundler:package:binary",
    "cachi2:found_by",
    "cachi2:rpm_summary",
    "cachi2:missing_hash:in_file",
    "cachi2:pip:package:binary",
    "cachi2:pip:package:build-dependency",
    "cdx:npm:package:bundled",
    "cdx:npm:package:development",
]


class Property(pydantic.BaseModel):
    """A property inside an SBOM component."""

    name: PropertyName
    value: str


@dataclass(frozen=True)
class PropertySet:
    """Represents the semantic meaning of the set of Properties of a single Component."""

    found_by: Optional[str] = None
    missing_hash_in_file: frozenset[str] = field(default_factory=frozenset)
    npm_bundled: bool = False
    npm_development: bool = False
    pip_package_binary: bool = False
    pip_build_dependency: bool = False
    bundler_package_binary: bool = False
    rpm_summary: str = ""

    @classmethod
    def from_properties(cls, props: Iterable[Property]) -> "Self":
        """Convert a list of SBOM component properties to a PropertySet."""
        found_by = None
        missing_hash_in_file = []
        npm_bundled = False
        npm_development = False
        pip_package_binary = False
        pip_build_dependency = False
        bundler_package_binary = False
        rpm_summary = ""

        for prop in props:
            if prop.name == "cachi2:found_by":
                found_by = prop.value
            elif prop.name == "cachi2:missing_hash:in_file":
                missing_hash_in_file.append(prop.value)
            elif prop.name == "cdx:npm:package:bundled":
                npm_bundled = True
            elif prop.name == "cdx:npm:package:development":
                npm_development = True
            elif prop.name == "cachi2:pip:package:binary":
                pip_package_binary = True
            elif prop.name == "cachi2:pip:package:build-dependency":
                pip_build_dependency = True
            elif prop.name == "cachi2:bundler:package:binary":
                bundler_package_binary = True
            elif prop.name == "cachi2:rpm_summary":
                rpm_summary = prop.value
            else:
                assert_never(prop.name)

        return cls(
            found_by,
            frozenset(missing_hash_in_file),
            npm_bundled,
            npm_development,
            pip_package_binary,
            pip_build_dependency,
            bundler_package_binary,
            rpm_summary,
        )

    def to_properties(self) -> list[Property]:
        """Convert a PropertySet to a list of SBOM component properties."""
        props = []
        if self.found_by:
            props.append(Property(name="cachi2:found_by", value=self.found_by))
        props.extend(
            Property(name="cachi2:missing_hash:in_file", value=filepath)
            for filepath in self.missing_hash_in_file
        )
        if self.npm_bundled:
            props.append(Property(name="cdx:npm:package:bundled", value="true"))
        if self.npm_development:
            props.append(Property(name="cdx:npm:package:development", value="true"))
        if self.pip_package_binary:
            props.append(Property(name="cachi2:pip:package:binary", value="true"))
        if self.pip_build_dependency:
            props.append(Property(name="cachi2:pip:package:build-dependency", value="true"))
        if self.bundler_package_binary:
            props.append(Property(name="cachi2:bundler:package:binary", value="true"))
        if self.rpm_summary:
            props.append(Property(name="cachi2:rpm_summary", value=self.rpm_summary))

        return sorted(props, key=lambda p: (p.name, p.value))

    def merge(self, other: "Self") -> "Self":
        """Combine two PropertySets."""
        cls = type(self)
        return cls(
            found_by=self.found_by or other.found_by,
            missing_hash_in_file=self.missing_hash_in_file | other.missing_hash_in_file,
            npm_bundled=self.npm_bundled and other.npm_bundled,
            npm_development=self.npm_development and other.npm_development,
            pip_package_binary=self.pip_package_binary or other.pip_package_binary,
            pip_build_dependency=self.pip_build_dependency and other.pip_build_dependency,
            bundler_package_binary=self.bundler_package_binary or other.bundler_package_binary,
            rpm_summary=self.rpm_summary or other.rpm_summary,
        )
