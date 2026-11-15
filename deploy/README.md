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

Verify `/healthz`, `/readyz`, the viewer, and the release checks in the build plan on the inactive loopback port. For public cutover, back up the shared Caddy configuration, add or update the SPHEREx site block using the approved hostname and inactive loopback port, then validate the entire Caddy configuration with `caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile`. Apply it through the host's approved procedure. The configured service has `admin off` and was started with `caddy run` and a Caddyfile. Versions with signal-based reload can use `systemctl kill --kill-whom=main --signal=SIGUSR1 caddy`. Confirm it actually applied in the Caddy log and with HTTP and HTTPS requests. Installed Caddy 2.10.2 logged the signal as unsupported. A coordinated restart was required for the SPHEREx vhost. App-only updates can switch the release behind the existing loopback listener without restarting Caddy.

Set `SPHEREX_REFRESH_RELEASES=1` in `release.env` when activating the public slot. The service checks the documented IRSA S3 release and Level 2 planning-period listings at startup when due and every 24 hours thereafter. With the current allowlist, it makes three metadata-only requests with a combined 384 KiB and 20-second cap. It uses the shared IRSA transfer allowance and yields queued priority to visitor jobs. `/readyz` reports the last attempt separately from the live archive status. The service logs each complete inventory and keeps the last complete snapshot if a listing fails. Review newly listed prefixes before adding collections or regenerating presets. [IRSA cloud access](https://irsa.ipac.caltech.edu/cloud_access/#spherex)

`/readyz` checks the built shell, each bundled manifest and its referenced files, and the local cache schema. The production unit emits per-minute `spherex_metrics` journal records for response counts and bytes, cache activity, transfer budgets, queue depth, disk reserve and peak process memory. It emits a `spherex_alert` journal warning after three consecutive samples of queue saturation or recent archive failures. Inspect them with `journalctl -u spherex@8765 -g 'spherex_metrics|spherex_alert'`. The unit uses these aggregate measurements in place of Uvicorn request URL logging.

`archive` reports the last sampled IRSA transfer and its purpose. `archiveDiscovery` reports the most recent live metadata sample, so a cube or cutout can remain available during a discovery outage. The daily release inventory has its own status.

Regenerate examples with `python -m tools.build_presets <slug> --calibration-dir <calibrations> --output <candidate>`. The destination uses `web/public/presets` for display files and `presets` for science arrays. Metadata and cutouts share the batch byte and time ceilings. The command validates every requested target in temporary storage before publishing files to the destination. Content-addressed assets are written before the manifest pointers. Check the candidate separately with `python -m tools.verify_presets --root <candidate> <slug>` before staging a release.

Preserve the previous slot until an external HTTPS check verifies the certificate, `/readyz`, all five presets and a covered live query. To roll back, restore the previous Caddy route to the previous healthy slot, validate the full configuration, apply the reload and verify the public route again. Stop the superseded slot after verification. Keep the latest two staged releases and their preset versions.
