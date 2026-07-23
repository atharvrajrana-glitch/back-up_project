import os
import subprocess
import boto3
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from fastapi import  HTTPException
from botocore.exceptions import NoCredentialsError , ClientError
import model

BACKUP_DIR = os.path.join(os.getcwd(), "storage", "backups")
os.makedirs(BACKUP_DIR, exist_ok=True)


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

def download_from_s3(s3_filename:str,local_path:str) ->bool:
    try:
        s3_client.download_file(BUCKET_NAME , s3_filename , local_path)
        return True
    except Exception as e :
        print(f"S3 download failed: {e}")
        return False

def upload_to_s3(local_file_path:str,s3_filename:str)-> bool:
    """function to upload the local file to the AWS cloud bucket"""
    s3_client = boto3.client(
        "s3",
        aws_access_key_id=AWS_ACCESS_KEY,
        aws_secret_access_key=AWS_SECRET_KEY,
        region_name=AWS_REGION
    )

    try:
        print(f"Uploading {s3_filename} to AWS S3 bucket:{BUCKET_NAME}")
        s3_client.upload_file(local_file_path,BUCKET_NAME , f"backups/{s3_filename}")
        print("Cloud upload successful!")
        return True
    
    except (NoCredentialsError , ClientError) as e :
        print(f"AWS cloud upload failure:{str(e)}")
        return False

def run_postgres_backup(db_id: int, db: Session) -> dict:
    """
    Spins up an isolated, temporary PostgreSQL worker container to pull a data snapshot
    from the target database profile, streams it out, and automatically deletes itself.
    """
    # 1. Fetch the target database profile from the metadata registry
    db_profile = db.query(model.RegisteredDatabase).filter(model.RegisteredDatabase.id == db_id).first()
    if not db_profile:
        return {"status": "error", "message": "Database profile not found"}

    # 2. Set up file timestamps and naming conventions
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"{db_profile.db_name}_{timestamp}.sql"
    output_path = os.path.join(BACKUP_DIR, filename)

    # DOCKER CONFIGURATION 
    # We bridge onto your isolated app network, using a matching major version image
    DOCKER_NETWORK = "app_network" 
    POSTGRES_IMAGE = "postgres:16"  # Using stable v16 CLI utility client

    #EPHEMERAL DOCKER RUN COMMAND
    command = [
        "docker", "run", "--rm",
        "--network", DOCKER_NETWORK,
        "-e", f"PGPASSWORD={db_profile.db_password}",
        POSTGRES_IMAGE,
        "pg_dump",
        "-h", db_profile.db_host,  # Internal container service name/host address
        "-p", str(db_profile.db_port),
        "-U", db_profile.db_user,
        "-d", db_profile.db_name,
        "-F", "p"
    ]

    try:
        # Execute the container and pipe the streamed stdout directly to your hard drive
        with open(output_path, "w", encoding="utf-8") as out_file:
            process = subprocess.run(
                command,
                stdout=out_file,
                stderr=subprocess.PIPE,
                text=True,
                check=True
            )
        file_size = os.path.getsize(output_path)

        upload_success = upload_to_s3(output_path , filename)

        if os.path.exists(output_path):
            os.remove(output_path)
            print("Cleaned up local snapshot file")
        
        if upload_success:
            return {
                "status":"success",
                "message":f"successfully stored in AWS S3",
                "filename":filename,
                "size_bytes":file_size
            }
        else:
            return {"status":"failed","message":"Database backup generated but S3 upload failed."}
            
    except subprocess.CalledProcessError as e:
        if os.path.exists(output_path):
            os.remove(output_path)
        print(f" [EPHEMERAL CRASH]: {e.stderr}")
        return {
            "status": "failed",
            "message": "Ephemeral backup container worker execution failed",
            "error": e.stderr
        }
    except Exception as e:
        if os.path.exists(output_path):
            os.remove(output_path)
        return {
            "status": "failed",
            "message": "An unexpected orchestration error occurred",
            "error": str(e)
        }
    
def run_postgres_restore(db_id:int , s3_filename:str , db:Session) -> dict:

    db_profile = db.query(model.RegisteredDatabase).filter(model.RegisteredDatabase.id == db_id).first()
    if not db_profile:
        return {"status": "error", "message": "Database profile not found"}
    
    local_filename = os.path.basename(s3_filename)
    local_path = os.path.join(BACKUP_DIR, local_filename)

    download_success = download_from_s3(s3_filename,local_path)
    if not download_success:
        return {"status":"error","message":"Failed to download bckup from s3"}
    
    DOCKER_NETWORK="app_network"
    POSTGRES_IMAGE="postgres:16"

    command = [
        "docker" , "run" , "--rm" , "-i",
        "--network", DOCKER_NETWORK,
        "-e", f"PGPASSWORD={db_profile.db_password}",
        POSTGRES_IMAGE,
        "psql",
        "-h", db_profile.db_host,
        "-p", str(db_profile.db_port),
        "-U", db_profile.db_user,
        "-d", db_profile.db_name,
        "-v", "ON_ERROR_STOP=1"
    ]
    try:
        with open(local_path, "r", encoding="utf-8") as sql_file:
            process = subprocess.run(
                command,
                stdin=sql_file,
                stderr=subprocess.PIPE,
                text=True,
                check=True,
                timeout=600   # 10 min safety timeout — adjust based on your DB size
            )

        if os.path.exists(local_path):
            os.remove(local_path)
            print("Cleaned up local restore file")

        return {
            "status": "success",
            "message": f"Database restored from {s3_filename}",
            "filename": s3_filename
        }

    except subprocess.CalledProcessError as e:
        if os.path.exists(local_path):
            os.remove(local_path)
        print(f"[RESTORE FAILED]: {e.stderr}")
        return {
            "status": "failed",
            "message": "Restore container execution failed",
            "error": e.stderr
        }
    except subprocess.TimeoutExpired:
        if os.path.exists(local_path):
            os.remove(local_path)
        return {
            "status": "failed",
            "message": "Restore timed out — database may be too large or unresponsive"
        }
    except Exception as e:
        if os.path.exists(local_path):
            os.remove(local_path)
        return {
            "status": "failed",
            "message": "An unexpected error occurred during restore",
            "error": str(e)
        }
        
def get_s3_bucket_config():
    required_vars = [
        "AWS_BUCKET_NAME",
        "AWS_REGION"
    ]

    missing = [v for v in required_vars if not os.environ.get(v)]

    if missing:
        raise HTTPException(
            status_code=500,
            detail={
                "status": "error",
                "message": (
                    f"Missing required environment variable(s): {', '.join(missing)}. "
                    "Add them to your .env file and recreate the container with "
                ),
            },
        )

    return (
        os.environ["AWS_BUCKET_NAME"],
        os.environ["AWS_REGION"],
    )
    
def _fetch_backups_from_s3(prefix: str):
    bucket, region = get_s3_bucket_config()
    s3 = boto3.client("s3", region_name=region)
    try:
        response = s3.list_objects_v2(Bucket=bucket, Prefix=prefix)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={"status": "error", "message": f"Failed to list backups from S3: {str(e)}"},
        )
    if "Contents" not in response:
        return []
    backups = [
        {
            "filename": obj["Key"],
            "size_bytes": obj["Size"],
            "last_modified": obj["LastModified"].isoformat(),
        }
        for obj in response["Contents"]
    ]
    backups.sort(key=lambda b: b["last_modified"], reverse=True)
    return backups

def _owned_db_names(owner_id: int, db: Session):
    """All db_name values belonging to databases this admin owns."""
    rows = db.query(model.RegisteredDatabase.db_name).filter(
        model.RegisteredDatabase.owner_id == owner_id
    ).all()
    return {r[0] for r in rows}

def _backup_belongs_to_owner(s3_filename: str, owner_id: int, db: Session) -> bool:
    """Checks the backup's filename prefix matches one of this admin's db_names."""
    owned_names = _owned_db_names(owner_id, db)
    return any(s3_filename.startswith(f"backups/{name}_") for name in owned_names)