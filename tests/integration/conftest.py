import contextlib
import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Iterator

import pytest
import requests

from . import utils

log = logging.getLogger(__name__)


@pytest.fixture
def test_data_dir() -> Path:
    """Path to the directory for storing unit test data."""
    return Path(__file__).parent / "test_data"


@pytest.fixture(scope="session")
def cachi2_image() -> utils.Cachi2Image:
    cachi2_image_ref = os.environ.get("CACHI2_IMAGE")
    if not cachi2_image_ref:
        cachi2_image_ref = "localhost/cachi2:latest"
        log.info("Building local cachi2:latest image")
        log.info("To skip this step, pass a CACHI2_IMAGE=<image-ref> environment variable, e.g.:")
        log.info("    CACHI2_IMAGE=localhost/cachi2:latest tox -e integration")
        # <arbitrary_path>/cachi2/tests/integration/conftest.py
        #                   [2] <- [1]  <-  [0]  <- parents
        cachi2_repo_root = Path(__file__).parents[2]
        utils.build_image(cachi2_repo_root, tag=cachi2_image_ref)

    cachi2 = utils.Cachi2Image(cachi2_image_ref)
    if not cachi2_image_ref.startswith("localhost/"):
        cachi2.pull_image()

    return cachi2


# autouse=True: It's nicer to see the pypiserver setup logs at the beginning of the test suite.
# Otherwise, pypiserver would start once the pip tests need it and the logs would be buried between
# test output.
@pytest.fixture(autouse=True, scope="session")
def local_pypiserver() -> Iterator[None]:
    if os.getenv("CACHI2_TEST_LOCAL_PYPISERVER") != "true":
        yield
        return

    pypiserver_dir = Path(__file__).parent.parent / "pypiserver"

    with contextlib.ExitStack() as context:
        proc = context.enter_context(subprocess.Popen([pypiserver_dir / "start.sh"]))
        context.callback(proc.terminate)

        pypiserver_port = os.getenv("PYPISERVER_PORT", "8080")
        for _ in range(60):
            time.sleep(1)
            try:
                resp = requests.get(f"http://localhost:{pypiserver_port}")
                resp.raise_for_status()
                log.debug(resp.text)
                break
            except requests.RequestException as e:
                log.debug(e)
        else:
            raise RuntimeError("pypiserver didn't start fast enough")

        yield
