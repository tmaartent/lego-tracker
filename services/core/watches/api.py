from lego_events import WatchState
from ninja import Router

from .models import Watch

router = Router(tags=["watches"])


@router.get("/", response=list[WatchState])
def list_watches(request):
    """Current state of every watch. The watcher loads this on startup, then follows events."""
    return [watch.to_state() for watch in Watch.objects.select_related("lego_set")]
