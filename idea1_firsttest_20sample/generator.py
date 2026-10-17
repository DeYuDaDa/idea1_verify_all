"""Construct the 20 paired designs in a real Linux AI2-THOR process.

No simulator imports or execution at import time. Never replaces observations
with expected outcomes. A construction failure remains a failed private attempt.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import shutil
import sys
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
DEFAULT_OUTPUT = Path('/root/will_not_be_push_to_git/idea1_firsttest_20sample/exports')
ALL_PAIRS = ('M01','M02','M03','M04','S05','S06','S07','W08','W09','W10',
             'W11','W12','C13','C14','C15','T16','T17','T18','B19','P20')
CAPABILITY = {'isCooked':'cookable', 'isDirty':'dirtyable',
              'isFilledWithLiquid':'canFillWithLiquid', 'fillLiquid':'canFillWithLiquid',
              'isToggled':'toggleable', 'isBroken':'breakable', 'isOpen':'openable'}


class ConstructionError(RuntimeError):
    pass


def write_json(path: Path, data: Any) -> None:
    from exporter import _jsonable
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(_jsonable(data), ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    temporary.replace(path)


def fingerprint(config_path: Path | None = None, platform: str | None = None) -> str:
    digest = hashlib.sha256()
    for name in ('generator.py','interactions.py','runtime.py','exporter.py','validate.py','specs.json','config.json'):
        path = HERE / name
        digest.update(name.encode())
        digest.update(path.read_bytes())
    if config_path is not None:
        digest.update(config_path.read_bytes())
    digest.update(str(platform).encode())
    return digest.hexdigest()


def get_object(metadata: dict, object_id: str) -> dict:
    for obj in metadata.get('objects', []):
        if obj.get('objectId') == object_id:
            return obj
    raise ConstructionError(f'Object missing from simulator metadata: {object_id}')


def temperature(obj: dict) -> Any:
    return obj.get('temperature', obj.get('ObjectTemperature'))


def normalize_parent(obj: dict) -> list[str]:
    return sorted(obj.get('parentReceptacles') or [])


def distance(a: dict, b: dict) -> float:
    return math.sqrt(sum((float(a[k])-float(b[k]))**2 for k in ('x','y','z')))


def family_for(pair_id: str) -> str:
    if pair_id == 'W12':
        return 'shower'
    return {'M':'microwave','S':'stove','W':'water','C':'coffee',
            'T':'toaster','B':'breakage','P':'carrying'}[pair_id[0]]


class CaseBuilder:
    """One variant. Setup calls are recorded separately from the evaluated event."""
    def __init__(self, session, pair_id: str, variant: str, stage: Path,
                 spec: dict, config: dict, seed: int):
        from interactions import Interactions
        self.session = session
        self.ops = Interactions(session, seed=seed)
        self.pair_id, self.variant, self.stage = pair_id, variant, stage
        self.spec, self.config, self.seed = spec, config, seed
        self.roles: dict[str,str] = {}
        self.frames: list[dict] = []
        self.checks: list[dict] = []
        self.history: list[dict] = []
        self.direct: dict[str,list[str]] = {}
        self.indirect: dict[str,list[str]] = {}
        self.questions: list[dict] = []
        self.selected: list[str] = []
        self.contrast: list[dict] = []
        self.before: dict | None = None
        self.after: dict | None = None
        self.event_result = None
        self.event_index = None
        self.rules: list[str] = []

    @property
    def a(self) -> bool:
        return self.variant == 'A'

    def obj(self, role: str) -> dict:
        return get_object(self.session.snapshot(), self.roles[role])

    def select(self, role: str, kind: str, *, origin: dict | None = None) -> str:
        obj = self.session.find_object(kind, origin=origin)
        if obj is None:
            raise ConstructionError(f'{self.pair_id}: scene {self.session.scene} has no {kind}; no silent type substitution')
        self.roles[role] = obj['objectId']
        return obj['objectId']

    def bind(self, role: str, object_id: str) -> None:
        get_object(self.session.snapshot(), object_id)
        self.roles[role] = object_id

    def require(self, name: str, passed: bool, detail: Any = None) -> None:
        self.checks.append({'name':name, 'passed':bool(passed), 'detail':detail})
        if not passed:
            raise ConstructionError(f'{self.pair_id}_{self.variant}: {name}: {detail}')

    def counter(self, near: str | None = None) -> str:
        origin = self.obj(near)['position'] if near else None
        return self.select('CounterTop_1', 'CounterTop', origin=origin)

    def check_parent(self, child: str, parent: str, expected: bool = True) -> None:
        actual = self.roles[parent] in normalize_parent(self.obj(child))
        self.require(f'{child}_parent_{parent}', actual == expected,
                     {'expected':expected,'actual_parents':normalize_parent(self.obj(child))})

    def place(self, child: str, parent: str) -> None:
        self.ops.place_initial(self.roles[child], self.roles[parent])
        self.check_parent(child, parent)

    def toggle(self, role: str, value: bool) -> None:
        self.ops.set_toggle(self.roles[role], value)
        self.require(f'{role}_toggle_setup', self.obj(role).get('isToggled') is value)

    def dirty(self, role: str, value: bool) -> None:
        self.ops.set_dirty(self.roles[role], value)
        self.require(f'{role}_dirty_setup', self.obj(role).get('isDirty') is value)

    def liquid(self, role: str, value: str | None) -> None:
        self.ops.set_liquid(self.roles[role], value)
        obj = self.obj(role)
        self.require(f'{role}_fillable', obj.get('canFillWithLiquid') is True)
        self.require(f'{role}_fill_setup', obj.get('isFilledWithLiquid') is bool(value), obj)
        if value:
            self.require(f'{role}_liquid_setup', str(obj.get('fillLiquid','')).lower() == value.lower(), obj.get('fillLiquid'))

    def cooked(self, role: str, value: bool) -> None:
        if value:
            self.ops.set_cooked(self.roles[role], True)
        self.require(f'{role}_cooked_setup', self.obj(role).get('isCooked') is value)

    def frame(self, stage: str) -> None:
        from runtime import StepResult
        event = self.session.controller.last_event
        result = StepResult(event, self.session.snapshot(), {})
        media = self.stage / 'data' / 'media'
        paths = self.session.save_pngs(result, media,
                    stem=f'{self.pair_id}_{self.variant}_{len(self.frames):02d}_{stage}',
                    include_instance=False)
        self.frames.append({'stage':stage,'path':Path(paths['rgb']).relative_to(self.stage).as_posix()})

    def history_frame(self, stage: str, look_at: str) -> None:
        self.ops.look(self.roles[look_at])
        self.frame(stage)
        self.history.append({'stage':stage, 'facts':self.public_facts(self.session.snapshot())})

    def public_facts(self, metadata: dict) -> list[dict]:
        inverse = {value:key for key,value in self.roles.items()}
        facts = []
        for alias, oid in self.roles.items():
            obj = get_object(metadata, oid)
            for prop in ('isCooked','isDirty','isFilledWithLiquid','fillLiquid','isToggled','isBroken','isOpen','isPickedUp'):
                cap = CAPABILITY.get(prop)
                if cap and obj.get(cap) is False:
                    continue
                if prop in obj:
                    facts.append({'subject':alias,'predicate':prop,'value':obj[prop]})
            temp = temperature(obj)
            if temp is not None:
                facts.append({'subject':alias,'predicate':'temperature','value':temp})
            parents = [inverse[p] for p in normalize_parent(obj) if p in inverse]
            facts.append({'subject':alias,'predicate':'parentReceptacles','value':parents})
            for cap in ('canFillWithLiquid','cookable','dirtyable','breakable','toggleable','receptacle'):
                if cap in obj:
                    facts.append({'subject':alias,'predicate':cap,'value':obj[cap]})
        return facts

    def question(self, role: str, predicates: list[str], *, selected: bool = False) -> None:
        for predicate in predicates:
            qid = f'{self.roles[role]}.{predicate}'
            if any(q['fact_id']==qid for q in self.questions):
                continue
            if predicate == 'position':
                text = f'Has the world position of {role} changed during this event, or stayed the same?'
                mode = 'change_status'
            elif predicate == 'parentReceptacles':
                text = f'What known container/support relations hold for {role} now? Use the provided object aliases.'
                mode = 'current_value'
            else:
                text = f'What is the current {predicate} of {role}? Answer not_applicable when the object has no such capability, or unknown when evidence is insufficient.'
                mode = 'current_value'
            self.questions.append({'fact_id':qid,'subject':role,'predicate':predicate,'question':text,'answer_mode':mode})
            if selected:
                self.selected.append(qid)

    def note_contrast(self, role: str, predicate: str, value: Any = None) -> None:
        obj = self.obj(role)
        if value is None:
            value = obj.get(predicate)
        self.contrast.append({'subject_id':self.roles[role], 'predicate':predicate, 'value':copy.deepcopy(value)})

    def freeze(self, look_at: str) -> None:
        if self.session.inventory():
            # Camera repositioning is setup, before M0 is captured. It is
            # allowed to reposition the carried object, but cannot be silently
            # inserted between the before snapshot and evaluated PutObject.
            held_before={o['objectId'] for o in self.session.inventory()}
            self.session.face_object(self.obj(look_at),min_distance=1.1,max_distance=1.8,
                                     force_teleport=True)
            self.require('camera_setup_preserved_inventory',
                         held_before=={o['objectId'] for o in self.session.inventory()})
        else:
            self.ops.look(self.roles[look_at])
        self.frame('before_event')
        self.before = self.session.snapshot()
        self.history.append({'stage':'immediately_before_event','facts':self.public_facts(self.before)})
        self.event_index = len(self.session.records)

    def execute(self, action: str, role: str, destination: str | None = None) -> None:
        if self.before is None:
            raise ConstructionError('freeze before executing the evaluated action')
        if action == 'PutObject':
            self.event_result = self.ops.put_event(self.roles[role], self.roles[destination])
            self.direct[self.roles[role]] = ['position','parentReceptacles','isPickedUp']
        elif action == 'PickupObject':
            self.event_result = self.ops.pickup_event(self.roles[role], look_first=False)
            self.direct[self.roles[role]] = ['position','parentReceptacles','isPickedUp']
        else:
            self.event_result = self.session.step(action, objectId=self.roles[role], forceAction=True, raise_on_failure=True)
            self.direct[self.roles[role]] = {'ToggleObjectOn':['isToggled'], 'BreakObject':['isBroken']}[action]
        self.require('evaluated_action_success', self.event_result.record.get('lastActionSuccess') is True,
                     self.event_result.record)
        self.frame('event_immediate')
        self.ops.settle(steps=int(self.config['settle_steps']))
        self.frame('event_settled')
        self.after = self.session.snapshot()

    def actual(self, role: str, field: str, when: str = 'after') -> Any:
        obj = get_object(self.before if when == 'before' else self.after, self.roles[role])
        return temperature(obj) if field == 'temperature' else obj.get(field)

    def expect(self, role: str, field: str, value: Any) -> None:
        actual = self.actual(role, field)
        self.require(f'{role}_{field}_native_outcome', actual == value,
                     {'actual':actual,'expected_construction_check':value})

    def preserved(self, role: str, field: str) -> None:
        before, after = self.actual(role, field, 'before'), self.actual(role, field)
        self.require(f'{role}_{field}_preserved', before == after, {'before':before,'after':after})

    def heat(self, role: str, applies: bool, cook: bool = False) -> None:
        self.indirect[self.roles[role]] = ['temperature'] + (['isCooked'] if cook else [])
        self.question(role, ['temperature'] + (['isCooked'] if cook else []), selected=True)
        if applies:
            self.expect(role, 'temperature', 'Hot')
            if cook:
                self.expect(role, 'isCooked', True)
        else:
            self.preserved(role, 'temperature')
            if cook:
                self.preserved(role, 'isCooked')

    def finish(self) -> dict:
        from exporter import export_case
        if self.after is None:
            raise ConstructionError('no evaluated event was executed')
        for role, oid in self.roles.items():
            if role.startswith(('CounterTop','SinkBasin','BathtubBasin')):
                continue
            self.question(role, ['parentReceptacles'])
            if self.obj(role).get('toggleable'):
                self.question(role, ['isToggled'])
        event = self.event_result.record
        input_event = {'action':event['action'], 'subject':next((a for a,o in self.roles.items() if o in self.direct), None),
                       'success':event['lastActionSuccess'], 'settle_steps':self.config['settle_steps']}
        if event['action'] == 'PutObject':
            dest_id = event.get('kwargs',{}).get('objectId')
            input_event['destination'] = next((a for a,o in self.roles.items() if o==dest_id), None)
        model_input = {'protocol':'oracle_history_and_declared_rules_with_observed_event',
                       'protocol_note':'Historical facts and device rules are supplied explicitly; this does not test autonomous discovery of those facts/rules.',
                       'objects':[{ 'alias':alias, 'object_type':get_object(self.before, oid)['objectType']} for alias,oid in self.roles.items()],
                       'history':self.history, 'rules':self.rules, 'event':input_event,
                       'frames':self.frames, 'questions':self.questions}
        # Visibility is only an audit signal. A visible target alone does not
        # prove every relevant precondition or mechanism was visually evidenced.
        target_ids = list(self.direct)
        event_visible = any(get_object(self.after, oid).get('visible', False) for oid in target_ids)
        knowability = {}
        for question in self.questions:
            field, oid = question['predicate'], self.roles[question['subject']]
            # Explicit oracle history + declared, construction-checked rules
            # support these query slots; visual-only validity remains unaudited.
            knowability.setdefault(oid, {})[field] = 'knowable' if field in {'temperature','isCooked','isDirty','isFilledWithLiquid','fillLiquid','isToggled','isBroken','isOpen','isPickedUp','parentReceptacles','position'} else 'not_assessed'
            if self.pair_id=='C14' and not self.a and question['subject']=='Mug_1' and field=='temperature':
                # The declared coffee-filling rule does not determine whether
                # an already water-filled mug is warmed. Metadata alone is not
                # model-visible thermal evidence.
                knowability[oid][field]='unknown'
        extra = {'role_bindings':self.roles, 'evaluated_action':event,
                 'event_action':event['action'], 'direct_fields':self.direct, 'indirect_fields':self.indirect,
                 'selected_pair_fact_keys':self.selected, 'contrast_evidence':self.contrast,
                 'scenario_checks':self.checks, 'initial_control_audited':False,
                 'observation_audit':{'event_target_visible':event_visible, 'required_frames_present':len(self.frames)>=3,
                                      'visual_preconditions_reviewed':False},
                 'knowability':knowability, 'knowability_protocol':'oracle_history_and_declared_rules_only',
                 'visual_only_knowability':'not_assessed', 'seed':self.seed,
                 'position_tolerance_m':self.config['position_tolerance_m'],
                 'construction_status':'simulator_recorded_candidate', 'frame_review_required':True}
        record = export_case(self.stage, self.pair_id, self.variant, model_input,
                             self.before, self.after, target_ids, list(self.roles.values()),
                             self.session.records[self.event_index:], extra)
        write_json(self.stage/'private_logs'/f'{self.pair_id}_{self.variant}_setup.json',
                   {'setup_actions':self.session.records[:self.event_index]})
        return record

    def build(self) -> dict:
        pid = self.pair_id
        if pid.startswith('M'):
            self.microwave()
        elif pid.startswith('S'):
            self.stove()
        elif pid.startswith('W'):
            self.water()
        elif pid.startswith('C'):
            self.coffee()
        elif pid.startswith('T'):
            self.toaster()
        elif pid == 'B19':
            self.breakage()
        elif pid == 'P20':
            self.carrying()
        else:
            raise ConstructionError(f'No scenario builder for {pid}')
        return self.finish()

    def microwave(self) -> None:
        self.select('Microwave_1','Microwave')
        self.select('Potato_1','Potato')
        self.counter('Microwave_1')
        self.toggle('Microwave_1',False)
        self.ops.set_open(self.roles['Microwave_1'],True)
        self.cooked('Potato_1', self.pair_id=='M02' and not self.a)
        self.place('Potato_1','CounterTop_1' if self.pair_id=='M01' and not self.a else 'Microwave_1')
        if self.pair_id in {'M01','M03'}:
            self.select('Bowl_1','Bowl')
            if self.pair_id=='M03':
                self.dirty('Bowl_1',self.a)
            self.place('Bowl_1','Microwave_1')
        if self.pair_id=='M04':
            self.select('Cup_1','Cup')
            self.place('Cup_1','Microwave_1')
            self.history_frame('cup_inside_earlier','Microwave_1')
            if not self.a:
                self.place('Cup_1','CounterTop_1')
                self.history_frame('cup_removed_before_activation','Cup_1')
        self.history_frame('microwave_contents_before_closing','Microwave_1')
        self.ops.set_open(self.roles['Microwave_1'],False)
        contrast_role, contrast_prop = {'M01':('Potato_1','parentReceptacles'), 'M02':('Potato_1','isCooked'),
                                        'M03':('Bowl_1','isDirty'), 'M04':('Cup_1','parentReceptacles')}[self.pair_id]
        self.note_contrast(contrast_role,contrast_prop)
        self.rules = ['An activated closed microwave heats the objects currently inside it.',
                      'An uncooked cookable potato inside the active microwave becomes cooked after the recorded settling interval.',
                      'Microwave heating does not clean a dirty bowl or move objects between containers.',
                      'Objects removed before activation are not heated by their former containment relation.']
        self.freeze('Microwave_1')
        self.execute('ToggleObjectOn','Microwave_1')
        self.expect('Microwave_1','isToggled',True)
        self.heat('Potato_1', not(self.pair_id=='M01' and not self.a), cook=True)
        if 'Bowl_1' in self.roles:
            self.heat('Bowl_1',True)
        if self.pair_id=='M03':
            self.question('Bowl_1',['isDirty'],selected=True)
            self.preserved('Bowl_1','isDirty')
        if self.pair_id=='M04':
            self.heat('Cup_1',self.a)
        self.question('Microwave_1',['isToggled','isOpen'])

    def stove(self) -> None:
        objects = self.session.snapshot()['objects']
        by_id = {o['objectId']:o for o in objects}
        controls = []
        for knob in sorted((o for o in objects if o['objectType']=='StoveKnob'),key=lambda o:o['objectId']):
            for value in knob.get('controlledObjects') or []:
                oid = value.get('objectId') if isinstance(value,dict) else value
                if oid in by_id and by_id[oid]['objectType']=='StoveBurner':
                    controls.append((knob['objectId'],oid))
        controls = list(dict.fromkeys(controls))
        self.require('two_distinct_native_stove_control_mappings',len(controls)>=2,controls)
        first=controls[0]
        second=next((entry for entry in controls if entry[0]!=first[0] and entry[1]!=first[1]),None)
        self.require('two_independent_control_targets',second is not None,controls)
        for alias, oid in zip(('StoveKnob_A','StoveBurner_A','StoveKnob_B','StoveBurner_B'),first+second):
            self.bind(alias,oid)
        self.select('Kettle_1','Kettle')
        self.counter('StoveBurner_A')
        self.toggle('StoveKnob_A',False)
        self.toggle('StoveKnob_B',False)
        dest = 'StoveBurner_A'
        if self.pair_id=='S05' and not self.a:
            dest='StoveBurner_B'
        elif self.pair_id=='S06' and not self.a:
            dest='CounterTop_1'
        self.place('Kettle_1',dest)
        target='StoveKnob_B' if self.pair_id=='S07' and not self.a else 'StoveKnob_A'
        if self.pair_id=='S07':
            self.note_contrast(target,'event_target',self.roles[target])
        else:
            self.note_contrast('Kettle_1','parentReceptacles')
        self.rules = [f'StoveKnob_A controls StoveBurner_A; StoveKnob_B controls StoveBurner_B.',
                      'Only an object on the activated burner is heated by this mechanism; proximity alone is insufficient.']
        self.history_frame('stove_control_and_support','Kettle_1')
        self.freeze(target)
        self.execute('ToggleObjectOn',target)
        self.indirect[self.roles['StoveBurner_A']] = ['isToggled']
        self.indirect[self.roles['StoveBurner_B']] = ['isToggled']
        self.expect('StoveBurner_A','isToggled',target=='StoveKnob_A')
        self.expect('StoveBurner_B','isToggled',target=='StoveKnob_B')
        applies = dest == ('StoveBurner_A' if target=='StoveKnob_A' else 'StoveBurner_B')
        self.heat('Kettle_1',applies)
        self.question('StoveBurner_A',['isToggled'],selected=True)
        self.question('StoveBurner_B',['isToggled'],selected=True)

    def water(self) -> None:
        shower = self.pair_id=='W12'
        controller, destination = ('ShowerHead_1','BathtubBasin_1') if shower else ('Faucet_1','SinkBasin_1')
        self.select(controller,'ShowerHead' if shower else 'Faucet')
        self.select(destination,'BathtubBasin' if shower else 'SinkBasin',origin=self.obj(controller)['position'])
        role, kind = ('Cloth_1','Cloth') if shower else (('Plate_1','Plate') if self.pair_id=='W11' else ('Bowl_1','Bowl'))
        self.select(role,kind)
        self.toggle(controller,False)
        self.dirty(role,self.pair_id!='W09')
        fillable = self.obj(role).get('canFillWithLiquid') is True
        if role=='Bowl_1':
            self.liquid(role,'water' if self.pair_id=='W10' else None)
        else:
            self.require('nonfillable_negative_control',not fillable,kind)
        self.ops.pickup_event(self.roles[role])
        self.toggle(controller,self.a)
        self.note_contrast(controller,'isToggled')
        self.rules = ['Successful placement in the running-water contact region cleans a dirty cleanable object.',
                      'Running water fills an empty fillable container with water; it does not create a fill capability.',
                      'With the water source off, placement alone does not clean or fill the object.',
                      'Already-clean and already-filled facts remain true rather than becoming new Boolean changes.']
        self.freeze(destination)
        self.execute('PutObject',role,destination)
        self.indirect[self.roles[role]] = ['isDirty','isFilledWithLiquid','fillLiquid']
        self.expect(role,'isDirty',False if self.a else self.pair_id!='W09')
        self.question(role,['isDirty','isFilledWithLiquid','fillLiquid'],selected=True)
        if fillable:
            self.expect(role,'isFilledWithLiquid',self.a or self.pair_id=='W10')
            if self.a or self.pair_id=='W10':
                self.expect(role,'fillLiquid','water')
        # Actual cleaning/filling is the positive contact witness. Merely
        # landing in SinkBasin is never sufficient for a positive label.
        self.require('running_water_contact_has_native_effect_or_valid_negative',
                     not self.a or self.actual(role,'isDirty','before')!=self.actual(role,'isDirty')
                     or self.actual(role,'isFilledWithLiquid','before')!=self.actual(role,'isFilledWithLiquid'))
        self.check_parent(role,destination)
        self.preserved(controller,'isToggled')

    def coffee(self) -> None:
        self.select('CoffeeMachine_1','CoffeeMachine')
        self.select('Mug_1','Mug')
        self.counter('CoffeeMachine_1')
        self.toggle('CoffeeMachine_1',False)
        self.place('Mug_1','CounterTop_1')
        self.liquid('Mug_1','water' if self.pair_id=='C14' and not self.a else None)
        self.ops.pickup_event(self.roles['Mug_1'])
        self.toggle('CoffeeMachine_1',self.a if self.pair_id=='C13' else True)
        destination='CounterTop_1' if self.pair_id=='C15' and not self.a else 'CoffeeMachine_1'
        if self.pair_id=='C13':
            self.note_contrast('CoffeeMachine_1','isToggled')
        elif self.pair_id=='C14':
            self.note_contrast('Mug_1','isFilledWithLiquid')
            self.note_contrast('Mug_1','fillLiquid')
        else:
            self.note_contrast('Mug_1','event_destination',self.roles[destination])
        self.rules = ['An empty mug successfully placed in an activated coffee machine is filled with hot coffee.',
                      'The coffee-filling rule requires an empty mug and the machine receptacle relation.',
                      'Placement beside the machine or in an inactive machine does not trigger that rule.',
                      'Placement does not toggle the machine; a water-filled mug is not silently replaced with coffee.']
        self.freeze('CoffeeMachine_1')
        self.execute('PutObject','Mug_1',destination)
        active = destination=='CoffeeMachine_1' and self.actual('CoffeeMachine_1','isToggled','before')
        empty = not self.actual('Mug_1','isFilledWithLiquid','before')
        self.indirect[self.roles['Mug_1']] = ['isFilledWithLiquid','fillLiquid','temperature']
        self.question('Mug_1',['isFilledWithLiquid','fillLiquid'],selected=True)
        self.question('Mug_1',['temperature'],selected=self.pair_id!='C14')
        if active and empty:
            self.expect('Mug_1','isFilledWithLiquid',True)
            self.expect('Mug_1','fillLiquid','coffee')
            self.expect('Mug_1','temperature','Hot')
        else:
            self.preserved('Mug_1','isFilledWithLiquid')
            self.preserved('Mug_1','fillLiquid')
            if not active:
                self.preserved('Mug_1','temperature')
        self.preserved('CoffeeMachine_1','isToggled')
        self.check_parent('Mug_1',destination)

    def toaster(self) -> None:
        self.select('Toaster_1','Toaster')
        self.counter('Toaster_1')
        existing = self.session.find_object('BreadSliced')
        if existing:
            self.bind('BreadSliced_1',existing['objectId'])
        else:
            bread = self.select('WholeBread_setup','Bread')
            new_ids = self.ops.slice_object(bread)
            slices = [get_object(self.session.snapshot(),oid) for oid in new_ids if get_object(self.session.snapshot(),oid)['objectType']=='BreadSliced']
            self.require('slicing_created_BreadSliced',bool(slices),new_ids)
            self.bind('BreadSliced_1',sorted(slices,key=lambda o:o['objectId'])[0]['objectId'])
            self.roles.pop('WholeBread_setup',None)
        self.toggle('Toaster_1',False)
        self.cooked('BreadSliced_1',self.pair_id=='T18' and not self.a)
        self.place('BreadSliced_1','Toaster_1' if self.pair_id=='T17' and self.a else 'CounterTop_1')
        self.rules = ['An activated toaster cooks an uncooked BreadSliced currently inside it.',
                      'A slice outside the toaster is not cooked by this relation.',
                      'An already-cooked slice stays cooked; applying a rule does not imply a new Boolean change.']
        if self.pair_id=='T17':
            self.note_contrast('BreadSliced_1','parentReceptacles')
            self.freeze('Toaster_1')
            self.execute('ToggleObjectOn','Toaster_1')
            applies=self.a
        else:
            self.ops.pickup_event(self.roles['BreadSliced_1'])
            self.toggle('Toaster_1',self.a if self.pair_id=='T16' else True)
            self.note_contrast('Toaster_1','isToggled') if self.pair_id=='T16' else self.note_contrast('BreadSliced_1','isCooked')
            self.freeze('Toaster_1')
            self.execute('PutObject','BreadSliced_1','Toaster_1')
            applies=self.actual('Toaster_1','isToggled','before')
        self.indirect[self.roles['BreadSliced_1']] = ['isCooked','temperature']
        self.question('BreadSliced_1',['isCooked'],selected=True)
        if applies:
            self.expect('BreadSliced_1','isCooked',True)
        else:
            self.preserved('BreadSliced_1','isCooked')

    def breakage(self) -> None:
        self.select('Laptop_1','Laptop')
        self.ops.set_open(self.roles['Laptop_1'],True)
        self.require('laptop_initially_unbroken',self.obj('Laptop_1').get('isBroken') is False)
        self.toggle('Laptop_1',self.a)
        self.note_contrast('Laptop_1','isToggled')
        self.rules=['Breaking this laptop makes it broken; an active laptop switches off when broken.',
                    'A laptop already off remains off; breaking does not by itself require its lid to close.']
        self.freeze('Laptop_1')
        self.execute('BreakObject','Laptop_1')
        self.expect('Laptop_1','isBroken',True)
        self.expect('Laptop_1','isToggled',False)
        self.preserved('Laptop_1','isOpen')
        self.require('laptop_did_not_move_incidentally',distance(self.actual('Laptop_1','position','before'),self.actual('Laptop_1','position'))<=self.config['position_tolerance_m'])
        self.indirect[self.roles['Laptop_1']] = ['isToggled']
        self.question('Laptop_1',['isBroken','isToggled','isOpen','position'])
        self.selected=[f'{self.roles["Laptop_1"]}.isToggled']

    def carrying(self) -> None:
        self.select('Plate_1','Plate')
        self.select('Apple_1','Apple')
        self.counter('Plate_1')
        self.place('Plate_1','CounterTop_1')
        self.place('Apple_1','Plate_1' if self.a else 'CounterTop_1')
        self.check_parent('Apple_1','Plate_1',self.a)
        self.note_contrast('Apple_1','parentReceptacles')
        self.rules=['Picking up a movable plate carries objects it actually contains/supports under the simulator carrying mechanism.',
                    'An apple on the counter beside the plate is not carried merely because it is near it.']
        self.history_frame('apple_plate_support','Plate_1')
        self.freeze('Plate_1')
        self.execute('PickupObject','Plate_1')
        apple_moved=distance(self.actual('Apple_1','position','before'),self.actual('Apple_1','position'))>self.config['position_tolerance_m']
        self.require('apple_carrying_boundary',apple_moved is self.a,{'moved':apple_moved})
        self.indirect[self.roles['Apple_1']]=['position','parentReceptacles','isPickedUp']
        self.question('Plate_1',['position','isPickedUp'])
        self.question('Apple_1',['position'],selected=True)
        self.check_parent('Apple_1','Plate_1',self.a)


def publish_pair(stage: Path, output: Path, pid: str) -> None:
    """Copy only a complete candidate; the receipt is written after all files."""
    for directory in ('data/input','data/media','hidden_gold','private_logs'):
        for source in (stage/directory).glob(f'{pid}_*'):
            target=output/directory/source.name
            target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(source,target)


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pairs',default=','.join(ALL_PAIRS))
    parser.add_argument('--output-root',type=Path,default=DEFAULT_OUTPUT)
    parser.add_argument('--platform',choices=('Linux64','CloudRendering'),default=None)
    parser.add_argument('--config',type=Path,default=HERE/'config.json')
    parser.add_argument('--resume',action='store_true')
    parser.add_argument('--max-scenes',type=int,default=10)
    parser.add_argument('--seeds',default='17,43,71')
    args=parser.parse_args()
    if sys.platform!='linux':
        parser.error('This entry point runs on the Linux server only. Do not run it in the Windows checkout.')
    pairs=[p.strip() for p in args.pairs.split(',') if p.strip()]
    if len(pairs)!=len(set(pairs)) or any(p not in ALL_PAIRS for p in pairs):
        parser.error(f'Unknown or duplicate pair ID. Allowed: {",".join(ALL_PAIRS)}')
    if args.max_scenes<1:
        parser.error('--max-scenes must be positive')
    config=json.loads(args.config.read_text(encoding='utf-8'))
    spec=json.loads((HERE/'specs.json').read_text(encoding='utf-8'))
    specs={p['pair_id']:p for p in spec['pairs']}
    output=args.output_root.expanduser().resolve()
    # Generation belongs outside source control, including any custom path.
    if output==HERE.parent or HERE.parent in output.parents:
        parser.error('--output-root must be outside the entire idea1_verify_all Git checkout')
    output.mkdir(parents=True,exist_ok=True)
    source_hash=fingerprint(args.config,args.platform or config['platform'])
    existing_spec=output/'specs.json'
    if existing_spec.exists() and existing_spec.read_bytes()!=(HERE/'specs.json').read_bytes():
        raise ConstructionError('Output contains a different design spec. Use a fresh DATA_ROOT; existing evidence was not overwritten.')
    if not existing_spec.exists():
        shutil.copy2(HERE/'specs.json',existing_spec)
    seeds=[int(s) for s in args.seeds.split(',')]
    if not seeds:
        parser.error('provide at least one seed')
    from runtime import ControllerSession
    from validate import _pair_result
    summaries=[]
    session=None
    try:
        for pid in pairs:
            receipt=output/'pair_receipts'/f'{pid}.json'
            if receipt.exists():
                old=json.loads(receipt.read_text(encoding='utf-8'))
                complete=all((output/'hidden_gold'/f'{pid}_{v}.json').exists() and (output/'data/input'/f'{pid}_{v}.json').exists() for v in ('A','B'))
                if args.resume and old.get('source_fingerprint')==source_hash and complete:
                    summaries.append(old)
                    print(f'SKIP {pid}: complete candidate with matching code fingerprint',flush=True)
                    continue
                raise ConstructionError(f'{pid} already exists but is not resumable with this code. Use a fresh DATA_ROOT to preserve earlier evidence.')
            print(f'BEGIN {pid}',flush=True)
            accepted=None
            for scene in config['scene_candidates'][family_for(pid)][:args.max_scenes]:
                for seed in seeds:
                    attempt_id=f'{scene}_{seed}_{uuid.uuid4().hex[:8]}'
                    stage=output/'_attempts'/pid/attempt_id
                    stage.mkdir(parents=True)
                    try:
                        for variant in ('A','B'):
                            if session is None:
                                session=ControllerSession(scene=scene,platform=args.platform or config['platform'],
                                                          width=config['width'],height=config['height'],
                                                          build_cache_dir=output.parent/'unity_cache',
                                                          render_depth=False,render_instance_segmentation=True,
                                                          controller_kwargs={'visibilityDistance':2.5,'server_timeout':180})
                            else:
                                session.reset(scene)
                            builder=CaseBuilder(session,pid,variant,stage,specs[pid],config,seed)
                            try:
                                builder.build()
                            finally:
                                write_json(stage/f'{pid}_{variant}_action_log.json',session.records)
                        a=json.loads((stage/'hidden_gold'/f'{pid}_A.json').read_text())
                        b=json.loads((stage/'hidden_gold'/f'{pid}_B.json').read_text())
                        a['_public_model_input']=json.loads((stage/'data/input'/f'{pid}_A.json').read_text())['model_input']
                        b['_public_model_input']=json.loads((stage/'data/input'/f'{pid}_B.json').read_text())['model_input']
                        comparison=_pair_result(specs[pid],a,b)
                        write_json(stage/'pair_construction_check.json',comparison)
                        # A full validator additionally checks evidence and human
                        # review. Here reject actual failed native mechanisms;
                        # incomplete audit can only become a review candidate.
                        if comparison.get('status')=='fail' or comparison.get('actual_flip_status')=='fail':
                            raise ConstructionError(f'Pair validation failed: {comparison}')
                        if comparison.get('actual_flip_status')=='inconclusive' and pid!='M03':
                            raise ConstructionError('No selected, metadata-verified mechanism contrast; refusing to publish a nominal pair')
                        publish_pair(stage,output,pid)
                        accepted={'pair_id':pid,'scene':scene,'seed':seed,'attempt_id':attempt_id,
                                  'source_fingerprint':source_hash,'status':'simulator_checks_passed_pending_review',
                                  'pair_check':comparison,'timestamp_utc':datetime.now(timezone.utc).isoformat()}
                        write_json(receipt,accepted)
                        print(f'CANDIDATE {pid}: {scene} seed={seed}; visual/minimal-control review still required',flush=True)
                        break
                    except KeyboardInterrupt:
                        raise
                    except Exception as exc:
                        failure={'pair_id':pid,'scene':scene,'seed':seed,'error':str(exc),'traceback':traceback.format_exc()}
                        write_json(stage/'failure.json',failure)
                        print(f'FAILED_ATTEMPT {pid} {scene} seed={seed}: {exc}',flush=True)
                        if session is None:
                            raise ConstructionError('Simulator startup failed. Stop here and inspect smoke/runtime logs before constructing further samples.') from exc
                        if 'has no ' in str(exc) or 'does not report ' in str(exc):
                            # Changing placement seeds cannot create an absent
                            # object type or capability in this static scene.
                            break
                if accepted:
                    break
            if accepted:
                summaries.append(accepted)
            else:
                summaries.append({'pair_id':pid,'status':'construction_failed','source_fingerprint':source_hash})
            write_json(output/'generation_summary.json',{'pairs':summaries,'code_was_run_on':sys.platform,
                       'not_a_model_evaluation':True,'all_candidates_require_visual_and_control_review':True})
    finally:
        if session is not None:
            session.stop()
    failed=[x['pair_id'] for x in summaries if x['status']=='construction_failed']
    print(json.dumps({'requested_pairs':len(pairs),'candidate_pairs':len(pairs)-len(failed),'failed_pairs':failed,
                      'output_root':str(output),'review_required':True},ensure_ascii=False),flush=True)
    return 2 if failed else 0


if __name__=='__main__':
    raise SystemExit(main())
