# Native summary editor authentication, 2026-10-28

Source: genuine P1 security finding https://github.com/cdeust/ai-architect-mcp-codebase/pull/464#discussion_r4395607291 on ec07e940d0aec81640425035660a7f473dc49cd5. A write collaborator can edit another account's PR comment while its original author remains the Bot.

The local RED fixture kept the original native Bot author, supplied a human last editor and forged clean current review flags. The old reader returned success with reviews_complete=true. No native App comment was edited or fabricated during reproduction.

The corrected reader obtains body, author and last-editor attribution together from GitHub `IssueComment` GraphQL nodes. It accepts pristine editor=null/lastEditedAt=null comments or edits by the original native Bot account, checking login, type and immutable actor ID. Missing, inconsistent or untrusted attribution fails closed. It selects the latest summary before authentication and also authenticates newer original-Bot comments, so removing a summary marker cannot expose an older clean verdict. Trusted ordinary Bot comments preserve their existing behavior.

Both Pipeline polling and the completion handler use the same API-boundary helper. Every comment page is bound to the requested PR/head; malformed, incomplete or duplicate pagination fails closed. Existing author, repository/head, finding resolution and live eligibility checks remain.

Primary API evidence: https://docs.github.com/en/graphql/reference/issues#issuecomment. GraphQL schema introspection confirmed editor and lastEditedAt. Native summary6456275844 has matching author/editor Bot IDs `BOT_kgDOC98s_g`; pristine native comments on Cortex814 have both edit fields null. Actor IDs require `... on Bot { id }` fragments. GitHub documents that deleting edit content preserves who edited and when: https://docs.github.com/en/communities/moderating-comments-and-conversations/tracking-changes-in-a-comment.

Verification includes the forged-human-editor RED case, genuine pristine/Bot-edited GREEN cases, immutable-ID mismatches, missing/inconsistent attribution, latest-summary marker removal, trusted non-summary messages, both production callers and GraphQL pagination/error/head binding. Codebase's existing regression entry point executes26 tests after the change.

A read-only live run against Codebase464 authenticated its actual Bot edit and returned blocked/review_unresolved with reviews_complete=true for summary6456275844. The genuine P1 finding remained open; that observation does not claim acceptance of the unpublished fix.

Final helper SHA256:

- Runtime: `5e391798ded9ba8b3c0eca06eaed7021b938a4539896317828e7d9457e71bf4e`.
- Reader: `5449540c56c8709fd01cbd9078fbaedf932560298c659c0ac70bde499da03737`.
- Completion handler: `6492f9c318ee5c496305475c6ef00076002a31d6958e1cd980616defdad90e23`.

The canonical receipt records these three scripts and the embedded review job as adaptations with original and delivered hashes. All six Anthropic command/reviewer Markdown files remain verbatim. No bot identity is impersonated and no new merge gate is added.

Cortex: 235 CI unit tests pass, including existing polling/event fixtures and the new adversarial contracts. Windows CLI resolver coverage remains 19 tests and 10 subtests; hosted Windows proof is pending.

Comment transport and edit attribution are separated into a shared module. Runtime, reader and comments modules contain 235, 287 and 166 lines. Six moved function bodies remain byte-identical; the isolated Pipeline loader registers all three trusted modules. The Cortex 300-line craftsmanship check passes without a baseline waiver.
