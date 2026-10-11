"""Idempotent, validated source patch for the current Phase-4/Night-Pack project.

Never replaces .env or clears tables. Makes timestamped backups before changing files.
Will abort without changes if a required code anchor cannot be found.
"""
from __future__ import annotations
from datetime import datetime
from pathlib import Path
import ast
import shutil

ROOT = Path(__file__).resolve().parent
APP = ROOT/'app'
# Refuse divergent migration chains rather than creating multiple competing heads.
foreign_0009 = [p for p in (ROOT/'migrations/versions').glob('0009_*.py')
                if p.name != '0009_auth_conflicts_delivery.py']
if foreign_0009:
    raise SystemExit('A different 0009 migration already exists. Stop and merge the migration branches: ' + ', '.join(x.name for x in foreign_0009))
payload = ROOT/'hardening_payload/auth_secure.py'
if not payload.is_file():
    raise SystemExit('Missing hardening_payload/auth_secure.py; re-extract whole ZIP')

entries={}

def replacement(old, needle, new, filename):
    if needle not in old:
        raise RuntimeError(f'{filename}: missing required integration marker; no files changed')
    return old.replace(needle,new,1)

config = APP/'config.py'; raw=config.read_text(encoding='utf-8')
if 'allow_insecure_demo_login:' not in raw:
    new=replacement(raw,'    auto_allocator_enabled: bool = True',
        '    allow_insecure_demo_login: bool = False\n'
        '    allow_insecure_demo_admin: bool = False\n'
        '    notification_webhook_url: str = ""\n'
        '    notification_webhook_secret: str = ""\n'
        '    auto_allocator_enabled: bool = True',str(config))
    entries[config]=new

models=APP/'models.py'; raw=models.read_text(encoding='utf-8')
if 'class UserAccount(Base)' not in raw:
    blocks=(ROOT/'hardening_payload/new_models.txt').read_text(encoding='utf-8')
    if 'class Appointment(Base)' not in raw or 'class Notification(Base)' not in raw:
        raise RuntimeError('models.py layout unexpected. No files changed')
    entries[models]=raw.rstrip()+'\n'+blocks

auth=APP/'auth.py'; raw=auth.read_text(encoding='utf-8')
if 'def _decode(credentials:' not in raw:
    if 'def issue_token(' not in raw or 'def current_user(' not in raw or 'def admin_user(' not in raw:
        raise RuntimeError('auth.py unknown version. No files changed')
    entries[auth]=payload.read_text(encoding='utf-8')

main=APP/'main.py'; raw=main.read_text(encoding='utf-8'); new=raw
if 'from .accounts_api import router as accounts_router' not in new:
    new=replacement(new, 'from .recovery_api import router as recovery_router',
          'from .recovery_api import router as recovery_router\nfrom .accounts_api import router as accounts_router',str(main))
if 'app.include_router(accounts_router)' not in new:
    new=replacement(new, 'app.include_router(recovery_router)',
          'app.include_router(recovery_router)\napp.include_router(accounts_router)',str(main))
if 'from fastapi.responses import JSONResponse' not in new:
    new=replacement(new, 'from fastapi.middleware.cors import CORSMiddleware',
          'from fastapi.middleware.cors import CORSMiddleware\nfrom fastapi.responses import JSONResponse\nfrom sqlalchemy.exc import IntegrityError',str(main))
if '@app.exception_handler(IntegrityError)' not in new:
    anchor='app.add_middleware(CORSMiddleware, allow_origins=settings.allowed_origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])'
    addition='''

@app.exception_handler(IntegrityError)
async def booking_conflict_handler(request, exc):
    if getattr(exc.orig, 'sqlstate', None) == '23P01':
        return JSONResponse(status_code=409, content={'detail': 'Slot was just taken. Refresh availability and retry.'})
    return JSONResponse(status_code=500, content={'detail': 'Database write failed; contact reception.'})
'''
    new=replacement(new,anchor,anchor+addition,str(main))
if 'Demo login disabled. Use /api/auth/login' not in new:
    anchor='def demo_login(body: DemoLogin, db: Session = Depends(get_db)):\n'
    addition="    if not settings.allow_insecure_demo_login:\n        raise HTTPException(403, 'Demo login disabled. Use /api/auth/login with an account.')\n    if body.role == 'admin' and not settings.allow_insecure_demo_admin:\n        raise HTTPException(403, 'Demo admin disabled. Use password-based admin login.')\n"
    new=replacement(new,anchor,anchor+addition,str(main))
if new != raw: entries[main]=new

# Validate every updated module compiles BEFORE touching any original file.
for file,contents in entries.items():
    ast.parse(contents,filename=str(file))
if not entries:
    print('Hardening already installed. No source files changed.')
else:
    stamp=datetime.now().strftime('%Y%m%d-%H%M%S')
    backup=ROOT/f'backup-before-hardening-{stamp}'
    backup.mkdir(exist_ok=False)
    for file in entries:
        shutil.copy2(file,backup/file.name)
    for file,new in entries.items():
        temp=file.with_suffix(file.suffix+'.hardening-tmp')
        temp.write_text(new,encoding='utf-8')
        temp.replace(file)
    print('Source hardening applied. Backup:',backup)
    print('Changed:', ', '.join(x.name for x in entries))
print('Next: run preflight_conflicts.py, then Alembic upgrade after a DB backup.')
