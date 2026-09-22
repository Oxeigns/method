from backend.logging import configure
from backend.api import create_app
from backend.setup import pending, web_app
configure()
app = web_app() if pending() else create_app()
