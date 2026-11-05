"""Mutual TLS against a real TLS server. The certificates are generated here, at run time, and never stored."""

from __future__ import annotations

import ssl
from collections.abc import Iterator
from pathlib import Path

import pytest

from pulse.clock import FixedClock
from pulse.exchange.gateway import GatewayClient
from pulse.standin import devcerts
from pulse.standin.gateway_app import create_gateway_app
from tests.conftest import START, RunningServer

# A server that refuses a client for its certificate does so after the TLS 1.3 handshake, and how that reaches the client
# depends on timing and on the TLS library: a TLS alert (ReadError) or a closed connection (RemoteProtocolError). Both
# are the server saying no. The client's own checks fail earlier, as a ConnectError, and are tested separately below.
SERVER_REFUSED = ("ReadError", "RemoteProtocolError")


@pytest.fixture(scope="module")
def certs(tmp_path_factory: pytest.TempPathFactory) -> Path:
    directory = tmp_path_factory.mktemp("certs-a")
    devcerts.generate(directory)
    return directory


@pytest.fixture(scope="module")
def other_certs(tmp_path_factory: pytest.TempPathFactory) -> Path:
    directory = tmp_path_factory.mktemp("certs-b")
    devcerts.generate(directory)
    return directory


@pytest.fixture(scope="module")
def server(certs: Path) -> Iterator[RunningServer]:
    app = create_gateway_app(control=True)
    with RunningServer(
        app,
        ssl_certfile=str(certs / "server.pem"),
        ssl_keyfile=str(certs / "server.key"),
        ssl_ca_certs=str(certs / "ca.pem"),
        ssl_cert_reqs=ssl.CERT_REQUIRED,
    ) as running:
        yield running


def client(server: RunningServer, **tls: str) -> GatewayClient:
    base = f"https://127.0.0.1:{server.port}"
    return GatewayClient(
        base_url=base,
        token_url=f"{base}/oauth/token",
        client_id="pulse-demo",
        client_secret="pulse-demo-secret",
        clock=FixedClock(START),
        timeout=3.0,
        **tls,
    )


def gateway_requests_seen(server: RunningServer, certs: Path) -> int:
    good = client(
        server, ca_file=str(certs / "ca.pem"), cert_file=str(certs / "client.pem"), key_file=str(certs / "client.key")
    )
    return int(good.raw("GET", "/control/state").json()["requests"])


def test_a_client_with_a_certificate_the_server_trusts_gets_through(server: RunningServer, certs: Path) -> None:
    good = client(
        server, ca_file=str(certs / "ca.pem"), cert_file=str(certs / "client.pem"), key_file=str(certs / "client.key")
    )
    delivery = good.send("mtls-ok", {"n": 1})
    assert (delivery.outcome, delivery.http_status) == ("delivered", 201)


def test_a_client_without_a_certificate_never_reaches_the_application(server: RunningServer, certs: Path) -> None:
    before = gateway_requests_seen(server, certs)
    bare = client(server, ca_file=str(certs / "ca.pem"))
    delivery = bare.send("mtls-none", {"n": 1})
    assert (delivery.outcome, delivery.http_status) == ("retry", None)  # a transport error with a name, not a crash
    assert delivery.detail.endswith(SERVER_REFUSED)  # the server refused after the handshake (TLS 1.3 client auth)
    assert gateway_requests_seen(server, certs) == before  # and no HTTP request ever reached the application


def test_a_certificate_signed_by_another_authority_is_refused(
    server: RunningServer, certs: Path, other_certs: Path
) -> None:
    before = gateway_requests_seen(server, certs)
    stranger = client(
        server,
        ca_file=str(certs / "ca.pem"),
        cert_file=str(other_certs / "client.pem"),
        key_file=str(other_certs / "client.key"),
    )
    delivery = stranger.send("mtls-stranger", {"n": 1})
    assert (delivery.outcome, delivery.http_status) == ("retry", None)
    assert delivery.detail.endswith(SERVER_REFUSED)  # refused by the server, not by the client's own checks
    assert gateway_requests_seen(server, certs) == before


def test_a_client_that_does_not_trust_the_servers_authority_refuses_to_talk(
    server: RunningServer, certs: Path, other_certs: Path
) -> None:
    suspicious = client(
        server,
        ca_file=str(other_certs / "ca.pem"),
        cert_file=str(certs / "client.pem"),
        key_file=str(certs / "client.key"),
    )
    delivery = suspicious.send("mtls-untrusted-server", {"n": 1})
    assert (delivery.outcome, delivery.http_status) == ("retry", None)
    assert delivery.detail.endswith(
        "ConnectError"
    )  # the client's own verification failed: nothing was sent to the server


def test_a_private_authority_is_not_trusted_just_because_the_system_store_exists(server: RunningServer) -> None:
    default_trust = client(server)  # no CA file: only the system trust store, which does not know this authority
    delivery = default_trust.send("mtls-default-trust", {"n": 1})
    assert (delivery.outcome, delivery.http_status) == ("retry", None)
    assert delivery.detail.endswith("ConnectError")


def test_the_generated_certificates_are_what_they_claim_to_be(certs: Path) -> None:
    from cryptography import x509
    from cryptography.x509.oid import ExtendedKeyUsageOID

    server_cert = x509.load_pem_x509_certificate((certs / "server.pem").read_bytes())
    client_cert = x509.load_pem_x509_certificate((certs / "client.pem").read_bytes())
    assert (
        ExtendedKeyUsageOID.SERVER_AUTH in server_cert.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
    )
    assert (
        ExtendedKeyUsageOID.CLIENT_AUTH in client_cert.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
    )
    assert (server_cert.not_valid_after_utc - server_cert.not_valid_before_utc).days <= 31  # short-lived on purpose
    for name in ("server.key", "client.key"):
        assert (certs / name).stat().st_mode & 0o077 == 0  # private keys are owner-only
