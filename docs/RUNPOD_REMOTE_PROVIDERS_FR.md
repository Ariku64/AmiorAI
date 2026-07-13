# AmiorAI — fournisseurs distants et Runpod

AmiorAI reste un **frontend local-first**. Il ne vend pas de crédits, ne loue pas de GPU et ne crée pas de compte chez un fournisseur. L’utilisateur configure son propre serveur ou son propre compte Runpod, accepte les conditions du fournisseur et paie directement ce fournisseur.

## Modes disponibles

### Conversation

- **LM Studio local** : comportement historique, aucune conversation envoyée à un service distant.
- **API compatible OpenAI** : serveur personnel ou service tiers choisi par l’utilisateur.
- **Runpod Serverless — vLLM** : endpoint personnel compatible OpenAI.
- **Runpod Pod — vLLM** : Pod personnel démarré au premier appel, puis arrêté par AmiorAI après la durée d’inactivité configurée.

### Images

- **ComfyUI local** : instance externe locale déjà démarrée.
- **ComfyUI distant** : instance personnelle accessible par HTTPS.
- **Runpod Serverless — ComfyUI** : workflow API envoyé à un endpoint personnel.
- **Runpod Pod — ComfyUI** : Pod personnel démarré à la première génération, puis arrêté après inactivité.

### Voix

Le TTS reste local dans cette version. Chatterbox et Qwen3-TTS ne sont pas envoyés à Runpod.

## Configuration recommandée

Pour une bonne confidentialité sur une petite configuration :

```text
Conversation et mémoire : LM Studio local
Images : Runpod Serverless ou Runpod Pod
Voix : locale
```

Seuls le workflow visuel, le prompt final et les éventuelles images de référence nécessaires à la génération quittent alors le PC. L’historique complet et la base mémoire restent locaux.

## Clés et données locales

Les clés suivantes sont enregistrées dans le gestionnaire de secrets du système lorsque celui-ci est disponible :

- clé du compte Runpod ;
- clé d’une API LLM compatible OpenAI ;
- clé d’une API ComfyUI distante.

Elles ne sont pas écrites dans la base SQLite AmiorAI. Si aucun gestionnaire de secrets compatible n’est disponible, elles restent uniquement en mémoire pour la session et doivent être ressaisies au prochain lancement.

## Runpod Serverless

### LLM vLLM

1. Déployer un endpoint vLLM depuis le Hub Runpod ou depuis le worker officiel.
2. Choisir le modèle et vérifier sa licence.
3. Régler **Active workers** sur `0`.
4. Pour la configuration AmiorAI recommandée, régler **Max workers** sur `1` et **Idle timeout** sur `900 secondes`.
5. Copier l’Endpoint ID dans AmiorAI.
6. Enregistrer la clé Runpod dans la section Cloud & Runpod.
7. Sélectionner l’identifiant exact du modèle exposé par `/models`.

AmiorAI utilise l’API compatible OpenAI de l’endpoint :

```text
https://api.runpod.ai/v2/ENDPOINT_ID/openai/v1
```

### Image ComfyUI

1. Déployer le worker ComfyUI officiel ou une image personnalisée contenant les modèles et custom nodes nécessaires.
2. Exporter les workflows ComfyUI au format **Workflow > Export (API)**.
3. Régler **Active workers** sur `0`, **Max workers** sur `1` et **Idle timeout** sur `900 secondes` si l’on souhaite garder le worker chaud quinze minutes.
4. Copier l’Endpoint ID dans AmiorAI.

AmiorAI envoie :

```json
{
  "input": {
    "workflow": { "...": "workflow ComfyUI API" },
    "images": [
      { "name": "reference.png", "image": "data:image/png;base64,..." }
    ]
  }
}
```

Les images de référence sont facultatives. Attention aux limites de taille des requêtes Runpod : le base64 augmente la taille des fichiers.

### Coût de l’attente Serverless

Un worker Serverless reste facturé pendant son délai d’inactivité. Un délai de quinze minutes réduit les cold starts lors d’une session mais coûte plus cher qu’un arrêt rapide. L’utilisateur peut modifier cette valeur dans son endpoint Runpod ; AmiorAI ne facture et ne rembourse rien.

## Runpod Pod

### Préparation

Le Pod doit exposer son service HTTP :

- vLLM ou autre serveur compatible OpenAI : généralement port `8000` ;
- ComfyUI : port `8188`.

Le proxy Runpod suit généralement cette forme :

```text
https://POD_ID-PORT.proxy.runpod.net
```

Dans AmiorAI, renseigner séparément :

- le **Pod ID** utilisé pour les commandes Start/Stop ;
- l’URL API publique du Pod ;
- la clé Runpod ;
- éventuellement une clé propre au service exposé.

### Cycle automatique

```text
Première requête
→ vérification de l’état du Pod
→ démarrage si nécessaire
→ attente de l’API
→ exécution de la tâche
→ compteur d’inactivité
→ arrêt après 15 minutes par défaut
```

Le compteur ne déclenche aucun arrêt pendant une requête, une génération, un téléchargement ou un flux encore actif. Les Pods LLM et image ont des compteurs indépendants.

### Limites importantes

- L’arrêt automatique dépend d’AmiorAI, du réseau et de l’API Runpod.
- Une panne électrique, un crash brutal, une coupure réseau ou l’arrêt forcé du processus peut empêcher la commande Stop.
- L’utilisateur doit toujours vérifier le tableau de bord Runpod après une session.
- L’arrêt libère le GPU, mais le stockage persistant peut rester facturé.
- Les fichiers importants doivent être placés dans le stockage persistant prévu par le template choisi.

## Confidentialité

En mode distant, les données nécessaires au calcul sont transmises au fournisseur configuré :

- LLM distant : messages et contexte nécessaires à la réponse, avec les extraits de mémoire sélectionnés par AmiorAI ;
- image distante : prompt visuel, workflow, paramètres et images de référence éventuelles.

Le mode local reste le seul mode où les prompts ne quittent jamais le PC. N’utilisez pas un fournisseur distant pour des données que vous ne souhaitez pas lui transmettre.

## Kits fournis

Le dossier `runpod_templates` contient quatre kits :

- `llm_serverless` ;
- `image_serverless` ;
- `llm_pod` ;
- `image_pod`.

Ils donnent des paramètres, variables et contrôles de validation. Ce ne sont pas encore des identifiants de templates publiés sur le Hub Runpod et ils n’incluent aucun poids de modèle.
