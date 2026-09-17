from sqlalchemy import Column, Integer, String, Float, DateTime
from geoalchemy2 import Geometry
from src.db.database import Base
import datetime

class LandParcel(Base):
    __tablename__ = "land_parcels"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    description = Column(String)
    
    # The starting price of the auction
    starting_price = Column(Float, nullable=False)
    
    # SRID 4326 is the standard coordinate system used by GPS and Google Maps
    boundary = Column(Geometry(geometry_type='POLYGON', srid=4326))
    
    auction_end_time = Column(DateTime, default=lambda: datetime.datetime.utcnow() + datetime.timedelta(days=7))