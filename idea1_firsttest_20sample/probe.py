"""Linux-only smoke test. Produces evidence outside Git, not dataset samples."""
from __future__ import annotations
import argparse
import json
import sys
import traceback
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-root', type=Path, required=True)
    parser.add_argument('--platform', choices=('Linux64','CloudRendering'), default='CloudRendering')
    parser.add_argument('--scene', default='FloorPlan1')
    parser.add_argument('--inventory', action='store_true')
    args = parser.parse_args()
    if sys.platform != 'linux':
        parser.error('Run on the Linux server only.')
    from runtime import ControllerSession, StepResult
    from generator import write_json
    output = args.output_root.expanduser().resolve() / 'smoke'
    if Path(__file__).resolve().parent.parent in output.parents:
        parser.error('Output must be outside the source checkout.')
    output.mkdir(parents=True,exist_ok=True)
    try:
        with ControllerSession(scene=args.scene,platform=args.platform,
                               build_cache_dir=args.output_root.expanduser().resolve()/'unity_cache',
                               render_depth=False,render_instance_segmentation=True,
                               controller_kwargs={'visibilityDistance':2.5,'server_timeout':180}) as rig:
            result=rig.step('Pass',raise_on_failure=True)
            rig.save_pngs(result,output,stem='scene',include_instance=True)
            write_json(output/'scene_metadata.json',rig.snapshot())
            report={'status':'simulator_started','scene':args.scene,'platform':args.platform,
                    'rgb_shape':list(result.event.frame.shape),'object_count':len(result.metadata.get('objects',[])),
                    'controller_version':rig.installed_version,
                    'execution_platform':sys.platform}
            if args.inventory:
                scenes=[f'FloorPlan{i}' for i in range(1,31)]+[f'FloorPlan{i}' for i in range(201,205)]+[f'FloorPlan{i}' for i in range(401,411)]
                inventory={}
                for scene in scenes:
                    rig.reset(scene)
                    inventory[scene]=rig.snapshot()['objects']
                    write_json(output/'inventory.json',inventory)
                    types=sorted({o['objectType'] for o in inventory[scene]})
                    print(f'{scene}: {", ".join(types)}',flush=True)
            rig.export_action_log(output/'actions.json')
            write_json(output/'report.json',report)
            print(json.dumps(report),flush=True)
        return 0
    except Exception as exc:
        write_json(output/'failure.json',{'error':str(exc),'traceback':traceback.format_exc(),
                                         'platform':args.platform,'scene':args.scene})
        raise


if __name__=='__main__':
    raise SystemExit(main())
