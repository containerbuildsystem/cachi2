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

test-integration:
	podman build -t cachi2-${USER} .
	CACHI2_IMAGE=localhost/cachi2-${USER}:latest tox -e integration

test:
	PATH="${PWD}/venv/bin:${PATH}" tox

test-unit:
	PATH="${PWD}/venv/bin:${PATH}" tox -e $(TOX_ENVLIST) -- $(TOX_ARGS)

pip-compile: venv/bin/pip-compile
	# --allow-unsafe: we use pkg_resources (provided by setuptools) as a runtime dependency
	venv/bin/pip-compile --allow-unsafe --generate-hashes --output-file=requirements.txt pyproject.toml
	venv/bin/pip-compile --allow-unsafe --generate-hashes --output-file=requirements-test.txt requirements-test.in

venv/bin/pip-compile:
	venv/bin/pip install pip-tools
