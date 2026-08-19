from datetime import datetime, UTC
from sqlalchemy import Column, Integer, String, Text, Numeric, DateTime, ForeignKey, UniqueConstraint, Boolean
from sqlalchemy.orm import relationship
from app.database import Base #the declarative base

#so it's like redifining the sql tables here
class Products(Base):
  __tablename__ = "products"
  product_id = Column(Integer, primary_key=True, index=True)
  #primary key, indexing for easy lookups?
  product_name = Column(String(255), nullable=False)
  brand_name = Column(String(100), nullable=False)
  product_description = Column(Text)
  product_category = Column(String(255), nullable=False)
  image_url = Column(Text)
  uniform_price = Column(Numeric(10,2), nullable=False)

  # New Sales fields mapped to SQLAlchemy
  is_on_sale = Column(Boolean, default=False)
  sale_price = Column(Numeric(10, 2), nullable=True)
  sale_ends_at = Column(DateTime(timezone=True), nullable=True)
  
  created_at = Column(DateTime(timezone=True), default = datetime.now(UTC))

  # Relationship to inventory
  #relationship() defines the relationship in Python, making it easy to navigate between related objects.
  inventories = relationship("StoreInventory", back_populates="product", cascade="all, delete-orphan")
  #so it seems here, that we will be able to navigate between the product and store inventory quite easily
  #Instead of writing a SQL query to fetch a store's details using a store ID, you can just type inventory_item.store.store_name.
  #"Hey Product, you can look up all your inventory entries across different stores by calling product.inventories

class Store(Base):
  __tablename__ = "stores"

  store_id = Column(Integer, primary_key=True, index=True)
  store_name = Column(String(150), nullable=False)
  store_logo_url = Column(Text)
  address = Column(Text, nullable=False)
  # Note: We store the PostGIS geography object. We can query it using raw text/functions in queries.
  location = Column(Text, nullable=False) 
  created_at = Column(DateTime(timezone=True), default = datetime.now(UTC))

  # Relationship to inventory
  inventories = relationship("StoreInventory", back_populates="store", cascade="all, delete-orphan")
  #"Hey store, you can look up all your inventory and product entries by calling store.inventories

class StoreInventory(Base):
  __tablename__ = "store_inventory"

  inventory_id = Column(Integer, primary_key=True, index=True)
  store_id = Column(Integer, ForeignKey("stores.store_id", ondelete="CASCADE"), nullable=False)
  product_id = Column(Integer, ForeignKey("products.product_id", ondelete="CASCADE"), nullable=False)
  quantity = Column(Integer, nullable=False)
  updated_at = Column(DateTime(timezone=True), default = datetime.now(UTC), onupdate= datetime.now(UTC))

  # Enforce unique constraint matching our SQL init file
  __table_args__ = (
    UniqueConstraint('store_id', 'product_id', name='unique_store_product'),
    )

  # Relationships back to product and store
  store = relationship("Store", back_populates="inventories")
  #Hey store, to know the exact stores holding you, call inventory_item.store
  #recall each row in inventory store corresponds to a store id product id pair
  product = relationship("Product", back_populates="inventories")
  #Hey StoreInventory item, if you want to know what exact product you represent, call inventory_item.product
  #so now both ends of each of these relationships are synchronized 