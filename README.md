# wIT-Remote

Fernwartungs-Client von weinert-IT: [RustDesk](https://github.com/rustdesk/rustdesk)
mit eigenem Namen, Logo und fest eingestelltem Server (`rd.weinert-it.com`),
dazu ein eigener, signierter Update-Kanal über den weinert-IT-Server.

Dieses Repo enthält nur die Änderungen; der Build holt RustDesk in der Version
aus `RUSTDESK_REF` (`.github/workflows/build.yml`) und wendet sie an.

## Inhalt

| Pfad | Zweck |
|---|---|
| `brand/brand.json` | Namen, Server, Android-Paket, Voreinstellungen und gesperrte Einstellungen |
| `brand/*.svg` | Icon und Logos (hell/dunkel); daraus entstehen alle Icons |
| `patches/rustdesk/` | Änderungen am RustDesk-Code |
| `patches/hbb_common/` | Änderungen an `libs/hbb_common` |
| `scripts/prepare.py` | Patches anwenden, Konfiguration einbauen, umbenennen, Icons erzeugen |
| `scripts/sign_release.py` | Update-Pakete signieren (`update.json`), Schlüssel erzeugen |

### Patches

- **0001-brand-config:** Die Markenkonfiguration (`res/brand/custom.json`, von
  `prepare.py` erzeugt) ist fest im Programm, im selben Format wie RustDesks
  Custom-Client-Konfiguration, aber ohne deren Signatur. Der App-Name
  `wIT-Remote` benennt auch Exe, Dienst, Pfade und URI-Schema und darf deshalb
  nur Buchstaben, Ziffern und `-` enthalten (RustDesk setzt ihn ungequotet in
  `sc`- und `taskkill`-Befehle); ein abweichender Anzeigename für Fenster, Tray
  und Texte ginge über `display_name` in `brand.json`.
- **0002-update-channel:** Updates kommen nicht von GitHub/RustDesk, sondern von
  `{api-server}/api/client/update`. Der Server entscheidet, welches Paket ein Gerät
  bekommt; der Client installiert es nur, wenn Größe, SHA-256 und die
  ed25519-Signatur des Release-Builds passen (`src/brand_update.rs`). Der
  Heartbeat kann ein Update sofort anstoßen ("Jetzt aktualisieren"), und der
  sysinfo-Upload meldet die Build-Nummer.
- **0003-retire-rustdesk:** Bei der Installation wird ein vorhandener
  RustDesk-Dienst gestoppt und deaktiviert (nicht entfernt).
- **0004-android-start-hint:** Der Dialog vor dem Starten der Freigabe unter
  Android zeigt statt RustDesks allgemeiner Betrugswarnung einen Hinweis im
  eigenen Branding: Freigabe nur im Gespräch mit dem eigenen Support (Texte
  setzt `prepare.py` mit dem Firmennamen aus `brand.json`).
- **0005-version-and-update-button:** Die Versionsanzeige enthält die
  Build-Nummer. Unter Einstellungen → Über gibt es unter Windows (installiert)
  „Nach Updates suchen“: Prüfung über den eigenen Update-Kanal, Installation
  nach Bestätigung mit derselben Signaturprüfung.
- **0006-cursor-outline-offset:** Behebt einen Fehler in RustDesk beim
  Erfassen von Mauszeigern mit Umriss (Windows-Zeiger mit invertierten
  Pixeln): Das Bild wurde um eine Zeile minus zwei Pixel versetzt in den
  Umriss kopiert, die linke Kante des Zeigers erschien rechts daneben.
- **0007-tray-hidden-by-strategy:** `hide-tray` wirkt auch als normale
  Option, also per Strategie vom API-Server für einzelne Geräte oder Gruppen
  (RustDesk liest es sonst nur aus den fest eingebauten Einstellungen). Gilt
  ab dem nächsten Start des Tray-Programms.
- **hbb_common/0001-migrate-config:** Beim ersten Start übernimmt der Client die
  Konfiguration einer vorhandenen RustDesk-Installation. ID, Schlüsselpaar und
  Passwort bleiben so erhalten.

## Build

GitHub Actions, manuell gestartet (Actions → *Build wIT-Remote* → Run
workflow). Mit **publish** entsteht ein Release `v{Version}-b{Build}` mit:

- `wIT-Remote-<version>-b<build>-x86_64.msi`: Windows-Installer (MSI)
- `wIT-Remote-<version>-b<build>-x86_64.exe`: Windows (Installer/portabel)
- `wIT-Remote-<version>-b<build>-aarch64.apk`: Android
- `update.json`: signierte Liste der Pakete für den Update-Server

Einstellungen im Repo:

| Art | Name | Inhalt |
|---|---|---|
| Variable | `SERVER_KEY` | öffentlicher Schlüssel des ID-Servers (`id_ed25519.pub`) |
| Secret | `UPDATE_SIGNING_KEY` | ed25519-Seed; öffentlicher Teil in `brand.json` → `update_public_key` |
| Secret | `ANDROID_SIGNING_KEY` | Keystore (JKS) als Base64 |
| Secret | `ANDROID_ALIAS`, `ANDROID_KEY_STORE_PASSWORD`, `ANDROID_KEY_PASSWORD` | dazu |

Neues Update-Schlüsselpaar: `pip install cryptography && python3 scripts/sign_release.py --keygen`.
Wer den Schlüssel tauscht, muss erst einen Build mit dem neuen öffentlichen
Schlüssel verteilen; ältere Clients nehmen nur Pakete mit dem alten an.

Lokal prüfen, ob alle Patches auf eine RustDesk-Version passen:

```bash
git clone --depth 1 --branch 1.5.0 --recurse-submodules --shallow-submodules https://github.com/rustdesk/rustdesk.git /tmp/rd
SERVER_KEY=test python3 scripts/prepare.py /tmp/rd
```

### Lokal unter Windows

`scripts/build-windows.ps1` macht dieselben Schritte wie der CI-Job `windows`
(PowerShell als Administrator):

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\build-windows.ps1 -Setup        # Werkzeuge per winget, Flutter, vcpkg, Rust (einmalig)
# neue PowerShell öffnen
.\scripts\build-windows.ps1 -RustDeskDir <vorbereiteter Baum> -ServerKey "<id_ed25519.pub>" -Build 1
```

Ergebnis: `out\wIT-Remote-<version>-b<build>-x86_64.{exe,msi}`. Der erste Lauf
dauert 1,5–2 h (vcpkg baut ffmpeg und die Codecs).

Der vorbereitete Baum ist ein RustDesk-Checkout, auf den `prepare.py` schon
angewandt wurde und der die Bridge-Dateien enthält (`src/bridge_generated*.rs`,
`flutter/lib/generated_bridge*.dart`). Beides entsteht am einfachsten unter
Linux: `prepare.py` braucht `rsvg-convert` für die Icons, die Bridge erzeugt
RustDesks `.github/workflows/bridge.yml` (Flutter 3.22.3,
`flutter_rust_bridge_codegen` 1.80.1, `cargo-expand` 1.0.95). Ohne `-RustDeskDir`
klont das Skript RustDesk selbst; die Bridge-Dateien kommen dann über `-BridgeDir`.

Korrekturen am RustDesk-Code gehören als Patch nach `patches/`, sonst gehen sie
beim nächsten `prepare.py` verloren (`git diff` im Quellbaum, für
`libs/hbb_common` dort eigenes `git diff`).

## Umstieg von RustDesk (Windows)

Den **exe**-Installer auf dem PC ausführen und installieren. Der Client übernimmt
ID und Passwort von RustDesk und deaktiviert dessen Dienst. Läuft der Umstieg
über eine RustDesk-Sitzung, bricht diese dabei kurz ab; danach ist der PC unter
derselben ID wieder erreichbar. RustDesk kann anschließend deinstalliert werden.

Danach aktualisiert sich der Client selbst über den Update-Server.

## Lizenz

AGPL-3.0 wie RustDesk (`LICENSE`). Wer den Client erhält, kann den Quellcode
(dieses Repo + RustDesk in der angegebenen Version) hier beziehen.
