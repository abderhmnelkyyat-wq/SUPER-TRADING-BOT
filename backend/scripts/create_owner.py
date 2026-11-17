from __future__ import annotations
import argparse, getpass
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.db import init_db, SessionLocal
from app.models import User
from app.security import uid, hash_password
from sqlalchemy import select, func

def main():
    parser=argparse.ArgumentParser(description='Create the first SUPER TRADING BOT owner account')
    parser.add_argument('--email', required=True)
    parser.add_argument('--name', default='Application Owner')
    args=parser.parse_args()
    password=getpass.getpass('Strong owner password (12+ characters): ')
    if len(password)<12: raise SystemExit('Password must be at least 12 characters.')
    init_db(); db=SessionLocal()
    try:
        existing=db.scalar(select(User).where(func.lower(User.email)==args.email.lower()))
        if existing: raise SystemExit('An account with this email already exists.')
        owner_count=db.scalar(select(func.count(User.id)).where(User.role=='owner')) or 0
        if owner_count: raise SystemExit('An owner account already exists; multiple owners are disabled.')
        u=User(id=uid(),full_name=args.name,email=args.email.lower(),password_hash=hash_password(password),role='owner',status='active')
        db.add(u); db.commit(); print(f'Owner account created: {u.email}')
    finally: db.close()
if __name__=='__main__': main()
