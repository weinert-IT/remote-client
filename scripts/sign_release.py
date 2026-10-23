#!/usr/bin/env python3
"""Signiert die Update-Pakete eines Releases und schreibt update.json.

  UPDATE_SIGNING_KEY=... python3 scripts/sign_release.py VERSION BUILD BASE_URL DATEI...

UPDATE_SIGNING_KEY ist der ed25519-Seed (32 Byte, Base64), Secret im Repo; der
öffentliche Teil steht in brand/brand.json (update_public_key) und ist in den
Client eingebaut. Signiert wird je Datei genau der Text aus
src/brand_update.rs (signed_message):

  weinert-it remote-client update v1\\n{version}\\n{build}\\n{os}\\n{arch}\\n{format}\\n{size}\\n{sha256}

Dateinamen: {app}-{version}-b{build}-{arch}.{format}, z. B.
wIT-Remote-1.5.0-b12-x86_64.msi. Der Update-Server liest update.json aus dem
GitHub-Release und bietet die Dateien den Geräten an.

Mit --keygen wird stattdessen ein neues Schlüsselpaar ausgegeben.
"""
import base64
import datetime
import hashlib
import json
import os
import re
import sys

CONTEXT = "weinert-it remote-client update v1"
OS_BY_FORMAT = {"msi": "windows", "exe": "windows", "apk": "android"}
NAME_RE = re.compile(r"^(?P<app>[A-Za-z0-9-]+)-(?P<version>[0-9.]+)-b(?P<build>\d+)-(?P<arch>[a-z0-9_]+)\.(?P<format>msi|exe|apk)$")


def load_key():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    seed = base64.b64decode(os.environ["UPDATE_SIGNING_KEY"].strip())
    if len(seed) == 64:  # libsodium secret key = seed + public key
        seed = seed[:32]
    if len(seed) != 32:
        sys.exit("UPDATE_SIGNING_KEY: 32 Byte Seed (Base64) erwartet")
    return Ed25519PrivateKey.from_private_bytes(seed)


def public_b64(key):
    from cryptography.hazmat.primitives import serialization
    raw = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(raw).decode()


def message(version, build, os_, arch, fmt, size, sha256):
    return "\n".join([CONTEXT, version, str(build), os_, arch, fmt, str(size), sha256.lower()])


def keygen():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    key = Ed25519PrivateKey.generate()
    seed = key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
    print("UPDATE_SIGNING_KEY (Secret):", base64.b64encode(seed).decode())
    print("update_public_key (brand.json):", public_b64(key))


def main(version, build, base_url, files):
    key = load_key()
    pub = os.environ.get("UPDATE_PUBLIC_KEY", "").strip()
    if pub and pub != public_b64(key):
        sys.exit("UPDATE_SIGNING_KEY passt nicht zu update_public_key in brand.json")
    out = []
    for path in files:
        name = os.path.basename(path)
        m = NAME_RE.match(name)
        if not m or m["version"] != version or m["build"] != str(build):
            sys.exit("unerwarteter Dateiname: %s" % name)
        data = open(path, "rb").read()
        sha = hashlib.sha256(data).hexdigest()
        os_ = OS_BY_FORMAT[m["format"]]
        sig = key.sign(message(version, build, os_, m["arch"], m["format"], len(data), sha).encode())
        out.append({
            "os": os_, "arch": m["arch"], "format": m["format"], "name": name,
            "url": base_url.rstrip("/") + "/" + name, "size": len(data), "sha256": sha,
            "signature": base64.b64encode(sig).decode(),
        })
        print("signiert: %s (%d Bytes)" % (name, len(data)))
    manifest = {
        "version": version, "build": int(build),
        "published_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "public_key": public_b64(key), "files": out,
    }
    with open("update.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)


if __name__ == "__main__":
    if sys.argv[1:] == ["--keygen"]:
        keygen()
    elif len(sys.argv) >= 5:
        main(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4:])
    else:
        sys.exit(__doc__)
