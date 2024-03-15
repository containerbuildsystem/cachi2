import functools
from dataclasses import dataclass, field
from itertools import groupby
from typing import TYPE_CHECKING, Iterable, Optional

if TYPE_CHECKING:
    from typing_extensions import Self, assert_never

from cachi2.core.models.sbom import Component, Property


def merge_component_properties(components: Iterable[Component]) -> list[Component]:
    """Sort and de-duplicate components while merging their `properties`."""
    components = sorted(components, key=Component.key)
    grouped_components = groupby(components, key=Component.key)

    def merge_component_group(component_group: Iterable[Component]) -> Component:
        component_group = list(component_group)
        prop_sets = (PropertySet.from_properties(c.properties) for c in component_group)
        merged_prop_set = functools.reduce(PropertySet.merge, prop_sets)
        component = component_group[0]
        return component.model_copy(update={"properties": merged_prop_set.to_properties()})

    return [merge_component_group(g) for _, g in grouped_components]


@dataclass(frozen=True)
class PropertySet:
    """Represents the semantic meaning of the set of Properties of a single Component."""

    found_by: Optional[str] = None
    missing_hash_in_file: frozenset[str] = field(default_factory=frozenset)
    npm_bundled: bool = False
    npm_development: bool = False
    pip_package_binary: bool = False

    @classmethod
    def from_properties(cls, props: Iterable[Property]) -> "Self":
        """Convert a list of SBOM component properties to a PropertySet."""
        found_by = None
        missing_hash_in_file = []
        npm_bundled = False
        npm_development = False
        pip_package_binary = False

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
            else:
                assert_never(prop.name)

        return cls(
            found_by,
            frozenset(missing_hash_in_file),
            npm_bundled,
            npm_development,
            pip_package_binary,
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
        )
