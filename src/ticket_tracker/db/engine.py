from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from ticket_tracker.config import settings

engine = create_engine(
    str(settings.database_url),
    pool_pre_ping=True,   # reconnect on stale connections
    pool_size=5,
    max_overflow=10,
)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
