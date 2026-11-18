import sqlite3
from contextlib import contextmanager
from collections.abc import Generator

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.sqlite import SqliteSaver
from sqlalchemy.engine import make_url

from app.config import settings


@contextmanager
def persistent_checkpointer() -> Generator[BaseCheckpointSaver, None, None]:
    """Open and initialize the LangGraph saver matching the application database."""
    database_url = settings.DATABASE_URL
    if database_url.startswith("sqlite"):
        database_path = make_url(database_url).database or ":memory:"
        connection = sqlite3.connect(database_path, check_same_thread=False)
        try:
            saver = SqliteSaver(connection)
            saver.setup()
            yield saver
        finally:
            connection.close()
        return

    postgres_url = make_url(database_url).set(drivername="postgresql")
    connection_string = postgres_url.render_as_string(hide_password=False)
    with PostgresSaver.from_conn_string(connection_string) as saver:
        saver.setup()
        yield saver
