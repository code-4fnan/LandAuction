from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.orm import declarative_base

# The connection string matches the credentials in your docker-compose.yml
# Notice we use 'postgresql+asyncpg' to enable asynchronous communication
DATABASE_URL = "postgresql+asyncpg://auction_admin:auction_password@localhost:5432/land_auction_db"

# Create the async engine
engine = create_async_engine(DATABASE_URL, echo=True)

# Create a session factory to generate database sessions for our API routes
AsyncSessionLocal = async_sessionmaker(
    bind=engine, 
    expire_on_commit=False
)

# The base class that all our future database models will inherit from
Base = declarative_base()

# A dependency function we will use in our FastAPI routes to get a database session
async def get_db():
    async with AsyncSessionLocal() as session:
        yield session