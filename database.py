import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
SSL_CA = os.getenv("MYSQL_SSL_CA")

connect_args = {"connect_timeout": 10}
if SSL_CA and os.path.exists(SSL_CA):
    import ssl
    ssl_ctx = ssl.create_default_context(cafile=SSL_CA)
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_REQUIRED
    connect_args["ssl"] = ssl_ctx
elif SSL_CA:
    connect_args["ssl"] = {"ca": SSL_CA}

engine = create_engine(
    DATABASE_URL,
    pool_size=10,
    max_overflow=20,
    pool_recycle=300,
    pool_pre_ping=True,
    pool_timeout=10,
    connect_args=connect_args
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()