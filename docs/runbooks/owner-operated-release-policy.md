# Release approval policy

Main requires pull requests, at least one independent approval, dismissal of
stale approvals, and approval after the latest push. It also retains strict CI
Gate, Security Gate and Docs Gate checks bound to GitHub Actions, admin
enforcement, conversation resolution, no force pushes, and no deletions.

Production requires a non-empty reviewer rule that prevents self-review,
protected-branch restrictions, and no admin bypass. RAILWAY_TOKEN remains
environment-scoped.

The release validator enforces these requirements in addition to exact-main/source
identity, complete required job/step evidence, security scans, runtime acceptance,
and credential containment.

Deployment stays a separate manual action after exact-main gates pass. This policy
does not enable Railway workflows, apply staged Railway changes, or enable trading.
