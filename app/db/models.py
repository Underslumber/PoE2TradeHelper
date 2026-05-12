from __future__ import annotations

from sqlalchemy import Column, String, Text
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class Snapshot(Base):
    __tablename__ = "snapshots"

    id = Column(String, primary_key=True)
    created_at = Column(String, nullable=False)
    league = Column(String, nullable=False)
    category = Column(String, nullable=False)
    source_url = Column(String, nullable=False)
    method = Column(String, nullable=False)


class Row(Base):
    __tablename__ = "rows"

    snapshot_id = Column(String, primary_key=True)
    row_id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    icon_url = Column(String)
    icon_local = Column(String)
    columns_json = Column(Text, nullable=False)
    raw_json = Column(Text, nullable=False)


class Artifact(Base):
    __tablename__ = "artifacts"

    snapshot_id = Column(String, primary_key=True)
    kind = Column(String, primary_key=True)
    url = Column(String)
    path = Column(String, primary_key=True)
