# ComTray

Petit utilitaire Windows qui se loge dans la zone de notification et indique **quel appareil USB est branché sur quel port COM** — plus besoin d'ouvrir le Gestionnaire de périphériques.

## Fonctions

- Icône avec le nombre de ports COM présents, liste au **survol**, liste complète au **clic gauche**
- **Détection instantanée** des branchements (événements Windows, sans attendre)
- **Popups** à chaque connexion (vert) / déconnexion (rouge), indépendantes des notifications Windows, sur l'écran de son choix (principal, celui de la souris, ou un écran précis)
- Par appareil (clic droit) :
  - **Renommer** — le nom suit l'appareil quel que soit le port COM attribué
  - **Vitesse** par défaut mémorisée (bauds)
  - **Couleur** pour le repérer dans le menu et les popups
  - **Ouvrir un terminal** (PuTTY, KiTTY, Tera Term… détecté automatiquement ou au choix) sur le bon port à la bonne vitesse
  - **Qui utilise ce port ?** — trouve le programme qui bloque le port et propose de le fermer
  - Détails : VID:PID, n° de série, fabricant, port USB physique
- Les adaptateurs **sans n° de série** (CH340, certains CP210x) sont identifiés par leur **port USB physique**
- **Historique** des connexions/déconnexions (menu + journal complet)
- Option pour masquer/afficher les ports non USB (COM1 de la carte mère…)
- **Mises à jour** : vérification automatique sur GitHub et installation en un clic
- Lancement au démarrage, instance unique

Configuration : `%APPDATA%\ComTray\` (`devices.json`, `settings.json`, `history.log`).

## Installation

Télécharger depuis la page [Releases](https://github.com/Darkmind64/ComTray/releases) :

- `ComTray-Setup-x.y.z.exe` — installateur (sans droits admin, démarrage rapide)
- `ComTray.exe` — version portable (fichier unique)

## Compilation

Prérequis : Python 3.10+, [Inno Setup 6](https://jrsoftware.org/isinfo.php) (pour l'installateur).

```bat
build.bat
```

Produit `dist\ComTray.exe` (portable), `dist\app\ComTray\` et `installer\ComTray-Setup-x.y.z.exe`.

## Limites

- Un programme lancé **en administrateur** n'apparaît pas dans « Qui utilise ce port ? » si ComTray ne l'est pas.
- Un adaptateur sans n° de série change d'identité s'il est branché sur un autre port USB physique.
