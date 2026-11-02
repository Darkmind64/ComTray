# ComTray

Petit utilitaire Windows qui se loge dans la zone de notification et indique **quel appareil USB est branché sur quel port COM** — plus besoin d'ouvrir le Gestionnaire de périphériques.

## Fonctions

- Icône avec le nombre de ports COM présents
- **Survol** : liste `COMx: appareil`
- **Clic gauche** : liste complète en popup
- **Clic droit** : détails par port (VID:PID, n° de série, fabricant), *Renommer…*, *Copier « COMx »*
- **Popup** à chaque connexion (vert) / déconnexion (rouge) — indépendant des notifications Windows
- Noms personnalisés persistants (clé VID:PID + n° de série), stockés dans `%APPDATA%\ComTray\aliases.json`
- Option *Lancer au démarrage*, raccourci vers le Gestionnaire de périphériques

## Installation

Télécharger depuis la page [Releases](https://github.com/Darkmind64/ComTray/releases) :

- `ComTray-Setup-x.y.z.exe` — installateur (sans droits admin)
- `ComTray.exe` — version portable

## Compilation

Prérequis : Python 3.10+, [Inno Setup 6](https://jrsoftware.org/isinfo.php) (pour l'installateur).

```bat
build.bat
```

Produit `dist\ComTray.exe` et `installer\ComTray-Setup-x.y.z.exe`.

## Limite

Deux adaptateurs identiques sans n° de série (CH340, certains CP210x) partagent le même nom personnalisé.
