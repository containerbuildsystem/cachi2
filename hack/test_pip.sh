#!/bin/bash

mkdir -p workdir

if [[ ! -e workdir/cachito-pip-with-deps ]]; then
    git clone https://github.com/cachito-testing/cachito-pip-with-deps.git \
        workdir/cachito-pip-with-deps
fi

pushd workdir/cachito-pip-with-deps
git checkout 83b387568b6287f6829403cff1e1377b0fb2f5d8
popd

venv/bin/cachi2 fetch-deps \
    --source workdir/cachito-pip-with-deps \
    --output workdir/pip-output \
    --package pip
