<!--
  PR Template
  -----------
  Fill out every section. PRs without a clear summary, test plan, and
  audit notes do not pass review.
-->

## Summary

<!-- One paragraph: what changed and why. Link the issue this addresses. -->

Closes #

## Type of change

- [ ] Bug fix (non-breaking change which fixes an issue)
- [ ] New feature (non-breaking change which adds functionality)
- [ ] Breaking change (fix or feature that would change existing behavior)
- [ ] Refactor (no functional change; rules/coding-standards.md compliance)
- [ ] Documentation only
- [ ] Audit-finding closure (cite the finding ID)

## Test plan

<!--
  How was this verified? List the specific tests run.
  - Existing tests: `pytest` — pass count?
  - New tests: what mutations would they catch?
  - Manual verification: what did you exercise that automated tests don't?
-->

- [ ] All existing tests pass.
- [ ] New tests added for new behavior.
- [ ] Mutation survival check: I considered what mutations would NOT be caught.
- [ ] Manual verification of any UI / CLI / MCP-tool behavior changes.

## Audit notes

<!--
  Which audit lenses ran on this change? What did they find?
  See CONTRIBUTING.md for the audit cycle.
-->

- Engineering review (code-reviewer / architect / refactorer / test-engineer): findings + closures
- Genius review (feynman / curie / popper / dijkstra / others): findings + closures
- Outstanding deferred findings (with follow-up issue links):

## Coding-standards compliance

<!-- See rules/coding-standards.md (or the linked zetetic standard). -->

- [ ] §2.2 Layer dependency direction preserved (no inward layer imports outward).
- [ ] §3.2 No `any` (or `as any`, or untyped dicts at boundaries) in production code.
- [ ] §4.1 No file > 500 lines (test files exempt).
- [ ] §4.2 No function > 50 lines (dispatch tables exempt).
- [ ] §4.4 No function with > 4 parameters.
- [ ] §7 Local reasoning preserved (no clever constructs that defeat single-function comprehension).
- [ ] §8 Every numeric constant ≥ 3 significant digits has a `// source:` annotation.
- [ ] §9 No dead code, no TODOs without issue references.

## Breaking changes

<!--
  If this is breaking, document:
  - what was the old behavior?
  - what is the new behavior?
  - how do consumers migrate?
-->

## Screenshots / logs

<!-- For UI changes or non-trivial output changes. -->

## Reviewer checklist

- [ ] CHANGELOG.md updated under the appropriate section.
- [ ] Documentation updated (README / SKILL.md / docs/).
- [ ] No secrets / credentials / PII in the diff.
- [ ] CI passes on the latest commit.
