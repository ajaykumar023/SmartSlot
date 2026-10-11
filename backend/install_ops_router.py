"""One-time, reversible registration of the optional demo operations router.

Creates backend/app/main.py.bak-before-demo-ops before modifying main.py.
Never changes models, database URL, Alembic migrations, or .env.
"""
from pathlib import Path

main = Path(__file__).parent / 'app' / 'main.py'
content = main.read_text(encoding='utf-8')
import_line = 'from .demo_ops_api import router as demo_ops_router'
include_line = 'app.include_router(demo_ops_router)'
if import_line in content and include_line in content:
    print('Operations API is already registered. No changes.')
else:
    if import_line in content or include_line in content:
        raise SystemExit('Found a partially edited main.py. Please review manually; no changes made.')
    anchor_import = 'from .service_intake_api import router as service_intake_router, save_intake, validate_intake'
    anchor_include = 'app.include_router(service_intake_router)'
    if content.count(anchor_import) != 1 or content.count(anchor_include) != 1:
        raise SystemExit('Your main.py differs from the supported Phase 4 layout. No changes made.')
    updated = content.replace(anchor_import, anchor_import + '\n' + import_line)
    updated = updated.replace(anchor_include, anchor_include + '\n' + include_line)
    backup = main.with_name('main.py.bak-before-demo-ops')
    if backup.exists():
        raise SystemExit(f'Existing backup: {backup}. Review it before rerunning; no changes made.')
    backup.write_text(content, encoding='utf-8')
    main.write_text(updated, encoding='utf-8')
    print('Registered /api/admin/ops/summary and /api/admin/ops/team')
    print('Backup saved:', backup)
