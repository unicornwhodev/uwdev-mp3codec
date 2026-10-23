# SPDX-License-Identifier: MIT
"""Build local release assets from the checked public repository and artifacts."""
import argparse,hashlib,json,shutil,subprocess,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
VERSION=json.loads((ROOT/'package.json').read_text())['version']

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def integrity():
    files=[ROOT/n for n in ('package.json','README.md','CHANGELOG.md','LICENSE','NOTICE.md')]
    files.append(ROOT/'tools/generate_demo_wav.py')
    for name in ('lib','bin','maven','third-party-notices','docs','qualification','example','demo'):
        files.extend(p for p in (ROOT/name).rglob('*') if p.is_file())
    result={'schema':'uwdev.artifact-integrity.v1','version':VERSION,'algorithm':'SHA-256',
            'files':[{'path':p.relative_to(ROOT).as_posix(),'sha256':sha(p)} for p in sorted(files)]}
    (ROOT/'INTEGRITY.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')

def package():
    output=ROOT/f'build/release-{VERSION}';output.mkdir(parents=True,exist_ok=True)
    core_version='0.2.0'
    version_dir=ROOT/'maven/io/github/unicornwhodev/uwdev-mp3codec'/core_version
    for name in (f'uwdev-mp3codec-{core_version}.aar',f'uwdev-mp3codec-{core_version}-sources.jar'):
        shutil.copyfile(version_dir/name,output/name)
    with zipfile.ZipFile(output/f'uwdev-mp3codec-{VERSION}-maven.zip','w',zipfile.ZIP_DEFLATED) as archive:
        for path in sorted((ROOT/'maven').rglob('*')):
            if path.is_file():archive.write(path,path.relative_to(ROOT/'maven').as_posix())
    subprocess.run(['git','archive','--format=zip','--prefix='+f'uwdev-mp3codec-{VERSION}/',
                    '--output='+str(output/f'uwdev-mp3codec-{VERSION}-sources.zip'),'HEAD'],cwd=ROOT,check=True)
    shutil.copyfile(ROOT/'qualification/summary.json',output/'QUALIFICATION.json')
    files=sorted(p for p in output.iterdir() if p.is_file() and p.name!='SHA256SUMS')
    (output/'SHA256SUMS').write_text(''.join(sha(p)+'  '+p.name+'\n' for p in files),encoding='ascii')
    print(json.dumps({'assets':len(files),'output':str(output)}))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--integrity-only',action='store_true');args=p.parse_args()
    if args.integrity_only:integrity()
    else:package()
