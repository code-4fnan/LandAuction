from fastapi import WebSocket
from typing import Dict, List

class ConnectionManager:
    def __init__(self):
        # A dictionary to hold lists of active connections per auction
        # Example: {"parcel-101": [connection1, connection2]}
        self.active_connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, auction_id: str):
        await websocket.accept()
        if auction_id not in self.active_connections:
            self.active_connections[auction_id] = []
        self.active_connections[auction_id].append(websocket)
        print(f"🔌 New viewer connected to {auction_id}")

    def disconnect(self, websocket: WebSocket, auction_id: str):
        if auction_id in self.active_connections:
            self.active_connections[auction_id].remove(websocket)
            print(f"❌ Viewer disconnected from {auction_id}")

    async def broadcast_price_update(self, auction_id: str, new_price: float, winner_id: str):
        # Send the new price to everyone currently watching this specific auction
        if auction_id in self.active_connections:
            message = {
                "type": "NEW_BID",
                "auction_id": auction_id,
                "current_price": new_price,
                "winner_id": winner_id
            }
            for connection in self.active_connections[auction_id]:
                await connection.send_json(message)

# Create a single global instance of the manager to use across the app
auction_manager = ConnectionManager()