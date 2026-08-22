# TLS certificates go here

This directory is mounted read-only into the proxy container at
`/etc/nginx/tls`. It is **empty in the repository on purpose**.

```
docker/nginx/tls/fullchain.pem     certificate + intermediate chain
docker/nginx/tls/privkey.pem       private key
```

Then uncomment the HTTPS `server` block in
[../nginx.conf](../nginx.conf).

## Why no certificate ships

A self-signed certificate committed to a repository is TLS with a
**publicly known private key**. That is worse than no TLS, because it
looks like protection: browsers show a padlock, operators stop asking,
and anyone with the repository can decrypt or impersonate.

So there is nothing here to "just use". Bring a real certificate.

## Nothing in here is ever committed

`.gitignore` excludes every file in this directory except this README, so
a private key cannot be committed by accident. Do not add an exception.

## Where certificates come from

Whatever you already use. Common cases:

- **Let's Encrypt / certbot** — point `VIGILOX_TLS_DIR` at
  `/etc/letsencrypt/live/<domain>/` instead of copying files, so renewals
  are picked up. The proxy needs a reload after each renewal:
  `docker compose exec proxy nginx -s reload`.
- **A corporate CA** — copy the issued certificate and its chain as
  `fullchain.pem`. nginx needs the **full chain**, not just the leaf; a
  leaf-only file works in browsers that happen to have the intermediate
  cached and fails in the ones that do not, which is a confusing bug to
  chase.
- **A load balancer terminating TLS upstream** — leave this empty and
  leave the HTTPS block commented out. Make sure the balancer sets
  `X-Forwarded-Proto: https`, because the application sends HSTS only
  when it believes the request arrived over HTTPS.

## Permissions

The private key should be readable only by the user nginx runs as. The
mount is `:ro`, so the container cannot modify either file.

## HSTS

The application sends `Strict-Transport-Security` **only** when the
request arrived over HTTPS. That is deliberate: an HSTS header served
over plain HTTP would tell browsers to refuse HTTP for the whole domain,
which locks a non-HTTPS deployment out of itself with no way back for the
duration of the max-age.

So HSTS starts working when TLS does, with no extra configuration.
