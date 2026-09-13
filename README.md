# Feishu Cloud Gateway

Cloud-side webhook relay and watchdog deployment for the Feishu notification path.

This deployment is intentionally separate from the Windows `feishu-gateway` Compose project.

## Layout

- `cloud/relay.py` — durable webhook relay.
- `cloud/watchdog.py` — the cloud readiness watchdog source.
- `deploy/` — systemd unit templates for the cloud deployment.

The runtime directory is `/srv/feishu-cloud-gateway`. Credentials and queue state stay outside this repository.
