from sqlalchemy import Column , Integer , String , Boolean , DateTime ,ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import datetime
from database import Base

class User(Base):
    """Table that store admin account.
        protected by password hashing.
    """
    __tablename__="users"


    id=Column(Integer,primary_key=True,autoincrement=True)
    username=Column(String , unique=True,index=True,nullable=False)
    hashed_password= Column(String,nullable=False)
    role= Column(String, default="admin")
    is_active = Column(Boolean , default=True)

class RegisteredDatabase(Base):

    __tablename__ = "ragistered_database"

    id = Column(Integer , primary_key=True , autoincrement=True)
    name = Column(String , nullable=False)

    db_host = Column(String,nullable=False)
    db_port = Column(String , default="5432")
    db_user = Column(String , nullable=False)
    db_password = Column(String,nullable=False)
    db_name = Column(String, nullable=False)
    is_active = Column(Boolean , default=True)
    created_at = Column (DateTime, default=datetime.utcnow)

    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)