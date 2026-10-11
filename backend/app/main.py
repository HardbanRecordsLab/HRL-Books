from fastapi import FastAPI

from app.routers import admin, assets, auth, books, distribution, health, metadata, shop, workspaces

app = FastAPI(title="HRL Books API", version="0.1.0", docs_url="/api/v1/docs", openapi_url="/api/v1/openapi.json")
for r in (health.router, auth.router, workspaces.router, admin.router, books.router, metadata.router, distribution.router, assets.router, shop.router):
    app.include_router(r)
