# Feishu Cloud Gateway

Cloud-side webhook relay and watchdog deployment for the Feishu notification path.

This deployment is intentionally separate from the Windows `feishu-gateway` Compose project.

## Layout

- `cloud/relay.py` — durable webhook relay.
- `cloud/watchdog.cpython-312.pyc` — the cloud watchdog runtime artifact.
- `deploy/` — systemd unit templates for the cloud deployment.

The runtime directory is `/srv/feishu-cloud-gateway`. Credentials and queue state stay outside this repository.
