# Contributing

Thanks for your interest in contributing!

## Getting started

1. Fork the repo
2. Create a feature branch: `git checkout -b feat/your-feature`
3. Commit using [Conventional Commits](https://www.conventionalcommits.org): `feat:`, `fix:`, `chore:`, `docs:`, etc.
4. Open a pull request against `master`, this repository's default branch

## Guidelines

- Keep PRs focused — one logical change per PR
- No commented-out code or leftover debug statements
- Update documentation if behaviour changes
- Secrets must never be committed — TruffleHog scans every PR

## Maintenance validation

Run `python -m unittest discover -s tests -v` for the offline bot-merge policy
checks. They use synthetic PR metadata and mocked GitHub CLI responses; they
never merge a real PR or run the QR generators. The policy requires a successful
required `Build Check / Build` result and leaves repositories without it for
manual review. The two documented Bandit annotations cover only the reviewed
subprocess import and invocation: commands have a fixed allowlist, resolve the
CLI to an absolute path, and never use a shell or execute pull-request code.

`Pull Request Labeler` is the single automatic label workflow and reads
`.github/labels.yml`. Action updates must retain reviewed versions and SHA pins.

## Reporting bugs

Use the [bug report](.github/ISSUE_TEMPLATE/bug_report.md) issue template.
