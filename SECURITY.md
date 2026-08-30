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
- Leaking `KEATING_MODEL_TOKEN`, or any other secret, into a response, a log, a generated page,
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
- **Course authorization.** Reaching a course with no enrollment record in it; writing a shared
  course package — a lesson, an asset, `RESOURCES.md`, uploaded material, the course's name —
  from a session enrolled only as a learner; a role that a caller can name in a query string,
  a body or a cookie; an enrollment that survives the course being archived and is inherited
  by a later course reusing the slug. An authoring role that widens what the API will read
  back is the cross-learner bug above.

**Package content runs in the reader's session, and that is a known limitation.** A lesson is
a page served from the app's own origin, and `assets/` may hold scripts because that is what a
quiz or a simulator is, so `script-src 'self'` lets a package script execute in the browser of
whoever opens the lesson — with their session, and with no CSP directive that can stop the page
navigating somewhere else. An author of a course can therefore reach a learner's own state
through a page that learner opens, which the API refuses to hand over. It is the reason the
author role is described as trusted rather than merely privileged, and it is why the two roles
are the only ones there are. Reports that sharpen this are welcome; a report demonstrating it
as designed is a duplicate of this paragraph.

### What does not

**Keating can be served on a network, behind TLS.** That is a change: it used to expect
loopback, and reaching it over anything else was a deployment mistake rather than a
vulnerability. It has accounts, invite-only registration, per-course roles, and an `Origin`
check on every state-changing request. **A way to reach learner state without signing in, or
to reach another learner's state while signed in, is in scope on any interface.**

Serving it means terminating TLS at a reverse proxy in front of it. The session cookie carries
`Secure`, so an instance published over plain HTTP on a LAN address does not work rather than
working insecurely — that is deliberate and is not a finding. `Strict-Transport-Security` is
sent on HTTPS responses only, because pinning a loopback install's `localhost` to HTTPS in
someone's browser is a hard thing to undo.

Tell the proxy's address to uvicorn with `FORWARDED_ALLOW_IPS`, or the app computes its own
origin as `http` while the browser says `https` and the `Origin` check refuses every write. It
says so when that happens rather than leaving a 403 to be guessed at.

If you find a way for a page loaded in the learner's browser from another origin to drive the
API (CSRF, a permissive CORS response, DNS rebinding), we want to hear about it. Note that cookies
are not port-scoped, so another service on `127.0.0.1` is same-site to Keating and
`SameSite=Lax` alone does not stop it — the app checks `Origin` and `Sec-Fetch-Site` on every
state-changing request for this reason, and a way past that check is a real finding.

The login lockout is per account and `/api/login` is public, so anyone who can reach the
instance and knows a username can lock that account for fifteen minutes. That is known and
accepted, not a finding: behind a proxy every request arrives from the proxy, which leaves a
per-IP counter little to distinguish, and `enable <name>` clears a lock at once. A way to lock an account *without* knowing a username, or a lockout that `enable` cannot
clear, would be a finding.

Also out of scope: denial of service against your own instance, missing security headers with
no demonstrated impact, results from an automated scanner with no working exploit, and
vulnerabilities in the model backend rather than in this code.
