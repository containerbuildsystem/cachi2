TOX_ENVLIST ?= py39
TOX_ARGS ?=
GENERATE_TEST_DATA = false
TEST_LOCAL_PYPISERVER = false

.PHONY: clean pip-compile
all: venv

clean:
	rm -rf dist venv .tox *.egg-info *.log*

venv:
	/usr/bin/env python3 -m venv venv
	venv/bin/pip install --upgrade pip
	venv/bin/pip install -r requirements.txt -r requirements-extras.txt
	venv/bin/pip install tox
	venv/bin/pip install -e .

test: venv
	venv/bin/tox

test-unit: venv
	venv/bin/tox -e $(TOX_ENVLIST) -- $(TOX_ARGS)

test-integration: venv
	CACHI2_GENERATE_TEST_DATA=$(GENERATE_TEST_DATA) \
	CACHI2_TEST_LOCAL_PYPISERVER=$(TEST_LOCAL_PYPISERVER) \
		venv/bin/tox -e integration -- $(TOX_ARGS)

mock-unittest-data:
	hack/mock-unittest-data/gomod.sh

build-image:
	podman build -t localhost/cachi2:latest .

# If you're worried that your local image may be outdated
# (old base image, old rpms cached in the microdnf install layer)
build-pristine-image:
	podman build --pull-always --no-cache -t localhost/cachi2:latest .

# we need git installed in the image due to setuptools-scm which has it as a direct dependency
pip-compile:
	@podman run \
	--rm \
	--volume ${PWD}:/cachi2:rw,Z \
	--workdir /cachi2 \
	docker.io/library/python:3.9-alpine sh -c \
		"apk add git && \
		pip3 install pip-tools && \
		pip-compile \
			--allow-unsafe \
			--generate-hashes \
			--output-file=requirements.txt \
			pyproject.toml && \
		pip-compile \
			--all-extras \
			--allow-unsafe \
			--generate-hashes \
			--output-file=requirements-extras.txt pyproject.toml"
