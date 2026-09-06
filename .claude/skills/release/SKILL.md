---
name: release
description: Cut a release of this integration - bump the version in manifest.json, run the validation gates, commit, tag the merged commit, and draft categorised release notes for the GitHub release form. Use when asked to cut or prepare a release, bump the version, prepare X.Y.Z, or tag a release.
---

# Release

Publishing the GitHub release stays manual. This skill takes it as far as a
pushed tag plus a notes draft, then hands over.

`custom_components/bestway/manifest.json` is the only file carrying the
release version. Do not touch the others: `pyproject.toml`'s `0.1.0` is an
unpublished placeholder, `hacs.json`'s `homeassistant` key is a support floor
that moves on its own schedule, and the README badge reads from the GitHub
releases API.

Tags are `vX.Y.Z`, lightweight (`git tag`, never `git tag -a`).

## Never

- Publish the release. No `gh release create`, no `gh release edit`.
- Push a tag without asking first. Once HACS sees a tag it is out.
- Force-push, or delete or move an existing tag.
- Merge the bump PR yourself.

## Work out which stage you are in

Take the target version from the argument, or propose the next patch above
the newest tag if none was given. Then:

```bash
git fetch origin --tags --quiet
git tag --list 'v*' --sort=-v:refname | head -1
git show origin/main:custom_components/bestway/manifest.json | jq -r .version
```

- `origin/main` does not yet have the target version → **stage A**.
- `origin/main` has it and tag `vX.Y.Z` does not exist → **stage B**.
- The tag already exists → stop. Say so, and offer only the notes draft.

## Stage A - bump

Preflight. On any failure, stop and explain which check failed and why:

- The working tree is clean, or its only change is the manifest version
  already edited to the target. Adopt that edit rather than rewriting it.
- The target matches `^[0-9]+\.[0-9]+\.[0-9]+$`. Strip a leading `v` if the
  user typed one; reject anything else, including a stray dot.
- The target sorts strictly above the newest existing tag.
- Neither `refs/tags/vX.Y.Z` nor `origin`'s copy of it exists.

Report version drift when the committed manifest version does not match the
newest tag. It means earlier releases shipped the wrong version to HACS. Say
what the gap is; the bump then closes it going forward.

Then bump and validate:

```bash
uv run pytest -qq --timeout=10 --durations=10 -n auto \
  --cov custom_components.bestway -o console_output_style=count \
  -p no:sugar tests
uv run pre-commit run --all-files
```

Commit, matching whichever convention the branch implies - `Version X.Y.Z`
on `main`, `Prepare for X.Y.Z` on a `prepare-X.Y.Z` branch. If anything else
rides along (a pre-commit autoupdate, a Python retarget), list it in the
commit body.

Push the branch. If it is not `main`, print the PR link and stop there:
the tag has to land on the commit that reaches `main`.

## Stage B - tag and draft notes

Re-check that `origin/main`'s manifest version equals the target before
anything else, then tag that commit and ask before pushing:

```bash
git tag "v$VERSION" origin/main
git push origin "v$VERSION"
```

Draft the notes from GitHub's own generator, which produces the same
"What's Changed" body used by past releases:

```bash
gh api repos/cdpuk/ha-bestway/releases/generate-notes \
  -f tag_name="v$VERSION" -f previous_tag_name="$PREVIOUS_TAG" \
  --jq .body
```

Regroup those lines under `Features:`, `Fixes:`, `Docs:` and `Chores:`.
PRs here carry no labels and no
commit-message prefixes, so the grouping is a judgement call from the
titles. Copy each `* <title> by @<author> in <url>` line through verbatim,
and leave any `## New Contributors` block and the `**Full Changelog**:`
line exactly as generated. Drop nothing: every generated line lands in some
group.

Write the draft to the scratchpad, print it, and hand over the release form:

```
https://github.com/cdpuk/ha-bestway/releases/new?tag=vX.Y.Z
```

The release name is the tag string verbatim.
