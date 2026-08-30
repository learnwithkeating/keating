# GLOSSARY.md Format

`GLOSSARY.md` lives at `learners/<your-id>/GLOSSARY.md` and is the canonical
language for this workspace. All explainers, exercises, and learning records
adhere to its terminology.

## Structure

```md
# {Topic} Glossary

{One or two sentence description of the topic this glossary covers.}

## Terms

**Hypertrophy**:
Muscle growth driven by mechanical tension and metabolic stress over repeated
training sessions.
_Avoid_: Bulking, getting big
```

Keep that shape exactly: a `## Terms` heading, then `**Term**:` on its own
line, the definition under it, and an optional `_Avoid_:` line.

## Rules

- **Add a term only when the user understands it.** The glossary records
  compressed knowledge; it is not a dictionary they read to learn.
- **The user drafts every definition first, from memory.** Compressing a
  concept into a tight definition is itself the evidence of understanding, so
  the compressing must be theirs. You critique the draft - what it has, what it
  misses, what it subtly gets wrong - and the entry is finalized in the user's
  own words. An agent-authored definition is a policy violation (see
  TEACHING-POLICY.md), even when the user asks for one.
- **Be opinionated.** Where several words exist for one concept, pick the best
  and list the rest on `_Avoid_:`.
- **Keep definitions tight.** One or two sentences, defining what the term IS,
  not what it does or how to do it.
- **Use the glossary's own terms inside definitions**, so later terms build on
  earlier ones.
- **Group under subheadings** when natural clusters emerge; a flat list is fine.
- **Flag ambiguities explicitly.** Where the wider field uses a term loosely,
  note the resolution in the definition.
- **Revise as understanding deepens.** Update an existing term in place; do not
  leave stale entries or a second entry for the same term.
