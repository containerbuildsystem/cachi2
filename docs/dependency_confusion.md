# Problem Statement

Recent research has shown novel
[ways](https://medium.com/@alex.birsan/dependency-confusion-4a5d60fec610)
to inject malicious content into applications. The question has been raised as to whether or not
using Cachito makes this issue worse. This document is an analysis of each package manager
supported by Cachito to address the security concern named *dependency confusion*.

# Dependency Confusion

To paraphrase the meaning of
*[dependency confusion](https://medium.com/@alex.birsan/dependency-confusion-4a5d60fec610)*:
a package manager is tricked into installing a dependency from an official, public, repository when
it should’ve installed it from a custom, often private, repository. For example, a company may host
its own internal npm registry which hosts internal-only packages. Then, someone on the Internet
uploads a package of the same name to the official npm repository. When the application is
installed, the package manager chooses the dependency package from the public repository instead
of the internal one.

## Potential Impact

What happens when Cachito is tricked into downloading a malicious version of one of your
dependencies? To Cachito itself, nothing. Cachito never executes your code, or the code of any of
your dependencies. What about your build?

You are likely using Cachito through OSBS. Cachito will serve the malicious dependency to the OSBS
build, where you will subsequently use it to build your application container. The malicious
behaviour may or may not manifest at build time. In the best case scenario, the build will fail.
In the worst case scenario, you will end up shipping malicious code to customers.

## Dependency Confusion vs Cachito

Before delving into the specifics of each supported package manager, let us make a general statement
about Cachito’s stance towards dependency confusion.

Cachito aims to match the behaviour of your package manager as closely as possible. Generally
speaking, Cachito is as vulnerable to dependency confusion as your package manager, not more, not
less. However, all the supported package managers provide means to protect yourself by following
best practices. For example, you can remove all known attack vectors by simply verifying the
checksums of your dependencies.

Cachito enforces *some* of these best practices. Typically, each package manager provides a lockfile
or other mechanism for pinning dependency versions. Cachito requires this. Verifying checksums is
usually up to you.

Additionally, due to the caching nature of Cachito, you should never be affected by dependency
confusion during a *rebuild*. If you build the same revision of your repository, or a different
revision which uses the same versions of dependencies, Cachito will use the dependencies that it has
already downloaded. Dependency confusion should only be a concern when building for the first time
or when changing the version of a dependency.

# Package Managers

*Sometimes users may state that Cachito supports a certain programming language. This is not
entirely accurate. Cachito only supports package managers. The ecosystem of a programming language
may provide different package managers, for example, npm and yarn are both available for managing
JavaScript packages.*

## gomod

*TL;DR: commit your go.sum. Be cautious when using Cachito’s dependency replacements.*

Golang modules are defined by their [go.mod](https://golang.org/ref/mod#go-mod-file) files. These
define the name of your module as well as the names and versions of its direct dependencies.
Thanks to golang’s unique system of dependency management, this file is enough to ensure
reproducible builds on its own.

However, due to golang versions being tied to git tags, you are technically at the mercy of
repository maintainers. To prevent surprises, whenever go downloads any dependencies, it
saves their checksums in a [go.sum](https://golang.org/ref/mod#go) file. This file is later used to
verify that the content of all direct and indirect dependencies is what you expect it to be. It’s
important to note that once Cachito downloads a dependency from the Internet, it caches it for
future usage. So even if a repository maintainer changes the git tags, Cachito will not detect this
change. 

As long as you make sure to always commit your go.sum file, your Golang module should be safe from
dependency attacks.

The one caveat is Cachito’s own
[dependency replacements](https://github.com/release-engineering/cachito#feature-support) feature.
This feature allows you to replace dependencies with different versions on the fly. Currently, there
is no way to verify their checksums. Always check that the replacement versions are what you want
when using dependency replacements.

## *[Cachito][cachito-1] also supports the following package managers, but Cachi2 does not (yet).*

> ## pip
>
> *TL;DR: if your package is Cachito compliant, it is most likely safe. If you want to be sure, verify
> checksums.*
>
> Python packages can have various formats, which are specified across multiple PEPs. Pip supports
> most of them. Cachito support for pip, on the other hand, is quite simple. You must define all the
> direct and indirect dependencies of your package in
> [requirements.txt](https://pip.pypa.io/en/stable/user_guide/#requirements-files) style files and
> tell Cachito to process them.
>
> Cachito further restricts what you can put in your requirements.txt files. All of the dependencies
> must be
> [pinned](https://github.com/release-engineering/cachito/blob/master/docs/pip.md#pinning-versions)
> to an exact version. Cachito will refuse to process requirements files that use the --index-url or
> --extra-index-url options, which means private registries are out of the question. These two
> restrictions should eliminate most attack vectors.
>
> To protect yourself even further, use pip’s
> [hash-checking mode](https://pip.pypa.io/en/stable/reference/pip_install/#hash-checking-mode). Note
> that pip does not support hash checking for VCS dependencies, e.g. git. Consider transforming your
> git dependencies to plain https dependencies. For example, if the repository is hosted on github,
> you can use https://github.com/{org_name}/{repo_name}/{commit_id}.tar.gz to get the tarball for a
> specific commit.
>
> ## npm
>
> *TL;DR: do not use unofficial registries. Even if you try to do so via .npmrc, Cachito will ignore
> it.*
>
> Npm packages follow the typical package file + lock file approach. The package file is
> [package.json](https://docs.npmjs.com/cli/v6/configuring-npm/package-json), the lock file is
> [package-lock.json](https://docs.npmjs.com/cli/v6/configuring-npm/package-lock-json) or
> [npm-shrinkwrap.json](https://docs.npmjs.com/cli/v6/configuring-npm/shrinkwrap-json). Cachito
> requires the lock file.
>
> The lock file pins all dependencies to exact versions. For https dependencies, which are impossible
> to pin, Cachito requires the integrity value (a checksum). For dependencies from the npm registry,
> Cachito does not require integrity values, but newer versions of npm will always include them. Check
> if all your dependencies have an integrity value, update your lock file if not.
>
> Do not try to use private registries. If you point npm to a private registry (or any registry other
> than the official one) via [.npmrc](https://docs.npmjs.com/cli/v6/configuring-npm/npmrc), Cachito
> will ignore it and look in the official registry anyway.
>
> ## yarn
>
> *TL;DR: same as npm, but the handling of unofficial registries is slightly less surprising. Still,
> you probably should not use them.*
>
> Yarn packages are identical to npm packages except that they use
> [yarn.lock](https://classic.yarnpkg.com/en/docs/yarn-lock/) as the lock file. Everything that
> applies to npm applies to yarn.
>
> The one difference is the handling of unofficial registries. If you point yarn to an unofficial
> registry via .npmrc or [.yarnrc](https://classic.yarnpkg.com/en/docs/yarnrc), this will be reflected
> in the resolved url in the lock file. Cachito will see that the url does not point to the official
> registry and will treat the dependency as a plain https dependency. If the url is accessible to
> Cachito, it will download the dependency directly without relying on npm/yarn dependency resolution.
> That does not necessarily make using unofficial registries a good idea. If the registry is private,
> your build will either fail or leak internal package names.

[cachito-1]: https://github.com/containerbuildsystem/cachito
