# SPLASH AI LLM Server for Home Assistant

Monitor one or more SPLASH AI LLM servers from Home Assistant. Each server appears as its own device and supplies sensors from its `/status` endpoint.

## Install with HACS

1. In HACS, open **Custom repositories** from the top-right menu.
2. Add `https://github.com/jtenniswood/splash-hacs` as an **Integration**, then download **SPLASH AI LLM Server**.
3. Restart Home Assistant.

For a manual or feature-branch install, copy `custom_components/splash_server` into your Home Assistant configuration directory's `custom_components` folder and restart Home Assistant.

## Add or edit a server

Go to **Settings → Devices & services → Add Integration** and search for **SPLASH AI LLM Server**. Enter:

- **Server name** for the Home Assistant device.
- **Server address** as an IP, hostname, or full status URL. A bare address uses HTTP on port 8000, and you can also enter an explicit port or paste a URL such as `http://192.168.1.50:8000/status`.
- **Update interval** from 10 to 3600 seconds. The default is 30 seconds.

Home Assistant itself must be able to reach the address. For a Tailscale address, make sure your Home Assistant host has a route to the server over Tailscale.

To add another server, select **Add Integration** again. To change an existing server's name, address, port, or update interval, use **Reconfigure** from that server entry's menu. The device and its entities keep their existing IDs and history.

## Sensors

The integration reports readiness and health, the loaded model and context limit, request counts and queue activity, memory and disk usage, cache efficiency, token throughput, and latency. All entities for a server share one request per polling cycle. If a field is absent, its sensor shows **Unknown**. If polling fails, the server's entities show **Unavailable** until a successful refresh.
