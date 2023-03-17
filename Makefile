PYTHON_VERSION_VENV ?= python3.9
TOX_ENVLIST ?= python3.9
TOX_ARGS ?=

all: venv

clean:
	rm -rf venv && rm -rf *.egg-info && rm -rf dist && rm -rf *.log* && rm -rf .tox

.PHONY: venv
venv:
	virtualenv --python=${PYTHON_VERSION_VENV} venv
	venv/bin/pip install --upgrade pip
	venv/bin/pip install -r requirements.txt
	venv/bin/pip install tox
	venv/bin/pip install -e .

test:
	PATH="${PWD}/venv/bin:${PATH}" tox

test-unit:
	PATH="${PWD}/venv/bin:${PATH}" tox -e $(TOX_ENVLIST) -- $(TOX_ARGS)

test-integration:
	tox -e integration

generate-test-data:
	CACHI2_GENERATE_TEST_DATA=true tox -e integration

build-image:
	podman build -t localhost/cachi2:latest .

# If you're worried that your local image may be outdated
# (old base image, old rpms cached in the microdnf install layer)
build-pristine-image:
	podman build --pull-always --no-cache -t localhost/cachi2:latest .

pip-compile:
	venv/bin/pip install -U pip-tools
	# --allow-unsafe: we use pkg_resources (provided by setuptools) as a runtime dependency
	venv/bin/pip-compile --allow-unsafe --generate-hashes --output-file=requirements.txt pyproject.toml
	venv/bin/pip-compile --all-extras --allow-unsafe --generate-hashes --output-file=requirements-extras.txt pyproject.toml
