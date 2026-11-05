"""Throwaway certificates for the demonstration: a CA, a server certificate and a client certificate.

Generated when the stack starts and written to a volume; nothing here is committed, and the CA signs nothing else.
Run with `python -m pulse.standin.devcerts /certs`.
"""

from __future__ import annotations

import ipaddress
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

FILES = ("ca.pem", "server.pem", "server.key", "client.pem", "client.key")


def _name(common_name: str) -> x509.Name:
    return x509.Name(
        [
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "pulse demonstration"),
            x509.NameAttribute(NameOID.COMMON_NAME, common_name),
        ]
    )


def _write_key(path: Path, key: ec.EllipticCurvePrivateKey) -> None:
    path.write_bytes(
        key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    )
    path.chmod(0o600)


def generate(directory: Path, *, hosts: tuple[str, ...] = ("localhost", "gateway"), days: int = 30) -> None:
    """Write the five files into `directory` (created if needed). Short-lived on purpose: 30 days by default."""
    directory.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC) - timedelta(minutes=5)
    until = now + timedelta(days=days)

    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca = (
        x509.CertificateBuilder()
        .subject_name(_name("pulse demonstration CA"))
        .issuer_name(_name("pulse demonstration CA"))
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(until)
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(x509.KeyUsage(False, False, False, False, False, True, True, False, False), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False)
        .sign(ca_key, hashes.SHA256())
    )

    def leaf(
        common_name: str, usage: x509.ObjectIdentifier, sans: list[x509.GeneralName]
    ) -> tuple[ec.EllipticCurvePrivateKey, x509.Certificate]:
        key = ec.generate_private_key(ec.SECP256R1())
        builder = (
            x509.CertificateBuilder()
            .subject_name(_name(common_name))
            .issuer_name(ca.subject)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now)
            .not_valid_after(until)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.ExtendedKeyUsage([usage]), critical=False)
            # Python 3.13+ verifies in strict mode, which refuses a certificate without its issuer's key identifier.
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
        )
        if sans:
            builder = builder.add_extension(x509.SubjectAlternativeName(sans), critical=False)
        return key, builder.sign(ca_key, hashes.SHA256())

    sans: list[x509.GeneralName] = [x509.DNSName(h) for h in hosts] + [
        x509.IPAddress(ipaddress.ip_address("127.0.0.1"))
    ]
    server_key, server = leaf("gateway", ExtendedKeyUsageOID.SERVER_AUTH, sans)
    client_key, client = leaf("pulse worker", ExtendedKeyUsageOID.CLIENT_AUTH, [])

    (directory / "ca.pem").write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    (directory / "server.pem").write_bytes(server.public_bytes(serialization.Encoding.PEM))
    (directory / "client.pem").write_bytes(client.public_bytes(serialization.Encoding.PEM))
    _write_key(directory / "server.key", server_key)
    _write_key(directory / "client.key", client_key)
    for name in ("ca.pem", "server.pem", "client.pem"):
        (directory / name).chmod(0o644)


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: python -m pulse.standin.devcerts DIRECTORY", file=sys.stderr)
        return 2
    target = Path(sys.argv[1])
    if all((target / name).exists() for name in FILES):
        print(f"certificates already in {target}; leaving them")
        return 0
    generate(target)
    print(f"wrote {', '.join(FILES)} to {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
