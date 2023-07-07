import json
from pathlib import Path

from utils.merge_syft_sbom import merge_sboms


def test_merge_sboms(data_dir: Path) -> None:
    result = merge_sboms(f"{data_dir}/sboms/cachi2.bom.json", f"{data_dir}/sboms/syft.bom.json")

    with open(f"{data_dir}/sboms/merged.bom.json") as file:
        expected_sbom = json.load(file)

    assert json.loads(result) == expected_sbom
