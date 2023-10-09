PYTHON_VERSION_VENV ?= python3.9
TOX_ENVLIST ?= py39
TOX_ARGS ?=

all: venv

clean:
	rm -rf dist venv .tox *.egg-info *.log*

.PHONY: venv
venv:
	virtualenv --python=${PYTHON_VERSION_VENV} venv
	venv/bin/pip install --upgrade pip
	venv/bin/pip install -r requirements.txt
	venv/bin/pip install tox
	venv/bin/pip install -e .

test: venv
	venv/bin/tox

test-unit: venv
	venv/bin/tox -e $(TOX_ENVLIST) -- $(TOX_ARGS)

test-integration: venv
	venv/bin/tox -e integration

mock-unittest-data:
	hack/mock-unittest-data/gomod.sh

generate-test-data: venv
	CACHI2_GENERATE_TEST_DATA=true venv/bin/tox -e integration

build-image:
	podman build -t localhost/cachi2:latest .

# If you're worried that your local image may be outdated
# (old base image, old rpms cached in the microdnf install layer)
build-pristine-image:
	podman build --pull-always --no-cache -t localhost/cachi2:latest .

pip-compile: venv
	venv/bin/pip install -U pip-tools
	# --allow-unsafe: we use pkg_resources (provided by setuptools) as a runtime dependency
	venv/bin/pip-compile --allow-unsafe --generate-hashes --output-file=requirements.txt pyproject.toml
	venv/bin/pip-compile --all-extras --allow-unsafe --generate-hashes --output-file=requirements-extras.txt pyproject.toml
