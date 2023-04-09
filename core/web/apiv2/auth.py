import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt

from core.config.config import yeti_config
from core.schemas.user import User, UserSensitive

ACCESS_TOKEN_EXPIRE_MINUTES = datetime.timedelta(
    minutes=yeti_config.auth['access_token_expire_minutes'])
SECRET_KEY = yeti_config.auth['secret_key']
ALGORITHM = yeti_config.auth['algorithm']

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/v2/auth/token")


def create_access_token(data: dict, expires_delta: datetime.timedelta | None = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.datetime.utcnow() + expires_delta
    else:
        expire = datetime.datetime.utcnow() + datetime.timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(
        to_encode,
        SECRET_KEY,
        algorithm=ALGORITHM)
    return encoded_jwt

async def get_current_user(token: str = Depends(oauth2_scheme)) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = User.find(username=username)
    if user is None:
        raise credentials_exception
    return user


# API Endpoints
router = APIRouter()

@router.post("/token")
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    http_exception = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
    )
    user = UserSensitive.find(username=form_data.username)
    if not (user and user.verify_password(form_data.password)):
        raise http_exception
    access_token = create_access_token(
        data={"sub": user.username}, expires_delta=ACCESS_TOKEN_EXPIRE_MINUTES
    )
    return {"access_token": access_token, "token_type": "bearer"}

@router.get("/me")
async def me(current_user: User = Depends(get_current_user)) -> User:
    return current_user
