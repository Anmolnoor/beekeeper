# Remote Access and Tailscale

This guide covers options for exposing Beehive services (Queen API, Beekeeper API, Open WebUI) to remote access without opening ports on your firewall.

## Options Overview

| Method | Setup | Use Case |
|--------|-------|----------|
| **Tailscale** | Install + auth | Secure mesh VPN; access from phone, laptop, or other Tailscale nodes |
| **ngrok** | Sign up + tunnel | Quick share with anyone (public or auth-protected URL) |
| **Cloudflare Tunnel** | Sign up + daemon | Free HTTPS tunnel; good for production-style setups |

---

## Tailscale (Recommended for Private Access)

Tailscale creates a private mesh network. Services reachable on `localhost` become reachable at your Tailscale hostname from any device on your Tailscale network.

### 1. Install Tailscale

**macOS (Homebrew):**
```bash
brew install tailscale
```

**Linux:**
```bash
curl -fsSL https://tailscale.com/install.sh | sh
```

### 2. Log in and enable

```bash
sudo tailscale up
# Follow the auth flow in browser
```

### 3. Get your Tailscale hostname

```bash
tailscale status
# Shows your node name, e.g. `machine-name` → reachable at `machine-name.tail12345.ts.net`
```

### 4. Expose services to Tailscale

Beehive services listen on `0.0.0.0` by default, so they're already reachable on your Tailscale IP.

From another Tailscale device:
- Queen API: `http://<machine>.tail12345.ts.net:8788/v1` (or your host port)
- Beekeeper API: `http://<machine>.tail12345.ts.net:8787`
- Open WebUI: `http://<machine>.tail12345.ts.net:3000`

### 5. Optional: Serve on Tailscale-only interface

To avoid exposing services to your LAN, bind only to the Tailscale interface:

```bash
# Tailscale usually adds tailscale0; find yours with:
ip addr show tailscale0   # Linux
ifconfig tailscale0       # macOS
```

Then start services with:
- `BEEKEEPER_HOST=100.x.x.x` (your Tailscale IP) when running Beekeeper API
- Or use a reverse proxy that listens only on the Tailscale IP

### 6. Docker Compose

If running via `beehive up`, ensure port mappings are correct. Defaults:

- Queen API: `8788:8788`
- Beekeeper API: `8787:8787`
- Open WebUI: `3000:3000`

Access from a Tailscale peer using your machine's Tailscale hostname and these ports.

---

## ngrok (Quick Public Share)

For a temporary public URL (e.g., demos, webhooks):

```bash
# Install
brew install ngrok   # or download from ngrok.com

# Expose Beekeeper API
ngrok http 8787

# Expose Queen API
ngrok http 8788
```

Use the generated `https://xxx.ngrok.io` URL. Add basic auth or use ngrok's paid plans for auth.

**Slack/Discord webhooks:** Point the webhook URL to your ngrok URL, e.g. `https://xxx.ngrok.io/api/channels/slack/webhook`.

---

## Cloudflare Tunnel

For a persistent HTTPS tunnel without opening ports:

```bash
# Install cloudflared
brew install cloudflare/cloudflare/cloudflared

# Login
cloudflared tunnel login

# Create and run tunnel
cloudflared tunnel create beehive
cloudflared tunnel route dns beehive api.yourdomain.com
cloudflared tunnel run --url http://localhost:8787 beehive
```

---

## Security Checklist

- [ ] Use Tailscale for private access; avoid exposing directly to the internet.
- [ ] If using ngrok/Cloudflare Tunnel, enable auth or restrict by IP where possible.
- [ ] Keep `BEEKEEPER_AUDIT_SIGNING_KEY` and channel secrets (Slack/Discord tokens) secure; never commit to git.
- [ ] For production, put a reverse proxy (Caddy, nginx) in front with TLS and rate limiting.

---

## Troubleshooting

**Tailscale: "Connection refused"**
- Ensure the service binds to `0.0.0.0` (default for uvicorn/FastAPI).
- Check firewall rules (macOS: System Preferences → Security → Firewall).

**ngrok: Webhook signature failures**
- Slack/Discord verify the request URL. Ensure your ngrok URL is stable (paid ngrok gives fixed domains) or update webhook config when the URL changes.
