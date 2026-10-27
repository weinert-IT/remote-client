#!/usr/bin/env python3
"""Macht aus einem RustDesk-Checkout den weinert-IT-Client.

  SERVER_KEY=... python3 scripts/prepare.py PFAD/ZU/rustdesk

1. Patches anwenden (patches/rustdesk auf das Repo, patches/hbb_common auf
   libs/hbb_common).
2. Markenkonfiguration nach res/brand/custom.json schreiben; der Client baut
   sie fest ein (src/common.rs: EMBEDDED_BRAND_CONFIG).
3. Namen in Windows-Ressourcen, Cargo-Metadaten und Android-Manifest ersetzen.
4. Icons und Logos aus brand/*.svg erzeugen.

Jede Textersetzung muss genau passen; sonst bricht das Skript ab, damit eine
neue RustDesk-Version nicht unbemerkt halb umbenannt gebaut wird.

Braucht git, rsvg-convert (librsvg2-bin) und Pillow.
"""
import io
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRAND = os.path.join(ROOT, "brand")


def die(msg):
    sys.exit("prepare: " + msg)


def load_brand():
    with open(os.path.join(BRAND, "brand.json"), encoding="utf-8") as f:
        b = json.load(f)
    # The app name names the exe, the Windows service and the URI scheme, and
    # lands unquoted in sc/taskkill commands (src/platform/windows.rs).
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9-]*", b["app_name"]):
        die("app_name darf nur Buchstaben, Ziffern und '-' enthalten: %r" % b["app_name"])
    return b


def apply_patches(src):
    for sub, target in (("rustdesk", src), ("hbb_common", os.path.join(src, "libs", "hbb_common"))):
        d = os.path.join(ROOT, "patches", sub)
        for name in sorted(os.listdir(d)):
            if not name.endswith(".patch"):
                continue
            p = os.path.join(d, name)
            r = subprocess.run(["git", "apply", "--check", p], cwd=target, capture_output=True, text=True)
            if r.returncode != 0:
                die("Patch %s/%s passt nicht:\n%s" % (sub, name, r.stderr))
            subprocess.run(["git", "apply", p], cwd=target, check=True)
            print("gepatcht: %s/%s" % (sub, name))


def replace(src, rel, old, new, count=1):
    path = os.path.join(src, rel)
    with open(path, encoding="utf-8") as f:
        text = f.read()
    n = len(re.findall(old, text)) if isinstance(old, re.Pattern) else text.count(old)
    if n != count:
        die("Ersetzung passt nicht (%d statt %d Treffer): %s\n%s" % (n, count, rel, getattr(old, "pattern", old)))
    text = old.sub(new, text) if isinstance(old, re.Pattern) else text.replace(old, new)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def write_config(src, b, server_key):
    override = {
        "custom-rendezvous-server": b["server"],
        "relay-server": b["server"],
        "api-server": b["api"],
        "key": server_key,
    }
    override.update(b.get("override_settings", {}))
    cfg = {
        "app-name": b["app_name"],
        "app-display-name": b["display_name"],
        "update-public-key": b.get("update_public_key", ""),
        "default-settings": b.get("default_settings", {}),
        "override-settings": override,
    }
    with open(os.path.join(src, "res", "brand", "custom.json"), "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def rename(src, b):
    app, disp, company = b["app_name"], b["display_name"], b["company"]
    copyright_ = "© %s · based on RustDesk (AGPL-3.0)" % company
    legal = re.compile(r'LegalCopyright = "[^"]*"')
    for rel, desc in (("Cargo.toml", 0), (os.path.join("libs", "portable", "Cargo.toml"), 1)):
        replace(src, rel, legal, 'LegalCopyright = "%s"' % copyright_)
        replace(src, rel, 'ProductName = "RustDesk"', 'ProductName = "%s"' % disp)
        replace(src, rel, 'FileDescription = "RustDesk Remote Desktop"', 'FileDescription = "%s"' % disp)
        if desc:
            replace(src, rel, 'description = "RustDesk Remote Desktop"', 'description = "%s"' % disp)
    replace(src, "Cargo.toml", 'OriginalFilename = "rustdesk.exe"', 'OriginalFilename = "%s.exe"' % app)

    rc = os.path.join("flutter", "windows", "runner", "Runner.rc")
    replace(src, rc, 'VALUE "CompanyName", "Purslane Tech Pte. Ltd."', 'VALUE "CompanyName", "%s"' % company)
    replace(src, rc, 'VALUE "FileDescription", "RustDesk Remote Desktop"', 'VALUE "FileDescription", "%s"' % disp)
    replace(src, rc, re.compile(r'VALUE "LegalCopyright", "[^"]*"'), 'VALUE "LegalCopyright", "%s"' % copyright_)
    replace(src, rc, 'VALUE "ProductName", "RustDesk"', 'VALUE "ProductName", "%s"' % disp)
    replace(src, rc, 'VALUE "OriginalFilename", "rustdesk.exe"', 'VALUE "OriginalFilename", "%s.exe"' % app)

    android = os.path.join("flutter", "android", "app")
    # Own application id: installs next to RustDesk instead of replacing it. The
    # Kotlin namespace stays, it only names the code.
    replace(src, os.path.join(android, "build.gradle"), 'applicationId "com.carriez.flutter_hbb"',
            'applicationId "%s"' % b["android_package"])
    manifest = os.path.join(android, "src", "main", "AndroidManifest.xml")
    replace(src, manifest, 'android:label="RustDesk"', 'android:label="%s"' % disp)
    replace(src, manifest, 'android:label="RustDesk Input"', 'android:label="%s Input"' % disp)
    replace(src, manifest, '<data android:scheme="rustdesk" />', '<data android:scheme="%s" />' % app.lower())
    replace(src, os.path.join(android, "src", "main", "res", "values", "strings.xml"),
            '<string name="app_name">RustDesk</string>', '<string name="app_name">%s</string>' % disp)

    # Android start dialog (patch 0004): a hint to share only with the own
    # support instead of RustDesk's generic scam warning.
    hint = {
        "de.rs": ("Fernwartung durch %s" % company,
                  "Starten Sie die Freigabe nur, wenn Sie gerade mit %s sprechen oder einen Termin mit uns vereinbart haben." % company,
                  "Ruft Sie jemand Unbekanntes an und verlangt Zugriff auf Ihr Gerät, beenden Sie das Gespräch und melden Sie sich bei uns."),
        "en.rs": ("Remote support by %s" % company,
                  "Only start sharing if you are talking to %s right now or have an appointment with us." % company,
                  "If someone you don't know calls and asks for access to your device, hang up and contact us."),
    }
    for name, (title, text1, text2) in hint.items():
        rel = os.path.join("src", "lang", name)
        for key, value in (("scam_title", title), ("scam_text1", text1), ("scam_text2", text2)):
            replace(src, rel, re.compile(r'\("%s", "[^"]*"\)' % key), '("%s", "%s")' % (key, value))


def svg_png(svg, width=None, height=None):
    args = ["rsvg-convert", "-f", "png"]
    if width:
        args += ["-w", str(width)]
    if height:
        args += ["-h", str(height)]
    args.append(svg)
    from PIL import Image
    return Image.open(io.BytesIO(subprocess.run(args, check=True, capture_output=True).stdout)).convert("RGBA")


def square(img, size, pad=0.0):
    """img centered on a transparent square canvas, scaled to fit with padding."""
    from PIL import Image
    inner = int(round(size * (1 - 2 * pad)))
    im = img.copy()
    im.thumbnail((inner, inner), Image.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.paste(im, ((size - im.width) // 2, (size - im.height) // 2), im)
    return canvas


def enclosing_circle(points):
    """Smallest circle around points (Welzl, iterative): (x, y, r)."""
    import random

    def circle2(a, b):
        x, y = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
        return x, y, ((a[0] - x) ** 2 + (a[1] - y) ** 2) ** 0.5

    def circle3(a, b, c):
        d = 2 * (a[0] * (b[1] - c[1]) + b[0] * (c[1] - a[1]) + c[0] * (a[1] - b[1]))
        if abs(d) < 1e-9:
            return max((circle2(a, b), circle2(a, c), circle2(b, c)), key=lambda k: k[2])
        sa, sb, sc = a[0] ** 2 + a[1] ** 2, b[0] ** 2 + b[1] ** 2, c[0] ** 2 + c[1] ** 2
        x = (sa * (b[1] - c[1]) + sb * (c[1] - a[1]) + sc * (a[1] - b[1])) / d
        y = (sa * (c[0] - b[0]) + sb * (a[0] - c[0]) + sc * (b[0] - a[0])) / d
        return x, y, ((a[0] - x) ** 2 + (a[1] - y) ** 2) ** 0.5

    def inside(k, p):
        return (p[0] - k[0]) ** 2 + (p[1] - k[1]) ** 2 <= k[2] ** 2 + 1e-6

    pts = list(points)
    random.Random(0).shuffle(pts)
    k = (pts[0][0], pts[0][1], 0.0)
    for i, p in enumerate(pts):
        if inside(k, p):
            continue
        k = (p[0], p[1], 0.0)
        for j, q in enumerate(pts[:i]):
            if inside(k, q):
                continue
            k = circle2(p, q)
            for r in pts[:j]:
                if not inside(k, r):
                    k = circle3(p, q, r)
    return k


def fit_circle(big, size, radius):
    """big scaled and placed so that the smallest circle around its visible
    pixels is centered with radius * size: launchers cut icons to a circle, and
    every outer corner then keeps the same distance to its edge (an uneven
    shape such as two hexagons above one is not centered by its box)."""
    from PIL import Image
    w, h = big.size
    alpha = big.getchannel("A").load()
    edge = []  # the outermost visible pixels of each row suffice
    for y in range(h):
        xs = [x for x in range(w) if alpha[x, y] > 16]
        if xs:
            edge += [(xs[0], y), (xs[-1] + 1, y), (xs[0], y + 1), (xs[-1] + 1, y + 1)]
    cx, cy, far = enclosing_circle(edge)
    f = radius * size / far
    im = big.resize((max(1, round(w * f)), max(1, round(h * f))), Image.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.paste(im, (round(size / 2 - cx * f), round(size / 2 - cy * f)), im)
    return canvas


def icons(src):
    from PIL import Image
    icon_svg = os.path.join(BRAND, "icon.svg")
    # Crop to the drawn content first, so empty space in the SVG's viewBox does
    # not shift the symbol off-center.
    raw = svg_png(icon_svg, width=1024)
    big = square(raw.crop(raw.getbbox()), 1024)
    sized = lambda n, pad=0.0: square(big, n, pad)

    def save(img, *rel):
        path = os.path.join(src, *rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        img.save(path)

    def save_ico(*rel):
        path = os.path.join(src, *rel)
        sized(256).save(path, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])

    # Desktop (res/ and the Windows runner)
    save(sized(1024), "res", "icon.png")
    for n, name in ((32, "32x32.png"), (64, "64x64.png"), (128, "128x128.png"), (256, "128x128@2x.png")):
        save(sized(n), "res", name)
    save_ico("res", "icon.ico")
    save_ico("res", "tray-icon.ico")
    save_ico("flutter", "windows", "runner", "resources", "app_icon.ico")

    # Flutter UI: assets/icon.* (loadIcon) and the logo above the ID (loadLogo,
    # max 300x60, light/dark variants picked by theme).
    with open(icon_svg, encoding="utf-8") as f, open(os.path.join(src, "flutter", "assets", "icon.svg"), "w", encoding="utf-8") as g:
        g.write(f.read())
    save(sized(256), "flutter", "assets", "icon.png")
    save(svg_png(os.path.join(BRAND, "logo-light.svg"), height=120), "flutter", "assets", "logo_light.png")
    save(svg_png(os.path.join(BRAND, "logo-dark.svg"), height=120), "flutter", "assets", "logo_dark.png")

    # Android launcher icons. Launchers cut them to a circle, so the symbol is
    # scaled to its farthest point, not its bounding box: the adaptive
    # foreground must stay inside the 66 dp safe circle of its 108 dp canvas
    # (radius 33/108, with some air), the round legacy icon inside its circle.
    # The notification icon is a white silhouette as Android requires.
    res = ("flutter", "android", "app", "src", "main", "res")
    for dpi, scale in (("mdpi", 1), ("hdpi", 1.5), ("xhdpi", 2), ("xxhdpi", 3), ("xxxhdpi", 4)):
        d = res + ("mipmap-" + dpi,)
        launcher = int(48 * scale)
        save(sized(launcher, 0.04), *d, "ic_launcher.png")
        save(fit_circle(big, launcher, 0.44), *d, "ic_launcher_round.png")
        save(fit_circle(big, int(108 * scale), 0.28), *d, "ic_launcher_foreground.png")
        stat = sized(int(24 * scale), 0.02)
        white = Image.new("RGBA", stat.size, (255, 255, 255, 0))
        white.putalpha(stat.getchannel("A"))
        save(white, *d, "ic_stat_logo.png")


def main(src):
    key = os.environ.get("SERVER_KEY", "").strip()
    if not key:
        die("SERVER_KEY fehlt (öffentlicher Schlüssel des ID-Servers, Repo-Variable SERVER_KEY)")
    b = load_brand()
    if not b.get("update_public_key"):
        print("prepare: Warnung: update_public_key leer, Auto-Update ist in diesem Build aus")
    apply_patches(src)
    write_config(src, b, key)
    rename(src, b)
    icons(src)
    print("fertig: %s (%s)" % (b["display_name"], b["app_name"]))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        die(__doc__)
    main(sys.argv[1])
