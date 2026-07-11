<p align="center">
  <img src="web/logo-icon-square.png" alt="Logo AmiorAI" width="150">
</p>

<h1 align="center">AmiorAI</h1>

<p align="center">
  <strong>Un compagnon IA gratuit et local pour la conversation, le roleplay, la mémoire des personnages, la génération d’images et la synthèse vocale optionnelle.</strong>
</p>

<p align="center">
  <strong>Français</strong> · <a href="README.md">English</a>
</p>

<p align="center">
  Version actuelle : <strong>v40.0.5</strong> · Windows 10/11 · Apache-2.0
</p>

---

## Qu’est-ce qu’AmiorAI ?

AmiorAI est une application locale permettant de créer des personnages IA et de discuter avec eux au sein de conversations persistantes. Elle se connecte à des logiciels exécutés sur votre propre ordinateur :

- **LM Studio** pour les modèles de conversation et les tâches utilitaires ;
- **ComfyUI** pour les avatars, les scènes et le Studio Image ;
- **Chatterbox Multilingual V3** comme moteur vocal local recommandé ;
- **Qwen3-TTS 0.6B Base** comme moteur vocal expérimental facultatif.

L’interface, les personnages, les conversations, les mémoires, les images et les réglages restent stockés localement. AmiorAI n’intègre aucun poids de modèle IA volumineux et ne nécessite aucun service cloud payant.

> AmiorAI est un projet communautaire partagé gratuitement. Les modèles IA, LoRA, nœuds ComfyUI et logiciels externes conservent leurs propres licences et conditions d’utilisation.

## Fonctions principales

| Fonction | Description |
|---|---|
| Conversations locales | Connexion au serveur compatible OpenAI de LM Studio. |
| Création de personnages | Personnalité, scénario, message d’accueil, description physique, avatar et voix. |
| Mémoire persistante | Conservation des personnages et conversations entre les sessions. |
| Affichage roleplay | Rendu distinct des dialogues, narrations et expressions. |
| Génération d’images | Workflows Flux 2 Klein avec références et workflow unifié Krea 2. |
| Gestion des LoRA | Dossiers locaux, classification, aperçus et attribution personnage/style. |
| Studio Image | Prompts modifiables, choix des modèles, réglages du sampler et historique. |
| Voix locale | Chatterbox par défaut et Qwen3-TTS comme option avancée. |
| Gestion de la VRAM | Déchargement coordonné de TTS, LM Studio et ComfyUI. |
| Interface mobile/LAN | Interface responsive pour un réseau local privé de confiance. |
| Diagnostic | Vérification de LM Studio, ComfyUI, modèles, workflows, chemins et TTS. |
| Interface multilingue | Français, anglais, espagnol et allemand. |

## Avant de télécharger

AmiorAI est la couche applicative. Une installation locale complète demande généralement :

1. AmiorAI ;
2. LM Studio et au moins un modèle chat/instruction compatible ;
3. ComfyUI et des modèles d’image compatibles si vous souhaitez générer des images ;
4. l’installateur Chatterbox ou Qwen si vous souhaitez utiliser la voix.

Aucun poids de modèle IA n’est inclus dans le dépôt Git ni dans l’archive de l’application.

## Installation rapide

### 1. Télécharger et extraire

Téléchargez la dernière archive depuis la page **Releases** du dépôt GitHub, puis extrayez-la dans un dossier accessible en écriture, par exemple :

```text
D:\AmiorAI
```

Ne lancez pas AmiorAI directement depuis l’archive ZIP.

### 2. Installer AmiorAI

Lancez :

```text
install.bat
```

L’installateur télécharge un Python Embedded officiel et isolé pour AmiorAI, puis installe les dépendances nécessaires. Il n’installe ni LM Studio, ni ComfyUI, ni les poids des modèles IA.

### 3. Démarrer l’application

Lancez :

```text
start.bat
```

L’interface locale s’ouvre à l’adresse :

```text
http://127.0.0.1:8800
```

### 4. Connecter LM Studio

1. Installez et ouvrez LM Studio.
2. Téléchargez puis chargez un modèle chat/instruction.
3. Démarrez le serveur local depuis la section Developer de LM Studio.
4. Conservez l’adresse par défaut sauf modification volontaire :

```text
http://127.0.0.1:1234/v1
```

5. Dans AmiorAI, ouvrez **Réglages → Modèle de langage**, actualisez la liste, choisissez le modèle de conversation et testez-le.

### 5. Connecter ComfyUI pour les images

1. Installez et démarrez ComfyUI.
2. Dans AmiorAI, ouvrez **Réglages → ComfyUI**.
3. Sélectionnez le dossier ComfyUI contenant directement `main.py`.
4. Sélectionnez son exécutable Python si la détection automatique échoue.
5. Conservez l’adresse par défaut :

```text
http://127.0.0.1:8188
```

6. Ouvrez **Diagnostic** et corrigez tous les éléments critiques rouges avant la première génération.

### 6. Installer la voix locale, facultatif

Pour le moteur Chatterbox recommandé :

```text
tts_server\install.bat
```

Pour le moteur expérimental Qwen :

```text
tts_server\install_qwen.bat
```

Chaque moteur possède son propre Python Embedded et ne nécessite aucun Python système.

## Première utilisation

Pour effectuer un premier test complet :

1. Ouvrez **Réglages** et testez LM Studio.
2. Configurez ComfyUI et lancez **Diagnostic** si vous souhaitez utiliser les images.
3. Ouvrez **Personnages** et créez un personnage.
4. Définissez son nom, sa personnalité, son scénario, son message d’accueil et sa description physique.
5. Importez ou générez son avatar.
6. Créez une conversation et envoyez le premier message.
7. Utilisez **Donner vie à cette scène** pour générer la scène actuelle.
8. Activez le TTS puis utilisez **▶ Écouter** sous une réponse du personnage.
9. Consultez les images dans **Galerie**.
10. Sauvegardez `%LOCALAPPDATA%\AmiorAI\data` avant toute mise à jour importante.

## Documentation

- [Installation et configuration complètes](#installation-et-configuration-complètes)
- [Guide d’utilisation](#guide-dutilisation)
- [Installation de la voix](#système-vocal)
- [Dépannage](#dépannage)
- [Documentation anglaise](README.md)
- [Démarrage rapide](docs/QUICKSTART.md)
- [Dépannage détaillé](docs/TROUBLESHOOTING.md)
- [Journal des modifications](docs/CHANGELOG.md)
- [Avertissement légal](LEGAL_NOTICE.md)
- [Licences tierces](THIRD_PARTY_NOTICES.md)

---

# Installation et configuration complètes

## 1. Prérequis

### Nécessaire pour l’application principale

- Windows 10 ou Windows 11 64 bits ;
- un dossier d’installation accessible en écriture ;
- assez d’espace disque pour l’application et les modèles externes ;
- LM Studio avec au moins un modèle chat/instruction.

### Recommandé pour les images et la voix

- une carte graphique NVIDIA RTX ;
- ComfyUI ;
- des modèles Flux 2 Klein ou Krea 2 compatibles ;
- assez de VRAM pour les modèles choisis.

Une carte de 16 Go peut convenir en activant les options de libération de VRAM d’AmiorAI, mais la taille des modèles, la résolution et le contexte restent déterminants.

### Logiciels externes officiels

- [Site officiel de LM Studio](https://lmstudio.ai/)
- [Documentation du serveur local LM Studio](https://lmstudio.ai/docs/developer/core/server)
- [Guide officiel ComfyUI Windows Portable](https://docs.comfy.org/installation/comfyui_portable_windows)
- [Guide officiel ComfyUI Desktop Windows](https://docs.comfy.org/installation/desktop/windows)

Évitez les repacks non officiels provenant de sources inconnues.

## 2. Installer AmiorAI

1. Extrayez l’intégralité de l’archive.
2. Lancez `install.bat`.
3. Lisez l’avertissement légal affiché.
4. Acceptez uniquement si vous êtes d’accord.
5. Attendez le message confirmant la fin de l’installation.
6. Démarrez AmiorAI avec `start.bat`.

Le runtime principal est installé dans `python_embed`. Il reste indépendant des deux runtimes TTS optionnels.

## 3. Configurer LM Studio

AmiorAI utilise LM Studio pour le modèle de conversation et, si souhaité, un modèle utilitaire distinct.

### Choisir un modèle

Sélectionnez un modèle qui :

- prend en charge les instructions ou le chat ;
- tient dans votre RAM/VRAM ;
- possède une licence adaptée à votre usage ;
- suit correctement les consignes de roleplay et les demandes structurées.

Un modèle utilitaire distinct peut être utile pour la création de personnages, les prompts d’image, les résumés et les tâches JSON. Lorsqu’il est désactivé, AmiorAI réutilise le modèle de conversation.

### Démarrer le serveur LM Studio

1. Ouvrez LM Studio.
2. Ouvrez la section **Developer**.
3. Démarrez le serveur local.
4. Utilisez le port `1234` sauf modification volontaire.
5. Chargez le modèle choisi ou activez le chargement Just-In-Time si votre version de LM Studio le permet.

Adresse par défaut :

```text
http://127.0.0.1:1234/v1
```

### Choisir les modèles dans AmiorAI

1. Ouvrez **Réglages → Modèle de langage**.
2. Vérifiez l’adresse LM Studio.
3. Cliquez sur **Actualiser la liste des modèles**.
4. Sélectionnez le modèle de conversation.
5. Testez-le.
6. Activez éventuellement un modèle utilitaire distinct.
7. Sélectionnez et testez ce modèle.
8. Sauvegardez la section.

Si un modèle n’apparaît pas, vérifiez que le serveur LM Studio fonctionne et que `/v1/models` expose bien son identifiant exact.

## 4. Configurer ComfyUI

AmiorAI communique avec ComfyUI via son API locale.

Adresse par défaut :

```text
http://127.0.0.1:8188
```

### ComfyUI Windows Portable

Exemple de chemins :

```text
Dossier ComfyUI :
D:\ComfyUI_windows_portable\ComfyUI

Python ComfyUI :
D:\ComfyUI_windows_portable\python_embeded\python.exe
```

Le dossier sélectionné doit contenir directement `main.py`.

### ComfyUI Desktop

Démarrez une première fois ComfyUI Desktop et vérifiez qu’une image peut être générée. Vous pouvez ensuite :

- laisser ComfyUI ouvert manuellement et désactiver le lancement automatique dans AmiorAI ;
- ou indiquer à AmiorAI le véritable dossier ComfyUI et son environnement Python.

### Installation manuelle, venv ou Stability Matrix

Ces installations sont compatibles à condition que :

- ComfyUI démarre correctement ;
- l’adresse configurée soit accessible ;
- AmiorAI connaisse le dossier contenant `main.py` ;
- le bon exécutable Python soit sélectionné si le lancement automatique est activé.

### Configuration dans AmiorAI

1. Ouvrez **Réglages → ComfyUI**.
2. Indiquez l’adresse de l’API ComfyUI.
3. Sélectionnez le dossier contenant `main.py`.
4. Sélectionnez l’exécutable Python de ComfyUI si nécessaire.
5. Activez le lancement automatique uniquement lorsque les deux chemins sont corrects.
6. Sauvegardez la section.
7. Ouvrez **Diagnostic** et testez ComfyUI.

## 5. Modèles d’image

AmiorAI ne redistribue aucun poids de modèle d’image. Téléchargez les modèles depuis des sources de confiance et vérifiez leurs licences.

### Krea 2

Le workflow Krea 2 unifié fourni attend des composants sélectionnables tels que :

```text
Modèle de diffusion :
krea2_turbo_fp8_scaled.safetensors

Encodeur de texte :
qwen3vl_4b_fp8_scaled.safetensors

VAE :
qwen_image_vae.safetensors
```

Dossiers ComfyUI habituels :

```text
ComfyUI\models\diffusion_models\
ComfyUI\models\text_encoders\
ComfyUI\models\vae\
ComfyUI\models\loras\
```

Dans **Studio Image** :

1. choisissez **Krea 2** ;
2. sélectionnez le modèle de diffusion, l’encodeur de texte et le VAE ;
3. choisissez le profil sampler, le ratio et le nombre de mégapixels ;
4. sélectionnez éventuellement le LoRA personnage 1, le LoRA personnage 2/persona et un LoRA utilitaire ;
5. placez les emplacements inutilisés sur `none` ;
6. sauvegardez puis lancez Diagnostic.

Krea 2 utilise des prompts text-to-image descriptifs. L’identité est renforcée par le LoRA du personnage, son token et sa description physique.

### Flux 2 Klein

Flux 2 Klein prend en charge :

- un UNet GGUF ou Safetensors ;
- un encodeur de texte et un VAE compatibles ;
- des emplacements LoRA optionnels ;
- des workflows avec images de référence pour les scènes solo, duo, trio et groupe.

Dans **Studio Image** :

1. choisissez **Flux 2 Klein** ;
2. sélectionnez le mode GGUF ou Safetensors ;
3. choisissez l’UNet correspondant ;
4. sélectionnez l’encodeur et le VAE compatibles ;
5. configurez les LoRA optionnels ;
6. sauvegardez puis lancez Diagnostic.

Le mode GGUF nécessite le nœud ComfyUI `UnetLoaderGGUF`.

## 6. Nœuds ComfyUI manquants

Lorsque Diagnostic signale des nœuds absents :

1. mettez ComfyUI à jour ;
2. notez le nom exact de chaque nœud manquant ;
3. utilisez ComfyUI Manager pour rechercher un paquet fiable fournissant ces nœuds ;
4. redémarrez complètement ComfyUI ;
5. relancez Diagnostic.

Selon le workflow, les noms peuvent notamment inclure :

```text
ResolutionSelector
UnetLoaderGGUF
ReferenceLatent
Flux2Scheduler
EmptyFlux2LatentImage
```

Les nœuds personnalisés exécutent du code Python sur votre ordinateur. Installez uniquement des sources et auteurs de confiance.

## 7. Système vocal

AmiorAI v40 propose deux moteurs vocaux entièrement locaux :

- **Chatterbox Multilingual V3** — recommandé et sélectionné par défaut ;
- **Qwen3-TTS 0.6B Base** — optionnel et expérimental.

### Installer Chatterbox

Lancez :

```text
tts_server\install.bat
```

Cela crée :

```text
tts_server\python_chatterbox
```

Le moteur utilise un Python 3.11.9 Embedded officiel et isolé.

Si AmiorAI affiche `No module named 'chatterbox'`, fermez l’application puis lancez :

```text
tts_server\repair_chatterbox.bat
```

Attendez le message `Chatterbox import: OK`, puis redémarrez AmiorAI.

### Installer Qwen3-TTS, facultatif

Lancez :

```text
tts_server\install_qwen.bat
```

Cela crée le runtime indépendant :

```text
tts_server\python_qwen
```

Pour obtenir le meilleur clonage Qwen, renseignez les paroles exactes de l’échantillon dans le champ **Transcription de l’échantillon vocal** du personnage. Cette transcription reste facultative pour Chatterbox.

### Configurer la voix dans AmiorAI

1. Ouvrez **Réglages → Voix / TTS**.
2. Activez la synthèse vocale.
3. Sélectionnez Chatterbox ou Qwen.
4. Conservez l’adresse `http://127.0.0.1:8810` sauf modification volontaire.
5. Activez le lancement automatique.
6. Conservez **Libérer la VRAM entre les moteurs** sur les cartes disposant de peu de VRAM.
7. Sauvegardez la section.
8. Ouvrez une conversation et cliquez sur **▶ Écouter** sous une réponse du personnage.

Le bouton haut-parleur situé en haut de la conversation active ou désactive la lecture automatique. Le bouton **▶ Écouter** permet une lecture manuelle de chaque réponse.

### Préparer un échantillon vocal

Utilisez un échantillon propre d’environ 6 à 20 secondes :

- une seule personne ;
- aucune musique ;
- peu de bruit de fond ;
- une voix naturelle ;
- un format accepté par AmiorAI.

Utilisez uniquement une voix vous appartenant ou pour laquelle vous disposez d’une autorisation claire. N’utilisez pas la synthèse vocale pour usurper l’identité ou tromper une personne.

### Coordination de la VRAM

Lorsque **Libérer la VRAM entre les moteurs** est activé :

1. AmiorAI arrête le processus TTS CUDA avant le chargement de LM Studio ou ComfyUI ;
2. cet arrêt libère le contexte CUDA de PyTorch ;
3. avant la lecture suivante, AmiorAI décharge LM Studio et demande à ComfyUI de libérer ses modèles inactifs ;
4. le moteur vocal sélectionné redémarre automatiquement.

Un TTS exécuté sur CPU n’est pas arrêté puisqu’il n’utilise aucune VRAM.

---

# Guide d’utilisation

## 1. Créer un personnage

Ouvrez **Personnages** et créez une nouvelle fiche. Les champs les plus importants sont :

- le nom ;
- la personnalité et le comportement ;
- le scénario ou contexte ;
- le premier message ;
- la description physique ;
- le token d’identité ou les réglages LoRA ;
- l’avatar et l’échantillon vocal facultatifs.

Une personnalité précise et concrète produit généralement des réponses plus cohérentes qu’une longue liste d’adjectifs vagues.

## 2. Démarrer une conversation

1. Sélectionnez un personnage.
2. Créez une conversation.
3. Choisissez ou rédigez le contexte initial.
4. Envoyez un message.
5. Utilisez **Continuer** pour prolonger la dernière réponse du modèle.

Le modèle, la taille du contexte, la longueur des réponses et la température se règlent dans les paramètres.

## 3. Générer une scène depuis le chat

Utilisez **Donner vie à cette scène** pour créer un prompt d’image à partir de la conversation récente. AmiorAI combine le personnage sélectionné, les informations pertinentes de la persona et la scène en cours.

Utilisez **Personnage uniquement** lorsque l’image doit contenir uniquement le personnage choisi.

Relisez le prompt modifiable avant la génération lorsque la précision est importante.

## 4. Utiliser le Studio Image

Le Studio Image sert aux générations manuelles indépendantes d’une conversation. Il permet :

- de choisir la famille de modèle ;
- de modifier le prompt ;
- de régler la résolution et le ratio ;
- de choisir un profil sampler ;
- de sélectionner les LoRA et leur intensité ;
- de retrouver l’historique des générations.

## 5. Utiliser une persona

La persona optionnelle représente l’utilisateur ou un second sujet récurrent. Elle peut contenir :

- un nom ;
- une description physique ;
- une image de référence ;
- un token d’identité Krea ;
- un LoRA persona et son intensité.

Les informations de persona sont utilisées uniquement lorsque le workflow et la scène les nécessitent.

## 6. Gérer les LoRA et les dossiers de modèles

Utilisez la bibliothèque de modèles et la page LoRA pour :

- ajouter des dossiers locaux ;
- relancer un scan ;
- corriger la famille détectée d’un modèle ;
- tester ou prévisualiser les LoRA ;
- ajouter des favoris ;
- affecter des LoRA au personnage, à la persona ou au rendu.

Ne placez jamais vos tokens personnels, modèles payants ou données privées dans le dépôt Git.

## 7. Galerie et fichiers utilisateur

Les images générées et fichiers importés sont conservés dans le dossier de données local d’AmiorAI. Utilisez **Galerie** pour consulter les créations et sauvegardez régulièrement le dossier de données.

## 8. Interface mobile et mode LAN

L’interface mobile est prévue pour un réseau local privé de confiance.

- gardez le code d’accès confidentiel ;
- n’exposez jamais les ports `8800`, `1234`, `8188` ou `8810` sur Internet ;
- ne créez pas de redirection de ports sur le routeur ;
- désactivez le mode LAN lorsque vous ne l’utilisez pas.

---

# Données, mises à jour et sauvegardes

## Emplacement des données locales

Sous Windows, les données persistantes se trouvent normalement dans :

```text
%LOCALAPPDATA%\AmiorAI\data
```

Ce dossier peut contenir :

- la base de données ;
- les personnages et conversations ;
- les mémoires ;
- les images et sons générés ;
- les avatars et images de persona importés ;
- les sauvegardes ;
- les journaux.

Le dossier de l’application et le dossier de données sont distincts. Supprimer le dossier source ne supprime pas nécessairement les données utilisateur.

## Avant une mise à jour

1. Fermez AmiorAI.
2. Sauvegardez `%LOCALAPPDATA%\AmiorAI\data`.
3. Extrayez la nouvelle version dans un dossier d’application propre, sauf indication explicite d’un correctif à superposer.
4. Ne recopiez pas d’anciens runtimes Python sur les nouveaux sans instruction.
5. Lancez la nouvelle version puis exécutez Diagnostic.

---

# Dépannage

## Module Chatterbox absent

Fermez AmiorAI puis lancez :

```text
tts_server\repair_chatterbox.bat
```

Le journal détaillé se trouve dans :

```text
tts_server\install_chatterbox_pip.log
```

## Le bouton ▶ Écouter est absent

Utilisez la v40.0.3 ou une version ultérieure. Dans **Réglages → Voix / TTS**, activez le TTS puis sauvegardez la section. Le bouton manuel apparaît sous les réponses du personnage ; le haut-parleur situé en haut contrôle la lecture automatique.

## LM Studio est inaccessible

- démarrez le serveur local LM Studio ;
- vérifiez `http://127.0.0.1:1234/v1` ;
- actualisez la liste des modèles ;
- sélectionnez un identifiant exact exposé par LM Studio ;
- vérifiez qu’aucune autre application n’utilise le port `1234`.

## LM Studio renvoie une réponse vide ou invalide

- utilisez un modèle chat/instruction ;
- augmentez la limite de tokens de sortie ;
- réduisez la taille du contexte si la mémoire est insuffisante ;
- testez un autre modèle utilitaire pour les tâches JSON ;
- consultez Diagnostic et les journaux.

## AmiorAI ne démarre pas ComfyUI

- sélectionnez le dossier contenant directement `main.py` ;
- sélectionnez le véritable exécutable Python de ComfyUI ;
- vérifiez le port `8188` ;
- démarrez ComfyUI manuellement puis désactivez son lancement automatique ;
- consultez `%LOCALAPPDATA%\AmiorAI\data\logs\comfyui.log`.

## Un modèle n’apparaît pas dans un sélecteur

- placez-le dans le bon dossier ComfyUI ;
- redémarrez ou actualisez ComfyUI ;
- rescanez la bibliothèque AmiorAI ;
- vérifiez l’extension et la famille détectée ;
- utilisez l’identification manuelle en cas d’erreur de détection.

## Mémoire GPU insuffisante

- choisissez un modèle de langage plus petit ou plus quantifié ;
- réduisez le contexte LM Studio ;
- réduisez la résolution ou le nombre d’étapes ;
- fermez les autres applications utilisant le GPU ;
- activez la libération de VRAM entre les moteurs ;
- utilisez Diagnostic pour identifier le moteur occupant encore la VRAM.

Plus d’informations : [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md).

---

# Dépôt Git et contributions

Le dépôt Git ignore volontairement :

- les runtimes Python Embedded et environnements virtuels ;
- les poids de modèles IA ;
- les voix, personnages et conversations personnels ;
- les images et sons générés ;
- les bases de données, journaux, secrets et tokens API ;
- les archives ZIP de release.

Après un clonage du dépôt, lancez `install.bat` pour reconstruire le runtime principal. Lancez les installateurs TTS uniquement si vous souhaitez utiliser ces moteurs.

Fichiers principaux :

```text
README.md                documentation GitHub anglaise
README_FR.md             documentation GitHub française
install.bat              installateur principal Windows
start.bat                lanceur Windows
LICENSE                  licence Apache 2.0
NOTICE                   copyright AmiorAI
LEGAL_NOTICE.md          avertissement et responsabilités
THIRD_PARTY_NOTICES.md   licences et sources externes
.gitignore               exclusions des runtimes, modèles et données privées
```

---

# Licence, copyright et responsabilité

**Copyright © 2026 Ariku.**

Le code source original d’AmiorAI est distribué sous **Apache License 2.0**. Consultez [`LICENSE`](LICENSE) et [`NOTICE`](NOTICE).

AmiorAI est fourni **en l’état**, sans garantie. L’utilisateur reste responsable des modèles, LoRA, prompts, contenus générés, sauvegardes, stabilité matérielle, confidentialité, droits liés aux voix et respect de la législation applicable. Lisez [`LEGAL_NOTICE.md`](LEGAL_NOTICE.md) avant l’installation ou le partage du logiciel.

Les logiciels, paquets Python, poids de modèles, LoRA, workflows et nœuds personnalisés provenant de tiers restent soumis à leurs propres licences. Consultez [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).
