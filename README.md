# Spotify Playlist Suite 🎵⚡

Eine vollständige, lokal und im Docker (Proxmox / Home Assistant) laufende Web-App (Python FastAPI Backend + minimalistisches Dark-Mode Frontend), die einen mächtigen **Playlist Inspector / Editor**, globale Spotify-Suche, Multi-Playlist Merging und **kostenlose Google Gemini KI-Modelle** vereint.

---

## 🌟 Kernfunktionen

1. **🔍 Playlist Inspector / Editor (Standard-Ansicht)**
   - Öffne eine beliebige eigene Playlist und filtere/bearbeite sie live:
   - **Live-Filter:** Suchbegriff (Titel/Artist/Album), Release-Jahre (z. B. `2000–2015`), Mindest-/Maximal-Popularity und Artist-Gewichtungsstatus (*Banned*, *Soft-Banned*, *Boosted*).
   - **Quick-Actions pro Artist:** Direkt neben jedem Song per Klick auf `⛔ 0.0` (Hard-Ban), `⚠️ 0.3` (Soft-Ban), `1.0` (Normal) oder `⭐ 1.8` (Boost) setzen – die SQLite-DB wird sofort aktualisiert!
   - **Duplikate aufspüren & bereinigen:** Erkennt Duplikate automatisch und entfernt sie per Klick auf Spotify.
   - **Reordering auf Spotify:** Sortiere die Playlist nach Popularity, Release-Datum, Artist-Gewichtung oder KI-Vibe und **speichere die neue Reihenfolge permanent in deinem Spotify-Account**.
   - **Sub-Playlist abzweigen:** Speichere die aktuell gefilterten Songs als neue Sub-Playlist ab.

2. **🤖 Flexible & Kostenlose Gemini-Modelle (Live von Google abrufbar)**
   - Unterstützt alle kostenlosen Gemini-Modelle (wie `gemini-2.5-flash`, `gemini-2.5-flash-lite`, `gemini-2.0-flash`, `gemini-1.5-flash`, etc.).
   - **Live-Modell-Abruf:** Rufe per Button in den Einstellungen direkt die aktuellsten Modelle von Google AI ab.
   - **API-Key direkt im Web-UI eintragbar:** Kein manuelles Editieren von `.env` auf dem Server nötig – trage den Key einfach in den Einstellungen ein.

3. **🔀 Playlist-Mixer & Mood-Extraktor (Multi-Playlist Merge)**
   - Wähle mehrere deiner Playlists und/oder deine **Lieblingssongs (Liked Songs)** als Pool aus.
   - **Zweistufiges Filtering:**
     1. *Vorfilter:* Mindest-Popularity Slider (unbekannte Lückenfüller aussortieren) + SQLite Artist Weights (Hard-Ban/Soft-Ban/Boost).
     2. *KI-Bewertung:* Gemini bewertet alle verbleibenden Tracks im Batch (0–10) auf Passgenauigkeit zum Ziel-Mood.
   - Ergebnis wird dedupliziert, kombiniert gescored und direkt als neue Spotify-Playlist gespeichert.

4. **✨ AI Playlist Generator (Globale Suche)**
   - Freier Mood-Prompt (z. B. *"White Girl Music 2010s Throwback"*, *"Dark Driving Techno"*).
   - Gemini generiert strukturierte Suchstrategien (Genres, Tags, Tracks, Playlists).
   - Sortierung nach Spotify Popularity, Balanced (max. 3/Artist) oder Hidden Gems.

5. **🔐 Headless Docker OAuth Fix für Proxmox**
   - OAuth-Token und SQLite-DB liegen im persistenten Docker-Volume `/app/data`.
   - **Manuelles Fallback-Feld im UI:** Falls dein Browser beim Login auf dem Proxmox-Server zu `http://localhost:8000/callback?code=...` umgeleitet wird, kopierst du einfach die URL aus der Adresszeile und fügst sie unter *Settings & Gemini* ein.

6. **📡 Home Assistant Integration**
   - Endpunkte: `POST /api/generate` & `POST /api/merge-playlists`
   - Fertige Vorlage mit `rest_command` und Automationen in [`home_assistant_examples.yaml`](home_assistant_examples.yaml).

---

## 🛠️ GitHub Repository & Umzug auf Proxmox

### Schritt 1: GitHub Repository umbenennen / hochladen

Das Repository heißt jetzt **`spotify-playlist`**:

```powershell
cd C:\Projects\spotify-ui
# Git Remote auf dein neues Repository setzen:
git remote set-url origin https://github.com/DEIN-USERNAME/spotify-playlist.git
# Oder falls noch kein Remote existiert:
# git remote add origin https://github.com/DEIN-USERNAME/spotify-playlist.git

git branch -M main
git push -u origin main
```

### Schritt 2: Spotify Developer Dashboard Redirect-URI

Unter [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard) → deine App → **Settings** → **Redirect URIs**:
- `http://localhost:8000/callback` (für lokalen Test)
- `http://<DEINE-PROXMOX-IP>:8000/callback` (für deinen Proxmox-Server)

### Schritt 3: Auf Proxmox starten (Docker Compose)

Auf deinem Proxmox-Server (im LXC-Container oder VM):

```bash
cd /opt
git clone https://github.com/DEIN-USERNAME/spotify-playlist.git
cd spotify-playlist
cp .env.example .env
nano .env   # Keys eintragen & SPOTIPY_REDIRECT_URI mit deiner Proxmox-IP befüllen

# Starten
docker compose up -d --build
```

### Schritt 4: Im Browser öffnen & verbinden

1. Öffne `http://<DEINE-PROXMOX-IP>:8000` im Browser.
2. Klicke auf **Connect Spotify**.
3. Unter **Settings & Gemini** kannst du jederzeit:
   - Deinen Gemini API Key eintragen / ändern.
   - Kostenlose Gemini-Modelle live von Google abrufen und auswählen.

---

## 🧪 Tests ausführen

```bash
.venv\Scripts\activate
pytest -v
```

---

## 📁 Projektstruktur

```
C:\Projects\spotify-ui\
├── main.py                     # FastAPI App Entrypoint
├── requirements.txt            # Python Dependencies
├── .env.example                # Config-Vorlage
├── docker-compose.yml          # Proxmox / Docker Setup (spotify-playlist)
├── Dockerfile                  # Python 3.12 Slim Container
├── home_assistant_examples.yaml # Home Assistant rest_commands & Automationen
├── README.md
│
├── app/
│   ├── config.py               # Pydantic Settings & Scopes
│   ├── database.py             # SQLite Async (ArtistWeight & AppSetting DB)
│   ├── spotify_client.py       # Spotipy OAuth & Headless Token Injection
│   ├── gemini_service.py       # Gemini Live Model Fetching, Strategy & Batch Scoring
│   ├── playlist_generator.py   # Multi-Playlist Merge, Scoring, Filter, Reordering
│   │
│   ├── routers/
│   │   ├── auth.py             # OAuth Login, Callback & Manual Token Endpoint
│   │   ├── playlist.py         # POST /api/generate
│   │   ├── library.py          # GET /api/library/* & POST /api/merge-playlists
│   │   ├── inspect.py          # POST /api/inspect/* (Filter, Duplicates, Reorder)
│   │   ├── settings_router.py  # GET/POST /api/settings/gemini & Live Model Fetch
│   │   ├── artists.py          # GET/POST/DELETE /api/artists/weights
│   │   └── devices.py          # GET /api/devices & Transfer
│   │
│   ├── templates/index.html    # Inspector als Default-Tab + Gemini Settings UI
│   └── static/
│       ├── style.css           # Styling
│       └── app.js              # Interaktives Frontend
│
└── tests/
    ├── test_playlist.py        # 36 Basistests (Scoring, Persistence, Gemini)
    └── test_power_user.py      # Power-User Tests (Merge, Batch Score, Inspector, Settings)
```
