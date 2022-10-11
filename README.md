# Cachi2

Cachi2 is a tool that identifies, fetches and lists the dependencies needed to perform a container build in a network-isolated environment. In order to do that, Cachi2 needs to be pointed to previously cloned source code and have a package manager (such as pip or go mod) specified. It will then proceed to fetch all dependencies that are declared and make them available in a local output folder, so they can be used by a following build step.

Cachi2 also generates a content manifest that contains all the dependencies that were fetched and their exact versions, serving as provenance of the build. It can also list transitive dependencies that are not directly listed in the source code, but that end up being part of the built container image.

It helps to make container builds:
  - hermetic, by prefetching all required dependencies so that the build can happen in a network-isolated environment
  - reproducible, by requiring that all the dependencies are explicitly defined, and that only them are downloaded to be made available to the build step
  - auditable, by generating a content manifest that lists all dependencies made available in the output directory


## Supported package managers

- [Go modules](https://go.dev/ref/mod)

## Project status

Cachi2 was derived (but it is not a direct fork) from [Cachito](https://github.com/containerbuildsystem/cachito) and is still in early development phase.
