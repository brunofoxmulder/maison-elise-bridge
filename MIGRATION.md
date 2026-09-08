# Migration vers le dépôt dédié Maison Élise Bridge

## Décision

Maison Élise Bridge est séparé du dépôt `brunofoxmulder/elise-investigator` afin d'empêcher les commits et versions de développement d'Élise Investigator d'apparaître comme des mises à jour HACS du Bridge.

## Source de référence

- Ancien dépôt : `brunofoxmulder/elise-investigator`
- Branche Bridge validée : `bridge-dev8-cloudhook-ui`
- Commit de référence : `3e03138b19926be37de14d62a1f2f9a7d30f0181`
- Version fonctionnelle : `0.1.0-dev.8`

## Contrôle d'intégrité du transfert

Les fichiers d'exécution suivants ont été repris à l'identique ; leurs blob SHA Git sont identiques à la source dev.8 :

- `__init__.py` : `8b59c212fc6b1e821987e8af38b16764de6ad87b`
- `config_flow.py` : `3edc35d3dfd6f5449cf9afc01faae733c2856f40`
- `const.py` : `95bdf365a132d377e152b8d0c2a7374809d05ff5`
- `strings.json` : `dd9c710f14364ececb3097ab817aa15e3c06e8eb`
- `translations/fr.json` : identique à `strings.json`

Le seul changement volontaire dans le composant est `manifest.json` : les champs `documentation` et `issue_tracker` pointent désormais vers `brunofoxmulder/maison-elise-bridge`. La version reste `0.1.0-dev.8`.

## État Home Assistant

Aucune modification Home Assistant, HACS, Cloudhook ou Lambda Alexa n'est réalisée par cette migration GitHub préparatoire.

L'installation actuellement opérationnelle doit rester en place jusqu'à validation explicite de la migration HACS vers ce dépôt dédié.

## Étape suivante

Après validation explicite : remplacer la source HACS du Bridge par `brunofoxmulder/maison-elise-bridge`, vérifier que le composant proposé est toujours `0.1.0-dev.8`, puis seulement après contrôle effectuer la bascule sans recréer l'entrée d'intégration et sans changer le Cloudhook.
