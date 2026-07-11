# AmiorAI troubleshooting

## LM Studio returns HTTP 400

AmiorAI now reads `/v1/models` and sends an exact model ID accepted by LM Studio. Check:

- the local server is running;
- the URL ends with `/v1` or points to the LM Studio server root;
- the selected conversation/utility model ID exists in LM Studio;
- the model can fit the requested context;
- the API key is correct when authentication is enabled.

The error message now includes LM Studio's actual HTTP response detail.

## LM Studio is reported as unreachable

Default URL: `http://127.0.0.1:1234/v1`.

Start the local server in LM Studio and verify that another application is not already using port 1234. AmiorAI supports LM Studio only; Kobold, Ollama and in-process llama.cpp routes were removed.

## ComfyUI rejects a Krea model with `value_not_in_list`

Update to v38.1.2 or later. The app now resolves catalog paths to the exact loader value exposed by `/object_info/UNETLoader`.

Example:

```text
models/diffusion_models/krea2_turbo_fp8_scaled.safetensors
→ krea2_turbo_fp8_scaled.safetensors
```

If the error remains, refresh/rescan the model list and select the exact entry returned by ComfyUI. Duplicate filenames in different subfolders require the full relative subfolder entry.

## Krea 2 model or node is missing

Update ComfyUI and verify:

- the diffusion model is in a folder scanned by `UNETLoader`;
- the Qwen text encoder is visible to `CLIPLoader` with type `krea2`;
- the Qwen Image VAE is visible to `VAELoader`;
- selected LoRAs are visible to `LoraLoader`;
- `workflows/krea2/krea2_unified.json` exists.

## A Krea group scene has no avatar reference

This is expected. In global Krea mode, avatar, emotion and group features use the same descriptive T2I workflow. Identity comes from the character LoRA, identity token and full physical description. Flux remains available for true reference-image workflows.

## ComfyUI does not release VRAM within 15 seconds

The warning is not automatically fatal. AmiorAI continues carefully when ComfyUI memory stabilizes later. Close other GPU applications, increase the release timeout in Settings, or start ComfyUI with a low-VRAM option.

## Python is not found

Run `install.bat`, or install Python 3.10–3.12 and add it to PATH.

## Reset without deleting the source

Close AmiorAI, back up the complete `data/` folder, then remove it. A clean data folder is created at the next launch.


## Conversation fails with `could not convert string to float: ''`

This was fixed in v39.1.3. Empty numeric fields such as response temperature or token limits now use safe defaults. Install v39.1.3 and restart AmiorAI.

### Réparer Chatterbox

Si AmiorAI signale `No module named 'chatterbox'`, ferme l'application puis lance
`tts_server\repair_chatterbox.bat`. Le script réutilise le Python Embedded existant,
répare pip et réinstalle le paquet officiel sans nécessiter Python sur Windows.
Le diagnostic détaillé est conservé dans `tts_server\install_chatterbox_pip.log`.
