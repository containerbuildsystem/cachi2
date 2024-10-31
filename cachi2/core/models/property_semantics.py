import functools
from dataclasses import dataclass, field
from itertools import groupby
from typing import TYPE_CHECKING, Dict, Iterable, List, Optional, Tuple

if TYPE_CHECKING:
    from typing_extensions import Self, assert_never

from cachi2.core.models.sbom import Component, Property, SPDXPackage, SPDXRelation


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
    bundler_package_binary: bool = False

    @classmethod
    def from_properties(cls, props: Iterable[Property]) -> "Self":
        """Convert a list of SBOM component properties to a PropertySet."""
        found_by = None
        missing_hash_in_file = []
        npm_bundled = False
        npm_development = False
        pip_package_binary = False
        bundler_package_binary = False

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
            elif prop.name == "cachi2:bundler:package:binary":
                bundler_package_binary = True
            else:
                assert_never(prop.name)

        return cls(
            found_by,
            frozenset(missing_hash_in_file),
            npm_bundled,
            npm_development,
            pip_package_binary,
            bundler_package_binary,
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
        if self.bundler_package_binary:
            props.append(Property(name="cachi2:bundler:package:binary", value="true"))

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
            bundler_package_binary=self.bundler_package_binary or other.bundler_package_binary,
        )


def merge_relationships(
    relationships_list: List[List[SPDXRelation]], doc_ids: List[str], packages: List[SPDXPackage]
) -> Tuple[List[SPDXRelation], List[SPDXPackage]]:
    """Merge SPDX relationships.

    Function takes relationships lists and unified list of packages.
    For relationhips lists, map and inverse map of relations are created. SPDX document usually
    contains virtual package which serves as "envelope" for all real packages. These virtual
    packages are searched in the relationships and their ID is stored as middle element.
    """

    def map_relationships(
        relationships: List[SPDXRelation],
    ) -> Tuple[Optional[str], Dict[str, List[str]], Dict[str, str]]:
        relations_map: Dict[str, List[str]] = {}
        inverse_map: Dict[str, str] = {}

        for rel in relationships:
            spdx_id, related_spdx = rel.spdxElementId, rel.relatedSpdxElement
            relations_map.setdefault(spdx_id, []).append(related_spdx)
            inverse_map[related_spdx] = spdx_id

        root_element = next((k for k in relations_map if k not in inverse_map), None)
        return root_element, relations_map, inverse_map

    package_ids = {pkg.SPDXID for pkg in packages}
    _packages = packages[:]
    root_ids = []
    maps = []
    inv_maps = []
    envelopes = []
    for relationships, doc_id in zip(relationships_list, doc_ids):
        root, _map, inv_map = map_relationships(relationships)
        maps.append(_map)
        inv_maps.append(inv_map)
        if not root:
            root = doc_id
        root_ids.append(root)

    for _map, _inv_map, root_id in zip(maps, inv_maps, root_ids):
        envelope = next((r for r, c in _map.items() if _inv_map.get(r) == root_id), None)
        envelopes.append(envelope)

    merged_relationships = []

    def process_relation(
        rel: SPDXRelation,
        root_main: Optional[str],
        root_other: Optional[str],
        envelope_main: str,
        envelope_other: Optional[str],
    ) -> None:
        new_rel = SPDXRelation(
            spdxElementId=root_main if rel.spdxElementId == root_other else rel.spdxElementId,
            relatedSpdxElement=(
                root_main if rel.relatedSpdxElement == root_other else rel.relatedSpdxElement
            ),
            relationshipType=rel.relationshipType,
        )
        if new_rel.spdxElementId == envelope_other:
            new_rel.spdxElementId = envelope_main
        if new_rel.spdxElementId in package_ids or new_rel.relatedSpdxElement in package_ids:
            merged_relationships.append(new_rel)

    envelope_main = envelopes[0]
    if not envelope_main:
        _packages.append(
            SPDXPackage(
                SPDXID="SPDXRef-DocumentRoot-File-",
                name="",
            )
        )
        envelope_main = "SPDXRef-DocumentRoot-File-"
    merged_relationships.append(
        SPDXRelation(
            spdxElementId=root_ids[0],
            relatedSpdxElement="SPDXRef-DocumentRoot-File-",
            relationshipType="DESCRIBES",
        )
    )

    root_main = root_ids[0]

    for relationships, root_id, envelope in zip(relationships_list, root_ids, envelopes):
        for rel in relationships:
            process_relation(rel, root_main, root_id, envelope_main, envelope)

    for envelope in envelopes[1:]:
        envelope_packages: List[Optional[SPDXPackage]] = [
            x for x in _packages if x.SPDXID == envelope
        ]
        envelope_package: Optional[SPDXPackage] = (envelope_packages or [None])[0]
        if envelope_package:
            _packages.pop(_packages.index(envelope_package))
    return merged_relationships, _packages
