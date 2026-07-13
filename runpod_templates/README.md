# AmiorAI Runpod deployment kits

These folders document four independent user-owned deployments. They are reproducible reference configurations that can later be published to Runpod Hub or copied into the Runpod console.

They include no model weights, credentials, account automation, billing or already-published Hub template IDs. Always select the latest stable official worker version compatible with the chosen model.

| Kit | Purpose | AmiorAI fields |
|---|---|---|
| `llm_serverless` | OpenAI-compatible vLLM | Endpoint ID + Runpod key + model ID |
| `image_serverless` | ComfyUI worker | Endpoint ID + Runpod key |
| `llm_pod` | persistent vLLM server | Pod ID + `/v1` URL + Runpod key |
| `image_pod` | persistent ComfyUI | Pod ID + proxy URL + Runpod key |

The JSON files are human-readable reference presets, not guaranteed one-click imports for every Runpod console version.
