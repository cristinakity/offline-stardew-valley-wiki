# Repository migration without losing historical releases

Keep the existing GitHub repository and merge the new architecture through an ordinary pull
request. Do not rename, archive/recreate, force-push, filter the history or delete tags/releases.
GitHub issues and release assets belong to the repository, so replacing tracked files in a normal
commit preserves them.

After the local candidate and draft release are both approved, prepare the code-only change on the
feature branch:

```bash
git rm -r src
git rm -- search-index.json
git add content-lock.json
git commit -m "Move generated wiki content to OCI snapshots"
```

Adjust the JSON filename to the actual tracked search artifact if it differs. Review `git status`
before committing. The old mirror remains reachable from every historical tag and commit, while
the new branch stops carrying it forward.

Before merging, confirm that these tags still resolve and that their GitHub release pages retain all
assets:

```bash
git show-ref --tags
git tag --list --sort=version:refname
```

A fresh full clone will still transfer the old objects (roughly 1 GB of Git history). CI uses shallow
checkout, and ordinary users should download release assets instead of cloning the mirror history.
