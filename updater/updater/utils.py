import requests

from updater.settings import settings


if settings.CACHE_REQUESTS:
    from joblib import Memory

    memory = Memory("cachedir")
    requests_get = memory.cache(requests.get)
else:
    requests_get = requests.get
