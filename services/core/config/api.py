from ninja import NinjaAPI

from watches.api import router as watches_router

# Internal API for the other services; interactive docs at /api/docs.
api = NinjaAPI(title="lego-tracker core", version="0.1.0")
api.add_router("/watches", watches_router)


@api.get("/health", tags=["ops"])
def health(request):
    return {"status": "ok"}
