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
    if "CACHI2_IMAGE" not in os.environ:
        raise RuntimeError("CACHI2_IMAGE env variable is mandatory!")

    cachi2 = utils.ContainerImage(os.environ["CACHI2_IMAGE"])
    if not os.environ["CACHI2_IMAGE"].startswith("localhost/"):
        cachi2.pull_image()
    return cachi2
