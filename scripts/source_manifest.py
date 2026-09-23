"""Hash source/config/tests without secrets or generated outputs."""
import argparse
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
EXCLUDED={'reports','node_modules','.next','.git','__pycache__','.pytest_cache','.venv','artifacts','uploads'}
EXTENSIONS={'.py','.ts','.tsx','.mjs','.json','.toml','.ini','.yml','.yaml','.css','.Dockerfile'}

def snapshot():
    result={}
    for path in sorted(ROOT.rglob('*')):
        rel=path.relative_to(ROOT)
        if not path.is_file() or any(part in EXCLUDED for part in rel.parts):continue
        if path.name.startswith('.env') and path.name!='.env.example':continue
        if path.suffix in EXTENSIONS or path.name in {'Makefile','.env.example','.gitignore','.dockerignore'}:
            result[rel.as_posix()]=hashlib.sha256(path.read_bytes()).hexdigest()
    return result

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--write',action='store_true');args=parser.parse_args()
    target=ROOT/'reports'/'source-manifest.json';current=snapshot()
    if args.write:
        target.parent.mkdir(exist_ok=True);target.write_text(json.dumps(current,indent=2)+'\n');print(f'Wrote {len(current)} source/config hashes')
    else:
        previous=json.loads(target.read_text())
        changed=sorted(k for k in set(previous)|set(current) if previous.get(k)!=current.get(k))
        if changed:raise SystemExit('STALE_SOURCE: '+', '.join(changed))
        print(f'FRESH_SOURCE: {len(current)} source/config files match')
if __name__=='__main__':main()
