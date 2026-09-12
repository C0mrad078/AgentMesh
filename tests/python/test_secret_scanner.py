from __future__ import annotations

from core.security.secret_scanner import SecretScanner


def test_detects_aws_access_key() -> None:
    scanner = SecretScanner()
    assert scanner.contains_secret("key = AKIAABCDEFGHIJKLMNOP") is True


def test_detects_openai_style_key() -> None:
    scanner = SecretScanner()
    assert scanner.contains_secret("OPENAI_API_KEY=sk-abcdefghijklmnopqrstuvwxyz123456") is True


def test_detects_private_key_block() -> None:
    scanner = SecretScanner()
    text = "-----BEGIN RSA PRIVATE KEY-----\nMIIBogIBAAJ...\n-----END RSA PRIVATE KEY-----"
    assert scanner.contains_secret(text) is True


def test_detects_generic_secret_assignment() -> None:
    scanner = SecretScanner()
    assert scanner.contains_secret('password: "SuperSecretValue123"') is True


def test_plain_text_has_no_secrets() -> None:
    scanner = SecretScanner()
    assert scanner.contains_secret("This is just a normal sentence about code.") is False


def test_redact_replaces_secret_with_placeholder() -> None:
    scanner = SecretScanner()
    redacted, matches = scanner.redact("here is my key: AKIAABCDEFGHIJKLMNOP end")
    assert "AKIAABCDEFGHIJKLMNOP" not in redacted
    assert "[REDACTED:aws_access_key]" in redacted
    assert len(matches) == 1


def test_redact_handles_multiple_secrets() -> None:
    scanner = SecretScanner()
    text = "aws=AKIAABCDEFGHIJKLMNOP openai=sk-abcdefghijklmnopqrstuvwxyz123456"
    redacted, matches = scanner.redact(text)
    assert "AKIAABCDEFGHIJKLMNOP" not in redacted
    assert "sk-abcdefghijklmnopqrstuvwxyz123456" not in redacted
    assert len(matches) == 2


def test_redact_no_secrets_returns_text_unchanged() -> None:
    scanner = SecretScanner()
    text = "nothing sensitive here"
    redacted, matches = scanner.redact(text)
    assert redacted == text
    assert matches == []
