"""Existing auth contract extracted without loosening origin/CSRF or RBAC."""
from datetime import datetime, timedelta, timezone
import hmac
import secrets
from fastapi import APIRouter, Request, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from packages.domain.errors import DomainError
from packages.infrastructure.models import User, AuthSession
from packages.infrastructure.db import aware
from packages.infrastructure.security import digest, verify_password
from packages.application.common import audit

class Login(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=128)


def create_auth_router(settings, factory, limiter):
    router = APIRouter(tags=["auth"])
    def origin(request):
        if request.headers.get('origin') != settings.public_origin: raise DomainError('ORIGIN_REJECTED',403)

    def identity(request:Request):
        token=request.cookies.get('saup_session','')
        if not token: raise DomainError('AUTHENTICATION_REQUIRED',401)
        limiter.hit('session:'+digest(token),180)
        with factory() as s:
            session=s.scalar(select(AuthSession).where(AuthSession.token_hash==digest(token)))
            if session is None or aware(session.expires_at)<=datetime.now(timezone.utc): raise DomainError('SESSION_EXPIRED',401)
            user=s.get(User,session.user_id)
            if not user or not user.active: raise DomainError('USER_DISABLED',403)
            if request.method not in {'GET','HEAD','OPTIONS'}:
                origin(request)
                if not hmac.compare_digest(session.csrf_hash,digest(request.headers.get('x-csrf-token',''))):
                    raise DomainError('CSRF_REJECTED',403)
            return {'id':user.id,'username':user.username,'role':user.role,'session_id':session.id}

    def role(*allowed):
        def guard(user=Depends(identity)):
            if user['role'] not in allowed: raise DomainError('ROLE_FORBIDDEN',403)
            return user
        return guard
    viewer=role('admin','operator','viewer');operator=role('admin','operator');admin=role('admin')
    @router.post('/auth/login')
    def login(data:Login,request:Request):
        origin(request);limiter.hit('login:'+(request.client.host if request.client else 'unknown'),10,60)
        with factory.begin() as s:
            user=s.scalar(select(User).where(User.username==data.username))
            valid=verify_password(data.password,user.password_hash if user else 'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA')
            if not user or not user.active or not valid: raise DomainError('INVALID_CREDENTIALS',401)
            token,csrf=secrets.token_urlsafe(32),secrets.token_urlsafe(32)
            s.add(AuthSession(user_id=user.id,token_hash=digest(token),csrf_hash=digest(csrf),
                expires_at=datetime.now(timezone.utc)+timedelta(seconds=settings.session_ttl_seconds)))
            audit(s,'ADMIN_LOGIN',user.id,actor=user.username)
            response=JSONResponse({'user':user.username,'role':user.role,'csrf_token':csrf,'mode':settings.app_mode})
            response.set_cookie('saup_session',token,max_age=settings.session_ttl_seconds,httponly=True,
                secure=settings.app_mode=='production',samesite='strict',path='/')
            response.set_cookie('saup_csrf',csrf,max_age=settings.session_ttl_seconds,httponly=False,
                secure=settings.app_mode=='production',samesite='strict',path='/')
            return response

    @router.post('/auth/logout')
    def logout(user=Depends(viewer)):
        with factory.begin() as s:
            row=s.get(AuthSession,user['session_id'])
            if row:s.delete(row)
        response=JSONResponse({'status':'signed_out'});response.delete_cookie('saup_session');response.delete_cookie('saup_csrf')
        return response

    @router.get('/auth/me')
    def me(user=Depends(viewer)): return {'username':user['username'],'role':user['role'],'mode':settings.app_mode}

    return router, identity, viewer, operator, admin
