from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
import model
from database import get_db
from dependencies import get_current_admin  # Import our security guard
from pydantic import BaseModel

router = APIRouter(
    prefix="/api/v1/database",
    tags=["Databases"]
)

class DBCreate(BaseModel):
    name: str
    db_host: str
    db_port: str = "5432"
    db_user: str
    db_password: str
    db_name: str


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register_target_db(
    db_data: DBCreate,
    db: Session = Depends(get_db),
    current_admin: model.User = Depends(get_current_admin),
):
    new_db = model.RegisteredDatabase(
        name=db_data.name,
        db_host=db_data.db_host,
        db_port=db_data.db_port,
        db_user=db_data.db_user,
        db_password=db_data.db_password,
        db_name=db_data.db_name,
        owner_id=current_admin.id,
    )

    db.add(new_db)
    db.commit()
    db.refresh(new_db)

    return {"message": "Database registered successfully", "database_id": new_db.id}


@router.get("/get_registered-databases")
def get_registered_databases(
    db: Session = Depends(get_db),
    current_admin: model.User = Depends(get_current_admin),
):
    databases = (
        db.query(model.RegisteredDatabase)
        .filter(model.RegisteredDatabase.owner_id == current_admin.id)
        .all()
    )
    return databases


@router.delete("/registered-databases/{db_id}")
def delete_registered_database(
    db_id: int,
    db: Session = Depends(get_db),
    current_admin: model.User = Depends(get_current_admin),
):
    database = (
        db.query(model.RegisteredDatabase)
        .filter(
            model.RegisteredDatabase.id == db_id,
            model.RegisteredDatabase.owner_id == current_admin.id,
        )
        .first()
    )

    if not database:
        raise HTTPException(
            status_code=404,
            detail="Database profile not found",
        )

    db.delete(database)
    db.commit()

    return {
        "status": "success",
        "message": f"Database '{database.db_name}' deleted successfully.",
    }