from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Depends
from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload
from db import engine, SessionLocal
from models import Base, RFP, User
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
import shutil
from pathlib import Path
import pdfplumber
import os
from openai import OpenAI
from datetime import date, datetime, timedelta
from passlib.context import CryptContext
from jose import JWTError, jwt
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm

app = FastAPI(root_path="/api")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://govcon.taptasky.com"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# OpenAI
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Folder for uploads
UPLOAD_DIR = Path(__file__).resolve().parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(password: str):
    return pwd_context.hash(password)

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

# JWT config
SECRET_KEY = os.getenv("SECRET_KEY", "secret")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_SECONDS = 60 * 60 * 24  # 24 hours

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(seconds=ACCESS_TOKEN_EXPIRE_SECONDS)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/login")

async def get_current_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(status_code=401, detail="Could not validate credentials")
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email = payload.get("sub")
        if email is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    async with SessionLocal() as session:
        result = await session.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        if user is None:
            raise credentials_exception
        return user

@app.on_event("startup")
async def startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

# Models
class UserCreate(BaseModel):
    email: EmailStr
    password: str

@app.post("/register")
async def register(user: UserCreate):
    async with SessionLocal() as session:
        result = await session.execute(select(User).where(User.email == user.email))
        if result.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Email already registered")

        user_obj = User(email=user.email, hashed_password=hash_password(user.password))
        session.add(user_obj)
        await session.commit()
        return {"message": "User registered successfully"}

@app.post("/login")
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    async with SessionLocal() as session:
        result = await session.execute(select(User).where(User.email == form_data.username))
        user = result.scalar_one_or_none()
        if user is None or not verify_password(form_data.password, user.hashed_password):
            raise HTTPException(status_code=401, detail="Invalid credentials")

        access_token = create_access_token(data={"sub": user.email})
        return {"access_token": access_token, "token_type": "bearer"}

# Upload an RFP
@app.post("/upload-rfp")
async def upload_rfp(title: str = Form(...), file: UploadFile = File(...), current_user: User = Depends(get_current_user)):
    file_location = UPLOAD_DIR / file.filename
    with open(file_location, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    async with SessionLocal() as session:
        rfp = RFP(title=title, filename=file.filename, user_id=current_user.id, submission_date=date.today())
        session.add(rfp)
        await session.commit()

    return {"message": f"RFP '{title}' uploaded successfully."}

# List all RFPs for the current user
@app.get("/rfps")
async def get_rfps(current_user: User = Depends(get_current_user)):
    async with SessionLocal() as session:
        result = await session.execute(
            select(RFP).where(RFP.user_id == current_user.id).options(joinedload(RFP.owner))
        )
        return result.scalars().all()

# Get one RFP
@app.get("/rfp/{rfp_id}")
async def get_rfp(rfp_id: int, current_user: User = Depends(get_current_user)):
    async with SessionLocal() as session:
        rfp = await session.get(RFP, rfp_id)
        if not rfp or rfp.user_id != current_user.id:
            raise HTTPException(status_code=404, detail="RFP not found")
        return {
            "id": rfp.id,
            "title": rfp.title,
            "filename": rfp.filename,
            "draft_text": rfp.draft_text,
            "company_name": rfp.company_name,
            "document_type": rfp.document_type,
            "submission_date": rfp.submission_date.isoformat() if rfp.submission_date else None,
        }

# Generate draft using OpenAI
@app.post("/generate-draft/{rfp_id}")
async def generate_draft(rfp_id: int, current_user: User = Depends(get_current_user)):
    async with SessionLocal() as session:
        rfp = await session.get(RFP, rfp_id)
        if not rfp or rfp.user_id != current_user.id:
            raise HTTPException(status_code=404, detail="RFP not found")

    pdf_path = UPLOAD_DIR / rfp.filename
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="RFP file not found")

    with pdfplumber.open(pdf_path) as pdf:
        full_text = "\n".join(page.extract_text() or "" for page in pdf.pages)

    prompt = f"""You are a government proposal writer. Based on the RFP text below, generate a high-level executive summary or introduction for a proposal.

RFP TEXT:
{full_text[:4000]}"""

    try:
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You are a proposal writer."},
                {"role": "user", "content": prompt}
            ]
        )
        draft_text = response.choices[0].message.content
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    async with SessionLocal() as session:
        rfp = await session.get(RFP, rfp_id)
        rfp.draft_text = draft_text
        await session.commit()

    return {
        "rfp_id": rfp_id,
        "title": rfp.title,
        "draft": draft_text
    }

# Update draft and cover page
class RFPUpdate(BaseModel):
    draft_text: str
    company_name: str
    document_type: str
    submission_date: str  # ISO format

@app.put("/rfp/{rfp_id}")
async def update_rfp(rfp_id: int, update: RFPUpdate, current_user: User = Depends(get_current_user)):
    async with SessionLocal() as session:
        rfp = await session.get(RFP, rfp_id)
        if not rfp or rfp.user_id != current_user.id:
            raise HTTPException(status_code=404, detail="RFP not found")

        rfp.draft_text = update.draft_text
        rfp.company_name = update.company_name
        rfp.document_type = update.document_type
        rfp.submission_date = datetime.fromisoformat(update.submission_date).date()

        await session.commit()

    return {"message": "Draft updated successfully", "rfp_id": rfp_id}

