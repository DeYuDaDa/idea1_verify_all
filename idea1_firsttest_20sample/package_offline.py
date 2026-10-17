"""Package only public inputs and their referenced RGB files for offline VLMs.

The private mapping stays next to hidden gold, never in the ZIP. Pair/variant
IDs and question fact IDs are replaced in the public package to avoid A/B naming
shortcuts. This creates no simulator data and evaluates no model.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
import secrets
import zipfile
from pathlib import Path


def package(root: Path, output: Path, *, allow_unreviewed: bool = False,
            pair_ids: list[str] | None = None) -> dict:
    from exporter import _scan_for_public_leaks
    from validate import validate
    root=root.resolve()
    report=validate(root,pair_ids)
    if not allow_unreviewed and report.get('status')!='pass':
        raise ValueError('Dataset is not fully validated/reviewed. Review the report first; --allow-unreviewed is only for pipeline debugging.')
    sources=sorted((root/'data'/'input').glob('*.json'))
    if pair_ids:
        wanted=set(pair_ids)
        sources=[path for path in sources if path.stem.rsplit('_',1)[0] in wanted]
    if not sources:
        raise ValueError('No actual exported samples found; design specs cannot be packaged as data.')
    if output.exists():
        raise FileExistsError(f'Refusing to overwrite package: {output}')
    output.parent.mkdir(parents=True,exist_ok=True)
    salt=secrets.token_hex(16)
    mapping={}
    staged=[]
    for source in sources:
        record=json.loads(source.read_text(encoding='utf-8'))
        model_input=copy.deepcopy(record['model_input'])
        if _scan_for_public_leaks(model_input):
            raise ValueError(f'Public/hidden key leak in {source.name}')
        sid='sample_'+hashlib.sha256((salt+record['sample_id']).encode()).hexdigest()[:16]
        per_sample={'original_sample_id':record['sample_id'],'questions':{},'media':{}}
        media=[]
        for index, frame in enumerate(model_input.get('frames', [])):
            relative=frame['path']
            path=(root/relative).resolve()
            allowed=(root/'data'/'media').resolve()
            if allowed not in path.parents or path.suffix.lower()!='.png' or not path.is_file():
                raise ValueError(f'Invalid or non-public RGB reference: {relative}')
            name=f'media/{sid}_{index:02d}.png'
            frame['path']=name
            per_sample['media'][name]=relative
            media.append((path,name))
        if not media:
            raise ValueError(f'{source.name} has no event/history images')
        for index, question in enumerate(model_input.get('questions', [])):
            qid=f'q{index+1:03d}'
            per_sample['questions'][qid]=question.pop('fact_id',None)
            question['question_id']=qid
        mapping[sid]=per_sample
        staged.append((sid,model_input,media))
    private_map=root/'packaging_maps'/f'{output.stem}_{salt[:8]}.json'
    private_map.parent.mkdir(parents=True,exist_ok=True)
    private_map.write_text(json.dumps(mapping,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    try:
        with zipfile.ZipFile(output,'x',compression=zipfile.ZIP_DEFLATED) as archive:
            for sid,model_input,media in sorted(staged,key=lambda row:row[0]):
                archive.writestr(f'inputs/{sid}.json',json.dumps({'sample_id':sid,'model_input':model_input},ensure_ascii=False,indent=2))
                for path,name in media:
                    archive.write(path,name)
            archive.writestr('README.txt',
                'Offline model inputs only. No AI2-THOR process is required.\n'
                'Pass model_input history/rules/event/questions and image bytes to the VLM.\n'
                'Do not pass filenames as textual clues. Pair IDs, hidden metadata and answers are omitted.\n'
                'Return sample_id and question_id with predictions. Score using the separate private mapping.\n'
                f'Construction review bypass used: {allow_unreviewed}\n')
    except Exception:
        # Preserve a failed package for inspection; never delete user data.
        raise
    return {'package':str(output),'samples':len(staged),'private_mapping':str(private_map),
            'review_bypass':allow_unreviewed,'contains_hidden_gold':False}


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--allow-unreviewed',action='store_true',help='Debug only; package remains explicitly unreviewed.')
    parser.add_argument('--pairs',help='Optional comma-separated subset, e.g. C13,T16,M01,S05,B19,P20.')
    args=parser.parse_args()
    pairs=[p.strip() for p in args.pairs.split(',') if p.strip()] if args.pairs else None
    print(json.dumps(package(args.root,args.output,allow_unreviewed=args.allow_unreviewed,pair_ids=pairs),ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
