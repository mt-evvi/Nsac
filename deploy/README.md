# Same-server rollout

Build and verify from the project root. Deploy an immutable bundle into the inactive loopback slot. The shared HTTPS proxy sends public requests to one slot at a time.

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
npm --prefix web ci
npm --prefix web run build
.venv/bin/python -m pytest -q
```

Copy the `server` and `presets` directories, `web/dist`, and `requirements.lock` into `/opt/nsac/releases/<release>` with root ownership and read access for the systemd dynamic user. Create the release's `.venv` there, install the locked dependencies, write `SPHEREX_RELEASE=<release>` to `release.env`, and point the inactive `/opt/nsac/slots/<port>` symlink at that directory. Set the slot to 8765 or 8766. Install `spherex@.service` in `/etc/systemd/system`, reload systemd, and start the inactive slot.

Verify `/healthz`, `/readyz`, the viewer, and the release checks in the build plan on the inactive loopback port. For public cutover, back up the shared Caddy configuration, add or update the SPHEREx site block using the approved hostname and inactive loopback port, then validate the entire Caddy configuration with `caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile`. Apply it through the host's approved procedure. The configured service has `admin off` and was started with `caddy run` and a Caddyfile. With that setup, supported signal-based reload uses `systemctl kill --kill-whom=main --signal=SIGUSR1 caddy`. Confirm it actually applied in the Caddy log and with HTTP and HTTPS requests.

Preserve the previous slot until an external HTTPS check verifies the certificate, `/readyz`, all five presets and a covered live query. To roll back, restore the previous Caddy route to the previous healthy slot, validate the full configuration, apply the reload and verify the public route again. Stop the superseded slot after verification. Keep the latest two staged releases and their preset versions.
