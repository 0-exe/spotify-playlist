# Spotify AI Playlist & Power-User Suite 🎵⚡

Eine vollständige, lokal und im Docker (Proxmox / Home Assistant) laufende Web-App (Python FastAPI Backend + minimalistisches Dark-Mode Frontend), die globale Spotify-Suche, eigene Playlists/Liked Songs und **Gemini 2.5 Flash KI** kombiniert.

---

## 🚀 Neue Power-User Features (v2.0)

1. **✨ AI Playlist Generator (Globale Suche)**
   - Freier Prompt (z. B. *"White Girl Music 2010s Throwback"*, *"Dark Driving Techno"*)
   - Gemini generiert strukturierte Suchstrategien (Genres, Tags, Tracks, Playlists)
   - Sortierung nach Spotify Popularity, Balanced (max. 3/Artist) oder Hidden Gems

2. **🔀 Playlist-Mixer & Mood-Extraktor (Multi-Playlist Merge)**
   - Mehrere eigene Playlists und/oder Lieblingssongs (Liked Songs) als Quellen-Pool auswählen
   - **Zweistufiges Filtering:**
     1. *Vorfilter:* Mindest-Popularity Slider (unbekannte Filler aussortieren) + SQLite Artist Weights (Hard-Ban/Soft-Ban/Boost)
     2. *KI-Bewertung:* Gemini 2.5 Flash bewertet alle Kandidaten im Batch von 0–10 auf Passgenauigkeit zum Ziel-Mood
   - Automatisches Deduplizieren und Speichern als neue Spotify-Playlist

3. **🔍 Playlist Inspector (Filtern & Reordering)**
   - Beliebige eigene Playlist öffnen
   - Live-Filter: Suchbegriff, Mindest-/Maximal-Popularity, Release-Zeitraum (z. B. 2000–2015), Artist-Status (Banned/Soft/Boost) oder KI-Vibe Score
   - **Bulk-Aktionen:**
     - 🔍 Duplikate automatisch aufspüren & mit einem Klick entfernen
     - 💾 Playlist intern neu ordnen (nach Popularity, Release-Jahr, Artist-Weight, KI-Score) und neue Reihenfolge auf Spotify speichern
     - 🗑️ Gefilterte Songs per Klick löschen
     - ✨ Gefilterte Songs als neue Sub-Playlist abzweigen
     - 🎚️ Direkte Quick-Buttons (⛔ 0.0, ⚠️ Soft 0.3, 1.0, ⭐ 1.8) neben jedem Artist

4. **🔐 Headless Docker OAuth Fix für Proxmox**
   - Unterstützt normalen Browser-Callback sowie manuelles Fallback-Feld im UI (*"Redirect-URL hier einfügen"*), falls Spotify bei Docker auf Proxmox auf `localhost` weiterleitet.
   - Persistente Speicherung von `.spotify_cache` und `spotify_ui.db` im Docker-Volume `/app/data`.

5. **📡 Home Assistant Integration**
   - Endpunkte: `POST /api/generate` & `POST /api/merge-playlists`
   - Fertige Vorlage mit `rest_command` und Automationen in [`home_assistant_examples.yaml`](home_assistant_examples.yaml).

---

## 🛠️ Installation & Lokaler Start

### 1. Repository vorbereiten & .env anlegen

```bash
git clone https://github.com/DEIN-USERNAME/spotify-ai-playlist.git
cd spotify-ai-playlist
cp .env.example .env
```

Fülle `.env` aus:
```env
SPOTIPY_CLIENT_ID=deine_client_id
SPOTIPY_CLIENT_SECRET=dein_client_secret
SPOTIPY_REDIRECT_URI=http://localhost:8000/callback   # bzw. http://PROXMOX_IP:8000/callback
GEMINI_API_KEY=dein_gemini_api_key
```

### 2. Spotify App Redirect URI einrichten
Unter [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard) in deiner App:
- `http://localhost:8000/callback` (lokal)
- `http://<DEINE-PROXMOX-IP>:8000/callback` (Proxmox-Server)

### 3. Lokal mit venv starten

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

pip install -r requirements.txt
mkdir data
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

Browser öffnen: **http://localhost:8000**

---

## 🐳 Proxmox Docker Setup (Docker Compose)

Auf deinem Proxmox-Host (oder in einem Debian/Ubuntu LXC Container mit Docker):

```bash
cd /opt
git clone https://github.com/DEIN-USERNAME/spotify-ai-playlist.git
cd spotify-ai-playlist
cp .env.example .env
nano .env   # IP deines Proxmox-Servers eintragen!

# Container starten
docker compose up -d --build
```

### Spotify Einmal-Login auf Proxmox:
1. Im Browser `http://<PROXMOX_IP>:8000` öffnen.
2. Auf **Connect Spotify** klicken.
3. Falls dein Browser dich auf `http://localhost:8000/callback?code=...` leitet und einen Verbindungsfehler anzeigt:
   - **Kopiere einfach die gesamte URL aus der Adresszeile**
   - Gehe in der Web-App auf den Tab **Settings & Auth**
   - Füge die URL in das Feld *"Headless Docker OAuth"* ein und klicke auf *"Token manuell übertragen"*.
   - Fertig! Der Token wird im Docker-Volume `/app/data` dauerhaft gespeichert.

---

## 🧪 Tests ausführen

```bash
.venv\Scripts\activate
pytest -v
```

Alle **55 Tests** testen u.a.:
- Scoring, Artist-Caps, Soft-Ban (0.1–0.4), Hard-Ban (0.0), Boost (1.5–2.0)
- Multi-Playlist Merging & Deduplizierung
- Batch-Vibe-Scoring mit Gemini (gemockt)
- Playlist Inspector Live-Filterung, Duplikate-Erkennung und Reordering
- REST-Endpunkte `/api/merge-playlists` und `/api/auth/manual-token`

---

## 📁 Projektstruktur

```
C:\Projects\spotify-ui\
├── main.py                     # FastAPI App Entrypoint
├── requirements.txt            # Python Dependencies
├── .env.example                # Config-Vorlage
├── docker-compose.yml          # Proxmox / Docker Setup
├── Dockerfile                  # Python 3.12 Slim Container
├── home_assistant_examples.yaml # Home Assistant rest_commands & Automationen
├── README.md
│
├── app/
│   ├── config.py               # Pydantic Settings & Scopes
│   ├── database.py             # SQLite Async (ArtistWeight DB)
│   ├── spotify_client.py       # Spotipy OAuth & Headless Token Injection
│   ├── gemini_service.py       # Gemini 2.5 Flash Suchstrategie & Batch Vibe Scoring
│   ├── playlist_generator.py   # Multi-Playlist Merge, Scoring, Filter, Reordering
│   │
│   ├── routers/
│   │   ├── auth.py             # OAuth Login, Callback & Manual Token Endpoint
│   │   ├── playlist.py         # POST /api/generate
│   │   ├── library.py          # GET /api/library/* & POST /api/merge-playlists
│   │   ├── inspect.py          # POST /api/inspect/* (Filter, Duplicates, Reorder)
│   │   ├── artists.py          # GET/POST/DELETE /api/artists/weights
│   │   └── devices.py          # GET /api/devices & Transfer
│   │
│   ├── templates/index.html    # Tab-basiertes Dark-Mode Interface
│   └── static/
│       ├── style.css           # Styling
│       └── app.js              # Interaktives Frontend
│
└── tests/
    ├── test_playlist.py        # 36 Basistests (Scoring, Persistence, Gemini)
    └── test_power_user.py      # 19 Power-User Tests (Merge, Batch Score, Inspector)
```
