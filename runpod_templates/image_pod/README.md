# Image Pod — ComfyUI

This kit assumes ComfyUI listens on all interfaces on internal port `8188`.

Example proxy URL:

```text
https://POD_ID-8188.proxy.runpod.net
```

Install ComfyUI, the exact custom nodes and all files referenced by the AmiorAI workflows. Store models and LoRAs under persistent `/workspace` storage or bake them into the image. Start ComfyUI with the example command adapted to its installation path.

In AmiorAI enter the Pod ID, proxy URL and Runpod API key. AmiorAI starts the Pod on the first image request and stops it after 15 inactive minutes by default.
