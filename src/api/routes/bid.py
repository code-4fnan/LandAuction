from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
import src.db.redis as redis_db

# Import the WebSocket manager to broadcast updates
from src.websockets.manager import auction_manager

# Create a router for all bid-related endpoints
router = APIRouter(prefix="/api/bids", tags=["Bidding"])

# Define the expected shape of the incoming request
class BidRequest(BaseModel):
    auction_id: str
    user_id: str
    amount: float

@router.post("/")
async def place_bid(bid: BidRequest):
    # Ensure Redis is connected before trying to process
    if not redis_db.redis_client or not redis_db.place_bid_script:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, 
            detail="Redis connection is not initialized."
        )
        
    # Construct the exact Redis keys for this specific auction
    price_key = f"auction:{bid.auction_id}:price"
    winner_key = f"auction:{bid.auction_id}:winner"
    
    try:
        # Execute the compiled Lua script in Redis
        result = await redis_db.place_bid_script(
            keys=[price_key, winner_key],
            args=[bid.amount, bid.user_id],
            client=redis_db.redis_client
        )
        
        if result == 1:
            # The bid was successful! Broadcast the new price to everyone watching.
            await auction_manager.broadcast_price_update(
                auction_id=bid.auction_id,
                new_price=bid.amount,
                winner_id=bid.user_id
            )
            
            return {
                "status": "success",
                "message": "Bid accepted! You are now the highest bidder.",
                "auction_id": bid.auction_id,
                "current_price": bid.amount
            }
        else:
            # If the script returns 0, the bid wasn't high enough
            current_high_bid = await redis_db.redis_client.get(price_key)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Bid rejected. Your bid must be higher than {current_high_bid}."
            )
            
    except Exception as e:
        # Catch any unexpected Redis errors
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, 
            detail=str(e)
        )