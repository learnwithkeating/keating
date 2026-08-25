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

- **Authentication and session handling.** Reaching any route that touches learner state
  without a valid session; forging or replaying a session cookie; a session that survives
  logout, `revoke-sessions`, or the account being disabled; registering without an invite;
  redeeming one invite twice; anything that lets a caller choose their own user id.
- **Cross-learner visibility, in either direction.** Any way one account reads another's
  practice log, mission, notes, glossary, learning records or chat history — including as an
  admin, and including a listing or aggregate that merely names who else exists. The charter's
  P25 makes this a prohibition rather than a permission check, so a hole here is a serious bug
  even when it looks like a UI detail.

### What does not

**Keating expects to be bound to `127.0.0.1`.** It has accounts, and sign-in is what stops
a second person on the same machine from reading your record — but it is not network
hardening, and it does not make the app safe to publish. The documented `docker run` publishes
to `127.0.0.1:8000` and the from-source instructions pass `--host 127.0.0.1` for exactly this
reason. The session cookie carries `Secure`, which browsers honour on loopback but not on a
LAN address over plain HTTP, so an exposed instance does not work rather than working
insecurely.

So "binding to `0.0.0.0` exposes it to the LAN" is not a vulnerability — exposing the app to a
network is a deployment mistake. **Reaching learner state without signing in is a different
matter and is always in scope**, on any interface, including loopback.

The loopback assumption is still part of the model, so a bug that breaks it is in scope: if you
find a way for a page loaded in the learner's browser from another origin to drive the API
(CSRF, a permissive CORS response, DNS rebinding), we want to hear about it. Note that cookies
are not port-scoped, so another service on `127.0.0.1` is same-site to Keating and
`SameSite=Lax` alone does not stop it — the app checks `Origin` and `Sec-Fetch-Site` on every
state-changing request for this reason, and a way past that check is a real finding.

The login lockout is per account and `/api/login` is public, so anyone who can reach the
instance and knows a username can lock that account for fifteen minutes. That is known and
accepted, not a finding: every request on a loopback-bound instance arrives from `127.0.0.1`,
which leaves nothing for a per-IP counter to distinguish, and `enable <name>` clears a lock at
once. A way to lock an account *without* knowing a username, or a lockout that `enable` cannot
clear, would be a finding.

Also out of scope: denial of service against your own instance, missing security headers with
no demonstrated impact, results from an automated scanner with no working exploit, and
vulnerabilities in Anthropic's API rather than in this code.
