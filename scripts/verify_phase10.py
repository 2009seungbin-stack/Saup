"""Reproducible checks with per-command exit codes, logs and source identity.

--require-services makes missing/skipped PostgreSQL or Redis gates fail the run.
This runner records executed failures honestly and never substitutes SQLite for PG.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
from time import monotonic
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]


def capture(command):
    # Explicit UTF-8: Korean docs in git diff are undecodable with a Windows ANSI codepage.
    result=subprocess.run(command,cwd=ROOT,text=True,encoding='utf-8',errors='replace',capture_output=True,check=False)
    return result.stdout.strip() if result.returncode==0 else None


def counts(path):
    if not path.exists():return None
    root=ET.parse(path).getroot()
    tests=root.findall('testsuite') if root.tag=='testsuites' else [root]
    return {key:sum(int(s.get(key,'0')) for s in tests) for key in ('tests','failures','errors','skipped')}


def verify(mode,out,require_services):
    out.mkdir(parents=True,exist_ok=True)
    entries=[]
    sha=capture(['git','rev-parse','HEAD'])
    status_before=capture(['git','status','--porcelain','--untracked-files=no'])
    (out/'source-status-before.txt').write_text((status_before or '')+'\n')
    (out/'source-sha.txt').write_text((sha or 'UNAVAILABLE')+'\n')
    source={}
    for path in sorted(ROOT.rglob('*')):
        rel=path.relative_to(ROOT)
        if any(part.startswith('.') or part in {'node_modules','__pycache__','reports'} for part in rel.parts):continue
        if path.is_file() and path.suffix in {'.py','.ts','.tsx','.json','.md','.yml','.yaml','.mjs'}:
            source[str(rel)]=hashlib.sha256(path.read_bytes()).hexdigest()
    (out/'source-manifest.json').write_text(json.dumps(source,sort_keys=True,indent=2)+'\n')
    def step(name,command,cwd=ROOT,junit=None):
        start=monotonic();log=out/f'{name}.txt'
        try:
            with log.open('w',encoding='utf-8') as stream:
                stream.write('$ '+' '.join(command)+'\n');stream.flush()
                result=subprocess.run(command,cwd=cwd,stdout=stream,stderr=subprocess.STDOUT,timeout=900,check=False)
            code=result.returncode;status='PASS' if code==0 else 'FAIL'
        except (OSError,subprocess.TimeoutExpired) as exc:
            with log.open('a',encoding='utf-8') as stream:stream.write(f'\n{type(exc).__name__}: {exc}\n')
            code=None;status='FAIL'
        measured=counts(junit) if junit else None
        if junit and (not measured or measured['tests']==0 or measured['skipped'] or measured['failures'] or measured['errors']):
            status='FAIL'  # Zero or skipped selected checks cannot satisfy a production gate.
        entries.append({'name':name,'status':status,'command':command,'returncode':code,
            'duration_seconds':round(monotonic()-start,3),'test_results':measured,'log':log.name})
        print(f'{name}: {status}',flush=True)
    if mode in {'backend','all'}:
        step('compile',[sys.executable,'-m','compileall','-q','packages','apps/api','apps/worker','scripts','tests','migrations'])
        unit=out/'unit.xml'
        step('unit',[sys.executable,'-m','pytest','-q','-m','not postgres and not redis',f'--junitxml={unit}',
            '--cov=packages','--cov=apps/api','--cov=apps/worker',f'--cov-report=json:{out / "coverage.json"}',
            f'--cov-report=xml:{out / "coverage.xml"}','--cov-report=term-missing'],junit=unit)
        step('synthetic',[sys.executable,'-m','scripts.demo_supplier_operations','--output',str(out/'synthetic.json')])
        for marker,variable in (('postgres','TEST_POSTGRES_URL'),('redis','TEST_REDIS_URL')):
            if os.environ.get(variable):
                xml=out/f'{marker}.xml'
                step(marker,[sys.executable,'-m','pytest','-q','-m',marker,f'--junitxml={xml}'],junit=xml)
            else:
                entries.append({'name':marker,'status':'BLOCKED','executed':False,'reason':f'{variable} not configured'})
    if mode in {'frontend','all'}:
        web=ROOT/'apps/web'
        step('frontend-install',['npm','ci','--no-fund'],cwd=web)
        if entries[-1]['status']=='PASS':
            step('frontend-typecheck',['npm','run','typecheck'],cwd=web)
            step('frontend-build',['npm','run','build'],cwd=web)
        else:
            for name in ('frontend-typecheck','frontend-build'):
                entries.append({'name':name,'status':'BLOCKED','executed':False,'reason':'npm ci failed'})
    coverage_file=out/'coverage.json'
    coverage=json.loads(coverage_file.read_text())['totals'] if coverage_file.exists() else None
    status_after=capture(['git','status','--porcelain','--untracked-files=no'])
    (out/'source-status-after.txt').write_text((status_after or '')+'\n')
    diff=capture(['git','diff','--no-ext-diff','--no-color','HEAD','--'])
    (out/'tracked-source-changes.patch').write_text((diff or '')+'\n')
    result={'source_commit_sha':sha,'source_dirty_before':bool(status_before),
        'source_dirty':bool(status_after),'tracked_source_diff':'tracked-source-changes.patch',
        'source_head_sha':os.environ.get('SOURCE_HEAD_SHA'), 'source_base_sha':os.environ.get('SOURCE_BASE_SHA'),
        'python':platform.python_version(),'recorded_at_utc':datetime.now(timezone.utc).isoformat(),
        'github_run_id':os.environ.get('GITHUB_RUN_ID'),'mode':mode,'checks':entries,'statement_coverage':coverage,
        'docker':'NOT_TESTED','browser_e2e':'NOT_TESTED','live_providers':'BLOCKED','production_ready':False}
    (out/'verification.json').write_text(json.dumps(result,indent=2)+'\n')
    failed=any(row['status']=='FAIL' or require_services and row['status']=='BLOCKED' for row in entries)
    return 1 if failed else 0


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--mode',choices=['backend','frontend','all'],default='all')
    parser.add_argument('--output',type=Path,default=ROOT/'reports'/'phase10')
    parser.add_argument('--require-services',action='store_true')
    args=parser.parse_args();return verify(args.mode,args.output.resolve(),args.require_services)

if __name__=='__main__':raise SystemExit(main())
