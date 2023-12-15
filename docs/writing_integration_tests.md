# Writing integration tests

## Developing the test source

If you are trying to write a cachi2 integration test, and wish to run cachi2
against a local source repo, assuming that

- the image "localhost/cachi2:latest" exists and is a valid cachi2 container
  image
- your test source is in "~/temp/cachi2-test", **and it is a valid git repo**
  (i.e. a valid ".git" directory is present)

executing e.g.

```bash
podman run --rm -ti -v "~/temp/cachi2-test:~/temp/cachi2-test:z" -w "~/temp/cachi2-test" localhost/cachi2:latest
```

*should* give you a way to properly process the test source with cachi2

## Running pytest locally

Once you have working test sources, you'll need to commit and push them
somewhere that pytest can clone them from.

We *strongly* recommend making a fork, specific to your test, from one of the
repos found under the [cachito test repos][] GitHub org (note that there
are *many* repos there, covering all of the package managers which cachi2 and
Cachito support) [^1].

Once you have a fork, push to a new branch named after your scenario - now
pytest will have a proper commit hash in a repo to which you have complete
access (once your test is complete and passing, you can simply open a PR against
the repo in the [cachito-testing][] org).

At this point, you should be able to test locally.

## Running the test suite

It's a good idea to run the whole cachi2 integration test suite, just to make
sure everything still works properly. The command for this, *from inside the
cachi2 repo* is `tox -e integration`. You can also provide
`CACHI2_IMAGE=localhost/cachi2:latest` if you already have a current cachi2
container. e.g. `CACHI2_IMAGE=localhost/cachi2:latest tox -e integration` - this
will save a lot of time, as otherwise the image will be rebuilt from scratch.

[^1]: If you **really** can't find an existing repo which is related to your test
scenario, ping a maintainer and explain your situation.

[cachito-testing]: https://github.com/orgs/cachito-testing
[cachito test repos]: https://github.com/orgs/cachito-testing/repositories?type%3Dsource
