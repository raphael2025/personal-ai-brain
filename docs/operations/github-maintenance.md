# GitHub Repository Maintenance

This guide records repository settings that must be configured in GitHub's web UI. The connected GitHub integration can manage repository files, issues, and pull requests, but it does not expose write operations for branch rulesets or repository feature settings.

## Recommended rules for `main`

Open **Settings → Rules → Rulesets** and create an active branch ruleset targeting `main`.

Recommended settings:

- Require a pull request before merging.
- Require the following status checks:
  - `test (3.11)`
  - `test (3.12)`
  - `test (3.13)`
  - `Analyze Python` (CodeQL)
- Require conversation resolution before merging.
- Block force pushes.
- Block branch deletion.
- Do not require one approving review yet: the project currently has one primary maintainer, so a mandatory approval could prevent normal maintenance. Add a trusted second maintainer before requiring independent approval.
- Keep an explicit owner bypass only if needed for emergency recovery; document its use.

After creating the ruleset, verify it is active and that a test pull request cannot merge while a required check is failing.

## Community Discussions

If community discussion is desired, enable **Settings → General → Features → Discussions**. Use Discussions for open-ended questions and design conversations; keep reproducible defects and scoped work in Issues.

## Security features

Where available for this public repository, enable:
- Secret scanning and push protection.
- Dependabot security updates.
- Private vulnerability reporting.

These controls complement, but do not replace, code review and CI.

## Maintainer workflow

1. Review incoming issues and label them by scope and priority.
2. Ask contributors to link changes to an issue.
3. Review the diff, tests, permissions, data handling, and dependency changes.
4. Require CI and CodeQL to pass.
5. Merge with squash to keep the history readable.
6. Update the roadmap only when acceptance evidence exists.
7. Never merge untested changes into the default branch merely to increase activity.
