# LLM Serverless — vLLM

Use the official `runpod-workers/worker-vllm` release or its Runpod Hub listing.

1. Select a vLLM-supported instruct/chat model.
2. Copy `env.example` values into endpoint environment variables and adapt them.
3. Apply the reference values in `endpoint-settings.json`.
4. Create the endpoint and copy its Endpoint ID.
5. In AmiorAI select **Runpod Serverless — vLLM**.
6. Save the Runpod API key, Endpoint ID and exact served model ID.

AmiorAI calls `/openai/v1/models` and `/openai/v1/chat/completions`.
