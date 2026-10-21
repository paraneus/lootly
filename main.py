from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware #später löschen
from sqlmodel import Field, Session, SQLModel, create_engine, select
from typing import Optional
from datetime import datetime, timedelta
from passlib.context import CryptContext
import uuid
import json

app = FastAPI()

#später löschen
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://lootly.nerdcave.space"],
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "Authorization"]
)

TOKEN_EXPIRE_HOURS = 24 * 90

pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(password: str, hashed: str) -> bool:
    return pwd_context.verify(password, hashed)

def create_token(user_id: int) -> str:
    return str(uuid.uuid4())

security = HTTPBearer()

class UserRegister(SQLModel):
    username: str
    email: str
    password: str

class UserLogin(SQLModel):
    username: str
    password: str

class Item(SQLModel, table=True):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    name: str = Field(min_length=1)
    category: str = ""
    icon: str = ""
    checked: bool = False

class ItemUpdate(SQLModel):
    name: Optional[str] = None
    category: Optional[str] = None
    icon: Optional[str] = None
    checked: Optional[bool] = None

class History(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(unique=True)
    category: str = ""
    count: int = 1

class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(unique=True)
    email: str = Field(unique=True)
    password_hash: str
    is_admin: bool = False

class UserSession(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id")
    token: str = Field(unique=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    expires_at: datetime

class PasswordChange(SQLModel):
    old_password: str
    new_password: str

engine = create_engine("sqlite:////app/data/lootly.db")
SQLModel.metadata.create_all(engine)

connected_clients = []

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials
    with Session(engine) as session:
        user_session = session.exec(
            select(UserSession).where(
                UserSession.token == token,
                UserSession.expires_at > datetime.utcnow()
            )
        ).first()
        if not user_session:
            raise HTTPException(status_code=401, detail="Invalid or expired token")
        user = session.get(User, user_session.user_id)
        return user
    
@app.post("/auth/register")
def register(data: UserRegister, current_user: User = Depends(get_current_user)):
    with Session(engine) as session:
        existing = session.exec(
            select(User).where(User.username == data.username)
        ).first()
        if existing:
            raise HTTPException(status_code=400, detail="Username already taken")
        user = User(
            username=data.username,
            email=data.email,
            password_hash=hash_password(data.password)
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        return {"message": "User created", "user_id": user.id}

@app.post("/auth/login")
def login(data: UserLogin):
    with Session(engine) as session:
        user = session.exec(
            select(User).where(User.username == data.username)
        ).first()
        if not user or not verify_password(data.password, user.password_hash):
            raise HTTPException(status_code=401, detail="Invalid credentials")
        token = create_token(user.id)
        session.add(UserSession(
            user_id=user.id,
            token=token,
            expires_at=datetime.utcnow() + timedelta(hours=TOKEN_EXPIRE_HOURS)
        ))
        session.commit()
        return {"token": token, "username": user.username}
    
@app.post("/auth/change-password")
def change_password(data: PasswordChange, current_user: User = Depends(get_current_user)):
    with Session(engine) as session:
        user = session.get(User, current_user.id)
        if not verify_password(data.old_password, user.password_hash):
            raise HTTPException(status_code=400, detail="Wrong password")
        user.password_hash = hash_password(data.new_password)
        session.add(user)
        session.commit()
        return {"message": "Password changed"}

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    token = await websocket.receive_text()

    with Session(engine) as session:
        user_session = session.exec(
            select(UserSession).where(
                UserSession.token == token,
                UserSession.expires_at > datetime.utcnow()
            )
        ).first()
    if not user_session:
        await websocket.close(code=1008)
        return

    connected_clients.append(websocket)
    try:
        while True:
            await websocket.receive_text()
            with Session(engine) as session:
                items = session.exec(select(Item)).all()
            await websocket.send_text(json.dumps([i.model_dump() for i in items]))
    except WebSocketDisconnect:
        connected_clients.remove(websocket)

async def broadcast(data):
    for client in connected_clients:
        await client.send_text(json.dumps(data))

@app.get("/")
def read_root():
    return {"message": "Lootly läuft!"}

@app.get("/items")
def get_items(current_user: User = Depends(get_current_user)):
    with Session(engine) as session:
        return session.exec(select(Item)).all()
    
@app.get("/history")
def get_history(current_user: User = Depends(get_current_user)):
    with Session(engine) as session:
        return session.exec(select(History)).all()

@app.post("/items")
async def create_item(item: Item, current_user: User = Depends(get_current_user)):
    if not item.name.strip():
        raise HTTPException(status_code=422, detail="Name must not be blank")
    item.id = str(uuid.uuid4())
    item.name = item.name.strip()
    with Session(engine) as session:
        session.add(item)
        session.commit()
        session.refresh(item)
        items = session.exec(select(Item)).all()
        await broadcast([i.model_dump() for i in items])
        return item
    
@app.post("/items/clear-checked")
async def clear_checked(current_user: User = Depends(get_current_user)):
    with Session(engine) as session:
        checked_items = session.exec(
            select(Item).where(Item.checked == True)
        ).all()
        for item in checked_items:
            existing = session.exec(
                select(History).where(History.name.ilike(item.name))
            ).first()
            if existing:
                existing.count += 1
                session.add(existing)
            else:
                session.add(History(name=item.name, category=item.category))
            session.delete(item)
        session.commit()
        items = session.exec(select(Item)).all()
        await broadcast ([i.model_dump() for i in items])
        return {"cleared": len(checked_items)}
        
@app.patch("/items/{item_id}")
async def update_item(item_id: str, updated: ItemUpdate, current_user: User = Depends(get_current_user)):
    with Session(engine) as session:
        item = session.get(Item, item_id)
        if not item:
            return {"error": "Item nicht gefunden"}
        if updated.name is not None:
            item.name = updated.name
        if updated.category is not None:
            item.category = updated.category
        if updated.icon is not None:
            item.icon = updated.icon
        if updated.checked is not None:
            item.checked = updated.checked
        session.add(item)
        session.commit()
        session.refresh(item)
        items = session.exec(select(Item)).all()
        await broadcast([i.model_dump() for i in items])
        return item

@app.delete("/items/{item_id}")
async def delete_item(item_id: str, current_user: User = Depends(get_current_user)):
    with Session(engine) as session:
        item = session.get(Item, item_id)
        if not item:
            return {"error": "Item nicht gefunden"}
        session.delete(item)
        session.commit()
        items = session.exec(select(Item)).all()
        await broadcast([i.model_dump() for i in items])
        return {"deleted": item_id}
    
@app.delete("/history")
async def delete_history(current_user: User = Depends(get_current_user)):
    with Session(engine) as session:
        all_history = session.exec(select(History)).all()
        for h in all_history:
            session.delete(h)
        session.commit()
        return {"deleted": len(all_history)}
    
@app.get("/health")
async def health_check():
    return JSONResponse(content={"status": "healthy"}, status_code=200)