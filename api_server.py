
import os
from fastapi import FastAPI, Depends, HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from pydantic import BaseModel
import datetime
import pytz
from config import TIMEZONE

# --- Security ---
security = HTTPBearer()
SERVER_API_KEY = os.environ.get("SERVER_API_KEY", "your_default_secret_key")

def get_current_user(credentials: HTTPAuthorizationCredentials = Security(security)):
    if credentials.scheme != "Bearer" or credentials.credentials != SERVER_API_KEY:
        raise HTTPException(status_code=403, detail="Invalid or missing API key")
    return True

# Use the timezone from the config file
CLIENT_TIMEZONE = TIMEZONE
# Convert the string timezone to a pytz timezone object
tz = pytz.timezone(CLIENT_TIMEZONE)

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./activity.db")

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class Activity(Base):
    __tablename__ = "activities"
    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=lambda: datetime.datetime.utcnow()) # Store as UTC
    category = Column(String)
    duration = Column(Integer)
    window_title = Column(String)
    source = Column(String, nullable=True)

Base.metadata.create_all(bind=engine)

app = FastAPI()

# Dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

class ActivityCreate(BaseModel):
    timestamp: float
    category: str
    duration: int
    window_title: str
    source: str | None = None

class ActivityResponse(BaseModel):
    id: int
    timestamp: datetime.datetime
    category: str
    duration: int
    window_title: str
    source: str | None = None

    class Config:
        orm_mode = True

class DailySummary(BaseModel):
    category: str
    total_duration: int

@app.post("/log", response_model=ActivityResponse)
def create_activity(activity: ActivityCreate, db: Session = Depends(get_db), authenticated: bool = Depends(get_current_user)):
    # Convert timestamp to a timezone-aware datetime object
    try:
        if isinstance(activity.timestamp, str):
            # If timestamp is a string, parse it assuming it's in ISO format from the server
            utc_dt = pytz.utc.localize(datetime.datetime.fromisoformat(activity.timestamp.replace('Z', '+00:00')))
        else:
            # Otherwise, assume it's a Unix timestamp (float/int)
            local_dt = tz.localize(datetime.datetime.fromtimestamp(activity.timestamp))
            # Convert to UTC for storage
            utc_dt = local_dt.astimezone(pytz.utc)
    except (ValueError, OSError) as e:
        raise HTTPException(status_code=400, detail=f"Invalid timestamp: {e}")
    
    db_activity = Activity(
        timestamp=utc_dt,
        category=activity.category,
        duration=activity.duration,
        window_title=activity.window_title,
        source=activity.source
    )
    db.add(db_activity)
    db.commit()
    db.refresh(db_activity)
    return db_activity

@app.get("/logs", response_model=list[ActivityResponse])
def read_activities(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    activities = db.query(Activity).offset(skip).limit(limit).all()
    return activities

@app.get("/days", response_model=list[str])
def get_available_days(db: Session = Depends(get_db)):
    """
    Returns a sorted list of unique days ('YYYY-MM-DD') that have activity data,
    adjusted for the client's timezone.
    """
    # The conversion from UTC to the local timezone needs to be handled carefully.
    # For SQLite, we can use the 'localtime' modifier, but for PostgreSQL, it's different.
    # This implementation will assume SQLite for simplicity of the example.
    # A more robust solution would handle different database backends.
    if "sqlite" in DATABASE_URL:
        days = db.query(
            func.strftime('%Y-%m-%d', func.datetime(Activity.timestamp, 'localtime'))
        ).distinct().order_by(func.strftime('%Y-%m-%d', func.datetime(Activity.timestamp, 'localtime')).desc()).all()
    else: # Assuming PostgreSQL
        days = db.query(
            func.to_char(Activity.timestamp.op('AT TIME ZONE')(CLIENT_TIMEZONE), 'YYYY-MM-DD')
        ).distinct().order_by(func.to_char(Activity.timestamp.op('AT TIME ZONE')(CLIENT_TIMEZONE), 'YYYY-MM-DD').desc()).all()

    return [day[0] for day in days]


@app.get("/summary/{day}", response_model=list[DailySummary])
def get_daily_summary(day: str, db: Session = Depends(get_db)):
    """
    Returns the total duration for each category for a specific day,
    adjusted for the client's timezone.
    """
    try:
        datetime.datetime.strptime(day, '%Y-%m-%d')
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")

    if "sqlite" in DATABASE_URL:
        summary = db.query(
            Activity.category,
            func.sum(Activity.duration).label("total_duration")
        ).filter(
            func.strftime('%Y-%m-%d', func.datetime(Activity.timestamp, 'localtime')) == day
        ).group_by(
            Activity.category
        ).all()
    else: # Assuming PostgreSQL
        summary = db.query(
            Activity.category,
            func.sum(Activity.duration).label("total_duration")
        ).filter(
            func.to_char(Activity.timestamp.op('AT TIME ZONE')(CLIENT_TIMEZONE), 'YYYY-MM-DD') == day
        ).group_by(
            Activity.category
        ).all()
        
    return summary

@app.get("/")
def read_root():
    return {"message": "Welcome to the Window Recorder API"}

@app.delete("/clear-data", status_code=204)
def clear_all_data(db: Session = Depends(get_db), authenticated: bool = Depends(get_current_user)):
    """
    [DANGEROUS] This endpoint deletes all records from the activities table.
    It is protected by the API key. Use with extreme caution.
    """
    try:
        num_deleted = db.query(Activity).delete()
        db.commit()
        print(f"Successfully deleted {num_deleted} records.")
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to delete data: {e}")

