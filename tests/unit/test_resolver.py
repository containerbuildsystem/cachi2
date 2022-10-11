from pathlib import Path
from typing import Callable
from unittest import mock

from cachi2.core import resolver
from cachi2.core.models.input import Request
from cachi2.core.models.output import Package, RequestOutput

GOMOD_PACKAGE = Package(
    type="gomod", path=".", name="github.com/foo/bar", version="v1.0.0", dependencies=[]
)
PIP_PACKAGE = Package(type="pip", path=".", name="spam", version="1.0.0", dependencies=[])


def mock_output(*packages: Package) -> RequestOutput:
    return RequestOutput(packages=packages, environment_variables=[])


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
            "gomod": mock_fetch("gomod", mock_output(GOMOD_PACKAGE)),
            "pip": mock_fetch("pip", mock_output(PIP_PACKAGE)),
        },
    ):
        assert resolver.resolve_packages(request) == mock_output(GOMOD_PACKAGE, PIP_PACKAGE)

    assert calls_by_pkgtype == ["gomod", "pip"]
