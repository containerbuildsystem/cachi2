from pathlib import Path
from typing import Callable
from unittest import mock

from cachi2.core import resolver
from cachi2.core.models.input import Request
from cachi2.core.models.output import EnvironmentVariable, ProjectFile, RequestOutput
from cachi2.core.models.sbom import Component

GOMOD_OUTPUT = RequestOutput.from_obj_list(
    components=[
        Component(
            type="library",
            name="github.com/foo/bar",
            version="v1.0.0",
            purl="pkg:golang/github.com/foo/bar@v1.0.0",
        )
    ],
    environment_variables=[
        EnvironmentVariable(name="GOMODCACHE", value="deps/gomod/pkg/mod", kind="path"),
    ],
    project_files=[
        ProjectFile(abspath="/your/project/go.mod", template="Hello gomod my old friend.")
    ],
)

PIP_OUTPUT = RequestOutput.from_obj_list(
    components=[
        Component(type="library", name="spam", version="1.0.0", purl="pkg:pypi/spam@1.0.0")
    ],
    environment_variables=[
        EnvironmentVariable(name="PIP_INDEX_URL", value="file:///some/path", kind="literal"),
    ],
    project_files=[
        ProjectFile(
            abspath="/your/project/requirements.txt", template="I've come to talk with you again."
        ),
    ],
)

NPM_OUTPUT = RequestOutput.from_obj_list(
    components=[Component(type="library", name="eggs", version="1.0.0", purl="pkg:npm/eggs@1.0.0")],
    environment_variables=[
        EnvironmentVariable(name="CHROMEDRIVER_SKIP_DOWNLOAD", value="true", kind="literal"),
    ],
    project_files=[
        ProjectFile(
            abspath="/your/project/package-lock.json", template="Because a vision softly creeping."
        )
    ],
)

COMBINED_OUTPUT = RequestOutput.from_obj_list(
    components=GOMOD_OUTPUT.components + NPM_OUTPUT.components + PIP_OUTPUT.components,
    environment_variables=(
        GOMOD_OUTPUT.build_config.environment_variables
        + PIP_OUTPUT.build_config.environment_variables
        + NPM_OUTPUT.build_config.environment_variables
    ),
    project_files=(
        GOMOD_OUTPUT.build_config.project_files
        + PIP_OUTPUT.build_config.project_files
        + NPM_OUTPUT.build_config.project_files
    ),
)


def test_resolve_packages(tmp_path: Path) -> None:
    request = Request(
        source_dir=tmp_path,
        output_dir=tmp_path,
        packages=[{"type": "pip"}, {"type": "npm"}, {"type": "gomod"}],
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
            "npm": mock_fetch("npm", NPM_OUTPUT),
            "pip": mock_fetch("pip", PIP_OUTPUT),
        },
    ):
        assert resolver.resolve_packages(request) == COMBINED_OUTPUT

    assert calls_by_pkgtype == ["gomod", "npm", "pip"]
