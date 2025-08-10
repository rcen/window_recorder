
import os
from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, func, cast, Date
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from pydantic import BaseModel
import datetime
import pytz

# This should match the client's timezone.
# In a real-world scenario, this might be configurable per-user.
CLIENT_TIMEZONE = os.environ.get("TZ", "America/New_York")

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./activity.db")

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class Activity(Base):
    __tablename__ = "activities"
    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow) # Timestamps are stored in UTC
    category = Column(String)
    duration = Column(Integer)
    window_title = Column(String)

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

class ActivityResponse(BaseModel):
    id: int
    timestamp: datetime.datetime
    category: str
    duration: int
    window_title: str

    class Config:
        orm_mode = True

class DailySummary(BaseModel):
    category: str
    total_duration: int

@app.post("/log", response_model=ActivityResponse)
def create_activity(activity: ActivityCreate, db: Session = Depends(get_db)):
    # The incoming timestamp is from the client's local time, convert to UTC for storage
    local_dt = datetime.datetime.fromtimestamp(activity.timestamp)
    db_activity = Activity(
        timestamp=local_dt, # Storing as naive datetime, but it represents UTC
        category=activity.category,
        duration=activity.duration,
        window_title=activity.window_title
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
    days = db.query(
        func.strftime('%Y-%m-%d', func.datetime(Activity.timestamp, 'localtime'))
    ).distinct().order_by(func.strftime('%Y-%m-%d', func.datetime(Activity.timestamp, 'localtime')).desc()).all()
    return [day[0] for day in days]


@app.get("/summary/{day}", response_model=list[DailySummary])
def get_daily_summary(day: str, db: Session = Depends(get_db)):
    """
    Returns the total duration for each category for a specific day,
    adjusted for the client's timezone.
    """
    try:
        # Validate date format
        datetime.datetime.strptime(day, '%Y-%m-%d')
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")

    summary = db.query(
        Activity.category,
        func.sum(Activity.duration).label("total_duration")
    ).filter(
        func.strftime('%Y-%m-%d', func.datetime(Activity.timestamp, 'localtime')) == day
    ).group_by(
        Activity.category
    ).all()
    return summary

@app.get("/")
def read_root():
    return {"message": "Welcome to the Window Recorder API"}

