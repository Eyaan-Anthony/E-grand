# app/routers/stores.py
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from app.database import get_db
from app.models import Store
from pydantic import BaseModel #data validation
from datetime import datetime, UTC
from app.redis_client import get_from_cache, set_to_cache, invalidate_cache

router = APIRouter(prefix="/stores", tags=["Stores & Proximity"])

class StoreResponse(BaseModel):
    store_id: int
    store_name: str
    address: str
    distance_km: float

    class Config:
        from_attributes = True

class StoreCreateResponse(BaseModel):
    store_id: int
    store_name: str
    address: str

    class Config:
        from_attributes = True


class StoreCreate(BaseModel):
    store_name: str
    store_logo_url: str | None = None
    address: str
    latitude: float   # e.g., 4.0815
    longitude: float  # e.g., 9.7645

class InventoryItemResponse(BaseModel):
    product_id: int
    quantity: int
    updated_at: str | None = None

    class Config:
        from_attributes = True

class InventoryUpdate(BaseModel):
    product_id: int
    quantity: int

    class Config:
        from_attributes = True

class GetStoreResponse(BaseModel) :
    store_id: int
    store_name: str
    address: str
    


#endpoint creation here
@router.get("/nearest", response_model=StoreResponse)
async def get_nearest_store(
    lat: float = Query(..., description="User latitude (e.g., 4.0511 for Douala)"),
    lon: float = Query(..., description="User longitude (e.g., 9.7679 for Douala)"),
    db: AsyncSession = Depends(get_db)
):
    """
    Uses PostGIS spatial functions (ST_Distance) to find the absolute 
    closest physical store branch relative to the user's GPS coordinates.
    """
    try:
        cache_key = "stores_list"
        cache = await get_from_cache(cache_key)
        #this may be a little tricky
        if cache : 
            for item in cache:
                #we may need to compute distance here
                #and return nearest store, is it a good idea to do it from cache?
                #we are not going to have an extensive amount of stores, at most
                #we are going to have in the best case hundreds of entries
                continue
                
        # PostGIS query: ST_MakePoint(lon, lat) creates a point, CAST(location AS geography) calculates true surface distance in meters
        query = text("""
            SELECT 
                store_id, 
                store_name, 
                address, 
                ST_Distance(
                    location::geography, 
                    ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography
                ) / 1000 AS distance_km
            FROM stores
            ORDER BY location::geography <-> ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography
            LIMIT 1;
        """)
        #limit 1 here return only the top row
        
        result = await db.execute(query, {"lat": lat, "lon": lon})
        store = result.fetchone()

        if not store:
            raise HTTPException(status_code=404, detail="No active stores found.")

        return {
            "store_id": store.store_id,
            "store_name": store.store_name,
            "address": store.address,
            "distance_km": round(store.distance_km, 2)
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/", response_model=StoreCreateResponse, status_code=201)
async def add_store(
    store_data: StoreCreate,  # FastAPI automatically validates the JSON body against this!
    db: AsyncSession = Depends(get_db)
):
    """Insert a new physical store branch into the database with PostGIS coordinates."""
    try:
        # Secure parameterized query (notice how we use bind parameters like :name instead of f-strings)
        query = text("""
            INSERT INTO stores (store_name, store_logo_url, address, location, created_at)
            VALUES (:name, :logo, :address, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography, :created_at)
            RETURNING store_id, store_name, address;
        """)
        result = await db.execute(query, {
            "name": store_data.store_name,
            "logo": store_data.store_logo_url,
            "address": store_data.address,
            "lat": store_data.latitude,
            "lon": store_data.longitude,
            "created_at": datetime.now(UTC)
        })
        
        new_store = result.fetchone()

        #fetch the row that was just inserted
        
        return {
            "store_id": new_store.store_id,
            "store_name": new_store.store_name,
            "address": new_store.address
        }

    except Exception as e:
        # Catching and raising a clean HTTP 400/500 error instead of crashing the server
        raise HTTPException(status_code=400, detail=f"Database error: {str(e)}")


@router.get("/stores/{store_id}/inventory", response_model=GetStoreResponse, status_code=200)
async def get_store_inventory(
    store_id: int, 
    include_inventory: bool = True, 
    page: int = 1, 
    page_size: int = 50, 
    db: AsyncSession = Depends(get_db)
):
    try:
        # 1. First, fetch the store details to make sure it exists
        cache_key = f"store_inventory:{store_id}:p{page}"
        if include_inventory:
          cached_data = await get_from_cache(cache_key)
        if cached_data:
            return cached_data
        store_query = text("SELECT store_id, store_name, address FROM stores WHERE store_id = :store_id")
        store_res = await db.execute(store_query, {"store_id": store_id})
        store = store_res.fetchone()
        #aren't we supposed to get cache too?, i don't think so, since the sql query here
        #only looks for a specific entry, where would i get the data to set to cache from
        if not store:
            raise HTTPException(status_code=404, detail="Store not found!")

        inventory_items = []
        
        # 2. If inventory is requested, fetch the paginated items for this store
        offset = (page - 1) * page_size
        inv_query = text("""
                SELECT product_id, quantity, updated_at 
                FROM store_inventory 
                WHERE store_id = :store_id 
                LIMIT :page_size OFFSET :offset;
            """)
        inv_res = await db.execute(inv_query, {
                "store_id": store_id, 
                "page_size": page_size, 
                "offset": offset
            })
        items = inv_res.fetchall()
            
        inventory_items = [
                {
                    "product_id": item.product_id,
                    "quantity": item.quantity,
                    "updated_at": str(item.updated_at) if item.updated_at else None
                } for item in items
            ]

        response_data = {
            "store_id": store.store_id,
            "store_name": store.store_name,
            "address": store.address,
            "inventory": inventory_items
        } 
        
        # 3. Save to cache ONLY if inventory was included
        if include_inventory:
          await set_to_cache(cache_key, response_data, expire=300)
        return response_data

    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Database error : {str(e)}")


@router.post("/stores/{store_id}/inventory", status_code=200, response_model=InventoryItemResponse)
async def update_inventory(
    store_id: int, 
    inventory_data: InventoryUpdate, 
    db: AsyncSession = Depends(get_db)
):
    try:
        # 1. Verify store exists
        store_query = text("SELECT store_id FROM stores WHERE store_id = :store_id")
        store_res = await db.execute(store_query, {"store_id": store_id})
        store = store_res.fetchone()

        if not store:
            raise HTTPException(status_code=404, detail="Store not found!")

        # 2. Upsert inventory (Insert if new, Update quantity if already exists)
        #if there is a conflict while inserting, update the specified values of the excluded row
        #the excluded row here is the row we're trying to insert
        inv_query = text("""
            INSERT INTO store_inventory (store_id, product_id, quantity, updated_at)
            VALUES (:store_id, :product_id, :quantity, :updated_at)
            ON CONFLICT (store_id, product_id) 
            DO UPDATE SET quantity = EXCLUDED.quantity, updated_at = EXCLUDED.updated_at
            RETURNING product_id, quantity, updated_at;
        """)

        params = {
            "store_id": store_id,
            "product_id": inventory_data.product_id,
            "quantity": inventory_data.quantity,
            "updated_at": datetime.now(UTC)
        }

        inv_result = await db.execute(inv_query, params=params)
        await db.commit()
        await invalidate_cache(f"store_inventory:{store_id}")
        updated_row = inv_result.fetchone()

        return {
            "product_id": updated_row.product_id,
            "quantity": updated_row.quantity,
            "updated_at": updated_row.updated_at
        }

    except HTTPException as he:
        raise he
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=f"Database error: {str(e)}")



            

