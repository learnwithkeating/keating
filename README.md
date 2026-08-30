# Keating

<p align="center"><strong>AI-assisted learning that keeps the learning yours.</strong></p>

---

Keating is not an AI tutor. Getting a language model to explain something well is a solved
problem and it is not what this is for. Keating is a platform for **learning with** an AI that
is deliberately constrained: you do the retrieving, the generating, the explaining and the
judging, because that is where memory is actually built. The software does the bookkeeping.

The goal is **depth, not speed**. Nothing here is designed to get you through material faster.

![The Keating interface](docs/screenshots/hero.png)

## Why constrain the AI at all

In the largest randomised trial of AI assistance in learning to date — roughly a thousand
Turkish high-school students, four maths practice sessions — those given unrestricted GPT-4
during practice scored **48% better while they had it** and **17% worse than the no-AI control**
on a later closed-book exam. The mechanism was not bad information; the model was right about
half the time and its errors did not predict the decline. The mechanism was answer-fetching.
The same trial ran a guardrailed arm — teacher-grounded hints, answers withheld — which raised
assisted practice performance 127%, eliminated the harm, and **produced no exam gain either**.
([Bastani et al. 2025, *PNAS*](https://www.pnas.org/doi/10.1073/pnas.2422633122))

Both halves matter, and the second is the one usually dropped. Guardrails are protective rather
than productive: they stop the damage, and they do not by themselves teach anyone anything. The
durable gains have to come from the learner's own retrieval and generation. Everything in this
platform that looks like a restriction is doing the first job; everything that looks like work
is doing the second.

The same split between performance-while-assisted and learning-measured-afterwards recurs
across settings. In a semester-long CS1 trial (N = 275), both a guarded hint tutor and
unrestricted ChatGPT raised exercise scores and lowered frustration, and neither raised
conceptual understanding; the authors call unrestricted AI's version of that a comfort trap.
([Bassner et al. 2026](https://www.sciencedirect.com/science/article/pii/S2666920X25001778))
ChatGPT assistance on an essay task improved the essay, produced no knowledge gain and no
transfer advantage, and reduced metacognitive engagement: learners offloaded evaluation and
monitoring to the model — "metacognitive laziness".
([Fan et al. & Gašević 2025](https://doi.org/10.1111/bjet.13544))
And the quality gains AI scaffolding produced vanished when the scaffolding was withdrawn
(N = 1,625), with explicit self-monitoring checklists sustaining them only partially — which is
why this platform's own success criterion is whether work survives the AI being taken away.
([Darvishi et al. 2024](https://doi.org/10.1016/j.compedu.2023.104967))

That evidence base is young — mostly single-site studies, immediate outcomes, fast-moving
models — and it is stated here at the strength it has. It is enough to know what not to build.

Those results are the reason this software exists in the shape it does.

## What the AI does, and what it refuses to do

| It does | It will not |
|---|---|
| Grade a committed attempt against a rubric written alongside the question | Answer a question about material you are studying before you have attempted it |
| Critique a draft **after** you have written it, and show its version as a comparison | Write your glossary entries, summaries, free recalls, or learning records |
| Keep the practice log, compute what is due, and schedule review | Present a streak or a session score as evidence that you learned something |
| Build lessons, quiz items and rubrics from your syllabus and sources | Touch graded coursework, unless an assignment explicitly permits it |
| Ask for your attempt, then respond to what you actually wrote | Tell you that you are doing great. Feedback evaluates the response, never the person |
| Record what you know, when the evidence supports it | Claim you understand something without a graded attempt, an artifact you wrote, or a real-world report to cite |
| Answer a question about the course, the schedule or the app directly and immediately | Apply the elicit-first rule to anything that is not course content |

The refusals are the very product. The friction is applied where the learning happens and
nowhere else: asking for your attempt before telling you which lessons exist would be an
obstacle rather than teaching, so that carve-out is written into the rule itself. And a refusal
is visible — when a guard stops a tool call, the call is marked refused in the transcript you
can read, so the activity log never shows a write that did not happen.

Two failures a chat surface could have quietly are loud here instead. A turn that keeps calling
tools without ever answering is stopped after twelve rounds and reported as that, rather than
the last tool's output coming back dressed as a reply. And a turn where the model spent its
whole budget reasoning and produced no prose is an error naming that cause, rather than a
successful response that renders as an empty bubble — which, to the person who asked, is
indistinguishable from being ignored.

## The evidence underneath

Every design rule traces back to our
[`Scientific Charter`](docs/learning-science-foundations.md), which states each finding with its
effect size and the boundaries beyond which it stops holding. What follows is that document at a
summary length. In each item the first part is a claim about how people learn and the sentence
beginning "So" is a claim about this software — the two are different kinds of thing, and the
distinction is worth holding on to for the whole section.

- **Offloading cuts both ways, and the split follows the cut.** Offloading the operations of
  learning diminishes memory for what was offloaded
  ([Risko & Gilbert 2016](https://doi.org/10.1016/j.tics.2016.07.002)); offloading
  already-processed information onto a store the learner *trusts* measurably frees capacity for
  the next thing, and that benefit disappears when the store is believed unreliable.
  ([Storm & Stone 2015](https://doi.org/10.1177/0956797614559285))
  So retrieval, generation, explanation, evaluation and monitoring stay with you, and schedules,
  records, sources and canonical references go to the software — which then has to be explicit
  about what it will and will not remember, and let you read all of it.
- **Retrieval beats review.** Practicing recall outperforms restudying the same material for the
  same time: *g* = 0.50 against restudy across 61 studies
  ([Rowland 2014](https://doi.org/10.1037/a0037559)), and *g* = 0.499 across 222 studies and
  48,478 students in real classrooms ([Yang et al. 2021](https://doi.org/10.1037/bul0000309)).
  Four independent meta-analyses support the effect; they test different comparisons and do not
  report one number between them.
  So every quiz item requires a typed answer before it will show you anything.
- **The ranking of study methods flips with time.** Rereading beat testing 83% to 71% five
  minutes after study, and lost 40% to 61% a week later.
  ([Roediger & Karpicke 2006](https://doi.org/10.1111/j.1467-9280.2006.01693.x))
  So the measure the platform treats as real is delayed, unassisted recall, and session accuracy
  is shown as what it is rather than as progress.
- **Spacing beat massing in 259 of 271 direct comparisons at equal total study time**, and the
  useful gap scales with how long you need to keep the material — roughly 10–30% of the retention
  interval at week-to-month horizons, with the asymmetry that spacing too little costs far more
  than spacing too much.
  ([Cepeda et al. 2006](https://augmentingcognition.com/assets/Cepeda2006.pdf);
  [Cepeda et al. 2008](https://files.eric.ed.gov/fulltext/ED505660.pdf))
  Separately: one correct recall is not learning. Dropping items from testing after a single
  correct answer took one-week retention from about 80% to 36%.
  ([Karpicke & Roediger 2008](https://doi.org/10.1126/science.1152408))
  So there are two loops, tomorrow's and a delayed one; nothing is finished after one success;
  the delayed gap is derived from your own retention horizon rather than from a constant; and a
  missed session reschedules forward instead of stacking.
- **You cannot feel your own learning.** Predictions of later recall are near-uncorrelated with
  actual recall ([Karpicke & Roediger 2008](https://doi.org/10.1126/science.1152408)) and drive
  study decisions anyway — when judgments were experimentally dissociated from actual recall,
  restudy choices followed the illusion
  ([Metcalfe & Finn 2008](https://doi.org/10.3758/PBR.15.1.174)) — and a judgment made with the
  answer already in view is inflated.
  ([Koriat & Bjork 2005](https://bjorklab.psych.ucla.edu/wp-content/uploads/sites/13/2016/07/Koriat_RBjork_2005.pdf))
  Delaying the judgment until after a retrieval attempt makes it far more accurate — an accuracy
  advantage of *g* = 0.93 across 112 effect sizes.
  ([Rhodes & Tauber 2011](https://doi.org/10.1037/a0021705))
  So Keating asks how sure you are **before** it reveals anything, and shows you the gap between
  what you predicted and what happened.
- **Generating beats reading** at *d* = 0.40 across 445 effect sizes.
  ([Bertsch et al. 2007](https://doi.org/10.3758/BF03193441))
  Two boundaries travel with that number. The paradigms are mostly words and sentences, so
  extending it to a whole glossary entry or summary rests on the wider generative-strategies
  literature rather than on the effect size itself; and generating one feature can cost memory
  for the ones around it.
  So you draft first and the AI critiques after, never the reverse — and the critique is not
  decoration, it is the other half of the mechanism.
- **Feedback is high-leverage and wildly uneven.** About *d* = 0.48 overall, near 0.99 for
  high-information feedback that names the task, the process and the self-regulation, and
  collapsing toward zero for praise and comments about the person. About a third of the effects
  in the classic synthesis were *negative*.
  ([Wisniewski et al. 2020](https://doi.org/10.3389/fpsyg.2019.03087); Kluger & DeNisi 1996)
  So every grade comes back in the same four parts, and praise and criticism of the person are
  excluded in both directions rather than left to the model's judgement.
- **Attempting a question before you study it helps** — even when the attempt is certain to
  fail, provided the answer follows. The benefit is specific to what was asked: *g* = 0.66 for
  the pretested points, *g* = 0.01 for everything else in the same material.
  ([King-Shepard et al. 2025](https://doi.org/10.1007/s10648-025-10075-7))
  So lessons open with attempt-first questions aimed at the points that section actually
  teaches, and a wrong answer there is treated as preparation rather than as a gap.
- **Interleaving helps where the difficulty is telling neighbours apart, and reverses where it
  is not.** Overall *g* = 0.42, ranging from 0.67 for visually confusable categories and 0.34
  for maths down to null for expository text and to −0.39 — favouring blocked practice — for
  unrelated material. ([Brunmair & Richter 2019](https://doi.org/10.1037/bul0000209))
  So practice mixes across a unit's neighbouring concepts, not across arbitrary content.
- **Free access to help gets abused, and help pitched for a novice harms someone further on.**
  24% of students gamed a tutoring system at least once and 11% did it often; frequent gamers
  averaged 44% on the post-test against 68% for non-gamers matched on prior knowledge.
  ([Baker et al. 2004](http://pact.cs.cmu.edu/pubs/Baker,%20Corbett,%20Koedinger%20Wagner_2004.pdf))
  Meanwhile high assistance helps low-prior-knowledge learners at *d* = 0.51 and *hurts*
  high-prior-knowledge learners at *d* = −0.43
  ([Tetzlaff et al. 2025](https://doi.org/10.1016/j.learninstruc.2025.102064)), and fading help
  on a fixed schedule shows no meta-analytic advantage over never fading
  ([Belland et al. 2017](https://doi.org/10.3102/0034654316670999)); fading driven by each
  learner's demonstrated understanding beat both fixed fading and unsupported problem solving,
  especially on delayed transfer, though on a small number of experiments.
  ([Salden et al. 2010](https://doi.org/10.1007/s11251-009-9107-8))
  So help arrives one rung at a time, up a rung after a failure and down after a success, and
  the bottom rung is followed by something you have to generate.
- **The friction has to be cognitive.** Disfluent fonts and degraded presentation produce no
  learning benefit while deflating confidence and inflating study time; the original effects
  failed direct replication. ([Xie et al. 2018](https://doi.org/10.1007/s10648-018-9442-x))
  What does help is signalling how the material is organised (retention *g* = 0.53;
  [Schneider et al. 2018](https://doi.org/10.1016/j.edurev.2017.11.001)) and leaving out
  interesting-but-irrelevant content, whose effect is small and negative — *g* = −0.33
  ([Sundararajan & Adesope 2020](https://doi.org/10.1007/s10648-020-09522-4)) and *g* = −0.16 in
  a later multi-level MASEM ([2025](https://doi.org/10.1007/s10648-025-10099-z)) — which at zero
  upside makes omission the easy call.
  So lessons are lean and plainly signposted, and every difficulty the platform adds is a
  retrieval, a delay or a piece of generation — never a harder interface.

### What none of this shows

No study shows that Keating improves anyone's learning, and none is claimed here. Nothing in
this repository compares a Keating learner against a control. The AI-assistance literature
cannot supply the claim second-hand either: the most-cited meta-analysis reporting that a
chatbot improves learning was
[retracted in April 2026](https://www.nature.com/articles/s41599-026-07310-z), and the surviving
ones measure immediate post-intervention performance in mostly short interventions, not delayed
retention and not transfer. No meta-analytic evidence currently speaks to durable learning under
AI assistance at all.

What the evidence does support is narrower and worth stating exactly: the mechanisms this
platform is assembled from — retrieval practice, spacing, withheld answers, generation before
critique, feedback that names a criterion — have support of their own, and the design follows
those findings rather than a hunch. That is a claim about the mechanisms and about the design.
It is not a claim about the result, and no sentence in this document should be read as making
one. For scale, the honest prize for excellent tutoring-style interaction is about 0.3–0.8 SD —
human tutoring at *d* ≈ 0.79 in synthesis
([VanLehn 2011](https://doi.org/10.1080/00461520.2011.611369)), field RCTs of real tutoring
programmes at 0.29–0.37 SD ([Nickow et al. 2024](https://doi.org/10.3102/00028312231208687)).
Bloom's famous two sigma came from two dissertations that combined tutoring with mastery
learning on narrow experimenter-made tests over about three weeks, and is not a benchmark anyone
should be quoting. Keating has measured nothing against that range.

That gap is not an omission in the write-up. It is the state of the field, and it is the reason
this platform instruments delayed unassisted recall at all: the measurement is an instrument
pointed at a question nobody has answered, not a result.

## How it works

### Attempts are gated, graded, and recorded

No answer is ever one click away. You commit a response and a confidence rating first.

The gate is not merely in the interface. The copy of a lesson your browser receives has every
answer and every rubric emptied out of it; the server keeps them in the course package and reads
them back only when it grades a committed attempt. There is no view-source route to the answer
because the answer was never sent.

![A quiz item before the attempt](docs/screenshots/quiz-gated.png)

The grade comes back as four fixed parts, never a compliment: the criterion for mastery, how
this attempt relates to it **citing your own words**, one strategy to try next, and a question
to ask yourself. That shape is not a request made in the prompt and hoped for: the grading call
sends the schema down with it, so a verdict either arrives in those four parts or the model
server never produced one, and a reply that still fails to parse is an error naming itself
rather than a guess. Every attempt lands in an append-only practice log.

![The same item, graded](docs/screenshots/quiz-answered.png)

That screenshot is a real attempt, graded live. The answer given was accurate as far as it went
and the response says so, then names exactly what was missing (the comparison is matched for
total time) and why the omission matters (without it, the effect could be dismissed as extra
exposure rather than a benefit of retrieval). Partially correct is reported as partially
correct.

### Your record is evidence, not vibes

![The practice page](docs/screenshots/practice.png)

Each square is one attempt: filled for correct, half for partial, hollow for wrong, grey for a
skip. Fill state carries the meaning, so the display works without colour. The calibration table
compares what you predicted against what happened, and high-confidence errors are flagged
because they are the most valuable thing in the system to re-test.

### The two review loops

Material you answered correctly today comes back tomorrow, once. An item is due when its last
attempt fell on an earlier local calendar day and either its latest verdict was a miss or every
correct answer it has ever had landed on the day it was first seen — learned and answered in one
sitting, never verified across a night. A correct answer on a later day retires it from the
daily loop; the delayed loop takes it from there, and re-testing exactly those items is what
that loop is for.

The delayed check is weekly, and its gap comes from your own answer to "when must you still know
this?" `MISSION.md` carries a horizon — a date, a duration, or indefinitely — and the first
delayed gap is 10% of it, the low end of Cepeda's band because later checks space out from
there, clamped to between three days and a month. Both clamps are arithmetic rather than
opinions about learning: the lower one is the one-night consolidation rule, the upper one is the
point past which feedback stops being useful. The vocabulary the heading accepts is deliberately
small, and anything else is left unparsed rather than guessed at, because a horizon read wrongly
moves every review you get. A mission that states none keeps the platform's own constant.
Silence is not an instruction.

Both loops cap the session — eight items in the daily one, ten in the weekly — and anything past
the cap simply stays eligible. Reviews reschedule forward and never collapse into one sitting,
and no backlog is ever put in front of you.

### The measure that counts

The weekly check is the one surface where the teaching agent is put away: the chat composer is
gone for its duration, and each attempt records that no assistance was offered rather than
having it inferred afterwards. That flag is stored on the event on purpose. A policy can change,
and a comparison whose history could be quietly restated later would not be a measurement.

That is what makes the assistance gap mean anything: the difference between how you do with the
agent beside you and how you do without it, computed only over items you have answered both
ways. The restriction is the whole point — comparing weekly accuracy against every lesson
attempt would measure item difficulty and report it as assistance. Attempts recorded before the
platform tracked availability are left out rather than assumed, because a gap computed over
guesses is exactly the vanity number this is meant to replace.

One limit travels with it. The charter asks that a platform's outcome measures not be authored
by the same pipeline that taught, and these items are: the model that writes the lesson writes
the check. The gap is a within-learner comparison of the same items under two conditions, which
is what it can honestly be, and not an independent measure of learning.

A positive gap means performance falls when the agent is not offered, which is the direction
Bastani found. The platform reports the number for you and nobody else. It does not claim to
have made anyone's gap small, and it has published no distribution of them.

### You write; the AI critiques

![The compose surface](docs/screenshots/compose.png)

Free recall and glossary entries are drafted from memory, then diffed against the AI's version:
what you had, what you missed, what is subtly off. Free recall is logged as a retrieval event,
so it feeds scheduling like any other attempt.

## Course packages

A course is stored once and can be handed to anyone. Learner state lives under `learners/`,
one directory per person, and never travels with it — copy the course directory without
`learners/` and what you hand over is the course package alone:

```
why-you-forget/
  course.json          manifest: title, units, and their order
  lessons/*.html       numbered lessons, each declaring the unit it belongs to
  assets/              shared stylesheet
  materials/           source material the course is taught from
  RESOURCES.md         curated, annotated sources
  learners/<id>/       one learner's own record — mission, notes, glossary,
                       learning records, practice log. Never shared, never
                       compared, never read from another learner's session.
```

`materials/` is the one directory with a format constraint. The model opens text and images
with its own tools and it does not read documents, so attaching a PDF to a chat message is
refused by name rather than accepted and quietly ignored. Convert it and put the text in the
package, where it can actually be read.

`<id>` is the account's user id, which the server assigns and a request can never choose. The
first account created on an instance is assigned the id `default`, which is also the id an
installation that predates accounts already keeps its record under — so adding accounts to an
existing workspace moves nothing on disk and the record stays exactly where it was.

[`examples/why-you-forget/`](examples/why-you-forget/) is a complete five-lesson course on the
memory research this platform is built on. Copy it into your workspace and you have something
real to try in about a minute.

### What a course page may load

Every page the app serves carries a Content-Security-Policy, and course-authored pages —
lessons, the daily review, the weekly review — get the strictest one their job allows. Two
consequences bind whoever writes a lesson, the AI teacher included:

- **Scripts must come from `/static/`.** `script-src 'self'` admits no inline `<script>`,
  no `onclick=` attribute, and no `eval`. Lesson interactivity goes through
  `/static/quiz.js`, which is what the authored quiz blocks already use. A
  `<script type="application/json">` data block is not executable and is unaffected.
- **Remote assets must come from the course package.** `img-src 'self'` and
  `media-src 'self'` mean a figure or an audio clip lives in the course directory, not on
  someone else's server. A webfont the course ships in `./assets/` is served from the
  course package too, and `font-src 'self'` admits it. Stylesheets may `@import` Google
  Fonts, as `assets/lesson.css` does — that one third-party origin is named in the policy
  — but any other remote font or stylesheet host is blocked.

A lesson that reaches past either line fails silently in the browser rather than loudly in
the server log, so it is worth knowing before you write one.

## Running it

Keating needs a model backend and a directory to keep your courses in. It runs as a container
or straight from source.

The default backend is [Ollama](https://ollama.com) on this machine, which is where the
teaching model runs — nothing leaves your computer and there is nothing to pay for. Install it,
then pull the model the platform defaults to:

```sh
ollama pull qwen3:8b
```

Settings offers two models, `qwen3:8b` and `qwen3:14b`, and both the teaching and the grading
model default to the smaller one. Pull whichever you select: choosing a model the server does
not have gets a 502 that says exactly that and names the `ollama pull` to run.

Ollama's own default context is smaller than this platform's prompt, so Keating asks for the
window it needs on every request. There is nothing to configure. Left alone, the shortfall would
not announce itself — every conversation would be truncated mid-instruction and the teaching
would quietly degrade with nothing in any log to say so.

> **On your own machine, publish to `127.0.0.1` as shown below.** To serve it to other people,
> put a reverse proxy in front of it that terminates TLS: the session cookie carries `Secure`,
> so plain HTTP on a LAN address does not work rather than working insecurely. Tell uvicorn the
> proxy's address with `FORWARDED_ALLOW_IPS`, or the app and the browser disagree about the
> scheme and every save is refused — it says so when that happens.
> [Deploying on a server](docs/deploying.md) has the proxy config, backups and upgrades.

Registration is invite-only and there is no open signup: an instance holds people's practice
records and shares out one machine's model server, and neither is something a stranger should be
able to join by finding the URL. The first account is created from the command line, by whoever
holds the workspace — see [Accounts](#accounts).

### With Docker

```sh
docker build -t keating .

mkdir -p ~/keating-courses
cp -r examples/why-you-forget ~/keating-courses/

docker run -d --name keating \
  -p 127.0.0.1:8000:8000 \
  -v ~/keating-courses:/workspace \
  -e KEATING_MODEL_BASE_URL=http://host.docker.internal:11434 \
  --user "$(id -u):$(id -g)" \
  keating
```

Create the first account, then open <http://127.0.0.1:8000>:

```sh
docker exec -it keating python main.py bootstrap --username <your-name>
```

- `-p 127.0.0.1:8000:8000` binds the published port to the loopback interface, which is what
  you want when the instance is only for you. Serving it to others means publishing to a proxy
  that terminates TLS instead; over plain HTTP on a LAN address the session cookie's `Secure`
  attribute means nobody can sign in.
- `-v ~/keating-courses:/workspace` is where courses, all learner state, and this
  installation's own state (`.keating/`: accounts, sessions, enrollments, the session signing
  key, the usage log the monthly cap reads, and the settings a new account inherits) live.
  Everything the app writes goes here, so the container stays disposable and your work does
  not — including the accounts, which is why replacing the container does not sign everyone
  out.
- `--user "$(id -u):$(id -g)"` makes files in the volume belong to you rather than to the
  container's user. The image runs unprivileged either way.

Leave `--user` out against a volume that belongs to somebody else, and the app cannot use
`.keating/` inside it — it can neither create the directory nor read what an earlier, correctly
run container left there. The container still serves, so you can read the reason in
`docker logs`, but every sign-in and every subcommand is refused. Startup, the `bootstrap`
subcommand and the login route all say the same thing, naming `read` or `write` for whichever
the filesystem refused:

```
keating: cannot write /workspace/.keating: Permission denied — the platform keeps this
installation's accounts, sessions and settings there. On a container this is usually a mounted
volume the app's user does not own: run the container as the volume's owner — the README's
--user "$(id -u):$(id -g)" — or give that user write access to the directory.
```

Restart with `--user` matching the volume's owner, or `chown` the volume to the user the
container runs as. Nothing needs to be deleted, and no state is lost.

A container reaches an Ollama running on the host at `host.docker.internal`, not at
`localhost` — inside the container, `localhost` is the container. Docker Desktop resolves that
name on its own; Docker on Linux does not, so add
`--add-host=host.docker.internal:host-gateway` to the `docker run` above, and make sure Ollama
is listening on more than loopback (`OLLAMA_HOST=0.0.0.0 ollama serve`) or the container's
connection is refused by a server that is running perfectly well.

A local Ollama needs no token, so on a default install there is no secret here to protect. Point
the instance at a backend that does check `KEATING_MODEL_TOKEN` and there is one: put the
configuration in a file and use `--env-file` instead of `-e`, which keeps the token out of your
shell history and out of `docker inspect`.

```sh
echo "KEATING_MODEL_BASE_URL=http://host.docker.internal:11434" > keating.env
chmod 600 keating.env
docker run -d --name keating -p 127.0.0.1:8000:8000 \
  -v ~/keating-courses:/workspace --env-file keating.env \
  --user "$(id -u):$(id -g)" keating
```

That file holds this instance's configuration and nothing else. A `.env` written for running
from source also carries `KEATING_WORKSPACE_ROOT`, which names a path on the host — inside the
container that path does not exist, so every course looks missing and nothing can be saved.
Startup says so when it happens:

```
keating: KEATING_WORKSPACE_ROOT is set to /home/you/courses, which does not exist — every
course will look missing and nothing will be saved. Check the path, and in a container check
that it names a path inside the container rather than on the host.
```

If you would rather reuse one env file for both, override the root back to the volume:

```sh
docker run -d --name keating -p 127.0.0.1:8000:8000 \
  -v ~/keating-courses:/workspace --env-file .env \
  -e KEATING_WORKSPACE_ROOT=/workspace \
  --user "$(id -u):$(id -g)" keating
```

Nothing an operator configures is baked into the image: `.env` and `.env.*` are excluded from
the build context, so configuration is supplied at run time only.

### From source

Requires [`uv`](https://docs.astral.sh/uv/).

```sh
uv sync

mkdir -p ~/keating-courses
cp -r examples/why-you-forget ~/keating-courses/

uv run python main.py bootstrap --username <your-name>
uv run uvicorn main:app --host 127.0.0.1 --port 8000
```

A local Ollama on its default port needs no configuration at all: it is what the platform
assumes when nothing is set, which is what makes a fresh checkout runnable with nothing in the
block above but `uv`, a course and a password. Two cases do need something. Point
`KEATING_MODEL_BASE_URL` at another machine to use a model server there, and set
`KEATING_MODEL_TOKEN` if that backend checks tokens. Either belongs in a `.env` beside the
checkout, which is gitignored and read at startup, so restarts pick it up automatically.

Courses live in `~/keating-courses` by default. Point `KEATING_WORKSPACE_ROOT` anywhere else.
The default deliberately sits outside this repository: a workspace holds your practice log,
chat history and learning records, and none of that belongs in the platform's source tree.

## Accounts

Keating has local accounts: a username, a password hashed with argon2id, and a signed,
HttpOnly session cookie the server can revoke. Registration is invite-only.

The first account is created from the command line rather than through a web form, because
creating it is what claims the `default` user id — and on a workspace that predates accounts,
that id already names a populated record. Making it an operator act means the person who
inherits that record is the person holding the workspace, not the first HTTP visitor.

```sh
uv run python main.py bootstrap --username <name>   # or: docker exec -it keating python ...
```

The password is read from the terminal, or from one line of stdin when piped. There is
deliberately no `--password` flag: a password in argv leaks into `ps`, `docker inspect` and
your shell history file. The minimum length is 12 characters and there are no composition
rules.

Everything else is a subcommand of the same file. Every one of them takes effect on a running
instance immediately — the account store on disk is what the server answers from, and these
commands and the server take the same lock over it — so `disable` during an incident is a
disable, not a note to restart later:

| Command | What it does |
| --- | --- |
| `invite [--expires-days N]` | print a single-use registration code |
| `invites` / `revoke-invite <n>` | list or withdraw outstanding codes |
| `accounts` | usernames, ids, and whether an account is disabled or locked |
| `disable <name>` / `enable <name>` | block an account and end its sessions, or restore it |
| `set-password <name>` | reset a password out of band |
| `revoke-sessions [--username X \| --all]` | end live sessions |
| `enroll --username X --course Y [--role learner\|author]` | join an account to a course |
| `set-role --username X --course Y --role learner\|author` | change an existing enrollment's role |
| `unenroll --username X --course Y` | remove an enrollment, leaving the record on disk |
| `enrollments [--course Y] [--username X]` | who is in which course, with what role |

**Password reset is out of band, by design.** There is no SMTP anywhere in this app, no email
verification and no self-service reset flow: on a personal instance shared with a few people
an operator running `set-password` is the whole mechanism, and it needs no infrastructure to
go wrong.

Five failed sign-ins lock an account for fifteen minutes, the correct password included.
Unknown username, wrong password, locked and disabled all answer identically, so the account
list of an invite-only instance stays private; `accounts` is where an operator sees the truth.

Sessions last seven days and are absolute — no sliding window. They are revocable server-side:
signing out deletes the record, so a copied cookie stops working immediately rather than
merely disappearing from the browser that agreed to forget it. `revoke-sessions` and `disable`
do the same from outside the app, on the next request the stolen cookie makes.

The lockout is per account, and `/api/login` is public, so anyone who can reach the instance
and knows a username can lock that account for fifteen minutes by guessing wrong five times.
That is the accepted cost of counting per account: on a loopback instance every request comes
from `127.0.0.1`, and behind a proxy every request comes from the proxy, so a per-IP limit has
little to tell apart either way. `enable <name>`
clears a lock at once.

### Courses are shared, and enrollment is what opens one

A course package is one directory, shared by everyone enrolled in it, and every learner's own
record sits under `learners/<id>/` inside it. Enrollment is the record that joins an account to
a course with a role, and it is kept in `.keating/enrollments.json` rather than in the course —
a package has to stay portable, and one carrying this instance's user ids would either mean
nothing on another machine or silently grant access on it.

There are two roles, and they are a ladder rather than alternatives:

| | reads the package | writes their own `learners/<id>/` | writes the package |
| --- | --- | --- | --- |
| `learner` | yes | yes | no |
| `author` | yes | yes | yes |

An **author** is a learner who may also change the shared package — add and edit lessons,
`RESOURCES.md`, reference documents, uploaded material, and the course's name. That is the
whole difference: no route reads back more for an author than it does for a learner, and no
route reads anyone else's record for either of them. What an author writes into the package is
still a page that runs in a learner's browser, which is the caveat below.
Being an instance admin confers no course role at all; an admin who wants to author a course
enrolls herself, which is one command and a deliberate act.

**No enrollment record means no access**, and the course answers `404` — the same answer as a
course that is not there, so the list of courses on the instance is not something an account
can enumerate by trying slugs. Creating a course through the app enrolls its creator as its
author. A workspace that predates enrollment is adopted once, at the first start or the first
`bootstrap`: the `default` account becomes an author of every course present, and every other
account with a directory in a course becomes a learner of it. A package copied into the
workspace by hand afterwards has no enrollment, so startup names it and prints the `enroll`
command that opens it.

`unenroll` removes access and touches nothing on disk: the learner's directory stays exactly
where it is. Removing someone from a course is not deleting their record.

### What an admin can and cannot do

An admin manages **accounts**, not **records**. There is no API and no page through which any
account — admin included — can read another learner's practice log, mission, glossary, notes,
learning records or chat history, and nothing an account does in the app reaches another's
record. Two operator subcommands do reach one: `export` and `forget`, which act on a named
account and are covered below. They grant no reach the person holding the volume did not
already have. There is no roster, no aggregate and no per-learner drill-down. An author is not an
instructor: authoring is permission to write the shared package, never permission to read
anyone's record.

With one caveat worth knowing before you hand out the author role. A lesson is a real web page
and its `assets/` may hold real scripts — that is how a quiz or a simulator works — and those
run in the browser of whoever opens the lesson, inside their signed-in session. An author who
wrote a hostile one could have it read that learner's own state and carry it off the page.
Nothing in the API lets an author read another learner's record; a page they authored,
running in that learner's browser, is a different route to the same place. Give the author
role to people you would trust with the content, and see [SECURITY.md](SECURITY.md).

`enrollments` is the one listing an admin gets, and it is metadata about access: who is in
which course, with what role, since when. Nothing in it changes when anyone studies — that is
the line. If the answer to a question would change because a learner practised, it is a record,
and it is out of reach.

That absence is a product decision, not a missing feature. The charter's
[P25](docs/learning-science-foundations.md) makes it one: every mechanism in this platform
reads the practice log — the scheduler selects from it, the mastery criterion reads it, the
calibration loop is computed from it — and a learner who believes the log is watched has an
incentive to attempt only what they can already do, to prefer the give-up path over a visible
wrong answer, and to inflate their confidence ratings. The degradation is silent: the log still
fills, the pages still render, and every inference drawn from them is quietly wrong.

The charter is careful about what kind of rule that is, and so is this. No study cited anywhere
in this project measured surveillance and found it harmful to learning. P25 is a design
constraint derived from the validity conditions the rest of the charter establishes — the record
has to be honest for anything downstream of it to mean anything — and it is written down because
a multi-learner build invites the opposite by reflex.

### Sharing an instance

One instance talks to one model server, so everyone signed in shares the same machine's compute.
Set a per-account monthly allowance in tokens:

```sh
-e KEATING_MONTHLY_TOKEN_CAP=2000000
```

Unset means no limit, which is the right default when you are the only account. Usage is
recorded per account in `.keating/usage.jsonl` and the allowance resets on the first of the
month. An account that reaches it gets a 429 naming what it used; nobody else is affected.

Against a local model the cap costs nothing to exceed: what it divides is a queue and some
memory, not a bill. It is a fairness measure between accounts. Where you have pointed the
instance at a backend that bills for usage, set a spend limit there as well — it does a
different job, since the cap here divides the budget fairly and the backend's caps it
absolutely.

The reader has a separate limit. `/api/reader` fetches a URL of the caller's choosing, so it is
held to twenty fetches a minute per account: the token allowance bounds what an account spends,
and this bounds what the instance does to somebody else's site in its own name.

### Checking a course's items

An item a learner cannot be graded fairly against is worse than a missing one: it produces a
confident verdict with nothing behind it. The platform checks the ones it can check —
duplicate ids, absent or placeholder rubrics, missing answers, unparseable payloads, a missing
concept tag, items in a lesson that never loads the quiz component:

```sh
uv run python main.py check <course>                # from source
docker exec keating python main.py check <course>   # in a container
```

It exits non-zero when there are problems, so it works as a gate. The same check runs whenever
the teaching agent writes a lesson, and its findings come back in the same breath as the write
— where the author can still fix them, rather than where a learner is already wrong. The checker
is covered by the ordinary test suite, and the item shape the authoring prompt documents is
asserted against the real checker, so the example the AI writes from cannot drift away from the
rule it is judged by.

What this does **not** do is judge whether an item is any good. It asks whether an item is
gradeable — a unique id, an answer, a rubric long enough to name the acceptable variants and the
misconceptions. Whether the question was worth asking is a judgement no structural check makes,
and the platform does not claim to make it. The warrant for having the gate at all is that a
third of one ChatGPT-3.5-era study's raw AI-generated hints failed quality checks before a
self-consistency pipeline was put in front of them.
([Pardos & Bhandari 2024](https://doi.org/10.1371/journal.pone.0304013))
That is a reason to check, not a measurement of anything in this repository or of any current
model.

### Checking the teaching itself

Generically instruction-tuned models optimise for helpfulness, and in a learning context
helpfulness means answer-giving. That is the failure this whole platform is built against, so
its required teaching behaviours are written down as assertions and run against real turns —
charter [P23](docs/learning-science-foundations.md), pedagogy as a tested artifact rather than a
hope. Nothing else in the suite would notice a required behaviour going missing from the prompt:
the unit tests would stay green and the platform would go on teaching worse.

[`tests/rubric/test_teaching_behaviour.py`](tests/rubric/test_teaching_behaviour.py) is five
checks against the real `/api/chat` route, with the real system prompt and the shipped example
course: that a question about course material is met with a request for your own attempt *and*
does not contain the answer, that pressing for the answer still does not get the answer, that it
will not write a learner's glossary entry, that it evaluates a draft without evaluating the
person, and that a logistics question is answered directly instead of turned into an exercise.

It drives a real model through six real turns, so it is minutes of local inference and its
result moves from run to run. That is why it is opt-in — a non-deterministic check standing
between someone and a merge teaches them to ignore it:

```sh
KEATING_RUBRIC_EVAL=1 uv run pytest tests/rubric -v
```

Ollama has to be running at `KEATING_MODEL_BASE_URL` with `qwen3:8b` pulled: the suite builds a
throwaway workspace, so it runs against the platform's default model rather than whatever your
own account has selected. Without a reachable server it does not skip — it runs, and fails with
the 502 that says the model server is unreachable.

Run it when the system prompt changes and when the teaching policy changes. That is the lever
the evidence identifies. Changing which model the platform teaches on is the same kind of event,
for the reason below.

#### What this suite found

The rule the whole platform turns on is elicit before explain — asked about course content, the
AI's first move is to ask for your attempt. Carrying the full prompt bundle, it failed four
times out of four on a 14-billion-parameter model. The failure was not refusal. The model
summarised the policy accurately and then answered the question anyway. The rule was diluted
by sitting as one paragraph inside roughly eight thousand tokens of instructions.

Restated in the imperative, in final position, with a carve-out so logistics questions are still
answered directly, it holds: in four runs against the smaller 8B model, not one reproduced that
failure, where the full bundle had produced it every time on the 14B. That is why the chat call
sends three system messages rather than one — the pedagogy package, then your current practice
state, then that one rule last, where least of it is lost on the way — and it is why the bundle
is kept short, since every paragraph in it competes with every other for the same attention.

Keep the claim the size of its evidence. The restated rule was never re-run on the 14B, so what
was measured is a change to a prompt and not a comparison of two models: it is a lesson about
where a rule sits, not about parameter count. Nor is the suite green every time. Of those four
runs, two were clean and two had a single failing check — a different one each time: once the
refusal to write a glossary entry, once the refusal to hand over the answer under pressure.
Neither was the lecture-instead-of-eliciting failure that started this.

#### What a passing run does and does not mean

A pass means five turns against the real route did not do five specific wrong things. It is not
evidence that anyone learned anything, that the teaching is good, or that the next turn will
behave the same way.

The checks are structural on purpose — a judge model would add a second source of
non-determinism to grade the first — and structural checks are coarse. The elicitation check
matches a question mark or one of eight verbs. The answer check looks for four particular
figures from lesson one, so a reply that hands over the finding in prose without the numbers
passes. The person-level check is a fixed list of phrases, so praise it has never seen passes. A
single failure is a transcript to read, not a proven regression. And the suite covers the chat
turn only: the four-part feedback grammar as the grading path applies it has no behavioural
check of its own.

### Your record, and getting rid of it

A practice log records what someone did not know and when they did not know it. That is more
revealing than most of what an application stores about a person, so the position is explicit
rather than implied:

**Nothing is deleted on a schedule.** The record is the product — spacing, calibration and what
is due all read the whole history — so an instance keeps it until someone says otherwise. There
is no retention timer to configure and no quiet expiry.

**Anything held about one account can leave in one file.** It is their own files at their own
paths, plus the usage lines that say what they spent, and no password hash:

```sh
# from source
uv run python main.py export <username>

# in a container
docker exec keating python main.py export <username> \
  --out /workspace/<username>-keating-export.zip
```

In a container the destination has to be on the mounted volume. The container's own working
directory is inside the image and is not writable by the user the app runs as, so an export
without `--out` stops on a permission error rather than writing anywhere; `/workspace` is both
writable and the directory the host is already looking at.

**And it can be removed.** Their record in every course, their enrollments, their sessions,
their usage lines and the account itself. It asks for the username back first, and it cannot be
undone:

```sh
docker exec -it keating python main.py forget <username>
```

Deletion is deletion, not a flag: a record marked deleted is still a record of what someone did
not know. The usage log is rewritten without their lines rather than appended to, because a
line saying who was forgotten is still a line about them.

Both are operator commands. Whoever runs them already holds the volume the records sit on, so
they grant no reach that person did not have — but they only ever touch the one account named.

The chat transcript is not the record. What the platform teaches from is the mission, the notes,
the glossary, the learning records and the practice log; a conversation is working material, and
one the server cannot replay is discarded rather than guessed at. Nothing that decides what you
are taught next lives in it.

### Choosing models

The teaching model and the grading model are set separately in Settings, in the app. Both default
to `qwen3:8b`, and `qwen3:14b` is the other option. Grading is a bounded rubric check against a
written answer, so it is where a smaller model gives up least.

Both models run on your own machine, so what a larger one costs is time and memory. What it buys
is not what you might expect: this platform's own rubric found the one rule everything turns on
holding on the smaller model once the rule was restated and moved to the end of the prompt, and
failing on the larger one before that.
See [Checking the teaching itself](#checking-the-teaching-itself).

Each account chooses its own. One learner switching models changes nothing for anyone else, and
the choice takes effect on the next request without a restart. An account's own choice is kept
with the account, in `.keating/accounts.json`. `.keating/settings.json` is what an account that
has never saved a choice inherits — the preference a single-user installation made before
accounts existed — and startup brings such a file in from a source checkout, keeping the original
as `settings.json.migrated` in case you pointed it at the wrong workspace. If a settings file
already exists in both places, nothing moves and the workspace copy is the one in use: startup
says so on stdout, and editing the one in the checkout will have no effect until you delete one
of them.

## Accessibility

Every surface a learner can reach is scanned with [axe-core](https://github.com/dequelabs/axe-core),
driven through the real UI with Playwright rather than against rendered fragments, so each state
is the one a learner actually sees. Twenty scans cover the app shell (empty, with a course
selected, and with a lesson open), a lesson both inside the reading pane's iframe and at its own
URL, the practice, compose and settings views, the generated review and weekly pages in both
their empty and populated states, a quiz item mid-attempt with submit armed, the mobile
layout at 375px where the tab bar replaces the rails, and the four surfaces a person meets
before they are signed in — the login view, the login error state, invite redemption, and the
instruction shown when no account exists yet.

The rulesets are WCAG 2.0 A and AA, 2.1 A and AA, and 2.2 AA. axe's "best-practice" rules are
deliberately excluded: they are opinions worth having, but they are not WCAG failures, and a red
check should mean a standard was broken. There is no blanket rule disabling and the per-surface
exclusion list is currently empty — every violation the first scan found was fixed in the markup
or the CSS.

The suite runs on every pull request. To run it yourself:

```sh
uv sync
uv run playwright install chromium
uv run pytest tests/a11y
```

It starts the app on a free port against a throwaway workspace seeded from
`examples/why-you-forget`, so it never touches your courses, and it needs no model server —
nothing in it submits an attempt for grading. Raw axe output for each surface is written to
`.a11y-report/`.

### What a passing check does and does not mean

**Automated testing detects roughly a third of WCAG failures.** A green check means no
*detectable* violations, which is not the same as conformance and is not a claim of ADA
compliance. Whether the focus order makes sense, whether every control can be reached and
operated from the keyboard, whether a screen reader announces something a person can act on,
and whether the alternative text is actually *useful* rather than merely present — none of that
is machine-checkable, and all of it still needs a person.

What the scan does do is catch the failures that are unambiguous, and it earns its place: the
first run against this codebase found three real ones. The reading pane's preview iframes had no
accessible name, so a screen reader announced them as an unlabelled frame with no way to tell
what was in it. Several form controls had no programmatic label, leaving them announced by
nothing but their position. And there was no skip link, so every keyboard user re-traversed the
entire course sidebar to reach the lesson they had just opened. All three are fixed, and the
suite is what keeps them fixed.

## The name

John Keating is the teacher in [Dead Poets Society](https://en.wikipedia.org/wiki/Dead_Poets_Society) who stands on his desk to remember to look
at things another way, and who refuses to hand Todd Anderson a poem, pushing until Todd produces
one himself. That refusal is the whole idea.

## License

MIT. See [LICENSE](LICENSE).
