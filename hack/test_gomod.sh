#!/bin/bash
mkdir workdir
git clone git@github.com:release-engineering/retrodep workdir/sources

./venv/bin/cachi2 fetch-deps \
    --source workdir/sources \
    --output workdir/output \
    gomod
