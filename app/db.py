from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, Text, UniqueConstraint, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()


class ExtractedData(Base):
    __tablename__ = "extracted_data"

    id = Column(Integer, primary_key=True)
    university = Column(String, nullable=False)
    page_type = Column(String, nullable=False)  # fees/admissions/deadlines/programs/aid/about
    url = Column(String, nullable=False)
    extracted_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    content_hash = Column(String, nullable=False)
    data_json = Column(Text, nullable=False)

    __table_args__ = (UniqueConstraint("url", "content_hash", name="uq_url_hash"),)


def get_engine(db_url: str):
    # check_same_thread False required for sqlite + background scheduler
    return create_engine(db_url, future=True, connect_args={"check_same_thread": False})


def get_session_maker(db_url: str):
    engine = get_engine(db_url)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)