from pathlib import Path
from unittest import mock

import pytest

from cachi2.core.errors import PackageRejected
from cachi2.core.package_managers.yarn_classic.workspaces import (
    Workspace,
    _extract_workspaces_globs,
    _get_workspace_paths,
    extract_workspace_metadata,
)
from cachi2.core.rooted_path import RootedPath


@mock.patch("cachi2.core.package_managers.yarn_classic.workspaces._read_package_from")
@mock.patch("cachi2.core.package_managers.yarn_classic.workspaces._get_workspace_paths")
def test_packages_with_workspaces_outside_source_dir_are_rejected(
    mock_get_ws_paths: mock.Mock,
    mock_read_package_from: mock.Mock,
) -> None:
    mock_read_package_from.return_value = {"workspaces": ["../../usr"]}
    mock_get_ws_paths.return_value = [Path("/tmp/foo/bar"), Path("/usr")]
    package_path = RootedPath("/tmp/foo")

    with pytest.raises(PackageRejected):
        extract_workspace_metadata(package_path)


@mock.patch("cachi2.core.package_managers.yarn_classic.workspaces._read_package_from")
@mock.patch("cachi2.core.package_managers.yarn_classic.workspaces._get_workspace_paths")
@mock.patch(
    "cachi2.core.package_managers.yarn_classic.workspaces._ensure_workspaces_are_well_formed"
)
def test_workspaces_could_be_parsed(
    mock_workspaces_ok: mock.Mock,
    mock_get_ws_paths: mock.Mock,
    mock_read_package_from: mock.Mock,
) -> None:
    mock_read_package_from.side_effect = [{"workspaces": ["quux"]}, {"name": "inner_package"}]
    mock_get_ws_paths.return_value = [Path("/tmp/foo/bar")]
    package_path = RootedPath("/tmp/foo")

    expected_result = [
        Workspace(
            path="/tmp/foo/bar",
            package_contents={"name": "inner_package"},
        ),
    ]
    result = extract_workspace_metadata(package_path)

    assert result == expected_result


@pytest.mark.parametrize(
    "package, expected",
    [
        pytest.param(
            {"workspaces": ["foo"]},
            ["foo"],
            id="workspaces_defined_in_an_array",
        ),
        pytest.param(
            {"workspaces": {"packages": ["foo"]}},
            ["foo"],
            id="workspaces_defined_in_an_array_within_an_object",
        ),
    ],
)
def test_extracting_workspace_globs_works_for_all_types_of_workspaces(
    package: dict,
    expected: list,
) -> None:

    result = _extract_workspaces_globs(package)

    assert expected == result


@pytest.mark.parametrize(
    "package_relpath",
    [
        pytest.param(
            ".",
            id="workspace_root_is_source_root",
        ),
        pytest.param(
            "src",
            id="workspace_root_is_not_source_root",
        ),
    ],
)
def test_workspace_paths_could_be_resolved(
    package_relpath: str, rooted_tmp_path: RootedPath
) -> None:
    package_path = rooted_tmp_path.join_within_root(package_relpath)
    workspace_path = package_path.join_within_root("foo")
    workspace_path.path.mkdir(parents=True)

    result = list(_get_workspace_paths(["foo"], package_path))

    assert result == [workspace_path.path]
