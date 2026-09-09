# Owner-operated release policy

On 2026-09-09 the repository owner requested removal of mandatory additional
reviewers. Pull requests remain required, with zero required approvals and no
last-push approval requirement. Existing automated review findings still require
technical assessment; this policy does not certify their fixes.

Main retains strict CI Gate, Security Gate and Docs Gate checks bound to GitHub
Actions, admin enforcement, conversation resolution, no force pushes and no
deletions. Production retains protected-branch restrictions and no admin bypass.
Its manual reviewer rule is removed. RAILWAY_TOKEN remains environment-scoped.

The release validator accepts this explicitly configured owner-operated policy
and still supports the stronger independent-review policy when configured. It
does not relax exact-main/source identity, complete required job/step evidence,
security scans, runtime acceptance or credential containment.

Deployment stays a separate manual action after exact-main gates pass. This policy
does not enable Railway workflows, apply staged Railway changes or enable trading.
