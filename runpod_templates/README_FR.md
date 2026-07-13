# Kits de déploiement Runpod pour AmiorAI

Ces dossiers décrivent quatre configurations indépendantes. Ils servent de base reproductible à publier ensuite sur le Hub Runpod ou à copier manuellement dans la console.

Ils ne contiennent :

- aucun modèle ;
- aucune clé ;
- aucun compte Runpod ;
- aucun système de paiement ;
- aucun template Hub déjà publié.

Toujours utiliser la dernière version stable du worker officiel compatible avec le modèle choisi, puis vérifier les notes de version avant déploiement.

| Kit | Usage | Valeurs à saisir dans AmiorAI |
|---|---|---|
| `llm_serverless` | vLLM compatible OpenAI | Endpoint ID + clé Runpod + Model ID |
| `image_serverless` | worker ComfyUI | Endpoint ID + clé Runpod |
| `llm_pod` | serveur vLLM persistant | Pod ID + URL `/v1` + clé Runpod |
| `image_pod` | ComfyUI persistant | Pod ID + URL proxy + clé Runpod |

Les paramètres `endpoint-settings.json` et `pod-settings.json` sont des **presets de référence lisibles**, pas des fichiers garantis importables tels quels dans toutes les versions de la console Runpod.
