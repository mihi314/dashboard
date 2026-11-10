import secrets
from typing import Annotated, Optional

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from updater import climate
from updater.settings import settings


# Publicly reachable through nginx, so don't expose any docs
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

bearer = HTTPBearer(auto_error=False)


def check_token(credentials: Annotated[Optional[HTTPAuthorizationCredentials], Depends(bearer)]):
    if credentials is None or not secrets.compare_digest(
        credentials.credentials.encode(), settings.DASH_INGEST_TOKEN.encode()
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing token",
            headers={"WWW-Authenticate": "Bearer"},
        )


@app.get("/ingest/health")
def health():
    return "ok"


# Endpoints of the individual updaters, all requiring the token
for router in [climate.router]:
    app.include_router(router, prefix="/ingest", dependencies=[Depends(check_token)])
