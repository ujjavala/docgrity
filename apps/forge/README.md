# Docgrity for Confluence (Forge app)

Thin Forge UI for the Docgrity backend. All analysis runs in the Python backend;
this app only renders findings and triggers scans via **Forge Remote**
(`invokeRemote` → backend verifies the Forge Invocation Token).

## Marketplace compliance checklist

- **Naming**: listed as "Docgrity for Confluence" (product name after the app name).
- **Auth**: Forge Invocation Token (FIT) only — no basic auth anywhere.
- **Performance**: no blocking work at render; findings load async with a spinner.
- **Privacy policy + documentation**: required before listing (Phase 7).
- Forge apps keep 100% of revenue up to USD 1M lifetime per vendor.

## One-time setup (requires your Atlassian account — do this yourself)

```sh
npm install -g @forge/cli@latest   # already installed (13.5.0)
forge login                        # email + API token from id.atlassian.com
cd apps/forge
npm install
forge register                     # writes the real app id into manifest.yml
```

## Deploy & install

```sh
forge deploy                       # development environment by default
forge install                      # choose Confluence + your dev site
```

Then update `remotes[0].baseUrl` in [manifest.yml](manifest.yml) to the public
URL of the Docgrity backend (use an https tunnel such as `ngrok` for local dev),
and set `FORGE_APP_ID` in the backend environment so FIT verification checks the
correct audience.
