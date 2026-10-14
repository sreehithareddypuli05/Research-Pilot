from types import SimpleNamespace
import pytest
import app.auth as auth

def test_password_hash_round_trip():
    encoded = auth.hash_password('correct horse battery staple')
    assert encoded != 'correct horse battery staple'
    assert auth.verify_password('correct horse battery staple', encoded)
    assert not auth.verify_password('wrong password', encoded)

def test_signed_token_rejects_tampering(monkeypatch):
    monkeypatch.setattr(auth, 'JWT_SECRET', 'unit-test-secret-with-more-than-32-characters')
    user = SimpleNamespace(id='user-1', email='user@example.com', name='Example User')
    token = auth.create_token(user)
    claims = auth.decode_token(token)
    assert claims['sub'] == 'user-1'
    header, payload, signature = token.split('.')
    tampered = f'{header}.{payload}.{signature[:-1]}x'
    with pytest.raises(Exception):
        auth.decode_token(tampered)
