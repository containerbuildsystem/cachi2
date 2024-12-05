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

    Function takes relationships lists, list of spdx document ids and unified list of packages.
    For all relationships lists, map and inverse map of relations are created.
    These maps are used to find root elements of the SPDX document.

    For relationhips lists, map and inverse map of relations are created. SPDX document usually
    contains root package containing all real packages. Root element is found by searching
    through map and inverse map of relationships. Element which has entry in map containing
    other elements and has entry in inverse map containing entry pointing to root element is
    considered as root element.

    packages are searched in the relationships and their ID is stored as middle element.
    """

    def map_relationships(
        relationships: List[SPDXRelation],
    ) -> Tuple[Dict[str, List[str]], Dict[str, str]]:
        """Return (map and inverse map) for given relationships.

        Map is where key is SPDXID of element in relationship which is refered by spdxElementId
        and value is list of elements refered by relatedSpdxElement in the relationship with the
        element.
        Inverse map is opposite of map where key is relatedSpdxElement and value is spdxElementId.
        """
        relations_map: Dict[str, List[str]] = {}
        inverse_map: Dict[str, str] = {}

        for rel in relationships:
            spdx_id, related_spdx = rel.spdxElementId, rel.relatedSpdxElement
            relations_map.setdefault(spdx_id, []).append(related_spdx)
            inverse_map[related_spdx] = spdx_id

        return relations_map, inverse_map

    def process_relation(
        rel: SPDXRelation,
        doc_main: Optional[str],
        doc_other: Optional[str],
        root_package_main: str,
        root_package_other: Optional[str],
        merged_relationships: List[SPDXRelation],
    ) -> None:
        """Process a single SPDX relationship.

        Add relatationship to merged relationships list while replacing spdxElementId and
        relatedSpdxElement with id of primary root package if original elements refers to
        other root package.
        Relationship is added only if it refers to package in the list of packages.
        """
        new_rel = SPDXRelation(
            spdxElementId=(
                root_package_main if rel.spdxElementId == root_package_other else rel.spdxElementId
            ),
            relatedSpdxElement=(
                doc_main if rel.relatedSpdxElement == root_package_other else rel.relatedSpdxElement
            ),
            relationshipType=rel.relationshipType,
        )
        if new_rel.spdxElementId == root_package_other:
            new_rel.spdxElementId = root_package_main
        if new_rel.spdxElementId in package_ids or new_rel.relatedSpdxElement in package_ids:
            merged_relationships.append(new_rel)

    package_ids = {pkg.SPDXID for pkg in packages}
    _packages = packages[:]
    maps = []
    inv_maps = []
    root_package_ids = []
    for relationships in relationships_list:
        _map, inv_map = map_relationships(relationships)
        maps.append(_map)
        inv_maps.append(inv_map)

    for _map, _inv_map, doc_id in zip(maps, inv_maps, doc_ids):
        root_package_id = next((r for r, c in _map.items() if _inv_map.get(r) == doc_id), None)
        root_package_ids.append(root_package_id)

    merged_relationships = []

    root_package_main = root_package_ids[0]
    if not root_package_main:
        _packages.append(
            SPDXPackage(
                SPDXID="SPDXRef-DocumentRoot-File-",
                name="",
            )
        )
        root_package_main = "SPDXRef-DocumentRoot-File-"
    merged_relationships.append(
        SPDXRelation(
            spdxElementId=doc_ids[0],
            relatedSpdxElement=root_package_main,
            relationshipType="DESCRIBES",
        )
    )

    doc_main = doc_ids[0]

    for relationships, doc_id, root_package_id in zip(
        relationships_list, doc_ids, root_package_ids
    ):
        for rel in relationships:
            process_relation(
                rel, doc_main, doc_id, root_package_main, root_package_id, merged_relationships
            )

    # Remove root packages of other elements from the list of packages
    for _root_package in root_package_ids[1:]:
        found_root_packages: List[Optional[SPDXPackage]] = [
            x for x in _packages if x.SPDXID == _root_package
        ]
        root_package: Optional[SPDXPackage] = (found_root_packages or [None])[0]
        if root_package:
            _packages.pop(_packages.index(root_package))
    return merged_relationships, _packages
