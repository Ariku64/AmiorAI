# LLM Pod — OpenAI-compatible vLLM

This kit assumes a Pod exposing an OpenAI-compatible server on internal port `8000`.

Example proxy base URL:

```text
https://POD_ID-8000.proxy.runpod.net/v1
```

Install a vLLM version compatible with the model, then use the example command in `start-command.example`. Keep model files under persistent `/workspace` storage unless they are baked into the container image.

In AmiorAI enter the Pod ID, proxy `/v1` URL, model ID and Runpod API key. AmiorAI starts the Pod on the first request and stops it after 15 inactive minutes by default.
