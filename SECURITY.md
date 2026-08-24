# Security Policy

## Supported versions

Keating is pre-1.0 and there are no releases yet. Only the `main` branch is supported;
fixes land there and nothing older is backported.

## Reporting a vulnerability

Please report privately, through GitHub's private vulnerability reporting:

**<https://github.com/learnwithkeating/keating/security/advisories/new>**

That opens a draft advisory only the maintainers can see. Please do not open a public issue
for anything you believe is exploitable.

Useful reports include the affected file or endpoint, the steps to reproduce, and what an
attacker gets out of it. A proof of concept helps; a scanner's raw output usually does not.

**Response times.** This is a small project maintained in spare time. Expect an
acknowledgement within 7 days and an assessment within 30 days. If you have not heard back
inside 7 days, assume the message was missed and comment on the advisory. Fixes ship when
they are ready; there is no release train to wait for. We will credit you in the advisory
unless you would rather we did not.

## Scope

### What counts

- Path traversal or any other escape from `KEATING_WORKSPACE_ROOT` — one course reading or
  writing another course's files, or anything reaching the host filesystem outside the
  workspace.
- Server-side request forgery in the URL-fetching path, or a bypass of the private-address
  checks that guard it.
- Stored or reflected XSS in lesson, review or weekly pages, including via course content or
  a fetched source document.
- Leaking `ANTHROPIC_API_KEY`, or any other secret, into a response, a log, a generated page,
  or a container image layer.
- Prompt injection in course material or fetched sources that causes the assistant to write
  outside the workspace or exfiltrate learner state. Injection that merely produces bad
  teaching output is a quality bug, not a vulnerability.
- Anything in the published container image: a root runtime, a writable application
  directory, credentials baked into a layer.

### What does not

**Keating ships with no authentication, on purpose, and is meant to be bound to
`127.0.0.1`.** It is single-learner software that reads and writes a local workspace
directory; there are no accounts because there is no second user to distinguish. The
documented `docker run` publishes to `127.0.0.1:8000` and the from-source instructions pass
`--host 127.0.0.1` for exactly this reason.

So "the app has no login page", "any request can read `/api/courses`", or "binding to
`0.0.0.0` exposes it to the LAN" are not vulnerabilities — they are the stated design, and
exposing the app to a network is a deployment mistake. A report that the app can be reached
without credentials **from another host** is a report about how it was deployed.

That boundary is the whole security model, so a bug that breaks it is very much in scope: if
you find a way for a page loaded in the learner's browser from another origin to drive the
API (CSRF, a permissive CORS response, DNS rebinding), that defeats the loopback assumption
and we want to hear about it.

Also out of scope: denial of service against your own instance, missing security headers with
no demonstrated impact, results from an automated scanner with no working exploit, and
vulnerabilities in Anthropic's API rather than in this code.
