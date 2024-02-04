from fastapi import FastAPI, status, Depends, HTTPException, Response, Form
import contextlib
from database import create_all_tables, get_async_session
import schemas
from sqlalchemy.ext.asyncio import AsyncSession
from models import User, AccessToken
from password import get_password_hash
from sqlalchemy import exc, select
from fastapi.security import OAuth2PasswordRequestForm, OAuth2PasswordBearer, APIKeyCookie
from authentication import authenticate, create_access_token
from datetime import datetime, timezone
from starlette_csrf import CSRFMiddleware
from starlette.middleware.cors import CORSMiddleware


TOKEN_COOKIE_NAME = "token"
CSRF_TOKEN_SECRET = "_THIS_IS_A_SECRET_TOKEN_"


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    await create_all_tables()
    yield


app = FastAPI(lifespan=lifespan)

app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:9000"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.add_middleware(CSRFMiddleware, secret=CSRF_TOKEN_SECRET, sensitive_cookies={TOKEN_COOKIE_NAME}, cookie_domain="localhost")


async def get_current_user(token: str = Depends(APIKeyCookie(name=TOKEN_COOKIE_NAME)), session: AsyncSession = Depends(get_async_session)) -> User:
    query = select(AccessToken).where(AccessToken.access_token == token, AccessToken.expiration_date >= datetime.now(tz=timezone.utc))
    result = await session.execute(query)
    access_token: AccessToken | None = result.scalar_one_or_none()
    if access_token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    return access_token.user


@app.get("/csrf")
async def csrf():
    return None


@app.post("/register", status_code=status.HTTP_201_CREATED, response_model=schemas.UserRead)
async def register(user_create: schemas.UserCreate, session: AsyncSession = Depends(get_async_session)) -> User:
    hashed_password = get_password_hash(user_create.password)
    user = User(**user_create.dict(exclude={"password"}), hashed_password=hashed_password)
    try:
        session.add(user)
        await session.commit()
    except exc.IntegrityError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already exists")
    return user


@app.post("/login")
async def login(response: Response, email: str = Form(...), password: str = Form(...), session: AsyncSession = Depends(get_async_session)):
    user = await authenticate(email, password, session)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    token = await create_access_token(user, session)
    response.set_cookie(TOKEN_COOKIE_NAME, token.access_token, max_age=token.max_age(), secure=True, httponly=True, samesite="lax")


@app.get("/me", response_model=schemas.UserRead)
async def get_me(user: User = Depends(get_current_user)):
    return user


@app.post("/me", response_model=schemas.UserRead)
async def update_me(user_update: schemas.UserUpdate, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_async_session)):
    user_update_dict = user_update.dict(exclude_unset=True)
    for key, value in user_update_dict.items():
        setattr(user, key, value)
    session.add(user)
    await session.commit()
    return user
