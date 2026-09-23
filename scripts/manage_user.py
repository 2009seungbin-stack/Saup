"""Local admin utility. Password is read from the terminal, never from shell history."""
import argparse
import getpass
from sqlalchemy import select
from packages.infrastructure.settings import Settings
from packages.infrastructure.db import database
from packages.infrastructure.models import User
from packages.infrastructure.security import hash_password
from packages.application.common import audit, lock_treasury

def main():
    parser=argparse.ArgumentParser();parser.add_argument('username');parser.add_argument('--role',choices=['admin','operator','viewer'],default='viewer')
    args=parser.parse_args();password=getpass.getpass('New user password: ')
    if password!=getpass.getpass('Confirm password: '):raise SystemExit('Passwords differ')
    settings=Settings();_,factory=database(settings.database_url)
    with factory.begin() as s:
        lock_treasury(s)
        if s.scalar(select(User).where(User.username==args.username)):raise SystemExit('User already exists; no overwrite')
        u=User(username=args.username,password_hash=hash_password(password),role=args.role);s.add(u);s.flush()
        audit(s,'ADMIN_USER_CREATED',u.id,actor='local-console',new={'role':args.role})
    print('User created')
if __name__=='__main__':main()
