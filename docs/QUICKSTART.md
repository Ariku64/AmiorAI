# AmiorAI quick start

English: [`README.md`](../README.md) · Français : [`README_FR.md`](../README_FR.md)

For complete setup instructions, model folders and troubleshooting, read the root `README.md`.

## 1. Accept the legal notice

The standard Windows and Linux launchers display `LEGAL_NOTICE.md` and request acknowledgement before first use of this release.

## 2. Start LM Studio

1. Open LM Studio.
2. Download or load a chat/instruction model.
3. Open the Developer tab.
4. Start the local server on port `1234`.

Default URL:

```text
http://127.0.0.1:1234/v1
```

## 3. Install and start AmiorAI

Windows:

```bat
install.bat
start.bat
```

Linux / macOS:

```bash
chmod +x platform/linux/start.sh
./platform/linux/start.sh
```

Open `http://127.0.0.1:8800`.

## 4. Configure text models

Open **Settings → Language model**.

1. Refresh the LM Studio model list.
2. Select the conversation model.
3. Test it.
4. Optionally enable and select a separate utility model.
5. Test the utility model.

## 5. Configure ComfyUI

Set:

- the folder that directly contains `main.py`;
- the ComfyUI Python executable if auto-detection fails;
- URL `http://127.0.0.1:8188`;
- auto-launch only when the path and Python executable are correct.

Portable Windows example:

```text
ComfyUI path:   D:\ComfyUI_windows_portable\ComfyUI
ComfyUI Python: D:\ComfyUI_windows_portable\python_embeded\python.exe
```

## 6. Choose the image engine

- **Flux 2 Klein** for reference-image workflows.
- **Krea 2** for the unified descriptive T2I workflow.

For Krea 2, select the diffusion model, text encoder and VAE, then configure up to three optional LoRAs: main character, persona/second character and utility/style.

## 7. Run Diagnostics

Before the first image generation, open **Diagnostics**, select the intended image family and fix all critical red items.
