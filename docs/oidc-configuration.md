# OIDC Configuration Guide

LitFlow uses **OpenID Connect (OIDC)** for authentication, implemented via [Authlib](https://docs.authlib.org/) and pre-wired for **[Pocket ID](https://github.com/pocket-id/pocket-id)** — a self-hosted, passkey-first OIDC provider. Any standard-compliant OIDC provider (Keycloak, Authentik, Dex, Auth0, etc.) will also work.

---

## How It Works

```
Browser           LitFlow Web          Pocket ID (OIDC Provider)
  |                    |                        |
  |-- GET /login ----→ |                        |
  |                    |-- redirect to /authorize →|
  |←-- 302 redirect --|                        |
  |                    |                        |
  |-- user logs in --------------------------→ |
  |←-- redirect to /auth/callback w/ code --- |
  |                    |                        |
  |-- GET /auth/callback→                      |
  |              POST /token (exchange code) →  |
  |              ←-- access_token + id_token -- |
  |              store sub, name, email,        |
  |              is_admin in Flask session      |
  |←-- 302 /dashboard--|                        |
```

The callback exchanges the authorization code for tokens, reads the `groups` claim from the `userinfo` endpoint, and stores the result in a server-side Flask session.

---

## Environment Variables

All OIDC settings live in `.env`. Copy `.env.example` and fill in each value.

| Variable | Required | Description |
|---|---|---|
| `OIDC_CLIENT_ID` | ✅ | OAuth2 client ID from your provider |
| `OIDC_CLIENT_SECRET` | ✅ | OAuth2 client secret from your provider |
| `OIDC_DISCOVERY_URL` | ✅ | Full URL to `/.well-known/openid-configuration` |
| `OIDC_REDIRECT_URI` | ✅ | Full callback URL (must match what's registered in the provider) |
| `OIDC_ADMIN_GROUP` | ❌ | Group name that grants admin access (default: `admin`) |
| `SECRET_KEY` | ✅ | A long random string used to sign Flask sessions |

### Example `.env` (Pocket ID running locally)

```env
OIDC_CLIENT_ID=litflow-local
OIDC_CLIENT_SECRET=super-secret-value
OIDC_DISCOVERY_URL=https://id.example.com/.well-known/openid-configuration
OIDC_REDIRECT_URI=http://localhost:5000/auth/callback

OIDC_ADMIN_GROUP=admin

SECRET_KEY=replace-with-a-long-random-string
```

> **Never commit `.env` to version control.**
> Only `.env.example` (with empty values) should be committed.

---

## Step-by-Step: Pocket ID Setup

Pocket ID is the default provider assumed by this project. Follow these steps to create an application in Pocket ID and connect it to LitFlow.

### 1. Install Pocket ID

Follow the [Pocket ID self-hosting guide](https://pocket-id.app/docs/getting-started/setup). It runs as a single Docker container.

### 2. Create an OIDC Application

1. Open Pocket ID → **Applications** → **New Application**
2. Fill in:
   - **Name**: `LitFlow`
   - **Redirect URIs**: `http://your-domain:5000/auth/callback`
     - Use `http://localhost:5000/auth/callback` for local development
     - Use your real domain in production (e.g., `https://litflow.example.com/auth/callback`)
3. Save and note down the generated **Client ID** and **Client Secret**

### 3. Get the Discovery URL

Pocket ID exposes its OIDC discovery document at:

```
https://<your-pocket-id-domain>/.well-known/openid-configuration
```

Example:

```
https://id.example.com/.well-known/openid-configuration
```

You can verify it works by opening that URL in a browser — it should return a JSON object with all endpoint URLs.

### 4. Create a Group for Admins

1. In Pocket ID → **Groups** → **New Group**
2. Name it `admin` (or whatever you set `OIDC_ADMIN_GROUP` to)
3. Add users who should have admin access to this group

Pocket ID includes group membership in the `groups` array of the userinfo response automatically — no extra configuration needed.

### 5. Populate `.env`

```env
OIDC_CLIENT_ID=<client-id-from-pocket-id>
OIDC_CLIENT_SECRET=<client-secret-from-pocket-id>
OIDC_DISCOVERY_URL=https://id.example.com/.well-known/openid-configuration
OIDC_REDIRECT_URI=http://localhost:5000/auth/callback
OIDC_ADMIN_GROUP=admin
SECRET_KEY=<generate with: python -c "import secrets; print(secrets.token_hex(32))">
```

### 6. Start LitFlow

```bash
docker compose up --build
```

Navigate to `http://localhost:5000` — you will be redirected to Pocket ID to log in. After login you are sent back to the dashboard.

---

## Step-by-Step: Other OIDC Providers

### Keycloak

| Setting | Value |
|---|---|
| `OIDC_CLIENT_ID` | Your client ID in Keycloak |
| `OIDC_CLIENT_SECRET` | Client secret (Credentials tab) |
| `OIDC_DISCOVERY_URL` | `https://<keycloak>/realms/<realm>/.well-known/openid-configuration` |
| `OIDC_REDIRECT_URI` | `https://litflow.example.com/auth/callback` |

For admin group detection, add a **Group Membership** mapper to the client that places groups in the `groups` claim of the userinfo response. Then set `OIDC_ADMIN_GROUP` to the exact group name (e.g., `/litflow-admins`).

### Authentik

| Setting | Value |
|---|---|
| `OIDC_CLIENT_ID` | Client ID from Authentik provider |
| `OIDC_CLIENT_SECRET` | Client secret from Authentik provider |
| `OIDC_DISCOVERY_URL` | `https://<authentik>/application/o/<slug>/.well-known/openid-configuration` |
| `OIDC_REDIRECT_URI` | `https://litflow.example.com/auth/callback` |

Enable the **`groups` scope** in your Authentik OAuth2/OIDC provider to expose group membership in the token claims.

### Auth0

| Setting | Value |
|---|---|
| `OIDC_CLIENT_ID` | Application Client ID |
| `OIDC_CLIENT_SECRET` | Application Client Secret |
| `OIDC_DISCOVERY_URL` | `https://<tenant>.auth0.com/.well-known/openid-configuration` |
| `OIDC_REDIRECT_URI` | `https://litflow.example.com/auth/callback` |

Groups are not a native Auth0 concept. Use an **Action** or **Rule** to inject a `groups` array into the user's ID token:

```js
// Auth0 Action (Post Login trigger)
exports.onExecutePostLogin = async (event, api) => {
  const roles = event.authorization?.roles || [];
  api.idToken.setCustomClaim('groups', roles);
};
```

Set `OIDC_ADMIN_GROUP` to the matching role name.

---

## Session Data

After a successful login, the following data is stored in the encrypted Flask session cookie:

| Key | Source | Description |
|---|---|---|
| `session['user_id']` | `sub` claim | Unique user identifier (never changes) |
| `session['user_name']` | `name` or `preferred_username` | Display name shown in the navbar |
| `session['user_email']` | `email` claim | User's email address |
| `session['is_admin']` | `groups` claim | `True` if `OIDC_ADMIN_GROUP` is in the groups list |

The session is signed with `SECRET_KEY` and stored in the browser cookie. No server-side session store is used.

---

## Route Protection

Two decorators defined in `web/auth.py` enforce access:

```python
@login_required   # redirects to /login if not authenticated
@admin_required   # returns 403 if not an admin (also redirects if unauthenticated)
```

| Route pattern | Protection |
|---|---|
| `/login`, `/auth/callback` | Public |
| `/dashboard`, `/upload`, `/jobs/*` | `@login_required` |
| `/admin/*` | `@admin_required` |

---

## Auth Flow — Code Reference

The full implementation is in `web/auth.py`.

### OAuth client registration

```python
oauth.register(
    name="pocket_id",
    client_id=os.environ["OIDC_CLIENT_ID"],
    client_secret=os.environ["OIDC_CLIENT_SECRET"],
    server_metadata_url=os.environ["OIDC_DISCOVERY_URL"],  # auto-fetches endpoints
    client_kwargs={"scope": "openid profile email"},
)
```

Authlib automatically fetches the provider's endpoints (authorization, token, userinfo, JWKS) from the discovery URL — no manual endpoint configuration is needed.

### Login redirect

```python
@auth_bp.route("/login")
def login():
    redirect_uri = os.environ["OIDC_REDIRECT_URI"]
    return oauth.pocket_id.authorize_redirect(redirect_uri)
```

### Callback and session setup

```python
@auth_bp.route("/auth/callback")
def callback():
    token = oauth.pocket_id.authorize_access_token()
    userinfo = token.get("userinfo") or oauth.pocket_id.userinfo(token=token)

    admin_group = os.environ.get("OIDC_ADMIN_GROUP", "admin")
    groups = userinfo.get("groups", [])

    session["user_id"]    = userinfo["sub"]
    session["user_name"]  = userinfo.get("name") or userinfo.get("preferred_username", "")
    session["user_email"] = userinfo.get("email", "")
    session["is_admin"]   = admin_group in groups

    return redirect(url_for("dashboard.index"))
```

---

## Production Checklist

- [ ] `OIDC_REDIRECT_URI` uses `https://` and your real domain
- [ ] The redirect URI is registered in your OIDC provider exactly as set in `.env`
- [ ] `SECRET_KEY` is a long (≥ 32 bytes), random, unique value — never reused across environments
- [ ] `.env` is excluded from git (check `.gitignore`)
- [ ] Your OIDC provider is reachable from the Docker container running the `web` service
- [ ] The admin group exists in the provider and the correct users are members
- [ ] HTTPS is configured (e.g., via a reverse proxy like Nginx or Caddy) — OIDC requires it in production

---

## Troubleshooting

### `KeyError: 'OIDC_CLIENT_ID'`

The `.env` file is missing or not being loaded. Make sure `.env` exists at the project root and all required keys are present.

### `mismatching_state` / CSRF error on callback

The Flask `SECRET_KEY` changed between the login redirect and the callback (e.g., multiple web container replicas using different keys). Use a single, consistent `SECRET_KEY` in `.env`, or use a shared session store.

### `groups` is empty / `is_admin` is always `False`

Your OIDC provider may not include `groups` in the userinfo response by default. Check your provider's documentation on how to add groups to the token claims (usually via a scope, mapper, claim rule, or action).

### Redirect URI mismatch

The `OIDC_REDIRECT_URI` in `.env` must **exactly** match what is registered in the OIDC provider — including scheme (`http`/`https`), port, and path. A trailing slash difference will cause an error.

### Discovery URL not reachable from Docker

The `OIDC_DISCOVERY_URL` must be reachable from inside the Docker container running the `web` service. If Pocket ID runs on the same Docker network (e.g., via a reverse proxy), use the container hostname or the shared network alias rather than `localhost`.

Example fix in `docker-compose.yml`:

```yaml
services:
  web:
    networks:
      - default
      - pocket_id_network

networks:
  pocket_id_network:
    external: true
    name: pocket-id_default
```
