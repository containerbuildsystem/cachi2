#!/bin/bash

mkdir -p workdir

if [[ ! -e workdir/cachito-pip-with-deps ]]; then
    git clone https://github.com/cachito-testing/cachito-pip-with-deps.git \
        workdir/cachito-pip-with-deps
fi

pushd workdir/cachito-pip-with-deps
git checkout 83b387568b6287f6829403cff1e1377b0fb2f5d8
popd

venv/bin/python << EOF
from pathlib import Path

from cachi2.core.package_managers import pip
from cachi2.interface.logging import setup_logging, LogLevel

setup_logging(LogLevel.DEBUG)

pip.resolve_pip(
    Path("workdir/cachito-pip-with-deps"),
    Path("workdir/pip-output"),
)
EOF
