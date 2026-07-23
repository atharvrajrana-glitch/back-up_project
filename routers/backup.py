from fastapi import APIRouter , Depends, HTTPException, status
from sqlalchemy.orm import Session
from database import get_db
from dependencies import get_current_admin
from utils.backup import run_postgres_backup, run_postgres_restore ,get_s3_bucket_config ,_fetch_backups_from_s3, _owned_db_names
from utils.restore import run_backup_reconcile
import model
import boto3
import os

router = APIRouter(prefix="/api/v1/backups", tags=["Backups Automation"])
AWS_ACCESS_KEY=os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_KEY=os.getenv("AWS_SECRET_ACCESS_KEY")
AWS_REGION=os.getenv("AWS_REGION")
BUCKET_NAME=os.getenv("AWS_BUCKET_NAME")

s3_client = boto3.client(
    "s3",
    aws_access_key_id=os.getenv("AWS_ACCESS_KEY"),
    aws_secret_access_key=os.getenv("AWS_SECRET_KEY"),
    region_name=os.getenv("AWS_REGION")
)

@router.post("/trigger/{database_id}", status_code=status.HTTP_200_OK)
def trigger_database_backup(
    database_id:int,
    db: Session = Depends(get_db),
    current_user: model.User = Depends(get_current_admin)
):
    result = run_postgres_backup(db_id=database_id,db=db)

    if result["status"] == "error":
        raise HTTPException(status_code=404, detail=result["message"])
    
    if result["status"] == "failed":
        raise HTTPException(status_code=500,detail=result)
    return result

@router.post("/restore/{db_id}")
def restore_database(db_id: int, s3_filename: str, db: Session = Depends(get_db)):
    result = run_postgres_restore(db_id, s3_filename, db)
    if result["status"] != "success":
        raise HTTPException(status_code=500, detail=result)
    return result


@router.post("/reconcile/{db_id}")
def reconcile_database(db_id: int, s3_filename: str, db: Session = Depends(get_db)):
    result = run_backup_reconcile(db_id, s3_filename, db)
    if result["status"] != "success":
        raise HTTPException(status_code=500, detail=result)
    return result

@router.get("/list/{db_id}")
def list_backups(
    db_id: int,
    db: Session = Depends(get_db),
    current_user: model.User = Depends(get_current_admin)
):
    """Backups belonging to this specific database only (used for Reconcile)."""
    database = db.query(model.RegisteredDatabase).filter(
        model.RegisteredDatabase.id == db_id,
        model.RegisteredDatabase.owner_id == current_user.id,
    ).first()
    if not database:
        raise HTTPException(status_code=404, detail="Database not found")

    prefix = f"backups/{database.db_name}_"
    return _fetch_backups_from_s3(prefix)


@router.get("/list-all")
def list_all_backups(
    db: Session = Depends(get_db),
    current_user: model.User = Depends(get_current_admin),
):
    """
    All backups belonging to databases this admin owns — across every
    database they registered, not just one. Used for Restore, so they
    can move a backup from an old/renamed db onto a new target, but
    never see another admin's backups.
    """
    owned_names = _owned_db_names(current_user.id, db)
    if not owned_names:
        return []

    all_backups = []
    for name in owned_names:
        all_backups.extend(_fetch_backups_from_s3(prefix=f"backups/{name}_"))

    all_backups.sort(key=lambda b: b["last_modified"], reverse=True)
    return all_backups

