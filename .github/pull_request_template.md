# Maintainers will complete the following section

- [ ] Commit messages are descriptive enough
- [ ] Code coverage from testing does not decrease and new code is covered
- [ ] Docs updated (if applicable)
- [ ] Docs links in the code are still valid (if docs were updated)

**Note:** if the contribution is external (not from an organization member), the CI
pipeline will not run automatically. After verifying that the CI is safe to run:

- [approve GitHub Actions workflows][approve-gh-actions] by clicking a button
- approve the Red Hat Trusted App Pipeline container build by commenting `/ok-to-test`
  (as is the [standard for Pipelines as Code][pac-running-pipeline])

[approve-gh-actions]: https://docs.github.com/en/actions/managing-workflow-runs/approving-workflow-runs-from-public-forks
[pac-running-pipeline]: https://pipelinesascode.com/docs/guide/running/#running-the-pipelinerun
