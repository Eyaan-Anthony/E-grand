from fastapi import APIRouter, Depends, HTTPException, Query, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from app.database import get_db
from app.models import Products
from datetime import datetime, UTC
from app.redis_client import get_from_cache, set_to_cache, invalidate_cache, set_idempotency_key_to_cache
from pydantic import BaseModel
from typing import List
import secrets
from uuid import uuid4

class CartItem(BaseModel):
    product_id: int
    quantity: int

class CartCheckout(BaseModel):
    items: List[CartItem]

#for separation of concerns we create a products.py file
router = APIRouter(prefix="/checkout", tags=["Checkout"])

@router.post("/checkout/split", status_code=200)
async def process_split_checkout(cart: CartCheckout, db: AsyncSession = Depends(get_db), 
                                 idempotency_key: str = Header(..., alias="Idempotency-Key"),
                                 payment_option : str =Header(..., alias="payment_option") ):

    
    service_fee = 200.0  # Base service fee
    subtotal = 0.0
    allocation_plan = []
    # Start explicit transaction context
    async with db.begin():
        try:
            claimed = await set_idempotency_key_to_cache()
            
            for cart_item in cart.items:
                remaining_needed = cart_item.quantity

                # 1. Fetch available stock across stores for this product, locking the rows (FOR UPDATE)
                inv_query = text("""
                    SELECT store_id, product_id, quantity 
                    FROM store_inventory 
                    WHERE product_id = :product_id AND quantity > 0
                    ORDER BY quantity DESC
                    FOR UPDATE;
                """)
                result = await db.execute(inv_query, {"product_id": cart_item.product_id})
                stores_with_stock = result.fetchall()

                # Check global stock sufficiency
                #the sum of all stock available for this specific product
                total_available = sum(s.quantity for s in stores_with_stock)
                if total_available < remaining_needed:
                    raise HTTPException(
                        status_code=400, 
                        detail=f"Insufficient inventory for product ID {cart_item.product_id}. Requested: {remaining_needed}, Available: {total_available}"
                    )

                else : 
                  cached = await get_from_cache("idempotency_keys")
                  if cached :
                      return cached["idem"]
                  else : 
                    idempotent_query = text("SELECT * FROM orders WHERE idempotency_key = :idempotency_key")
                    idem_result = db.execute(idempotent_query, params={"idempotency_key" : idempotency_key})
                    if idem_result.fetchone():
                        #well if not in cache, check db
                        return idem_result.fetchone() #this maynot be a dictionary tho, so adjust for that
                    else : 

                      # 2. Fetch product details for pricing
                      prod_query = text("SELECT uniform_price, product_name FROM products WHERE product_id = :product_id")
                      prod_res = await db.execute(prod_query, {"product_id": cart_item.product_id})
                      product = prod_res.fetchone()

                      if not product:
                          raise HTTPException(status_code=404, detail=f"Product ID {cart_item.product_id} not found.")

                      subtotal += float(product.uniform_price) * cart_item.quantity

                      # 3. Greedily distribute the required quantity across stores
                      for store in stores_with_stock:
                          if remaining_needed <= 0:
                              break

                      take_qty = min(store.quantity, remaining_needed)

                      allocation_plan.append({
                            "store_id": store.store_id,
                            "product_id": cart_item.product_id,
                            "quantity_taken": take_qty
                        })

                      remaining_needed -= take_qty

                  # 4. Apply all inventory updates in bulk after validation passes completely
                  for allocation in allocation_plan:
                      update_query = text("""
                          UPDATE store_inventory 
                          SET quantity = quantity - :qty, updated_at = :updated_at 
                          WHERE store_id = :store_id AND product_id = :product_id;
                      """)
                      await db.execute(update_query, {
                          "qty": allocation["quantity_taken"],
                          "store_id": allocation["store_id"],
                          "product_id": allocation["product_id"],
                          "updated_at": datetime.now(UTC)
                      })

                  grand_total = subtotal + service_fee

                  insert_query = text("""INSERT INTO orders(order_id, idempotency_key, total_amount, status, created_on
                  updated_on)
                  VALUES (:idempotency_key, :total_amount, :status, :created_on, :updated_on)
                  RETURNING order_id, idempotency_key, total_amount, status, payment_option, created_on""")
                  params = {
                      "idempotency_key" : idempotency_key,
                      "total_amount" : grand_total,
                      "status" : "PENDING",
                      #we will update this to completed or failed, relative to the response of the payment api,
                      "payment_option" : payment_option,
                      "created_on" : datetime.now(UTC)
                  }

                  order = await db.execute(insert_query, params=params)
                  await invalidate_cache("idempotency_keys")





                  # Note: db.begin() automatically commits here if no exception is raised!
                  return {
                      "message": "Split checkout successful!",
                      "subtotal": subtotal,
                      "service_fee": service_fee,
                      "grand_total": grand_total,
                      "fulfillment_plan": allocation_plan
                  }
                  #from here we will taylor the response that is sent to the payment api

        except HTTPException as he:
              # Context manager handles rollback automatically, but we re-raise the HTTP error
          raise he
        except Exception as e:
          raise HTTPException(status_code=500, detail=f"Checkout transaction failed: {str(e)}")