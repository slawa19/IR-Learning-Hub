<INSTRUCTIONS>
Когда я прошу работать как Оркестратор или в режиме Оркестратора (любые варианты формулировки), прочитай docs/codex-orchestrator-rule.md и работай по нему.

## Release / HACS Rules

HACS determines this repository's released version from GitHub Releases. A pushed
git tag by itself is not enough.

Before publishing a release:

- Keep `custom_components/ir_learning_hub/manifest.json`,
  `custom_components/ir_learning_hub/www/ir-learning-hub-card.js`,
  `CHANGELOG.md`, README release examples, and `docs/INSTALLATION.md` in sync.
- Commit release metadata first, then tag that exact commit as `vX.Y.Z`.
- Verify the tag resolves to the release metadata commit, not an older commit.
- Push the commit and tag.
- Create a GitHub Release named `vX.Y.Z` from the same tag.
- For normal user-facing releases, the GitHub Release must be non-draft and not
  prerelease.
- Verify the latest release through GitHub before telling users HACS can see it.

If any of those pieces disagree, treat the release as incomplete.
</INSTRUCTIONS>
