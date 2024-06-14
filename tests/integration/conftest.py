import logging
import os
from pathlib import Path

import pytest

from . import utils

log = logging.getLogger(__name__)


@pytest.fixture
def test_data_dir() -> Path:
    """Path to the directory for storing unit test data."""
    return Path(__file__).parent / "test_data"


@pytest.fixture(scope="session")
def cachi2_image() -> utils.ContainerImage:
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

    cachi2 = utils.ContainerImage(cachi2_image_ref)
    if not cachi2_image_ref.startswith("localhost/"):
        cachi2.pull_image()

    return cachi2
