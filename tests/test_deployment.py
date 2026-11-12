"""Hosted database TLS and local static asset checks."""

import ssl
from types import SimpleNamespace

import pytest

import app as application
from db_setup import mysql_tls_options


@pytest.mark.parametrize("enabled", ["true", "false"])
def test_mysql_connection_tls_configuration(monkeypatch, enabled):
    monkeypatch.setenv("MYSQL_SSL", enabled)
    monkeypatch.delenv("MYSQL_SSL_CA", raising=False)
    captured = {}
    connection = SimpleNamespace(close=lambda: None)

    def connect(**kwargs):
        captured.update(kwargs)
        return connection

    monkeypatch.setattr(application.pymysql, "connect", connect)
    app = application.create_app({"TESTING": True})
    with app.app_context():
        assert application.get_db() is connection
        if enabled == "true":
            assert isinstance(captured["ssl"], ssl.SSLContext)
            assert captured["ssl"].verify_mode == ssl.CERT_REQUIRED
            assert captured["ssl"].check_hostname
        else:
            assert "ssl" not in captured


def test_invalid_ca_is_not_silently_accepted(monkeypatch):
    monkeypatch.setenv("MYSQL_SSL", "true")
    monkeypatch.setenv("MYSQL_SSL_CA", "invalid certificate")
    with pytest.raises(ssl.SSLError):
        mysql_tls_options()


def test_static_urls_still_work_after_public_directory_move(client):
    for path in (
        "/static/css/style.css",
        "/static/vendor/bootstrap.min.css",
        "/static/images/family-with-dog.jpg",
    ):
        response = client.get(path)
        assert response.status_code == 200, path
        assert response.data
