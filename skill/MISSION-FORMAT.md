# MISSION.md Format

`MISSION.md` lives at `learners/<your-id>/MISSION.md`, inside this learner's own
directory. It captures the _reason_ the user is learning this topic. Every
teaching decision (what to teach next, which resources to surface, which
exercises to design) should trace back to this document.

## Template

```md
# Mission: {Topic}

## Why
{1-3 sentences. The concrete real-world goal the user is chasing. What changes
in their life or work when they have this skill? Avoid abstract framings like
"to understand X"; push for the underlying outcome.}

## Success looks like
- {A specific, observable thing the user will be able to do}
- {Another specific thing}
- {…}

## Horizon
{When must the user still know this? A date to work back from (2026-12-15), a
duration (18 months), or `indefinitely`. One line.}

## Constraints
- {Time, budget, prior commitments, learning preferences, anything that bounds
  the approach}

## Out of scope
- {Adjacent topics the user explicitly does not want to chase right now,
  protecting the zone of proximal development}
```

## Rules

- **One mission per workspace.** If the user wants to learn two unrelated
  things, that is two workspaces.
- **Concrete over abstract.** "Run a half marathon by October" beats "get
  fitter." "Ship a Rust CLI to my team" beats "learn Rust."
- **Push back on vagueness.** If the user cannot articulate why, interview them
  before writing anything. A bad mission is worse than no mission.
- **The horizon is a retention question, not a deadline.** "When is the exam"
  and "when must you still know this" are different, and the second is the one
  that sets review timing. A course taken for a term whose material matters for
  a career has a horizon of years, not weeks. Ask for the second; the first is
  usually what the user says first.

- **Leave the horizon out rather than guess it.** The scheduler reads it, and an
  invented horizon moves every review the user gets. An absent Horizon section
  means the platform keeps its own default, which is the honest state until the
  user has answered.

- **Revise when reality shifts.** Missions change. When the user's goal moves,
  update this file: don't leave a stale mission steering future sessions.
- **Keep it short.** If `MISSION.md` runs past a screen, it has stopped being a
  compass and started being a plan.
