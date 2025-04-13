from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base, relationship
from sqlalchemy import Column, Integer, String, Text, Date, Boolean, ForeignKey
from dotenv import load_dotenv
import os

# Load .env variables
load_dotenv()

# Read DATABASE_URL from env
DATABASE_URL = os.getenv("DATABASE_URL")

# Setup SQLAlchemy engine and session
engine = create_async_engine(DATABASE_URL, echo=True)
SessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

# Base class for models
Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    default_company_name = Column(String, default="GovCon AI")
    default_document_type = Column(String, default="Proposal")
    default_submission_date = Column(Date)
    is_active = Column(Boolean, default=True)

    rfps = relationship("RFP", back_populates="owner")


class RFP(Base):
    __tablename__ = "rfps"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String)
    filename = Column(String)
    draft_text = Column(Text)

    company_name = Column(String, default="GovCon AI")
    document_type = Column(String, default="Proposal")
    submission_date = Column(Date)

    user_id = Column(Integer, ForeignKey("users.id"))
    owner = relationship("User", back_populates="rfps")

