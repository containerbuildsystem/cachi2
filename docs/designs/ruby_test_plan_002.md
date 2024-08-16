# Test plan for RubyGems/Bundler package manager

This document is intended to describe RubyGems/Bundler package manager
usage patterns to be tested. The document follows package manager design
proposed in [PR-565](https://github.com/containerbuildsystem/cachi2/pull/565).
The document captures behaviors under test in a DSL for test scenario
description. The format is straightforward and self-documenting, for a formal
specification and tooling please refer to
[the specification](https://cucumber.io/docs/gherkin/reference/).

## General overview

Cachi2 is intended to prefetch project's dependencies and to prepare a local
environment to make it possible to build projects without network connectivity.
Cachi2 can handle a number of package formats, RubyGems/Bundler (RG/B) is among
the supported ones. Cachi2 does not support all features of RG/B, opting to
support the most widespread and safe ones instead of supporting everything.

The tests are to check that conforming packages could be preprocessed by Cachi2
and that non-conforming packages are rejected by Cachi2.

The checks are expected to be run against actual packages published either on
rubygems.org, on github.com or locally.

Each example in every test scenario requires a separate repository/package
demonstrating an aspect under test. A list of necessary repositories could be
found [below](#necessary-repositories).

## Test cases

@e2e_test
Feature: Projects prepared with Cachi2 could be hermetically built
    Scenario: a user can successfully build a project prepared with Cachi2
        Given a clean repository of a well-defined project
         When a user request to fetch dependencies for a well-defined project
          And a user generates environment for well-defined project
          And a user triggers a hermetic build
         Then the build system exits successfully
          And a build artifact is produced.


@integration_test
Feature: Cachi2 can prefetch dependencies for Ruby projects

    Scenario outline: a user wants to fetch dependencies for a package containing well-defined Gemfile.lock
       Given  clean repository of a "well-defined project"
        When  a user request to fetch dependencies for a "well-defined project"
        Then  direct and transitive dependencies are fetched
         And  dependencies could be found within the "well-defined project"
    Examples:
        |    well-defined project                                       |
        | Has a mixture of gems, Git and path dependencies and .gemspec |
        | Has a mixture of gems, Git and path dependencies              |

    Scenario outline: a user wants to fetch dependencies for a poorly-defined project
       Given  clean repository of a "poorly-defined project"
        When  a user request to fetch dependencies for a "poorly-defined project"
        Then  direct and transitive dependencies are fetched
         And  dependencies could be found within the "poorly-defined project"
         But  cachi2 warns about problems with "poorly-defined project"
    Examples:
        |    poorly-defined project                                                     |
        | Has a combination of dependency types in Gemfile.lock, but misses Gemfile     |

    Scenario outline: a user wants to fetch dependencies for a package containing ill-defined Gemfile.lock
       Given  clean repository of a "ill-defined project"
        When  a user request to fetch dependencies for a "ill-defined project"
        Then  Cachi2 reports an error
         And  repository for "ill-defined project" remains unchanged
    Examples:
        |    ill-defined project                           |
        | Gemfile.lock is missing                          |
        | Git dependency is not pinned to a revision       |
        | Transitive dependency is ill-defined             |


@integration_test
Feature: Cachi2 can preset configuration for hermetic builds

    Scenario outline: a user prepares a repository with a Ruby project
        When  a user generates environment for "a Ruby project"
        Then  the environment contains a pointer to local Bundler config
         And  Bundler cache directory structure is recreated for every project
    Examples:
        |    a Ruby project                                       |
        | Single-project repository with mixed depenendcies types |
        | Multi-project repository with mixed depenendcies types  |

    Scenario: a user tries to prepare a project with malformed path dependency
        When  a user generates environment for "malformed path dependency project"
        Then  Cachi2 reports an error
         And  repository for "malformed path dependency project" remains unchanged

    Rule: cachi2-generated project configuration must coexist with user-generated configuration
        Example: a user pre-configures a Ruby project and then runs cachi2
            When a user modifies project configuraion
             And generates an environment for "this project"
            Then "cachi2-generated" configuration is stored within the project
             And "user-generated" configuration is stored within the project

    Rule: fetched dependencies directory structure must replicate Bundler cache structure
        Example: a user prepares simple Ruby project with just gem dependencies
            When a user generates an environment for "purely gem-dependent project"
            Then dependencies are stored in vendor/cache
             And .gem dependencies are kept as is

        Example: a user prepares simple Ruby project with git dependencies
            When a user generates an environment for "git and gem-dependent project"
            Then dependencies are stored in vendor/cache
             And Git dependnecies directories  names contain revisions

        Example: a user prepares complex Ruby project
            When a user generates an environment for "complex Ruby project"
            Then dependencies are stored in vendor/cache
             And dependencies are not duplicated

*Note*, that actual implementations of scenarios described above might need to combine several
steps or to share some initialization via a fixture or class-level set up for efficiency reasons.
For example fetching from GitHub could be done once and then repository could be copied
locally.

### Necessary repositories

Following the existing practice just one repository is needed. This repository
must contain branches representing test scenarios. I.e. each Ruby project
described below is a branch in the test repository.

Each line below describes a properly defined Ruby project:
 1.  with a mixture of gem, git and path dependencies and a .gemspec file;
 2.  with a mixture of gem, git and path dependencies without a .gemspec file;

These repositories must transitively depend on other gems, their depednencies must
contain common dependencies.

Each line below describes a malformed Ruby project:
 1.  containing a Gemfile.lock with git dependency not pinned to a revision;
 2.  containing a dependency with missing Gemfile.lock;
 3.  containing a dependency on any project from this list;
 4.  containing an Gemfile.lock with all types of dependencies in correct format, but missing Gemfile.
