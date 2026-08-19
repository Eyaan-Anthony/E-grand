import os
#to get connection string from environment variable
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
#all of these are imported in order to handle async calls to the db

DATABASE_URL = os.getenv(
    "DATABASE_URL", 
    "postgresql+asyncpg://esanta_admin:secure_password_123@127.0.0.1:5432/esanta_db"
)

engine = create_async_engine(DATABASE_URL, echo=True, future=True)
#echo controls whether SQLAlchemy prints the SQL statements it executes.
#apparently future, is obsolete

#an async session is what permits you to effectively interact (do stuff) with the database when using FastAPI, 
#running queries, updating stuff, etc, etc

#create the async session
AsyncSessionLocal = async_sessionmaker(
  bind=engine,
  class_=AsyncSession,
  expire_on_commit=False,
  autoflush=False,
  #well basically the idea here is we fully control when data is written to disk or to storage
)

#define base class for our sql alchemy ORM models
Base = declarative_base()
#this is the manager that maps python to sql
#since they don't speak the same language, so python classes map to databases table

#Dependency Injection function for FastAPI endpoints
async def get_db():
    """
    Provides an asynchronous database session for a request,
    and automatically closes it when the request is finished.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            #yield doesn't terminate a function but returns a value, ideal for async calls
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


