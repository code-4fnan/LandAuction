from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pydantic import BaseModel

from src.db.database import get_db
from src.models.auction import LandParcel
import src.db.redis as redis_db

router = APIRouter(prefix="/api/auctions", tags=["Auctions"])

class ParcelCreate(BaseModel):
    title: str
    description: str
    starting_price: float
    boundary_wkt: str
    auction_end_time: datetime

@router.post("/")
async def create_land_parcel(parcel: ParcelCreate, db: AsyncSession = Depends(get_db)):
    try:
        new_parcel = LandParcel(
            title=parcel.title,
            description=parcel.description,
            starting_price=parcel.starting_price,
            boundary=f"SRID=4326;{parcel.boundary_wkt}",
            auction_end_time=parcel.auction_end_time
        )
        
        db.add(new_parcel)
        await db.commit()
        await db.refresh(new_parcel) # <--- CRITICAL: Get the new ID back from PostgreSQL
        
        auction_id = f"parcel-{new_parcel.id}"
        
        # Start the Redis live auction engine
        if redis_db.redis_client:
            price_key = f"auction:{auction_id}:price"
            winner_key = f"auction:{auction_id}:winner"
            
            await redis_db.redis_client.set(price_key, new_parcel.starting_price)
            await redis_db.redis_client.set(winner_key, "No bids yet")
        
        return {
            "status": "success",
            "message": "Land parcel created and live auction started!",
            "database_id": new_parcel.id,
            "auction_id": auction_id
        }
        
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to create parcel. Error: {str(e)}"
        )

# --- CORRECTED GET ROUTE ---
@router.get("/")
async def get_all_parcels(db: AsyncSession = Depends(get_db)):
    try:
        query = select(
            LandParcel.id,
            LandParcel.title,
            LandParcel.description,
            LandParcel.starting_price,
            LandParcel.auction_end_time, # <--- Added the missing end time!
            func.ST_AsText(LandParcel.boundary).label('boundary_wkt')
        )
        
        result = await db.execute(query)
        parcels = result.all()
        
        formatted_parcels = [
            {
                "database_id": row.id,
                "auction_id": f"parcel-{row.id}",
                "title": row.title,
                "description": row.description,
                "starting_price": row.starting_price,
                # Convert the date into a string the frontend clock can read
                "end_time": row.auction_end_time.isoformat() if row.auction_end_time else None,
                "boundary_wkt": row.boundary_wkt
            }
            for row in parcels
        ]
        
        return {
            "status": "success",
            "count": len(formatted_parcels),
            "data": formatted_parcels
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch parcels. Error: {str(e)}"
        )