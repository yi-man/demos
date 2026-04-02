from fastapi import FastAPI

from orders.api.routes import router
from orders.core.settings import settings

app = FastAPI(debug=settings.debug)
app.include_router(router)
