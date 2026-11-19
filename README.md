# Inference Assistant for Home Assistant

<img src="https://raw.githubusercontent.com/jtenniswood/inference-assistant/main/custom_components/inference_assistant/brand/icon.png" width="80" height="80" alt="Inference Assistant icon">

Monitor your local AI inference servers in Home Assistant. Add as many servers as you need, mix server types, and set a polling interval for each one. Every server appears as its own device, with sensors you can use in dashboards and automations. Polling reads the server's metrics and status APIs without sending prompts or loading models.

<!-- ha-marketplace:exclude-start -->
## Install and update

Inference Assistant requires Home Assistant **2025.10.0 or later**. Add it as a custom repository using the button below, then install the latest stable release.

[![Open Inference Assistant in Home Assistant](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=jtenniswood&repository=inference-assistant&category=integration)

### Install with Home Assistant Marketplace (2026.11 and later)

1. Open **Settings → Marketplace** and choose **Add from link**.
2. Connect GitHub if prompted, then enter `jtenniswood/inference-assistant`. If asked for the type, choose **Integration**.
3. Open **Inference Assistant** and choose **Install**.

New releases appear in **Settings → Updates**. Restart Home Assistant when prompted after installing or updating. [Home Assistant Marketplace documentation](https://www.home-assistant.io/integrations/marketplace/#custom-repositories)

### Install with HACS

On Home Assistant versions that use standalone HACS, open **HACS → ⋮ → Custom repositories**. Add `https://github.com/jtenniswood/inference-assistant` as an **Integration**, then open Inference Assistant and choose **Download**. Restart Home Assistant after downloading or updating. [HACS custom repository documentation](https://www.hacs.xyz/docs/faq/custom_repositories/)

### Install manually

Download the source archive from the [latest release](https://github.com/jtenniswood/inference-assistant/releases/latest), or use your feature branch for testing. Copy `custom_components/inference_assistant` into the `custom_components` folder in your Home Assistant configuration directory. Restart Home Assistant.
<!-- ha-marketplace:exclude-end -->

## Supported servers

All five server types report readiness. Other sensors depend on what the server exposes.

| Server | Default port | Endpoints read | Metrics |
| --- | ---: | --- | --- |
| Splash | 8000 | `/status` | Model, requests, memory and thermal state, cache, throughput, and latency |
| Ollama | 11434 | `/api/ps` | Loaded model names and count, largest loaded context, and model memory including GPU memory |
| LM Studio | 1234 | `/api/v1/models` | Loaded models and instances, largest loaded context, and configured parallel prediction capacity |
| llama.cpp | 8080 | `/health`, `/metrics` | Active and queued requests, prompt and generation throughput, and token totals |
| vLLM | 8000 | `/health`, `/metrics` | Active and queued requests, served models, peak KV cache usage across engines, prefix cache hit rate, average time to first token, token totals, and request preemptions |

## Add or edit a server

1. Open **Settings → Devices & services → Add integration** and search for **Inference Assistant**.
2. Choose the server type. Splash also offers [local network discovery](#discover-splash-servers).
3. Enter a **Server name**, **Server address**, and **Update interval**. Polling defaults to **30 seconds** and accepts **10 to 3600 seconds**.
4. Add other servers by repeating these steps.

Enter a bare hostname or IP to use HTTP on the default port from the table. To use a different port, enter a host and port such as `192.168.1.50:8001`, or a full URL such as `http://192.168.1.50:8001/status`. A full URL without a port uses port 80 for HTTP or 443 for HTTPS. If Home Assistant runs on a separate machine, use an address reachable from Home Assistant, such as the server's LAN or VPN address.

For **Ollama**, **LM Studio**, **llama.cpp**, and **vLLM**, enter a bearer token in **API key** if your monitoring endpoints require one. For **Splash**, `/status` must be reachable without a key.

- **LM Studio** needs the local server running and the v1 REST API available.
- **llama.cpp** needs to be started with `--metrics`. For router mode, enter the exact model ID of a loaded model in **Router model ID**. Use a separate entry for each model you want to monitor. Leave the field blank for a standalone server.
- **vLLM** needs both health and metrics endpoints available on the same server address.

Use **Reconfigure** in the server entry's menu to change its name, address, polling interval, or supported API key settings. Leave the API key field blank to keep the saved key, or select **Remove the saved API key** to clear it. Reconfiguring an entry preserves its device and entity IDs.

## Discover Splash servers

In the Splash desktop app, set **Listen on** to **All Networks**. For the CLI, start Splash with `--host 0.0.0.0` to allow Home Assistant to connect.

- **Discover on local network** checks port 8000 on nearby private IPv4 addresses from Home Assistant's enabled network interfaces. On networks larger than a /24, it checks the /24 containing the interface's own address. Select a result, then set its name and update interval.
- **Bonjour** announcements appear under **Discovered** in Home Assistant, including when the server uses a custom port. To publish one from the Mac hosting Splash, run the command below and leave it running while you want the announcement to be visible. Substitute your own name and port.

```sh
dns-sd -R "My Splash Server" _splash._tcp local 8000
```

Use **Enter server address manually** for a known address that the network scan cannot reach, such as a server across Tailscale.

## Sensors and diagnostics

In **Settings → Devices & services → Inference Assistant**, open a server's device page. The **Sensors** section shows the everyday metrics available for its server type. **Diagnostic** holds additional metrics such as token or request totals, storage details, and health indicators where available.

- **Ready** means Splash reports readiness, Ollama or LM Studio answered its models endpoint, or llama.cpp or vLLM reported healthy. Ollama and LM Studio can be ready with zero loaded models.
- **Unknown** means the most recent successful response did not provide a value for that sensor.
- **Unavailable** means the last poll failed. Sensors resume updating when the server responds successfully.

For llama.cpp and vLLM, a health endpoint returning HTTP 503 turns **Ready** off and leaves the metrics unknown until the server is ready again.

## Troubleshooting

- **Could not reach the monitoring endpoint.** Check the address, port, network route, and server listener from the Home Assistant host. For a VPN address, Home Assistant also needs access to that VPN.
- **The endpoint did not return monitoring data.** Check the selected server type and the endpoint in the table. llama.cpp and vLLM need their server-specific Prometheus metrics.
- **Splash discovery found no servers.** Confirm the server is listening on the network and on port 8000, or enter its address manually.
- **The Marketplace icon is missing before installation.** The icon ships with the integration. On Home Assistant 2026.3 or later, Home Assistant can display it after installation. [Home Assistant branding documentation](https://github.com/home-assistant/brands#marketplace-icons)

[Report an issue](https://github.com/jtenniswood/inference-assistant/issues) with your Home Assistant version, server type and version, and the error shown in setup or logs. Remove API keys from anything you share.

## Upgrading from the former Splash integration

Inference Assistant uses a new integration ID. Back up Home Assistant and note your server names, addresses, and update intervals. Remove the previous integration under **Settings → Devices & services**, then remove the old download in HACS or Marketplace. For a manual installation, remove the old `custom_components/splash_server` folder.

Install Inference Assistant and add your servers again. Check any dashboards and automations that refer to the old entities.

## License

Inference Assistant is licensed under [Apache 2.0](LICENSE).

The integration icon uses a modified [Material Design Infinity icon](https://pictogrammers.com/library/mdi/icon/infinity/) by Pictogrammers, licensed under [Apache 2.0](https://www.apache.org/licenses/LICENSE-2.0).
