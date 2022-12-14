from pathlib import Path
from typing import Callable
from unittest import mock

from cachi2.core import resolver
from cachi2.core.models.input import Request
from cachi2.core.models.output import RequestOutput

GOMOD_OUTPUT = RequestOutput(
    packages=[
        {
            "type": "gomod",
            "path": ".",
            "name": "github.com/foo/bar",
            "version": "v1.0.0",
            "dependencies": [],
        },
    ],
    environment_variables=[
        {"name": "GOMODCACHE", "value": "deps/gomod/pkg/mod", "kind": "path"},
    ],
)
PIP_OUTPUT = RequestOutput(
    packages=[
        {
            "type": "pip",
            "path": ".",
            "name": "spam",
            "version": "1.0.0",
            "dependencies": [],
        },
    ],
    environment_variables=[
        {"name": "PIP_INDEX_URL", "value": "file:///some/path", "kind": "literal"},
    ],
)

COMBINED_OUTPUT = RequestOutput(
    packages=(GOMOD_OUTPUT.packages + PIP_OUTPUT.packages),
    environment_variables=(GOMOD_OUTPUT.environment_variables + PIP_OUTPUT.environment_variables),
)


def test_resolve_packages(tmp_path: Path):
    request = Request(
        source_dir=tmp_path,
        output_dir=tmp_path,
        packages=[{"type": "pip"}, {"type": "gomod"}],
    )

    calls_by_pkgtype = []

    def mock_fetch(pkgtype: str, output: RequestOutput) -> Callable[[Request], RequestOutput]:
        def fetch(req: Request) -> RequestOutput:
            assert req == request
            calls_by_pkgtype.append(pkgtype)
            return output

        return fetch

    with mock.patch.dict(
        resolver._package_managers,
        {
            "gomod": mock_fetch("gomod", GOMOD_OUTPUT),
            "pip": mock_fetch("pip", PIP_OUTPUT),
        },
    ):
        assert resolver.resolve_packages(request) == COMBINED_OUTPUT

    assert calls_by_pkgtype == ["gomod", "pip"]
