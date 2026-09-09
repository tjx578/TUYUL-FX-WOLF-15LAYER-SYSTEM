# Release approval policy

On 2026-09-09 the repository owner requested removal of mandatory additional
reviewers. Pull requests remain required; required approvals and last-push
approval are governed by the current branch protection settings. Existing
automated review findings still require technical assessment; this policy does not
certify their fixes.

Production requires a non-empty reviewer rule that prevents self-review,
protected-branch restrictions, and no admin bypass. RAILWAY_TOKEN remains
environment-scoped.

The release validator enforces these requirements in addition to exact-main/source
identity, complete required job/step evidence, security scans, runtime acceptance,
and credential containment.

Deployment stays a separate manual action after exact-main gates pass. This policy
does not enable Railway workflows, apply staged Railway changes, or enable trading.
