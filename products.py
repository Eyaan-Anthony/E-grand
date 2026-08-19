from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from app.database import get_db
from app.models import Products
from pydantic import BaseModel #data validation
from datetime import datetime, UTC
from app.redis_client import get_from_cache, set_to_cache, invalidate_cache

#for separation of concerns we create a products.py file
router = APIRouter(prefix="/products", tags=["Products"])

class ProductCreate(BaseModel):
    product_name : str
    brand_name : str
    product_description : str
    product_category : str
    image_url : str | None
    uniform_price : float
    is_on_sale: bool = False
    sale_price: float | None = None
    sale_ends_at: datetime | None = None
    class Config:
              from_attributes = True


class ProductCreateResponse(BaseModel):
  #when we create product, we define the response model
  product_id : int
  product_name : str
  product_description : str
  brand_name : str
  uniform_price : float
  is_on_sale: bool = False
  sale_price: float | None = None
  sale_ends_at: datetime | None = None
  class Config:
          from_attributes = True

class ProductUpdate(BaseModel):
  product_name: str | None = None
  brand_name: str | None = None
  product_description: str | None = None
  product_category: str | None = None
  image_url: str | None = None
  uniform_price: float | None = None
  is_on_sale: bool | None = None
  sale_price: float | None = None
  sale_ends_at: datetime | None = None


class ProductResponse(BaseModel):
    product_id: int
    product_name: str
    product_description: str | None = None
    brand_name: str
    uniform_price: float
    is_on_sale: bool
    sale_price: float | None = None
    sale_ends_at: datetime | None = None

    class Config:
        from_attributes = True
     

@router.post("/add_product", response_model=ProductCreateResponse, status_code=201)
async def add_product(product_data : ProductCreate,
                      db : AsyncSession = Depends(get_db)):
     """To add a new product"""
     try :
          query = text("""INSERT INTO products (product_name, brand_name, product_description,
          product_category, image_url, uniform_price, is_on_sale, sale_price, sale_ends_at, created_at)
          VALUES(:name, :brand, :description, :category, :url, :price, :is_sale, :sale_price, :sale_ends, :created_at)
          RETURNING product_id, product_name, product_description, brand_name, uniform_price, is_on_sale, sale_price, sale_ends_at;
          """)

          result = await db.execute(query, params=
                          {
                              "name" : product_data.product_name,
                              "brand" : product_data.brand_name,
                              "description" : product_data.product_description,
                              "category" : product_data.product_category,
                              "url" : product_data.image_url,
                              "price" : product_data.uniform_price,
                              "is_sale": product_data.is_on_sale,
                              "sale_price": product_data.sale_price,
                              "sale_ends": product_data.sale_ends_at,
                              "created_at" : datetime.now(UTC)       
                          })
          new_product = result.fetchone()
          #we fetch the just inserted product
          #this has to invalidate cache
          await invalidate_cache(pattern= "all_products_list")
          #the cache will be regenerated the next time some does a get or post request
          return {
              "product_id" : new_product.product_id,
              "product_name" : new_product.product_name,
              "product_description" : new_product.product_description,
              "brand_name" : new_product.brand_name,
              "uniform_price" : float(new_product.uniform_price),
              "is_on_sale": new_product.is_on_sale,
              "sale_price": float(new_product.sale_price) if new_product.sale_price else None,
              "sale_ends_at": new_product.sale_ends_at
          }
     except Exception as e:
        # Catching and raising a clean HTTP 400/500 error instead of crashing the server
        raise HTTPException(status_code=400, detail=f"Database error: {str(e)}")

#then add delete product, edit product endpoints etc etc
#i was also thinking about modifying the product part of this, add a sales attribute
#if sales then new price is what, check new price is less than original price, now maybe add
#a sales duration too, so that it automatically sets the original price back to normal,

#get products endpoint
@router.get("/", status_code=200)
async def get_products(
    db: AsyncSession = Depends(get_db), 
    brand: str | None = None, 
    category: str | None = None, 
    sales: bool | None = None, 
    price_sort: str | None = None, # "asc" or "desc"
    page: int = 1, 
    page_size: int = 50
):
    try:
        cache_key = "all_products_list"

        #check cache
        cached = await get_from_cache(cache_key)
        if cached:
            return cached #here the result is a python dict

        query = "SELECT * FROM products WHERE 1=1 "
        offset = (page - 1) * page_size
        params = {}

        if brand:
            query += " AND brand_name = :brand "
            params["brand"] = brand
        if category: 
            query += " AND product_category = :category "
            params["category"] = category
        if sales is not None:
            query += " AND is_on_sale = :sales "
            params["sales"] = sales

        if price_sort == "asc":
            query += " ORDER BY uniform_price ASC "
        elif price_sort == "desc":
            query += " ORDER BY uniform_price DESC "

        query += " LIMIT :page_size OFFSET :offset "
        params["page_size"] = page_size
        params["offset"] = offset

        #here we write to cache
        
        results = await db.execute(text(query), params=params)
        products = results.fetchall()

        # Convert rows to dicts for clean JSON serialization
        product_list = [
            {
                "product_id": p.product_id,
                "product_name": p.product_name,
                "product_description": p.product_description,
                "brand_name": p.brand_name,
                "uniform_price": float(p.uniform_price),
                "is_on_sale": p.is_on_sale,
                "sale_price": float(p.sale_price) if p.sale_price else None,
                "sale_ends_at": p.sale_ends_at
            } for p in products
        ]

        await set_to_cache(cache_key, product_list)

        return {
            "page": page,
            "page_size": page_size,
            "items": product_list
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Database error: {str(e)}")


@router.get("/{product_id}", response_model=ProductResponse, status_code=200)
async def get_product_by_id(product_id: int, db: AsyncSession = Depends(get_db)):
    try:
        #check cache
        cache_key = f"product:{product_id}"
        cache_product = await get_from_cache(cache_key)
        if cache_product :
            return cache_product
        #check cache return only element we want, can a cache contain multiple instances of data?
        #this kinds of defeats the purpose of the cache, it's not a db, it stores data in a ram
        #also i don't think it is worth it to invalidate cache after a single search
        query = text("SELECT * FROM products WHERE product_id = :product_id")
        result = await db.execute(query, {"product_id": product_id})
        product = result.fetchone()

        if not product:
            raise HTTPException(status_code=404, detail="Product not found")

        response_data =  {
            "product_id": product.product_id,
            "product_name": product.product_name,
            "product_description": product.product_description,
            "brand_name": product.brand_name,
            "uniform_price": float(product.uniform_price),
            "is_on_sale": product.is_on_sale,
            "sale_price": float(product.sale_price) if product.sale_price else None,
            "sale_ends_at": product.sale_ends_at
        }
        await set_to_cache(cache_key, response_data)
        return response_data
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Database error: {str(e)}")

@router.put("/{product_id}", response_model=ProductResponse, status_code=200)
async def edit_product(product_id: int, product_data: ProductUpdate, db: AsyncSession = Depends(get_db)):
    try:
        # Dynamically build the update query based on provided fields
        fields = []
        params = {"product_id": product_id}

        update_data = product_data.model_dump(exclude_unset=True)
        if not update_data:
            raise HTTPException(status_code=400, detail="No fields provided for update")

        for key, value in update_data.items():
            fields.append(f"{key} = :{key}")
            params[key] = value

        query = f"UPDATE products SET {', '.join(fields)} WHERE product_id = :product_id RETURNING *"
        
        result = await db.execute(text(query), params=params)
        await db.commit()
        updated_product = result.fetchone()

        if not updated_product:
            raise HTTPException(status_code=404, detail="Product not found")

        #this has to invalidate cache
        await invalidate_cache("all_products_list")
        await invalidate_cache(f"product:{product_id}")
        #the cache will be regenerated the next time some does a get or post request
        response_data =  {
            "product_id": updated_product.product_id,
            "product_name": updated_product.product_name,
            "product_description": updated_product.product_description,
            "brand_name": updated_product.brand_name,
            "uniform_price": float(updated_product.uniform_price),
            "is_on_sale": updated_product.is_on_sale,
            "sale_price": float(updated_product.sale_price) if updated_product.sale_price else None,
            "sale_ends_at": updated_product.sale_ends_at
        }
        await set_to_cache(key=f"product:{product_id}", data=response_data)
        #we can set to cache directly, since the response model corresponds directly to the product data
        return response_data
    except HTTPException as he:
        raise he
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=f"Database error: {str(e)}")


#drop products
@router.delete("/{product_id}", status_code=200)
async def drop_product(product_id: int, db: AsyncSession = Depends(get_db)):
    try:
        query = text("DELETE FROM products WHERE product_id = :product_id RETURNING product_id")
        result = await db.execute(query, {"product_id": product_id})
        await db.commit()
        deleted = result.fetchone()

        if not deleted:
            raise HTTPException(status_code=404, detail="Product not found")

        #this has to invalidate cache
        await invalidate_cache("all_products_list")
        await invalidate_cache(pattern= f"product:{product_id}")
        #the cache will be regenerated the next time some does a get or post request

        return {"message": f"Product with ID {product_id} successfully deleted"}
    except HTTPException as he:
        raise he
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=f"Database error: {str(e)}")
         
          
         


           
      
         


         

     

     
     