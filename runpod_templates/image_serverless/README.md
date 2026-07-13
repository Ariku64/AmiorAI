# Image Serverless — ComfyUI worker

Use the latest stable release of `runpod-workers/worker-comfyui`.

The stock Hub listing may contain a model that does not match AmiorAI workflows. For Krea 2, Flux 2 Klein, custom LoRAs or custom nodes, build or select an image containing the exact files expected by the AmiorAI workflows.

1. Export every workflow with **Workflow > Export (API)**.
2. Verify model filenames and custom-node class names.
3. Apply `endpoint-settings.json`.
4. Enter the Endpoint ID and Runpod key in AmiorAI.
5. Test text-to-image and image-to-image separately.

The worker must accept `input.workflow` and optional `input.images`, and return `output.images` as base64 or URLs.
