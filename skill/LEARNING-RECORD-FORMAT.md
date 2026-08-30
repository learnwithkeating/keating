# Learning Record Format

Learning records live in `learners/<your-id>/learning-records/` as
`0001-slug.md`, `0002-slug.md`. The platform computes the number, the filename
and the directory - never pick one yourself.

They are the teaching equivalent of architectural decision records: they
capture non-obvious lessons, key insights, and stated prior knowledge that
steer future sessions, and they feed the zone of proximal development.

## Format

A title, and 1-3 sentences: what was learned (or what prior knowledge was
established), and why it matters for future sessions. That is the whole format
- a record can be a single paragraph. The value is recording _that_ this is now
known and _why_ it changes what to teach next, not in filling out sections.

## When to write a learning record

1. **The user demonstrated genuine understanding of something non-trivial**:
   not exposure, but evidence they can use the concept correctly. This sets a
   new floor for what to teach next. Evidence must be citable - a graded
   practice event (the practice log), a user-authored artifact, or a real-world
   report. A fluent conversation is not evidence; your impression of one is not
   evidence. Records that assert understanding name their evidence.
2. **The user disclosed prior knowledge**: "I already know X." Record it, and
   the _depth_ claimed, so future sessions don't re-teach it.
3. **A misconception was corrected**: high-value, because these predict future
   stumbling blocks on related topics.
4. **The mission shifted in response to learning**: cross-link to
   [[MISSION.md]] and update it.

### What does _not_ qualify

- Material merely covered. Coverage is not learning; wait for evidence.
- Anything already captured tersely in [[GLOSSARY.md]].
- Session-by-session activity logs. Learning records are not a journal: they
  are decision-grade insights.

## Supersession

When a later record corrects or deepens an earlier one, supersede the old
record rather than deleting it. The history of how understanding evolved is
itself useful signal.
