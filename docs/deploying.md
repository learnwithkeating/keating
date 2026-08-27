# Deploying Keating on a server

For running it for yourself on your own machine, the README's `docker run` is the whole story.
This is for serving it to other people.

Three things change: something has to terminate TLS, that something has to be trusted, and the
state on the volume becomes worth backing up.

## Terminate TLS in front of it

Keating does not speak TLS and should not. Put a reverse proxy in front, give it a certificate,
and let it forward plain HTTP to the container on the loopback interface.

The session cookie carries `Secure`, so **an instance published over plain HTTP on a public or
LAN address does not work** — nobody can sign in. That is deliberate: it fails rather than
running insecurely.

### Caddy

Caddy gets a certificate on its own and sets the forwarded headers correctly with no
configuration:

```caddyfile
keating.example.com {
    reverse_proxy 127.0.0.1:8000
}
```

### nginx

nginx needs the headers set by hand. `X-Forwarded-Proto` is the one that matters:

```nginx
server {
    listen 443 ssl;
    server_name keating.example.com;

    ssl_certificate     /etc/letsencrypt/live/keating.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/keating.example.com/privkey.pem;

    client_max_body_size 32m;   # matches the app's upload cap

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host              $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
    }
}
```

## Tell the app which proxy to trust

This is the step that is easy to miss and confusing to debug.

uvicorn ignores forwarded headers from anywhere it has not been told to trust, and it trusts
`127.0.0.1` by default. A proxy in another container is not that. When the headers are ignored,
the app believes it is being served over `http` while the browser says `https`, the `Origin`
check on every state-changing request sees a mismatch, and **every save is refused** — no
sign-in, no chat, no attempts.

Set `FORWARDED_ALLOW_IPS` to the address the proxy connects *from*, as the container sees it:

```sh
-e FORWARDED_ALLOW_IPS=172.17.0.1     # a proxy on the Docker host
-e FORWARDED_ALLOW_IPS=10.0.0.5       # a proxy elsewhere on the network
```

The app says so when this is wrong, rather than leaving a bare 403 to be guessed at:

```
403 cross-site request refused: this app believes it is served over 'http' while the
    browser says 'https'. The host matches, so the scheme is the whole difference — a
    proxy is terminating TLS and this app has not been told to trust its forwarded
    headers. Set FORWARDED_ALLOW_IPS to the proxy's address.
```

Do not set it to `*`. Trusting forwarded headers from anywhere lets a caller claim any client
address.

## Putting it together

```sh
docker run -d --name keating \
  -p 127.0.0.1:8000:8000 \
  -v /srv/keating:/workspace \
  --env-file /etc/keating.env \
  -e KEATING_WORKSPACE_ROOT=/workspace \
  -e FORWARDED_ALLOW_IPS=172.17.0.1 \
  -e KEATING_MONTHLY_TOKEN_CAP=2000000 \
  --user "$(id -u):$(id -g)" \
  --restart unless-stopped \
  keating
```

`/etc/keating.env` holds `ANTHROPIC_API_KEY=sk-ant-...` and nothing else. In particular it must
not hold `KEATING_WORKSPACE_ROOT`: a path from the host machine is meaningless inside the
container, and the app will report an empty workspace.

Then create the first account, which is also the only way one gets created:

```sh
docker exec -it keating python main.py bootstrap --username <your-name>
```

## Back up the volume

Everything worth keeping is in the workspace directory, and none of it is in the image:

| | |
|---|---|
| `<course>/` | the course packages |
| `<course>/learners/<id>/` | each learner's mission, notes, glossary, records, practice log |
| `.keating/accounts.json` | accounts, password hashes, invites |
| `.keating/sessions.json` | live sessions |
| `.keating/session-key` | the session signing key |
| `.keating/usage.jsonl` | per-account model usage |

Copying the directory while the app is running is safe enough for a personal instance: every
file the app writes is written to a temporary file and renamed into place, so a copy catches
either the old file or the new one, never half of one. The practice logs are append-only, so
the worst case is a backup missing the last line.

```sh
tar czf keating-$(date +%F).tar.gz -C /srv keating
```

Restoring is the reverse: stop the container, replace the directory, start it again. Sessions
survive, because the signing key and the session store are both in the backup — so nobody is
signed out by a restore.

## Upgrading

The image holds no state, so an upgrade is a rebuild and a replace:

```sh
docker pull ghcr.io/... || docker build -t keating .
docker rm -f keating
docker run -d ... keating          # the same command as above
```

Learner state, accounts and sessions are on the volume and are untouched. Startup migrates
anything an older layout left behind, and says what it moved.

Take a backup first anyway. The migrations refuse to act on an ambiguous state rather than
guessing, but a backup is cheaper than reading the code to find out what they decided.

## Sharing the budget

One instance holds one API key, so everyone signed in spends the same money.
`KEATING_MONTHLY_TOKEN_CAP` sets a per-account monthly allowance in tokens; unset means no
limit. Usage is recorded per account in `.keating/usage.jsonl` and the allowance resets on the
first of the month.

Setting a spend limit in the Anthropic console is worth doing as well, and does a different
job: the cap here divides the budget between accounts, the console's caps it absolutely.

## What this does not cover

Running more than one worker. The reader's rate limiter counts in process memory, so a second
worker would double the effective limit. Everything else — accounts, sessions, settings, usage
— is on the volume behind a lock and would be correct; the limiter is the one thing that
assumes a single process.
