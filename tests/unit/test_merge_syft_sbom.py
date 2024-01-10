import json
from pathlib import Path
from typing import Any

import pytest

from utils.merge_syft_sbom import merge_sboms

TOOLS_METADATA = {
    "syft-cyclonedx-1.4": {
        "name": "syft",
        "vendor": "anchore",
        "version": "0.47.0",
    },
    "syft-cyclonedx-1.5": {
        "type": "application",
        "author": "anchore",
        "name": "syft",
        "version": "0.100.0",
    },
    "cachi2-cyclonedx-1.4": {
        "name": "cachi2",
        "vendor": "red hat",
    },
    "cachi2-cyclonedx-1.5": {
        "type": "application",
        "author": "red hat",
        "name": "cachi2",
    },
}


def test_merge_sboms(data_dir: Path) -> None:
    result = merge_sboms(f"{data_dir}/sboms/cachi2.bom.json", f"{data_dir}/sboms/syft.bom.json")

    with open(f"{data_dir}/sboms/merged.bom.json") as file:
        expected_sbom = json.load(file)

    assert json.loads(result) == expected_sbom


@pytest.mark.parametrize(
    "syft_tools_metadata, expected_result",
    [
        (
            [TOOLS_METADATA["syft-cyclonedx-1.4"]],
            [
                TOOLS_METADATA["syft-cyclonedx-1.4"],
                TOOLS_METADATA["cachi2-cyclonedx-1.4"],
            ],
        ),
        (
            {
                "components": [TOOLS_METADATA["syft-cyclonedx-1.5"]],
            },
            {
                "components": [
                    TOOLS_METADATA["syft-cyclonedx-1.5"],
                    TOOLS_METADATA["cachi2-cyclonedx-1.5"],
                ],
            },
        ),
    ],
)
def test_merging_tools_metadata(
    syft_tools_metadata: str, expected_result: Any, tmpdir: Path
) -> None:
    syft_sbom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "metadata": {
            "tools": syft_tools_metadata,
        },
        "components": [],
    }

    cachi2_sbom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "components": [],
    }

    syft_sbom_path = f"{tmpdir}/syft.bom.json"
    cachi2_sbom_path = f"{tmpdir}/cachi2.bom.json"

    with open(syft_sbom_path, "w") as file:
        json.dump(syft_sbom, file)

    with open(cachi2_sbom_path, "w") as file:
        json.dump(cachi2_sbom, file)

    result = merge_sboms(cachi2_sbom_path, syft_sbom_path)

    assert json.loads(result)["metadata"]["tools"] == expected_result
