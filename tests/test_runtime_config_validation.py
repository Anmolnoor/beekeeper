from __future__ import annotations

from beekeeper.config.settings import RuntimeMode
from beekeeper.config.validators import validate_runtime_config


def test_dev_mode_allows_missing_critical_values(monkeypatch) -> None:
    monkeypatch.delenv("BEEKEEPER_JWT_SECRET", raising=False)
    monkeypatch.delenv("BEEKEEPER_AUDIT_SIGNING_KEY", raising=False)
    report = validate_runtime_config(RuntimeMode.DEV)
    assert report.ok
    assert report.warnings


def test_prod_mode_requires_critical_values(monkeypatch) -> None:
    for key in [
        "BEEKEEPER_JWT_SECRET",
        "BEEKEEPER_AUDIT_SIGNING_KEY",
        "BEEKEEPER_CHANNEL_ENCRYPTION_KEY",
        "BEEKEEPER_WEBHOOK_SECRET",
        "BEEKEEPER_DATABASE_DSN",
        "BEEKEEPER_OBJECT_STORAGE_ENDPOINT",
        "BEEKEEPER_OBJECT_STORAGE_BUCKET",
        "BEEKEEPER_TEMPORAL_ENDPOINT",
        "BEEKEEPER_TEMPORAL_NAMESPACE",
        "BEEKEEPER_SECRET_MANAGER_PROVIDER",
    ]:
        monkeypatch.delenv(key, raising=False)

    report = validate_runtime_config(RuntimeMode.PROD)
    assert not report.ok
    assert any("BEEKEEPER_JWT_SECRET" in err for err in report.errors)


def test_prod_mode_rejects_dev_defaults(monkeypatch) -> None:
    monkeypatch.setenv("BEEKEEPER_JWT_SECRET", "dev-secret-change-in-production")
    monkeypatch.setenv("BEEKEEPER_AUDIT_SIGNING_KEY", "beekeeper-dev-signing-key")
    monkeypatch.setenv("BEEKEEPER_CHANNEL_ENCRYPTION_KEY", "key")
    monkeypatch.setenv("BEEKEEPER_WEBHOOK_SECRET", "secret")
    monkeypatch.setenv("BEEKEEPER_DATABASE_DSN", "postgresql://user:pass@localhost/db")
    monkeypatch.setenv("BEEKEEPER_OBJECT_STORAGE_ENDPOINT", "http://localhost:9000")
    monkeypatch.setenv("BEEKEEPER_OBJECT_STORAGE_BUCKET", "beekeeper")
    monkeypatch.setenv("BEEKEEPER_TEMPORAL_ENDPOINT", "localhost:7233")
    monkeypatch.setenv("BEEKEEPER_TEMPORAL_NAMESPACE", "default")
    monkeypatch.setenv("BEEKEEPER_SECRET_MANAGER_PROVIDER", "local")

    report = validate_runtime_config(RuntimeMode.PROD)
    assert not report.ok
    assert any("insecure development default" in err for err in report.errors)
    assert any("managed secret backend" in err for err in report.errors)
