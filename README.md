# 📚 KDP Performance Dashboard

> **Private Amazon Review & Book Performance Monitor**
> Una dashboard web moderna, privata e protetta per monitorare in tempo reale le recensioni e le performance dei tuoi libri pubblicati con Amazon KDP.

---

## 🌟 Funzionalità Principali

- 🔒 **Accesso Privato con Autenticazione Reale**: Schermata di login protetta lato server con password hashing avanzato (`bcrypt`), sessioni crittografate e logout. Nessun dato esposto pubblicamente.
- 📊 **Dashboard Analitica Completa**:
  - **KPI in tempo reale**: Libri monitorati, recensioni totali, nuove recensioni a 7/30/90 giorni con indicatori di trend (↗ crescita, → stabile, ↘ calo), rating medio complessivo.
  - **Sezioni Intelligenti**: *Top Performers* (ordinati per crescita recensioni) e *Attenzione Richiesta* (alert per rating < 4.0, errori di scansione o nuove recensioni critiche $\le$ 3 stelle).
  - **Indicatori di Stato Visivi**: 🟢 OK, 🟡 Attenzione, 🔴 Errore.
- 📖 **Dettaglio Libro e Storico**:
  - Grafico e distribuzione stelle (da 5★ a 1★ con percentuali e barre visive).
  - Storico temporale cumulativo delle recensioni.
  - Elenco recensioni con evidenziazione speciale per recensioni a 1, 2 o 3 stelle.
- ⚙️ **Amministrazione Completa 100% da Dashboard**:
  - **Gestione Libri**: Aggiungi ASIN (con autogenerazione URL prodotto e validazione), modifica dati, disattiva/riattiva monitoraggio temporaneamente, eliminazione definitiva con doppia conferma.
  - **Configurazione Frequenza Dinamica**: 1 ora, 6 ore, 12 ore, 1 giorno (24h), 3 giorni, 7 giorni.
  - **Gestione Email Notifiche**: Modifica email destinataria, attiva/disattiva notifiche, pulsante per invio immediato di email di test.
  - **URL Dashboard Personalizzabile**: Configura l'URL pubblico per i pulsanti `👉 APRI DASHBOARD` nelle email.
  - **Sicurezza**: Cambio password direttamente dall'interfaccia con verifica della password corrente.
  - **Controllo Manuale**: Pulsante `🔄 Esegui Controllo Adesso` per lanciare subito la scansione da web.
  - **Registro Audit**: Storico delle ultime 20 attività amministrative (login, modifiche libri, cambio impostazioni).
- ✉️ **Notifiche Email Intelligenti**:
  - **Bootstrap Silenzioso**: Al primo avvio di un libro, salva lo storico esistente senza inviare centinaia di email.
  - **Rilevamento Nuove Recensioni**: Invia una notifica solo quando compaiono recensioni realmente nuove.
  - **Email Consolidata**: In caso di recensioni multiple nello stesso controllo, invia una singola email riepilogativa.
  - **Pulsanti Diretti**: Link immediato `👉 APRI DASHBOARD` e link diretto Amazon per ogni recensione/prodotto.
- 🌐 **Supporto Multi-Marketplace Amazon**:
  - `amazon.it` 🇮🇹
  - `amazon.com` 🇺🇸
  - `amazon.co.uk` 🇬🇧
  - `amazon.de` 🇩🇪
  - `amazon.fr` 🇫🇷
  - `amazon.es` 🇪🇸
- 🤖 **Parser Robusto & Fallback**:
  - Parsing multi-selettore BeautifulSoup4.
  - Distinzione chiara tra `OK`, `NO_REVIEWS`, `PAGE_UNAVAILABLE` e `PARSER_ERROR` (non interpreta blocchi o captcha come 0 recensioni).
  - Supporto per fallback Playwright headless (se configurato).

---

## 🏗️ Architettura 100% GitHub-Native

Questa applicazione è progettata per funzionare in modo **completamente autonomo e senza server esterni (No Render, No PaaS)** sfruttando esclusivamente l'ecosistema GitHub:

1. **Persistenza su Git**: Il database SQLite (`data/kdp_monitor.db`) è tracciato e versionato direttamente nel repository.
2. **Automazione Notturna (GitHub Actions)**:
   - Ogni notte alle **03:00 UTC** (04:00/05:00 ora italiana), GitHub Actions esegue automaticamente la scansione di tutti i libri su Amazon.
   - Può essere eseguito anche manualmente su richiesta (pulsante **Run workflow** su GitHub o da app mobile).
3. **Notifiche Email al Mattino**:
   - Invia una notifica consolidata via email con tutte le nuove recensioni trovate (stelle, testo, autore, link Amazon).
   - Se non ci sono nuove recensioni, invia un report di riepilogo "Heartbeat" a conferma del corretto funzionamento del controllo.
4. **Auto-Commit e Push**:
   - Al termine della scansione, GitHub Actions effettua il commit e il push automatico di `data/kdp_monitor.db`, garantendo la persistenza continua dello storico senza costi e senza database esterni.


---

## 📁 Struttura del Progetto

```
kdp-performance-dashboard/
├── app/
│   ├── main.py                  # Entrypoint FastAPI, sessioni e lifespan DB
│   ├── config.py                # Configurazione settings da .env / DB
│   ├── database.py              # Engine SQLAlchemy & SessionLocal
│   ├── models.py                # Modelli ORM (Book, Review, CheckRun, Setting, AuditLog)
│   ├── schemas.py               # Schemi Pydantic
│   ├── auth.py                  # Autenticazione server-side & hashing password
│   ├── amazon/
│   │   ├── marketplace.py       # Domini e generatori URL Amazon
│   │   ├── client.py            # Client HTTP + Playwright fallback
│   │   └── parser.py            # Parser BeautifulSoup4 multi-selettore
│   ├── reviews/
│   │   ├── monitor.py           # Engine di controllo, bootstrap e scheduling
│   │   └── statistics.py        # Calcolo KPI, distribuzioni e trend
│   ├── notifications/
│   │   └── email.py             # Formattazione HTML/TXT e invio SMTP
│   ├── routes/
│   │   ├── auth.py              # /login, /logout
│   │   ├── dashboard.py         # /, /book/{id}, /reviews
│   │   ├── books.py             # /books (Aggiungi, Modifica, Disattiva, Elimina)
│   │   └── settings.py          # /settings (Email, Frequenza, Password, Test, Scan)
│   ├── templates/               # Template Jinja2 responsive
│   │   ├── base.html
│   │   ├── login.html
│   │   ├── dashboard.html
│   │   ├── books.html
│   │   ├── book_detail.html
│   │   ├── reviews.html
│   │   └── settings.html
│   └── static/
│       ├── css/style.css        # CSS moderno responsive (slate theme)
│       └── js/app.js            # Modali e interazioni client
├── scripts/
│   ├── run_monitor.py           # Script CLI per eseguire il controllo
│   └── set_admin_password.py    # Script CLI per resettare la password
├── tests/                       # Suite di test pytest completa
│   ├── fixtures/                # HTML Amazon mock per i test
│   ├── test_auth.py
│   ├── test_parser.py
│   ├── test_monitor.py
│   ├── test_statistics.py
│   ├── test_email.py
│   └── test_routes.py
├── .github/
│   └── workflows/
│       ├── monitor.yml          # GitHub Actions per scansione programmata
│       └── tests.yml            # CI test runner
├── .env.example
├── .gitignore
├── requirements.txt
└── README.md
```

---

## 🚀 Installazione e Avvio Locale

### 1. Clona o apri la cartella del progetto
```bash
git clone <URL_DEL_TUO_REPO>
cd kdp-performance-dashboard
```

### 2. Crea e attiva un ambiente virtuale Python
Su Linux/macOS:
```bash
python3 -m venv venv
source venv/bin/activate
```
Su Windows (PowerShell):
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

### 3. Installa le dipendenze
```bash
pip install -r requirements.txt
```

### 4. Configura le variabili d'ambiente
Copia il file `.env.example` in `.env`:
```bash
cp .env.example .env
```
Modifica il file `.env` inserendo:
- `APP_SECRET_KEY`: una stringa casuale lunga e sicura.
- `ADMIN_PASSWORD`: la password iniziale per accedere alla dashboard.
- `SMTP_USER` e `SMTP_PASSWORD`: le credenziali Gmail (App Password da 16 caratteri).
- `ALERT_EMAIL`: la tua email su cui ricevere gli alert.

### 5. Avvia la Dashboard
```bash
uvicorn app.main:app --reload --port 8000
```
Apri il browser su: **`http://localhost:8000`**

---

## 🧪 Esecuzione dei Test

Tutti i test utilizzano fixture HTML locali senza effettuare chiamate ad Amazon né inviare email reali:
```bash
pytest -v tests/
```

---

## 🔐 Configurazione Gmail SMTP per le Notifiche

Per consentire l'invio delle email di notifica tramite Gmail:
1. Vai su [Google Account - Sicurezza](https://myaccount.google.com/security).
2. Assicurati che la **Verifica in due passaggi** sia attiva.
3. Cerca **Password per le app** (App Passwords).
4. Crea una nuova password denominata "KDP Monitor".
5. Copia la password generata da 16 caratteri e inseriscila in `SMTP_PASSWORD` nel tuo file `.env` o nei GitHub Secrets.

---

## 📦 Come Creare il Repository GitHub e Pubblicarlo

### 1. Inizializza il repository Git
```bash
git init
git add .
git commit -m "feat: initial release of KDP Performance Dashboard"
```

### 2. File protetti (NON committati)
Grazie a `.gitignore`, i seguenti elementi **non** verranno mai caricati su GitHub:
- File `.env` e `.env.*`
- Database locali `data/*.db` e `*.sqlite`
- Directory `secrets/` e `credentials/`

### 3. Collega il tuo repository GitHub privato
Crea un nuovo repository **Privato** su GitHub e lancia:
```bash
git branch -M main
git remote add origin https://github.com/TUO_USERNAME/kdp-performance-dashboard.git
git push -u origin main
```

---

## 🔑 GitHub Secrets per le Notifiche Email
 
Nel tuo repository GitHub, vai su **Settings** &rarr; **Secrets and variables** &rarr; **Actions** &rarr; **New repository secret** e configura:

| Nome Secret | Descrizione | Esempio |
| :--- | :--- | :--- |
| `SMTP_USER` | Il tuo indirizzo Gmail | `saluccimarco@gmail.com` |
| `SMTP_PASSWORD` | Gmail App Password (16 caratteri) | `abcd efgh ijkl mnop` |
| `ALERT_EMAIL` | Indirizzo email su cui ricevere i report | `saluccimarco@gmail.com` |
| `SMTP_HOST` | (Opzionale) Host SMTP | `smtp.gmail.com` (default) |
| `SMTP_PORT` | (Opzionale) Porta SMTP | `587` (default) |

---


## 📖 Istruzioni d'Uso della Dashboard

### 1. Primo Accesso e Login
1. Naviga all'indirizzo della tua dashboard.
2. Inserisci la password configurata in `ADMIN_PASSWORD` (default: `admin123`).
3. Clicca su **LOGIN**.

### 2. Aggiungere un Libro
1. Vai nella sezione **📚 Libri** o clicca su **+ Aggiungi Libro**.
2. Inserisci l'ASIN di 10 caratteri (es. `B0H6ZDZ2N8`).
3. Seleziona il marketplace (es. `amazon.com` o `amazon.it`).
4. Inserisci il Titolo.
5. Clicca su **SALVA**.
6. Il sistema aggiunge il libro e autogenera il link ufficiale Amazon.

### 3. Eseguire il Monitor e Verificare il Funzionamento
- **Dalla Dashboard**: Vai in **⚙️ Impostazioni** e clicca su **🔄 Esegui Controllo Adesso**.
- **Da Terminale / CLI**:
  ```bash
  python scripts/run_monitor.py --force
  ```
- **Da GitHub Actions**: Vai su **Actions** &rarr; Seleziona **KDP Review Monitor** &rarr; Clicca **Run workflow**.

### 4. Modificare la Password
1. Vai su **⚙️ Impostazioni** &rarr; Sezione **🔒 Sicurezza & Accesso**.
2. Inserisci la password attuale, la nuova password (minimo 6 caratteri) e la conferma.
3. Clicca su **🔑 Cambia Password**.
4. La password verrà crittografata con `bcrypt` e salvata nel database persistente.

---

## 🛡️ Privacy e Sicurezza

- Nessun dato personale, recensione o credenziale viene salvato in repository pubblici o pagine statiche.
- Tutte le chiamate e le pagine sono protette da autenticazione server-side.
- Il database e le sessioni sono crittografati.

---

## 📄 Licenza
Progetto personale distribuito per uso privato.
