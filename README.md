<p align="center">
  <img src="web/amiorai-banner.png" alt="AmiorAI logo" width="1600">
</p>

<h1 align="center">AmiorAI</h1>

<p align="center">
  <strong>A free, local AI companion for conversation, roleplay, character memory, image generation and optional voice synthesis.</strong>
</p>

<p align="center">
  <a href="README\\\\\\\_FR.md">Français</a> · <strong>English</strong>
</p>

<p align="center">
  <a href="https://discord.gg/wYqhQBJV5z">
    <img src="https://img.shields.io/badge/Join%20the%20Discord-5865F2?style=for-the-badge\\\\\\\&logo=discord\\\\\\\&logoColor=white" alt="Join the AmiorAI Discord">
  </a>
</p>

<p align="center">
  Current release: <strong>v40.0.5</strong> · Windows 10/11 · Apache-2.0
</p>

<p align="center">
  <a href="https://buymeacoffee.com/ArikuDono">
    <img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" alt="Buy Me a Coffee" width="217" height="60">
  </a>
</p>

\---

## What is AmiorAI?

AmiorAI is a local application for creating AI characters and interacting with them through persistent conversations. It connects to software already running on your computer:

* **LM Studio** for the conversation and utility language models;
* **ComfyUI** for character images, scenes and the Image Studio;
* **Chatterbox Multilingual V3** for the recommended local voice engine;
* **Qwen3-TTS 0.6B Base** as an optional experimental voice engine.

The application interface, characters, conversations, memories, images and settings remain stored locally. AmiorAI does not include large AI model weights and does not require a paid cloud service.

> AmiorAI is a community project shared free of charge. AI models, LoRAs, ComfyUI custom nodes and external applications keep their own licences and requirements.

## Main features

|Feature|Description|
|-|-|
|Local conversations|Connects to an OpenAI-compatible LM Studio server.|
|Character creation|Personality, scenario, greeting, physical description, avatar and voice sample.|
|Persistent memory|Keeps character and conversation information between sessions.|
|Roleplay display|Distinct rendering for dialogue, narration and expressions.|
|Image generation|Flux 2 Klein reference-image workflows and the unified Krea 2 workflow.|
|LoRA management|Local folders, model classification, previews and character/style LoRA selection.|
|Image Studio|Manual prompt editing, model selection, sampler controls and generation history.|
|Local voice|Chatterbox by default, Qwen3-TTS as an optional advanced engine.|
|VRAM coordination|Can unload TTS, LM Studio and idle ComfyUI models when another engine needs the GPU.|
|Mobile/LAN interface|Responsive interface for use on a trusted private local network.|
|Diagnostics|Checks LM Studio, ComfyUI, models, workflows, paths and optional TTS engines.|
|Multilingual UI|English, French, Spanish and German.|

## Before downloading

AmiorAI is the application layer. A complete local setup normally requires:

1. AmiorAI;
2. LM Studio and at least one compatible chat/instruction model;
3. ComfyUI and compatible image models if image generation is wanted;
4. the optional Chatterbox or Qwen TTS installer if voice generation is wanted.

No model weights are bundled in the repository or release archive.

## Quick installation

### 1\. Download and extract

Download the latest AmiorAI archive from the GitHub **Releases** page. Extract it into a writable folder such as:

```text
D:\\\\\\\\AmiorAI
```

Do not run AmiorAI directly from inside the ZIP archive.

### 2\. Install AmiorAI

Run:

```text
install.bat
```

The installer downloads an official isolated Python Embedded runtime for AmiorAI and installs the required Python packages. It does not install LM Studio, ComfyUI or AI model weights.

### 3\. Start the application

Run:

```text
start.bat
```

The local interface opens at:

```text
http://127.0.0.1:8800
```

### 4\. Connect LM Studio

1. Install and open LM Studio.
2. Download and load a chat/instruction model.
3. Start the local server from LM Studio’s Developer section.
4. Keep the default address unless you changed it:

```text
http://127.0.0.1:1234/v1
```

5. In AmiorAI, open **Settings → Language model**, refresh the model list, select a conversation model and test it.

### 5\. Connect ComfyUI for images

1. Install and start ComfyUI.
2. In AmiorAI, open **Settings → ComfyUI**.
3. Select the ComfyUI folder that directly contains `main.py`.
4. Select its Python executable if automatic detection fails.
5. Keep the default API address:

```text
http://127.0.0.1:8188
```

6. Open **Diagnostics** and fix every critical red item before generating an image.

### 6\. Install local voice, optional

For the recommended Chatterbox engine, run:

```text
tts\\\\\\\_server\\\\\\\\install.bat
```

For the optional experimental Qwen engine, run:

```text
tts\\\\\\\_server\\\\\\\\install\\\\\\\_qwen.bat
```

Both engines use separate Python Embedded runtimes and do not require a system Python installation.

## First use

A simple first session is:

1. Open **Settings** and test LM Studio.
2. Configure ComfyUI and run **Diagnostics** if images are wanted.
3. Open **Characters** and create a character.
4. Define its name, personality, scenario, greeting and physical description.
5. Add an avatar or generate one.
6. Create a conversation and send the first message.
7. Use **Bring this scene to life** to generate the current scene.
8. Use **▶ Listen** below a character reply after enabling TTS.
9. Review generated images in **Gallery**.
10. Back up `%LOCALAPPDATA%\\\\\\\\AmiorAI\\\\\\\\data` before major upgrades.

## Documentation

* [Full installation and configuration](#full-installation-and-configuration)
* [Daily use guide](#daily-use-guide)
* [Voice installation](#voice-system)
* [Troubleshooting](#troubleshooting)
* [French documentation](README_FR.md)
* [Quick start](docs/QUICKSTART.md)
* [Detailed troubleshooting](docs/TROUBLESHOOTING.md)
* [Changelog](docs/CHANGELOG.md)
* [Legal notice](LEGAL_NOTICE.md)
* [Third-party notices](THIRD_PARTY_NOTICES.md)

\---

# Full installation and configuration

## 1\. Requirements

### Required for the main application

* Windows 10 or Windows 11, 64-bit;
* a writable installation folder;
* enough storage for the application and external AI models;
* LM Studio with at least one chat/instruction model.

### Recommended for image and voice generation

* an NVIDIA RTX GPU;
* ComfyUI;
* compatible Flux 2 Klein or Krea 2 model files;
* sufficient VRAM for the chosen models.

A 16 GB GPU can work well when AmiorAI’s VRAM release options are enabled, but model size, resolution and context length still matter.

### Official external applications

* [LM Studio official website](https://lmstudio.ai/)
* [LM Studio local server documentation](https://lmstudio.ai/docs/developer/core/server)
* [ComfyUI official Windows portable guide](https://docs.comfy.org/installation/comfyui_portable_windows)
* [ComfyUI official Windows desktop guide](https://docs.comfy.org/installation/desktop/windows)

Avoid unofficial repacks from unknown sources.

## 2\. Install AmiorAI

1. Extract the complete archive.
2. Run `install.bat`.
3. Read the legal notice displayed by the installer.
4. Accept only if you agree.
5. Wait for the installation-complete message.
6. Start AmiorAI with `start.bat`.

The main application runtime is stored in `python\\\\\\\_embed`. It is independent from the two optional TTS runtimes.

## 3\. Configure LM Studio

AmiorAI uses LM Studio for the conversation model and, optionally, a separate utility model.

### Download a model

Choose a model that:

* supports chat or instruction prompts;
* fits your available RAM/VRAM;
* has a licence suitable for your use;
* follows roleplay and structured instructions reliably.

A separate utility model can be useful for character creation, prompt planning, summaries and structured JSON tasks. When disabled, the conversation model is reused.

### Start the LM Studio server

1. Open LM Studio.
2. Open the **Developer** section.
3. Start the local server.
4. Use port `1234` unless you intentionally changed it.
5. Load the chosen model or enable LM Studio Just-In-Time loading if supported by your LM Studio version.

Default AmiorAI URL:

```text
http://127.0.0.1:1234/v1
```

### Select models in AmiorAI

1. Open **Settings → Language model**.
2. Confirm the LM Studio URL.
3. Click **Refresh model list**.
4. Select the conversation model.
5. Test the conversation model.
6. Optionally enable a separate utility model.
7. Select and test the utility model.
8. Save the section.

If a model does not appear, verify that the LM Studio server is running and that `/v1/models` exposes the expected model ID.

## 4\. Configure ComfyUI

AmiorAI communicates with ComfyUI through its local API.

Default address:

```text
http://127.0.0.1:8188
```

### ComfyUI Windows Portable

Typical paths:

```text
ComfyUI folder:
D:\\\\\\\\ComfyUI\\\\\\\_windows\\\\\\\_portable\\\\\\\\ComfyUI

ComfyUI Python:
D:\\\\\\\\ComfyUI\\\\\\\_windows\\\\\\\_portable\\\\\\\\python\\\\\\\_embeded\\\\\\\\python.exe
```

The selected ComfyUI folder must directly contain `main.py`.

### ComfyUI Desktop

Start ComfyUI Desktop once and confirm that it can generate an image. You can then either:

* leave it running manually and disable AmiorAI auto-launch; or
* point AmiorAI to the actual ComfyUI folder and Python environment.

### Manual, venv or Stability Matrix installation

These installations are supported as long as:

* ComfyUI starts correctly;
* the configured URL is reachable;
* AmiorAI knows the folder containing `main.py`;
* the correct Python executable is selected when auto-launch is enabled.

### Configure inside AmiorAI

1. Open **Settings → ComfyUI**.
2. Enter the ComfyUI API URL.
3. Select the folder containing `main.py`.
4. Select the ComfyUI Python executable if needed.
5. Enable automatic launch only when both paths are correct.
6. Save the section.
7. Open **Diagnostics** and test ComfyUI.

## 5\. Image models

AmiorAI does not redistribute image model weights. Download models only from sources you trust and read their licences.

### Krea 2

The bundled unified Krea 2 workflow expects selectable components such as:

```text
Diffusion model:
krea2\\\\\\\_turbo\\\\\\\_fp8\\\\\\\_scaled.safetensors

Text encoder:
qwen3vl\\\\\\\_4b\\\\\\\_fp8\\\\\\\_scaled.safetensors

VAE:
qwen\\\\\\\_image\\\\\\\_vae.safetensors
```

Typical folders:

```text
ComfyUI\\\\\\\\models\\\\\\\\diffusion\\\\\\\_models\\\\\\\\
ComfyUI\\\\\\\\models\\\\\\\\text\\\\\\\_encoders\\\\\\\\
ComfyUI\\\\\\\\models\\\\\\\\vae\\\\\\\\
ComfyUI\\\\\\\\models\\\\\\\\loras\\\\\\\\
```

Inside **Studio Image**:

1. Select **Krea 2**.
2. Select the diffusion model, text encoder and VAE.
3. Choose the sampler profile, aspect ratio and megapixel target.
4. Optionally select Character LoRA 1, Character LoRA 2/persona and a Utility LoRA.
5. Set unused LoRA slots to `none`.
6. Save and run Diagnostics.

Krea 2 uses descriptive text-to-image prompts. Identity is reinforced with the character LoRA, identity token and physical description.

### Flux 2 Klein

Flux 2 Klein supports:

* GGUF or Safetensors UNet mode;
* compatible text encoder and VAE;
* optional LoRA slots;
* reference-image workflows for solo, duo, trio and group scenes.

Inside **Studio Image**:

1. Select **Flux 2 Klein**.
2. Select GGUF or Safetensors mode.
3. Choose the matching UNet.
4. Select the compatible text encoder and VAE.
5. Configure optional LoRAs.
6. Save and run Diagnostics.

The GGUF mode requires a ComfyUI installation providing `UnetLoaderGGUF`.

## 6\. Missing ComfyUI nodes

When Diagnostics reports missing nodes:

1. update ComfyUI;
2. note the exact missing node names;
3. use ComfyUI Manager to find a trusted package providing those nodes;
4. restart ComfyUI completely;
5. run Diagnostics again.

Depending on the workflow, examples may include:

```text
ResolutionSelector
UnetLoaderGGUF
ReferenceLatent
Flux2Scheduler
EmptyFlux2LatentImage
```

Custom nodes execute Python code on your computer. Install only packages and authors you trust.

## 7\. Voice system

AmiorAI v40 provides two fully local voice engines:

* **Chatterbox Multilingual V3** — default and recommended;
* **Qwen3-TTS 0.6B Base** — optional and experimental.

### Install Chatterbox

Run:

```text
tts\\\\\\\_server\\\\\\\\install.bat
```

This creates:

```text
tts\\\\\\\_server\\\\\\\\python\\\\\\\_chatterbox
```

The installer uses an isolated official Python 3.11.9 Embedded runtime.

If AmiorAI reports `No module named 'chatterbox'`, close AmiorAI and run:

```text
tts\\\\\\\_server\\\\\\\\repair\\\\\\\_chatterbox.bat
```

Wait for `Chatterbox import: OK`, then restart AmiorAI.

### Install Qwen3-TTS, optional

Run:

```text
tts\\\\\\\_server\\\\\\\\install\\\\\\\_qwen.bat
```

This creates the independent runtime:

```text
tts\\\\\\\_server\\\\\\\\python\\\\\\\_qwen
```

For the strongest Qwen clone, enter the exact words spoken in the reference sample in the character’s **Voice sample transcript** field. The transcript is optional for Chatterbox.

### Configure voice in AmiorAI

1. Open **Settings → Voice / TTS**.
2. Enable TTS.
3. Select Chatterbox or Qwen.
4. Keep the local URL at `http://127.0.0.1:8810` unless changed intentionally.
5. Enable automatic launch.
6. Keep **Release VRAM between engines** enabled on GPUs with limited VRAM.
7. Save the voice section.
8. Open a conversation and click **▶ Listen** below a character reply.

The top conversation speaker control enables or disables automatic playback. The **▶ Listen** button provides manual playback for individual replies.

### Prepare a voice sample

Use a clean sample of approximately 6 to 20 seconds:

* one speaker;
* no music;
* little background noise;
* natural speaking voice;
* a format accepted by AmiorAI.

Only use a voice you own or have clear permission to use. Do not use synthetic speech to impersonate or deceive anyone.

### VRAM coordination

With **Release VRAM between engines** enabled:

1. AmiorAI stops the CUDA TTS process before LM Studio or ComfyUI needs the GPU.
2. Stopping the process releases its PyTorch CUDA context.
3. Before the next spoken reply, AmiorAI unloads LM Studio models and asks idle ComfyUI models to release VRAM.
4. The selected TTS engine starts again automatically.

CPU TTS is not stopped because it consumes no GPU VRAM.

\---

# Daily use guide

## 1\. Create a character

Open **Characters** and create a new entry. The most important fields are:

* name;
* personality and behavior;
* scenario/context;
* first greeting;
* physical description;
* image-generation identity token or LoRA settings;
* optional avatar and voice sample.

A precise personality description usually produces more consistent replies than a long list of vague adjectives.

## 2\. Start a conversation

1. Select a character.
2. Create a conversation.
3. Choose or write the opening context.
4. Send a message.
5. Use **Continue** when you want the model to extend its last reply.

The selected language model, context size, output length and temperature are controlled in Settings.

## 3\. Generate a scene from the chat

Use **Bring this scene to life** to build an image prompt from the recent conversation. AmiorAI combines the selected character, relevant persona information and the current scene.

Use **Character only** when the image must contain only the selected character.

Before generation, review the editable prompt when precision matters.

## 4\. Use Image Studio

Image Studio is intended for manual generations independent from a conversation. It provides:

* model-family selection;
* prompt editing;
* dimensions and aspect ratio;
* sampler profiles;
* LoRA selection and strength;
* generation history.

## 5\. Use a persona

The optional persona represents the user or a recurring second subject. It can include:

* name;
* physical description;
* reference image;
* Krea identity token;
* persona LoRA and strength.

Persona information is used only when the selected workflow and scene need it.

## 6\. Manage LoRAs and model folders

Use the model library and LoRA pages to:

* add local folders;
* rescan files;
* identify or correct a detected model family;
* preview LoRAs;
* mark favourites;
* assign character, persona or utility LoRAs.

Avoid placing personal API tokens or paid model files in the Git repository.

## 7\. Gallery and user files

Generated images and imported files are stored in AmiorAI’s local data directory. Use Gallery to review generated content. Back up the data directory regularly.

## 8\. Mobile/LAN mode

The mobile interface is intended for a trusted private network.

* keep the access code private;
* do not expose ports `8800`, `1234`, `8188` or `8810` to the public Internet;
* do not create router port-forwarding rules for AmiorAI;
* disable LAN access when it is not needed.

\---

# Data, updates and backups

## Local data location

On Windows, persistent data is normally stored in:

```text
%LOCALAPPDATA%\\\\\\\\AmiorAI\\\\\\\\data
```

It can contain:

* the application database;
* characters and conversations;
* memories;
* generated images and audio;
* imported persona and avatar files;
* backups;
* logs.

The source/application folder and the persistent data folder are separate. Removing the source folder does not necessarily remove user data.

## Before updating

1. Close AmiorAI.
2. Back up `%LOCALAPPDATA%\\\\\\\\AmiorAI\\\\\\\\data`.
3. Extract the new release into a clean application folder unless the release notes explicitly describe a hotfix overlay.
4. Do not copy old Python runtimes over newer ones unless instructed.
5. Start the new release and run Diagnostics.

\---

# Troubleshooting

## Chatterbox module missing

Close AmiorAI and run:

```text
tts\\\\\\\_server\\\\\\\\repair\\\\\\\_chatterbox.bat
```

Detailed installation logs are written to:

```text
tts\\\\\\\_server\\\\\\\\install\\\\\\\_chatterbox\\\\\\\_pip.log
```

## The ▶ Listen button is missing

Use v40.0.3 or later. In **Settings → Voice / TTS**, enable TTS and save the voice section. The manual button is displayed below character replies; the speaker control at the top of the conversation controls automatic playback.

## LM Studio is unreachable

* start the LM Studio local server;
* verify `http://127.0.0.1:1234/v1`;
* refresh the model list;
* select an exact model ID exposed by LM Studio;
* check whether another application uses port `1234`.

## LM Studio returns an empty or invalid response

* use a chat/instruction model;
* increase the output-token limit;
* reduce context size if memory is insufficient;
* test a different utility model for structured JSON tasks;
* inspect Diagnostics and the application logs.

## AmiorAI cannot start ComfyUI

* select the folder directly containing `main.py`;
* select the exact ComfyUI Python executable;
* verify port `8188`;
* start ComfyUI manually and disable auto-launch;
* inspect `%LOCALAPPDATA%\\\\\\\\AmiorAI\\\\\\\\data\\\\\\\\logs\\\\\\\\comfyui.log`.

## A model is absent from a selector

* copy it into the correct ComfyUI model folder;
* restart or refresh ComfyUI;
* rescan the AmiorAI model library;
* verify the file extension and detected family;
* use the manual identification feature when detection is wrong.

## Out of memory

* choose a smaller or more quantized language model;
* reduce LM Studio context size;
* reduce image resolution or steps;
* close other GPU applications;
* enable VRAM release between engines;
* use Diagnostics to identify the engine still occupying VRAM.

More details: [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md).

\---

# Repository and contribution notes

The Git repository intentionally excludes:

* Python Embedded runtimes and virtual environments;
* AI model weights;
* personal voices, characters and conversations;
* generated images/audio;
* databases, logs, secrets and API tokens;
* ZIP release archives.

Run `install.bat` after cloning the repository to recreate the main runtime. Run the TTS installers only when those engines are wanted.

Important root files:

```text
README.md                English GitHub documentation
README\\\\\\\_FR.md             French GitHub documentation
install.bat              main Windows installer
start.bat                standard Windows launcher
LICENSE                  Apache License 2.0
NOTICE                   AmiorAI copyright notice
LEGAL\\\\\\\_NOTICE.md          disclaimer and user responsibilities
THIRD\\\\\\\_PARTY\\\\\\\_NOTICES.md   external component licences and sources
.gitignore               local runtimes, models and personal data exclusions
```

\---

# Licence, copyright and responsibility

**Copyright © 2026 Ariku.**

The original AmiorAI source code is licensed under the **Apache License 2.0**. See [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE).

AmiorAI is provided **as is**, without warranty. The user remains responsible for installed models, LoRAs, prompts, generated content, backups, hardware stability, privacy, voice rights and compliance with applicable law. Read [`LEGAL\\\\\\\_NOTICE.md`](LEGAL_NOTICE.md) before installing or sharing the application.

Third-party applications, Python packages, model weights, LoRAs, workflows and custom nodes remain governed by their own licences. See [`THIRD\\\\\\\_PARTY\\\\\\\_NOTICES.md`](THIRD_PARTY_NOTICES.md).

