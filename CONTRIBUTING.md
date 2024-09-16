# Contributing to Cachi2

## Table of contents

* [How to start a contribution](#how-to-start-a-contribution)
  * [How we deal with larger features](#how-we-deal-with-larger-features)
  * [Cachi2's ethos](#cachi2s-ethos)

## How to start a contribution

The team always encourages early communication for all types of contributions. Found a bug or see something that could be improved? Open an issue. Want to address something bigger like adding new package manager support or overhauling the entire project? Open an issue or start a Discussion on Github. This way, we can give you guidance and avoid your work being wasted on an implementation which does not fit the project's scope and goal.

Alternatively, submit a pull request with one of the following

* A high-level design of the feature, highlighting goals and key decision points.
* A proof-of-concept implementation.
* In case the change is trivial, you can start with a draft or even provide a PR with the final implementation.

### How we deal with larger features

Implementing a larger feature (such as adding a new package manager) is usually a very long and detailed effort. This type of work does not fit well into a single pull request; after several comment threads it becomes almost unmanageable (for you) and very hard to review (for us). For that reason, we request that larger features be split into a series of pull requests. Once approved, these pull requests will be merged into "main", but the new feature will be marked as experimental, and will retain this mark until it meets code quality standards and all necessary changes are merged.

This has several implications

* Experimental features are not fully endorsed by the maintainers, and maintainers will not provide support.
* Experimental features are not production-ready and should never be used in production.
* Always expect that an experimental feature can be fully dropped from this project without any prior notice.
* A feature toggle is needed to allow users to opt-in. This is currently being handled by the `dev-package-managers` flag.
* All SBOMs produced when an experimental feature is used will be marked as such.

If, for some reason, you feel this proposed workflow does not fit the feature you're contributing, please reach out to the maintainers so we can provide an alternative.

#### Making experimental features production-ready

When a feature's development has reached a stable point, you can propose making it an official part of the project. This signals to users that the feature is production-ready. To communicate this intent to the maintainers, open a pull request containing an Architecture Decision Record (ADR) with an outline of the implementation, and a clear statement of all decisions which were made (as well as their rationale).

Once maintainers are confident that they have enough information to maintain the new feature as officially supported they will accept it and help with moving it out from under experimental flag.

### Cachi2's Ethos
Whenever adding a new feature to Cachi2, it is important to keep these fundamental aspects in mind

1. Report prefetched dependencies as accurately as possible

    Cachi2's primary goal is to prefetch content and enable hermetic builds. But hermetic builds are only useful if they end up providing a more accurate SBOM than a non-hermetic build would. Cachi2 strives to download only what's explicitly declared in a project's source code, and accurately report it in the resulting SBOM.

2. Avoid arbitrary code execution

    Some package manager implementations rely on third-party tools to gather data or even for fetching dependencies. This brings the risk of arbitrary code execution, which opens the door for random things to be part of the prefetched content. This undermines the accuracy of the SBOM, and must be avoided at all costs.

3. Always perform checksum validation

    The content provided to the build will only be safe if all of the downloaded packages have their checksums verified. In case a mismatch is found, the entire request must be failed, since the prefetched content is tainted and is potentially malicious. There are two types of checksums: server-provided and user-provided. Cachi2 prefers but does not require the latter. Every dependency which does not have a user-provided checksum verified, must be clearly marked as such in the resulting SBOM (e.g. see 'pip' support). All dependencies must have at least one checksum in order to be considered validated.

4. Favor reproducibilty

    Always use fully resolved lockfiles or similar input files to determine what content needs to be download for a specific project (e.g. npm's `package-lock.json`, a `pip-compile` generated `requirements.txt`, etc). Resolving the dependencies during the prefetch will prevent its behavior from being deterministic—in other words, the same repository and the same commit hash should always result in identical prefetch results.
