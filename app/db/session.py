from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import SQLITE_PATH

engine = create_engine(f"sqlite:///{SQLITE_PATH}", future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def get_session():
    return SessionLocal()
