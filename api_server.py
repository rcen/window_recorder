
import os
from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from pydantic import BaseModel
import datetime

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./activity.db")

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class Activity(Base):
    __tablename__ = "activities"
    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)
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

@app.post("/log", response_model=ActivityResponse)
def create_activity(activity: ActivityCreate, db: Session = Depends(get_db)):
    db_activity = Activity(
        timestamp=datetime.datetime.fromtimestamp(activity.timestamp),
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

@app.get("/")
def read_root():
    return {"message": "Welcome to the Window Recorder API"}

