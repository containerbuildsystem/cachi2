PYTHON_VERSION_VENV ?= python3
TOX_ENVLIST ?= py39
TOX_ARGS ?=
GENERATE_TEST_DATA = false
TEST_LOCAL_PYPISERVER = false

.PHONY: clean
all: venv

define make_venv
	$(PYTHON_BIN) -m venv $(VENV)
	$(VENV)/bin/pip install --upgrade pip
endef

clean:
	rm -rf dist venv .tox *.egg-info *.log*


venv: PYTHON_BIN := $(shell which $(PYTHON_VERSION_VENV))
venv: VENV := venv
venv:
	$(call make_venv)
	$(VENV)/bin/pip install -r requirements.txt
	$(VENV)/bin/pip install tox
	$(VENV)/bin/pip install -e .

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

generate-test-data: GENERATE_TEST_DATA = true
generate-test-data: test-integration

build-image:
	podman build -t localhost/cachi2:latest .

# If you're worried that your local image may be outdated
# (old base image, old rpms cached in the microdnf install layer)
build-pristine-image:
	podman build --pull-always --no-cache -t localhost/cachi2:latest .

pip-compile: PYTHON_BIN := $(shell which python3.9)
pip-compile: VENV := $(shell mktemp -d -u --tmpdir --suffix .venv pip_compileXXX)
pip-compile:
	$(call make_venv)
	$(VENV)/bin/pip install -U pip-tools
	# --allow-unsafe: we use pkg_resources (provided by setuptools) as a runtime dependency
	$(VENV)/bin/pip-compile --allow-unsafe --generate-hashes --output-file=requirements.txt pyproject.toml
	$(VENV)/bin/pip-compile --all-extras --allow-unsafe --generate-hashes --output-file=requirements-extras.txt pyproject.toml
	rm -rf $(VENV)
