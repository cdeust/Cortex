---
name: preflight
description: Diagnostique l'environnement Cortex et guide la réparation (DB, extensions, modèles)
allowed-tools: Bash(python -m mcp_server.doctor*), Bash(python3 -m mcp_server.doctor*), Read
---

## Préflight Cortex $ARGUMENTS

Tu diagnostiques l'installation de Cortex pour un utilisateur qui vient de
cloner le repo ou d'installer le plugin — il n'est ni expert PostgreSQL ni
expert Python. S'il a passé un argument ($ARGUMENTS), c'est le symptôme
qu'il observe : commence par le relier au check concerné.

Exécute `python -m mcp_server.doctor` (essaie `python3` si `python` échoue)
et interprète la sortie :

- Pour CHAQUE check en échec : cite le nom exact du check, explique en une
  phrase ce qu'il vérifie, puis donne LA commande de réparation que le
  doctor propose — telle quelle, prête à copier.
- Ordonne les réparations par dépendance (Python → driver → DATABASE_URL →
  connexion → extensions → filesystem), pas dans l'ordre d'affichage.
- Si tous les checks passent : dis-le en une ligne et indique le premier
  usage (`query_methodology` au prochain démarrage de session).

Format de sortie :
1. **Verdict** : PRÊT / X réparations nécessaires
2. **Réparations dans l'ordre** (numérotées, une commande par étape)
3. **Vérification finale** : la commande à relancer pour confirmer

Ne modifie AUCUN fichier. Ne devine jamais une commande de réparation qui
n'est pas dans la sortie du doctor : si le doctor ne propose rien, dis
« le doctor ne propose pas de fix automatique pour ce check » et cite la
section concernée de PRIVACY.md ou README.md.
