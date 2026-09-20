# Maintenance guide

## Structure

Stack: **Python 3.12+ / standard library**. Main paths: `shardlab/, tests/, scripts/, evidence/`.

The existing layout already separates implementation, tests and research evidence. Keep it stable: moving import roots or frozen paths would add migration risk without improving the public entry points.

- `.github/`: issue forms, PR template, project wordmark and Actions workflows.
- `CONTRIBUTING.md`: contributor setup and relevant local checks.
- `docs/`: explanations and maintenance guidance; historical reports retain their original scope.
- Temporary outputs and environments belong in ignored directories, never in published evidence.

## Automation

Existing project checks: [ci.yml](../.github/workflows/ci.yml). These remain the source of truth for the
actual test and replay commands. Workflow concurrency cancels superseded runs on the
same ref; job timeouts bound hung checks. No inference or training coverage is implied.

[Documentation CI](../.github/workflows/documentation.yml) runs a dependency-free Python
check for local file links in README, contribution/conduct guidance, the PR template and
this page. It also checks whitespace in the changed entry-point documents and `.github/` files,
using a two-commit checkout so historical frozen records are not treated as new files. It does not validate external URLs, heading
anchors, SVG rendering or every historical document. New linked files must be staged
with `git add` before the local check so they are included in `git ls-files`.

```sh
python3 .github/scripts/check_docs.py
```

## Releases

Automatic package publishing is not configured: this repository has no established
package publication contract. Use a reviewed, manually created GitHub Release only when
there is a meaningful version to distribute. Before creating a tag:

1. Run the relevant project checks and documentation checks on the exact commit.
2. Confirm Actions has passed for that same commit; record skipped model/hardware checks.
3. Review the diff for secrets, large generated files and changes to frozen evidence.
4. Confirm code, data and model licensing separately; preserve authorship and attribution.
5. Write release notes covering behavior changes, validation scope and remaining limits.

A future automated release should use explicit version tags, validate the tagged commit
and upload reviewed artifacts. Add package registry credentials and write permissions only
when that publication workflow is deliberately adopted.
