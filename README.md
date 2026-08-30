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

In the largest randomised trial of AI assistance in learning to date, roughly a thousand
students given unrestricted GPT-4 during practice scored **48% better while they had it** and
**17% worse than the no-AI control** on a later closed-book exam. The mechanism was not bad
information; the model was right about half the time and its errors did not predict the decline.
The mechanism was answer-fetching. A guardrailed version, which withheld answers and gave hints,
eliminated the harm entirely.
([Bastani et al. 2025, *PNAS*](https://www.pnas.org/doi/10.1073/pnas.2422633122))

That result is the reason this software exists in the shape it does.

## What the AI does, and what it refuses to do

| It does | It will not |
|---|---|
| Grade a committed attempt against a rubric written alongside the question | Answer a question about material you are studying before you have attempted it |
| Critique a draft **after** you have written it, and show its version as a comparison | Write your glossary entries, summaries, free recalls, or learning records |
| Keep the practice log, compute what is due, and schedule review | Present a streak or a session score as evidence that you learned something |
| Build lessons, quiz items and rubrics from your syllabus and sources | Touch graded coursework, unless an assignment explicitly permits it |
| Ask for your attempt, then respond to what you actually wrote | Tell you that you are doing great. Feedback evaluates the response, never the person |
| Record what you know, when the evidence supports it | Claim you understand something without a graded attempt, an artifact you wrote, or a real-world report to cite |

The refusals are the very product.

## The evidence underneath

Every design rule traces back to our 
[`Scientific Charter`](docs/learning-science-foundations.md):

- **Retrieval beats review.** Practicing recall outperforms restudying the same material for the
  same time at *g* ≈ 0.50, across four independent meta-analyses and 222 classroom studies.
  ([Rowland 2014](https://doi.org/10.1037/a0037559);
  [Yang et al. 2021](https://doi.org/10.1037/bul0000309))
  So every quiz item requires a typed answer before it will show you anything.
- **The ranking of study methods flips with time.** Rereading beat testing 83% to 71% five
  minutes after study, and lost 40% to 61% a week later.
  ([Roediger & Karpicke 2006](https://doi.org/10.1111/j.1467-9280.2006.01693.x))
  So the platform measures delayed, unassisted recall and treats session performance as a
  vanity metric.
- **Spacing won 259 of 271 direct comparisons.**
  ([Cepeda et al. 2006](https://augmentingcognition.com/assets/Cepeda2006.pdf))
  So material you answered correctly today comes back tomorrow, and a night's sleep sits between
  first exposure and first verification.
- **You cannot feel your own learning.** Predictions of later recall are near-uncorrelated with
  actual recall, and they drive study decisions anyway. Judgments made *after* a retrieval
  attempt are dramatically better calibrated (*g* = 0.93).
  ([Rhodes & Tauber 2011](https://doi.org/10.1037/a0021705))
  So Keating asks how sure you are **before** it reveals anything, then shows you the gap.
- **Generating beats reading** at *d* = 0.40.
  ([Bertsch et al. 2007](https://doi.org/10.3758/BF03193441))
  So you draft the definition and the AI critiques it, never the reverse.
- **Interleaving helps for confusable material and reverses for unrelated material**
  (*g* = 0.67 vs *g* = −0.39).
  ([Brunmair & Richter 2019](https://doi.org/10.1037/bul0000209))
  So practice mixes across a unit's neighbouring concepts, not across arbitrary content.

## How it works

### Attempts are gated, graded, and recorded

No answer is ever one click away. You commit a response and a confidence rating first.

![A quiz item before the attempt](docs/screenshots/quiz-gated.png)

The grade comes back as four fixed parts, never a compliment: the criterion for mastery, how
this attempt relates to it **citing your own words**, one strategy to try next, and a question
to ask yourself. Every attempt lands in an append-only practice log.

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

Ollama serves a 4,096-token context by default, which is smaller than this platform's own
prompt. Give it room, or every conversation is silently truncated:

```sh
OLLAMA_CONTEXT_LENGTH=32768 ollama serve
```

> **On your own machine, publish to `127.0.0.1` as shown below.** To serve it to other people,
> put a reverse proxy in front of it that terminates TLS: the session cookie carries `Secure`,
> so plain HTTP on a LAN address does not work rather than working insecurely. Tell uvicorn the
> proxy's address with `FORWARDED_ALLOW_IPS`, or the app and the browser disagree about the
> scheme and every save is refused — it says so when that happens.
> [Deploying on a server](docs/deploying.md) has the proxy config, backups and upgrades.

Registration is invite-only and there is no open signup: an instance holding your API key that
anyone could register on is a billing incident waiting to happen. The first account is created
from the command line, by whoever holds the workspace — see [Accounts](#accounts).

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
  installation's own state (`.keating/`: settings, accounts, sessions, enrollments, the
  session signing key) live. Everything the app writes goes here, so the container stays disposable and your
  work does not — including the accounts, which is why replacing the container does not sign
  everyone out.
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
`localhost` — inside the container, `localhost` is the container. To keep a backend token out
of your shell history and process list, put it in a file and use `--env-file` instead of `-e`:

```sh
echo "KEATING_MODEL_BASE_URL=http://host.docker.internal:11434" > keating.env
chmod 600 keating.env
docker run -d --name keating -p 127.0.0.1:8000:8000 \
  -v ~/keating-courses:/workspace --env-file keating.env \
  --user "$(id -u):$(id -g)" keating
```

That file must hold the key and nothing else. A `.env` written for running from source also
carries `KEATING_WORKSPACE_ROOT`, which names a path on the host — inside the container that
path does not exist, so every course looks missing and nothing can be saved. Startup says so
when it happens:

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

The image never contains a key: `.env` is excluded from the build context, and credentials are
supplied at run time only.

### From source

Requires [`uv`](https://docs.astral.sh/uv/).

```sh
uv sync

mkdir -p ~/keating-courses
cp -r examples/why-you-forget ~/keating-courses/

echo "KEATING_MODEL_BASE_URL=http://localhost:11434" > .env
uv run python main.py bootstrap --username <your-name>
uv run uvicorn main:app --host 127.0.0.1 --port 8000
```

`.env` is gitignored and read at startup, so restarts pick the settings up automatically. A
local Ollama on the default port needs none of this — it is what the platform assumes when
nothing is set. Point `KEATING_MODEL_BASE_URL` at another machine to use one, and set
`KEATING_MODEL_TOKEN` if that backend checks tokens.

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

An admin manages **accounts**, not **records**. There is no API, no page, and no subcommand
through which any account — admin included — can read another learner's practice log, mission,
glossary, notes, learning records or chat history. There is no roster, no aggregate and no
per-learner drill-down. An author is not an instructor: authoring is permission to write the
shared package, never permission to read anyone's record.

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
reads the practice log, and a learner who believes the log is watched has an incentive to
attempt only what they can already do and to inflate their confidence ratings — which corrupts
the calibration loop at its source, silently, while the dashboards keep rendering.

### Sharing an instance

One instance holds one API key, so anyone signed in spends the same budget. Set a per-account
monthly allowance in tokens:

```sh
-e KEATING_MONTHLY_TOKEN_CAP=2000000
```

Unset means no limit, which is the right default when you are the only account. Usage is
recorded per account in `.keating/usage.jsonl` and the allowance resets on the first of the
month. An account that reaches it gets a 429 naming what it used; nobody else is affected.

Against a local model the cap costs nothing to exceed, and is really a fairness measure
between accounts. Where the backend bills for usage, setting a spend limit there is worth doing
too, and does a different job: the cap here divides the budget fairly, the backend's caps it
absolutely.

### Checking the teaching itself

The item check above asks whether an item is gradeable. A separate suite asks whether the
teaching agent still behaves the way the policy says it must — that it elicits before
explaining, that pressing it for an answer gets a hint rather than the answer, that it will not
write a learner's glossary entry, that it evaluates the response and never the person, and that
it answers a logistics question directly instead of turning every request into an exercise.

It drives real turns against a real model, so it costs tokens and is opt-in:

```sh
KEATING_RUBRIC_EVAL=1 uv run pytest tests/rubric -v
```

Run it when the system prompt or the teaching policy changes — that is the lever the evidence
identifies, and the thing that regresses without anything else failing. A model is not
deterministic, so a single failure is a reason to read the printed reply, not proof of a
regression.

### Checking a course's items

An item a learner cannot be graded fairly against is worse than a missing one: it produces a
confident verdict with nothing behind it. The platform checks the ones it can check —
duplicate ids, absent or placeholder rubrics, missing answers, unparseable payloads, items in a
lesson that never loads the quiz component:

```sh
docker exec keating python main.py check <course>
```

It exits non-zero when there are problems, so it works as a gate. The same check runs whenever
the teaching agent writes a lesson, and its findings come back in the same breath as the write
— where the author can still fix them, rather than where a learner is already wrong.

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
docker exec keating python main.py export <username>
```

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

### Choosing models

The teaching model and the grading model are set separately in Settings, in the app. Grading is
a bounded rubric check, so a smaller model there is the main cost lever; teaching is where the
larger model earns its keep.

These are instance-wide: one model choice for the instance, not one per account.

What you choose is saved in the workspace, as `.keating/settings.json` beside your courses, so
it belongs to the workspace rather than to the container or the checkout that wrote it. A
source installation that saved settings before they lived there has its `settings.json` copied
into the workspace on the next start, and the file it came from kept as `settings.json.migrated`
in case you pointed it at the wrong workspace. If a settings file already exists in both places,
nothing moves and the workspace copy is the one in use — startup says so on stdout, and editing
the one in the checkout will have no effect until you delete one of them.

## Accessibility

Every surface a learner can reach is scanned with [axe-core](https://github.com/dequelabs/axe-core),
driven through the real UI with Playwright rather than against rendered fragments, so each state
is the one a learner actually sees. Sixteen scans cover the app shell (empty, with a course
selected, and with a lesson open), a lesson both inside the reading pane's iframe and at its own
URL, the practice, compose and settings views, the generated review and weekly pages in both
their empty and populated states, a quiz item mid-attempt with submit armed, and the mobile
layout at 375px where the tab bar replaces the rails.

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
`examples/why-you-forget`, so it never touches your courses, and it needs no API key — nothing in
it submits an attempt for grading. Raw axe output for each surface is written to `.a11y-report/`.

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
