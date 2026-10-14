from datetime import datetime, timezone
from sqlalchemy import create_engine, String, Text, DateTime, ForeignKey, inspect, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker, relationship
from .config import DATABASE_URL

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = 'users'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(300), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class Workspace(Base):
    __tablename__ = 'workspaces'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class ResearchRun(Base):
    __tablename__ = 'research_runs'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey('users.id', ondelete='SET NULL'), index=True, nullable=True)
    workspace_id: Mapped[str | None] = mapped_column(ForeignKey('workspaces.id', ondelete='SET NULL'), index=True, nullable=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    depth: Mapped[str] = mapped_column(String(20), default='standard', nullable=False)
    status: Mapped[str] = mapped_column(String(30), default='completed', index=True)
    report: Mapped[str] = mapped_column(Text, nullable=False)
    plan_json: Mapped[str] = mapped_column(Text, default='[]', nullable=False)
    sources_json: Mapped[str] = mapped_column(Text, default='[]', nullable=False)
    events_json: Mapped[str] = mapped_column(Text, default='[]', nullable=False)
    analysis: Mapped[str] = mapped_column(Text, default='', nullable=False)
    verification: Mapped[str] = mapped_column(Text, default='', nullable=False)
    notes: Mapped[str] = mapped_column(Text, default='', nullable=False)
    metrics_json: Mapped[str] = mapped_column(Text, default='{}', nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)

engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_recycle=1800)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

def init_db():
    Base.metadata.create_all(bind=engine)
    # Small additive migration for users upgrading from the original MVP table.
    inspector = inspect(engine)
    if 'research_runs' in inspector.get_table_names():
        columns = {col['name'] for col in inspector.get_columns('research_runs')}
        additions = {
            'user_id': 'VARCHAR(36)', 'workspace_id': 'VARCHAR(36)', 'depth': "VARCHAR(20) NOT NULL DEFAULT 'standard'",
            'plan_json': "TEXT NOT NULL DEFAULT '[]'", 'sources_json': "TEXT NOT NULL DEFAULT '[]'",
            'events_json': "TEXT NOT NULL DEFAULT '[]'", 'analysis': "TEXT NOT NULL DEFAULT ''",
            'verification': "TEXT NOT NULL DEFAULT ''", 'notes': "TEXT NOT NULL DEFAULT ''",
            'metrics_json': "TEXT NOT NULL DEFAULT '{}'",
        }
        with engine.begin() as conn:
            for name, sql_type in additions.items():
                if name not in columns:
                    conn.execute(text(f'ALTER TABLE research_runs ADD COLUMN {name} {sql_type}'))
