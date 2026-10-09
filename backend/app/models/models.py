import uuid
from typing import Any, List, Optional, Annotated, Dict
from datetime import datetime, timezone
from pydantic import BaseModel, Field, ConfigDict
from beanie import Document, Indexed
from sqlalchemy import Column, String, Text, Float, Integer, DateTime, ForeignKey, JSON, Boolean
from sqlalchemy.orm import relationship
from app.core.database import Base, IS_POSTGRES, HAS_PGVECTOR

VECTOR_TYPE = JSON


# ==========================================
# MongoDB Beanie Document Models
# ==========================================

class UserDoc(Document):
    model_config = ConfigDict(populate_by_name=True)

    id: Any = Field(default_factory=lambda: str(uuid.uuid4()))  # type: ignore[override]
    name: str
    email: Annotated[str, Indexed(unique=True)]
    password_hash: str
    is_verified: bool = False
    otp_code: Optional[str] = None
    otp_expires_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "users"


class PatentDoc(Document):
    model_config = ConfigDict(populate_by_name=True)

    id: Any = Field(default_factory=lambda: str(uuid.uuid4()))  # type: ignore[override]
    patent_number: Annotated[str, Indexed(unique=True)]
    title: str
    abstract: str
    description: str
    claims: Optional[str] = None
    inventors: Optional[str] = "Unknown"
    assignee: Optional[str] = "Independent"
    publication_date: Optional[str] = "2024-01-01"
    domain: Annotated[str, Indexed()]
    source_url: Optional[str] = None
    source_type: Optional[str] = "DATABASE"
    source_status: Optional[str] = "DATABASE"
    document_type: Optional[str] = "DATABASE RECORD"
    lens_id: Optional[str] = None
    filing_date: Optional[str] = None
    earliest_priority_date: Optional[str] = None
    simple_family_id: Optional[str] = None
    simple_family_size: Optional[int] = 1
    extended_family_size: Optional[int] = 1
    data_quality_status: Optional[str] = "LIMITED"
    cpc_codes: Optional[str] = None
    ipc_codes: Optional[str] = None
    jurisdiction: Optional[str] = None
    embedding: Optional[List[float]] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "patents"


class SearchResultItem(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    patent_id: str
    semantic_score: float
    keyword_score: float
    domain_score: float
    final_score: float
    matched_concepts: List[str] = Field(default_factory=list)
    rank: int
    analysis_payload: Optional[Dict[str, Any]] = None


class SearchDoc(Document):
    model_config = ConfigDict(populate_by_name=True)

    id: Any = Field(default_factory=lambda: str(uuid.uuid4()))  # type: ignore[override]
    user_id: str
    invention_title: str
    domain: str
    problem_statement: str
    description: str
    keywords: List[str] = Field(default_factory=list)
    risk_level: str
    highest_similarity: float
    total_results: int = 0
    very_high_similarity: int = 0
    high_similarity: int = 0
    moderate_similarity: int = 0
    low_similarity: int = 0
    patents_searched: int = 0
    patents_retrieved: int = 0
    patents_shortlisted: int = 0
    patents_deeply_analyzed: int = 0
    pipeline_metrics: Optional[Dict[str, Any]] = None
    results: List[SearchResultItem] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "searches"


class SavedPatentDoc(Document):
    model_config = ConfigDict(populate_by_name=True)

    id: Any = Field(default_factory=lambda: str(uuid.uuid4()))  # type: ignore[override]
    user_id: str
    patent_id: str
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "saved_patents"


class ReportDoc(Document):
    model_config = ConfigDict(populate_by_name=True)

    id: Any = Field(default_factory=lambda: str(uuid.uuid4()))  # type: ignore[override]
    user_id: str
    search_id: str
    report_path: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "reports"


# ==========================================
# SQL SQLAlchemy Models (Legacy / Postgres)
# ==========================================

class User(Base):
    __allow_unmapped__ = True
    __tablename__ = "users"

    id: Any = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Any = Column(String(255), nullable=False)
    email: Any = Column(String(255), unique=True, index=True, nullable=False)
    password_hash: Any = Column(String(255), nullable=False)
    is_verified: Any = Column(Boolean, default=False, nullable=False)
    otp_code: Any = Column(String(6), nullable=True)
    otp_expires_at: Any = Column(DateTime, nullable=True)
    created_at: Any = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Any = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    searches: Any = relationship("Search", back_populates="user", cascade="all, delete-orphan")
    saved_patents: Any = relationship("SavedPatent", back_populates="user", cascade="all, delete-orphan")
    reports: Any = relationship("Report", back_populates="user", cascade="all, delete-orphan")


class Patent(Base):
    __allow_unmapped__ = True
    __tablename__ = "patents"

    id: Any = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    patent_number: Any = Column(String(100), unique=True, index=True, nullable=False)
    title: Any = Column(String(500), nullable=False)
    abstract: Any = Column(Text, nullable=False)
    description: Any = Column(Text, nullable=False)
    claims: Any = Column(Text, nullable=True)
    inventors: Any = Column(String(500), default="Unknown", nullable=True)
    assignee: Any = Column(String(500), default="Independent", nullable=True)
    publication_date: Any = Column(String(50), default="2024-01-01", nullable=True)
    domain: Any = Column(String(100), index=True, nullable=False)
    source_url: Any = Column(String(500), nullable=True)
    source_type: Any = Column(String(50), default="DATABASE", nullable=True)
    source_status: Any = Column(String(50), default="DATABASE", nullable=True)  # LIVE_API, CACHE, DATABASE, FALLBACK
    document_type: Any = Column(String(50), default="DATABASE RECORD", nullable=True)
    lens_id: Any = Column(String(100), nullable=True)
    filing_date: Any = Column(String(50), nullable=True)
    earliest_priority_date: Any = Column(String(50), nullable=True)
    simple_family_id: Any = Column(String(100), nullable=True)
    simple_family_size: Any = Column(Integer, default=1, nullable=True)
    extended_family_size: Any = Column(Integer, default=1, nullable=True)
    data_quality_status: Any = Column(String(50), default="LIMITED", nullable=True)
    cpc_codes: Any = Column(Text, nullable=True)
    ipc_codes: Any = Column(Text, nullable=True)
    jurisdiction: Any = Column(String(20), nullable=True)
    embedding: Any = Column(VECTOR_TYPE, nullable=True)
    created_at: Any = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    search_results: Any = relationship("SearchResult", back_populates="patent", cascade="all, delete-orphan")
    saved_by_users: Any = relationship("SavedPatent", back_populates="patent", cascade="all, delete-orphan")


class Search(Base):
    __allow_unmapped__ = True
    __tablename__ = "searches"

    id: Any = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Any = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    invention_title: Any = Column(String(500), nullable=False)
    domain: Any = Column(String(100), nullable=False)
    problem_statement: Any = Column(Text, nullable=False)
    description: Any = Column(Text, nullable=False)
    keywords: Any = Column(JSON, default=list)
    risk_level: Any = Column(String(50), nullable=False)  # LOW, MODERATE, HIGH, VERY HIGH
    highest_similarity: Any = Column(Float, nullable=False)
    total_results: Any = Column(Integer, default=0, nullable=True)
    very_high_similarity: Any = Column(Integer, default=0, nullable=True)
    high_similarity: Any = Column(Integer, default=0, nullable=True)
    moderate_similarity: Any = Column(Integer, default=0, nullable=True)
    low_similarity: Any = Column(Integer, default=0, nullable=True)
    patents_searched: Any = Column(Integer, default=0, nullable=True)
    patents_retrieved: Any = Column(Integer, default=0, nullable=True)
    patents_shortlisted: Any = Column(Integer, default=0, nullable=True)
    patents_deeply_analyzed: Any = Column(Integer, default=0, nullable=True)
    pipeline_metrics: Any = Column(JSON, nullable=True)
    created_at: Any = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    user: Any = relationship("User", back_populates="searches")
    results: Any = relationship("SearchResult", back_populates="search", cascade="all, delete-orphan", order_by="SearchResult.rank")
    reports: Any = relationship("Report", back_populates="search", cascade="all, delete-orphan")


class SearchResult(Base):
    __allow_unmapped__ = True
    __tablename__ = "search_results"

    id: Any = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    search_id: Any = Column(String(36), ForeignKey("searches.id", ondelete="CASCADE"), nullable=False, index=True)
    patent_id: Any = Column(String(36), ForeignKey("patents.id", ondelete="CASCADE"), nullable=False, index=True)
    semantic_score: Any = Column(Float, nullable=False)
    keyword_score: Any = Column(Float, nullable=False)
    domain_score: Any = Column(Float, nullable=False)
    final_score: Any = Column(Float, nullable=False)
    matched_concepts: Any = Column(JSON, default=list)
    rank: Any = Column(Integer, nullable=False)
    analysis_payload: Any = Column(JSON, nullable=True)

    # Relationships
    search: Any = relationship("Search", back_populates="results")
    patent: Any = relationship("Patent", back_populates="search_results")


class SavedPatent(Base):
    __allow_unmapped__ = True
    __tablename__ = "saved_patents"

    id: Any = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Any = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    patent_id: Any = Column(String(36), ForeignKey("patents.id", ondelete="CASCADE"), nullable=False, index=True)
    notes: Any = Column(Text, nullable=True)
    created_at: Any = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    user: Any = relationship("User", back_populates="saved_patents")
    patent: Any = relationship("Patent", back_populates="saved_by_users")


class Report(Base):
    __allow_unmapped__ = True
    __tablename__ = "reports"

    id: Any = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Any = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    search_id: Any = Column(String(36), ForeignKey("searches.id", ondelete="CASCADE"), nullable=False, index=True)
    report_path: Any = Column(String(500), nullable=False)
    created_at: Any = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    user: Any = relationship("User", back_populates="reports")
    search: Any = relationship("Search", back_populates="reports")
