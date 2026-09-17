from src.api.routes import bid, auction, auth
from src.models.user import User
from src.api.routes import bid, auction
from fastapi import WebSocket, WebSocketDisconnect
from src.websockets.manager import auction_manager
from src.api.routes import bid
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Import our Redis lifecycle functions
from src.db.redis import init_redis, close_redis

# Import Postgres database engine and Base
from src.db.database import engine, Base
# IMPORTANT: You must import your models here so SQLAlchemy knows they exist!
from src.models.auction import LandParcel 

# 1. Define the Lifespan Manager
@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- STARTUP LOGIC ---
    print("🚀 Starting up the server...")
    
    # Initialize Redis
    await init_redis()
    
    # Initialize PostgreSQL Tables
    async with engine.begin() as conn:
        print("🏗️  Checking and creating PostgreSQL tables...")
        await conn.run_sync(Base.metadata.create_all)
        print("✅ PostgreSQL tables are ready.")
    
    yield # This tells FastAPI to start accepting web requests now
    
    # --- SHUTDOWN LOGIC ---
    print("🛑 Shutting down the server...")
    await close_redis()
    # Safely close the Postgres connection pool
    await engine.dispose()

# 2. Pass the lifespan to the FastAPI app
app = FastAPI(
    title="Land Auction API",
    description="Real-time bidding engine and property management for land auctions.",
    version="1.0.0",
    lifespan=lifespan
)

# 3. Set up CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 4. Basic Routes
@app.get("/", tags=["System"])
async def root():
    return {
        "system": "Land Auction Platform",
        "status": "Online",
        "message": "Welcome to the core API"
    }

@app.get("/health", tags=["System"])
async def health_check():
    return {
        "api": "healthy",
        "redis": "connected",
        "database": "connected"  # Updated this to "connected"!
    }
    
@app.websocket("/ws/auction/{auction_id}")
async def websocket_endpoint(websocket: WebSocket, auction_id: str):
    await auction_manager.connect(websocket, auction_id)
    try:
        # Keep the connection open and listen for client disconnects
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        auction_manager.disconnect(websocket, auction_id)

app.include_router(bid.router)
app.include_router(auction.router)
app.include_router(auth.router)