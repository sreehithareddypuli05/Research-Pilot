import base64, hashlib, hmac, json, os, secrets, time
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session
from .config import JWT_SECRET, JWT_EXPIRE_HOURS
from .database import SessionLocal, User

bearer = HTTPBearer(auto_error=False)

def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip('=')

def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + '=' * (-len(value) % 4))

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 600_000)
    return f"pbkdf2_sha256$600000${_b64(salt)}${_b64(digest)}"

def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, rounds, salt, digest = encoded.split('$')
        if algorithm != 'pbkdf2_sha256': return False
        actual = hashlib.pbkdf2_hmac('sha256', password.encode(), _unb64(salt), int(rounds))
        return hmac.compare_digest(actual, _unb64(digest))
    except Exception:
        return False

def create_token(user: User) -> str:
    secret = JWT_SECRET or os.getenv('JWT_SECRET', '')
    if len(secret) < 32:
        raise HTTPException(status_code=503, detail='Set JWT_SECRET to a random secret of at least 32 characters in backend/.env.')
    header = _b64(json.dumps({'alg':'HS256','typ':'JWT'}, separators=(',', ':')).encode())
    payload = _b64(json.dumps({'sub':user.id,'email':user.email,'name':user.name,'exp':int(time.time()) + JWT_EXPIRE_HOURS * 3600}, separators=(',', ':')).encode())
    signing = f'{header}.{payload}'.encode()
    signature = _b64(hmac.new(secret.encode(), signing, hashlib.sha256).digest())
    return f'{header}.{payload}.{signature}'

def decode_token(token: str) -> dict:
    try:
        header, payload, signature = token.split('.')
        secret = JWT_SECRET or os.getenv('JWT_SECRET', '')
        expected = _b64(hmac.new(secret.encode(), f'{header}.{payload}'.encode(), hashlib.sha256).digest())
        if not secret or not hmac.compare_digest(signature, expected): raise ValueError('signature')
        claims = json.loads(_unb64(payload))
        if int(claims.get('exp', 0)) < int(time.time()): raise ValueError('expired')
        return claims
    except Exception as exc:
        raise HTTPException(status_code=401, detail='Session expired or invalid. Please sign in again.') from exc

def get_current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> User:
    if not credentials:
        raise HTTPException(status_code=401, detail='Please sign in to continue.')
    claims = decode_token(credentials.credentials)
    with SessionLocal() as db:
        user = db.get(User, claims.get('sub'))
        if not user: raise HTTPException(status_code=401, detail='Account not found. Please sign in again.')
        # Detached object is safe to serialize/use for scalar fields after session closes.
        return user
