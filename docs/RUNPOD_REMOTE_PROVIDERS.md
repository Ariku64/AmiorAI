# AmiorAI — remote providers and Runpod

AmiorAI remains a **local-first frontend**. It does not sell credits, rent GPUs, create provider accounts, or process provider billing. Each user connects a server or Runpod account they own and accepts the provider's terms directly.

## Available providers

### Conversation

- **Local LM Studio**.
- **OpenAI-compatible API** owned or selected by the user.
- **Runpod Serverless — vLLM**.
- **Runpod Pod — vLLM**, started on the first request and stopped after the configured inactivity period.

### Images

- **Local external ComfyUI**.
- **Remote ComfyUI-compatible API**.
- **Runpod Serverless — ComfyUI**.
- **Runpod Pod — ComfyUI**, started on the first generation and stopped after inactivity.

### Voice

TTS remains local in this release. Chatterbox and Qwen3-TTS are not sent to Runpod.

## Recommended private hybrid

```text
Conversation and memory: local LM Studio
Images: user-owned Runpod Serverless endpoint or Pod
Voice: local
```

Only the final visual prompt, workflow and optional reference images leave the computer in this configuration. The full chat history and memory database remain local.

## Secrets

Runpod, remote LLM and remote image keys are stored in the operating-system credential store when available and are never written to the AmiorAI SQLite database. Without a compatible credential store, secrets remain in session memory only.

## Serverless vLLM

1. Deploy the official vLLM worker or a Hub endpoint on the user's Runpod account.
2. Select a model and verify its licence.
3. Set **Active workers** to `0`.
4. The AmiorAI reference preset uses **Max workers** `1` and **Idle timeout** `900 seconds`.
5. Enter the Endpoint ID and Runpod API key in AmiorAI.
6. Select the exact model ID returned by `/models`.

AmiorAI uses:

```text
https://api.runpod.ai/v2/ENDPOINT_ID/openai/v1
```

## Serverless ComfyUI

Deploy the official ComfyUI worker or a custom image containing the required models and nodes. Export workflows with **Workflow > Export (API)**. AmiorAI sends `input.workflow` and optional base64 `input.images`, then polls the asynchronous job until completion.

A fifteen-minute Serverless idle timeout keeps the worker warm but is billed idle time. Users may choose a shorter value directly in Runpod.

## Runpod Pods

Expose the API port through the Runpod HTTP proxy:

```text
https://POD_ID-INTERNAL_PORT.proxy.runpod.net
```

Typical ports are `8000` for an OpenAI-compatible vLLM server and `8188` for ComfyUI.

AmiorAI checks the Pod, starts it if required, waits for the configured API to become reachable, executes the request and starts a 15-minute inactivity countdown. It never stops a Pod while a tracked job is active.

Automatic stopping cannot be guaranteed after a power loss, hard crash, forced process termination or network/API outage. Users must verify their Runpod dashboard after each session. Persistent storage may continue to incur charges after the GPU stops.

## Privacy

Remote LLM use sends the messages, context and memory excerpts needed for the response. Remote image use sends the visual prompt, workflow, parameters and optional reference images. Local mode is the only mode where these prompts never leave the PC.

## Deployment kits

`runpod_templates` contains four documented reference kits. They are not published Runpod Hub template IDs and do not redistribute model weights.
