"""Authenticated symmetric encryption for private WORLD SHARDS workflow artifacts.

GnuPG's AES-256 symmetric format provides integrity protection and avoids
uploading unpublished magazine content or SQLite state in plaintext.
"""
import subprocess
import tempfile
from pathlib import Path


def _passphrase(secret):
    if not secret:
        raise RuntimeError("Hiányzik a WORLD SHARDS artifact-titkosítási kulcs.")
    return secret.encode("utf-8") + b"\n"


def encrypt_bytes(plaintext, secret):
    with tempfile.TemporaryDirectory(prefix="world-shards-encrypt-") as directory:
        source = Path(directory) / "input.bin"
        target = Path(directory) / "output.gpg"
        source.write_bytes(plaintext)
        command = [
            "gpg", "--batch", "--yes", "--no-symkey-cache",
            "--pinentry-mode", "loopback", "--passphrase-fd", "0",
            "--symmetric", "--cipher-algo", "AES256",
            "--compress-algo", "none",
            "--output", str(target), str(source),
        ]
        result = subprocess.run(
            command,
            input=_passphrase(secret),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(
                "A WORLD SHARDS artifact titkosítása sikertelen: "
                + result.stderr.decode("utf-8", errors="replace")[-1000:]
            )
        return target.read_bytes()


def decrypt_bytes(ciphertext, secret):
    with tempfile.TemporaryDirectory(prefix="world-shards-decrypt-") as directory:
        source = Path(directory) / "input.gpg"
        target = Path(directory) / "output.bin"
        source.write_bytes(ciphertext)
        command = [
            "gpg", "--batch", "--yes", "--no-symkey-cache",
            "--pinentry-mode", "loopback", "--passphrase-fd", "0",
            "--decrypt", "--output", str(target), str(source),
        ]
        result = subprocess.run(
            command,
            input=_passphrase(secret),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(
                "A WORLD SHARDS artifact visszafejtése sikertelen: "
                + result.stderr.decode("utf-8", errors="replace")[-1000:]
            )
        return target.read_bytes()
