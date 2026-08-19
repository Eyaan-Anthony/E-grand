import redis.asyncio as redis
import json
from fastapi import HTTPException

# Connection singleton
redis_conn = redis.Redis(
    host='localhost', 
    port=6379, 
    db=0, 
    decode_responses=True
)

#change of all these to try except blocks
#since redis can crash too

async def get_from_cache(key: str):
    try : 
        data = await redis_conn.get(key)
        return json.loads(data) if data else None
        #get json string from cache, convert to python dictionary
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Redis error : {e}")
        

async def set_to_cache(key: str, data, expire: int = 300):
    try : 
        # We use json.dumps because Redis only stores strings/bytes
        await redis_conn.set(key, json.dumps(data, default=str), ex=expire)
    except Exception as e :
        raise HTTPException(status_code=400, detail=f"Redis error : {e}")


async def set_idempotency_key_to_cache(key: str, data, expire: int = 300):
    try :
        # We use json.dumps because Redis only stores strings/bytes
        await redis_conn.set(key, json.dumps(data, default=str), ex=expire, nx=True)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Redis error : {e}")

async def invalidate_cache(pattern: str):
    """
    Deletes keys matching a pattern (e.g., 'products_*').
    Redis 'keys' command can be slow, but for an MVP it works well.
    """
    try : 
        keys = await redis_conn.keys(f"{pattern}*")
        if keys:
            await redis_conn.delete(*keys)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Redis error : {e}")