# Lancer le projet sur votre machine (Windows)

## Méthode la plus simple : double-clic

1. Ouvrez l’Explorateur de fichiers.
2. Allez dans :
   `C:\Users\HP\smart-ecommerce-marketplace`
3. Double-cliquez sur **`run_local.bat`**.

Le script applique les migrations, vérifie les données de démonstration, démarre
le serveur et ouvre automatiquement votre navigateur sur :

**http://127.0.0.1:8000/**

Pour arrêter : appuyez sur `Ctrl+C` dans la fenêtre noire.

> Le script utilise l’environnement virtuel déjà présent dans `venv/`.
> Aucune installation supplémentaire n’est nécessaire sur cette machine.

## Méthode manuelle (PowerShell)

Ouvrez PowerShell (touche Windows, tapez `PowerShell`, Entrée), puis :

```powershell
cd C:\Users\HP\smart-ecommerce-marketplace

# Optionnel : activer l'environnement virtuel
.\venv\Scripts\Activate.ps1
# Si PowerShell bloque l'activation :
# Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

# Installer les dépendances si besoin
python -m pip install -r requirements.txt

# Préparer la base et les données de démonstration
python manage.py migrate
python manage.py seed_demo

# Démarrer le serveur
python manage.py runserver
```

Puis ouvrez **http://127.0.0.1:8000/**.

Si vous n’activez pas l’environnement virtuel, utilisez directement :

```powershell
.\venv\Scripts\python.exe manage.py runserver
```

## Comptes de démonstration

| Rôle | Identifiant | Mot de passe |
|---|---|---|
| Admin | `admin` / `admin@rukomeza.test` | `Admin#2026` |
| Client | `amina@example.com` | `Customer#2026` |
| Vendeur | `greenbasket@example.com` | `Seller#2026` |

## Pages utiles

| Adresse | Contenu |
|---|---|
| http://127.0.0.1:8000/ | Boutique |
| http://127.0.0.1:8000/shop/ | Catalogue avec filtres |
| http://127.0.0.1:8000/dashboard/ | Dashboard administrateur |
| http://127.0.0.1:8000/dashboard/reports/ | Rapports et graphiques |
| http://127.0.0.1:8000/seller/ | Studio vendeur |
| http://127.0.0.1:8000/api/docs/ | Documentation API |
| http://127.0.0.1:8000/admin/ | Admin Django |

## En cas de problème

### « Le port 8000 est déjà utilisé »

Un ancien serveur tourne encore. Dans PowerShell :

```powershell
netstat -ano | findstr :8000
taskkill /PID <NUMERO_DU_PID> /F
```

Ou lancez sur un autre port :

```powershell
.\venv\Scripts\python.exe manage.py runserver 8001
```

puis ouvrez http://127.0.0.1:8001/.

### « Page inaccessible »

Vérifiez que la fenêtre noire affiche bien :

```text
Starting development server at http://127.0.0.1:8000/
```

et qu’aucun message d’erreur rouge n’apparaît.

### Réinitialiser les données de démonstration

```powershell
.\venv\Scripts\python.exe manage.py seed_demo --reset
```

Cela supprime les commandes/produits de démonstration et les recrée proprement.

## Pour la version en ligne (URL publique HTTPS)

L’adresse `127.0.0.1` est **locale** : elle fonctionne uniquement sur votre
machine. Pour une URL publique accessible par le correcteur, déployez sur Render :

<https://render.com/deploy?repo=https://github.com/joelleruk-lab/smart-ecommerce-marketplace>

Le guide complet est dans [DEPLOYMENT.md](DEPLOYMENT.md).
