# SPLASH AI LLM Server for Home Assistant

Monitor one or more SPLASH AI LLM servers from Home Assistant. Each server appears as its own device and supplies sensors from its `/status` endpoint.

## Install with HACS

[![Open SPLASH AI LLM Server in HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=jtenniswood&repository=splash-hacs&category=integration)

Open the repository with the button above, select **Download** in HACS, and restart Home Assistant.

To add the repository manually in HACS:

1. In HACS, open **Custom repositories** from the top-right menu.
2. Add `https://github.com/jtenniswood/splash-hacs` as an **Integration**, then download **SPLASH AI LLM Server**.
3. Restart Home Assistant.

For a manual or feature-branch install, copy `custom_components/splash_server` into your Home Assistant configuration directory's `custom_components` folder and restart Home Assistant.

## Add or edit a server

Go to **Settings → Devices & services → Add Integration** and search for **SPLASH AI LLM Server**.

Choose **Discover on local network** to find servers listening on port 8000. Select a result, give it a name, and choose an update interval. In the SPLASH desktop app, set **Listen on** to **All Networks**. For the CLI, start the server with `--host 0.0.0.0`.

The search checks the nearby private IPv4 addresses on Home Assistant's enabled network interfaces. On networks larger than a /24, it checks the /24 containing the interface's address. For a server on a different network, including Tailscale, or one using a different port, select **Enter server address manually**.

For manual setup, enter:

- **Server name** for the Home Assistant device.
- **Server address** as an IP, hostname, or full status URL. A bare address uses HTTP on port 8000, and you can also enter an explicit port or paste a URL such as `http://192.168.1.50:8000/status`.
- **Update interval** from 10 to 3600 seconds. The default is 30 seconds.

Home Assistant itself must be able to reach the address. For a Tailscale address, make sure your Home Assistant host has a route to the server over Tailscale.

To add another server, select **Add Integration** again. To change an existing server's name, address, port, or update interval, use **Reconfigure** from that server entry's menu. The device and its entities keep their existing IDs and history.

### Automatic discovery with Bonjour

Home Assistant also shows SPLASH servers under **Discovered** when they advertise a `_splash._tcp` Bonjour service. To publish the announcement from macOS, run the following on the Mac hosting SPLASH, using your server's port and a name of your choice. Keep the command running while you want the announcement to be visible.

```sh
dns-sd -R "My SPLASH Server" _splash._tcp local 8000
```

## Sensors

The device's **Sensors** section shows readiness, the loaded model, active and queued requests, current memory and memory headroom, memory pressure, thermal state, cache hit rate, prefill and decode speed, and median time to first token.

The **Diagnostic** section contains the remaining entities, including request totals, storage, detailed latency, and server health indicators. The entities keep their existing IDs and history.

All entities for a server share one request per polling cycle. If a field is absent, its sensor shows **Unknown**. If polling fails, the server's entities show **Unavailable** until a successful refresh.
