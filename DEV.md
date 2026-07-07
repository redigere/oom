# Developer Guide

## Commit Convention

Every commit MUST have exactly one subject line followed by a signed-off-by trailer.
No body, no multi-line messages.

```
Meaningful change description in 72 chars or fewer

Signed-off-by: Name <email>
```

- Subject line: imperative mood, capitalized, no period at end (e.g., "Add THP defrag tuning to prevent compaction stalls")
- Signed-off-by: one blank line after subject, then `Signed-off-by: Firstname Lastname <email>`
- Name must be at least two words (first and last name), not a nickname or username
- No body paragraphs, no co-authors, no footers other than signoff
