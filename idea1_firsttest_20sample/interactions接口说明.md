# `Interactions` 接口说明

`interactions.py` 只调用 AI2-THOR 原生动作，并通过 `ControllerSession.step` 记下每一步的 action、参数和结果。任何 `lastActionSuccess` 不为 `True` 的动作都会抛出 `ActionFailure`；动作成功但元数据没有确认目标状态时会抛出 `RuntimeError`。调用方应把这类失败记为 setup/event failure 并按样本策略重试，不能写入伪造状态。构造器接受 `Interactions(session, seed=17)`，`PutObject` 使用该 seed 的原生 `randomSeed` 参数。

```python
from interactions import Interactions

ix = Interactions(session)
ix.obj(object_id)                         # 元数据对象副本，不存在时 LookupError
ix.find("Mug", optional=True)             # 类型匹配对象，或 None
ix.set_toggle(object_id, True)             # ToggleObjectOn/Off，并核对 isToggled
ix.set_open(object_id, True)               # OpenObject/CloseObject，并核对 isOpen
ix.set_dirty(object_id, False)             # DirtyObject/CleanObject，并核对 isDirty
ix.set_cooked(object_id, True)             # CookObject；False 明确不支持
ix.set_liquid(object_id, "water")          # 填充 water/coffee/wine
ix.set_liquid(object_id, None)              # EmptyLiquidFromObject
ix.room_temperature(object_id)              # 轮询自然温度衰减；返回 Pass 步骤
ix.place_initial(object_id, receptacle_id)  # setup 放置，返回 [spawn query, placement]
ix.pickup_event(object_id)                  # PickupObject，核对 inventory
ix.put_event(object_id, receptacle_id)      # 单一评测 PutObject；必须已由 setup 拿在手中
ix.slice_object(object_id)                  # SliceObject，返回新生成切片 objectId 列表
ix.settle(steps=5)                           # 多次原生 Pass
ix.look(object_id)                           # GetInteractablePoses + TeleportFull；回退 face_object
```

`place_initial` 与 `put_event` 有意分开。前者在初始化阶段查询 `GetSpawnCoordinatesAboveReceptacle`，逐个尝试原生 `PlaceObjectAtPoint`，运行少量 `Pass` 稳定后再检查关系，并只在 `parentReceptacles` 或 receptacle 的 `receptacleObjectIds` 证实关系后返回；spawn/placement/settle 都进入动作台账。`put_event` 只执行一条评测 `PutObject`，若对象未预先持有就报错；generator 必须在事件冻结前完成并记录 `PickupObject` setup。PutObject 的 `forceAction=True` 只放宽交互距离/容器限制，成功仍必须通过实际关系元数据验证。二者都不把“在 SinkBasin 中”当作接触水流的证明；水流接触仍须从实际状态变化或其他可观测证据独立确认。

对已经满足目标值的状态 setter，helper 记录真实 `Pass`，并在该记录的 `setup_noopnote` 说明跳过原因；它不会假调用 Toggle/Cook/Fill 等动作。填充状态以 `isFilledWithLiquid` 为主；当它为 False 时，`fillLiquid` 允许是 `None` 或空字符串。`pickup_event` 若目标已在 inventory 中也记录 Pass。Pickup 前默认先调用 `look`；若当前已有任何 held object，`look` 会记录 Pass 并保持相机不动，避免 TeleportFull 使手持物重置位置。需要移动视角的调用方应在拿起物体前完成 look。

温度限制：官方 iTHOR 没有直接设置某个对象 `ObjectTemperature` 的 setter。对象脱离冷热源后会随模拟时间衰减到 `RoomTemp`；`room_temperature` 只等待并读取真实元数据，超时则报错。官方另有 `SetRoomTempDecayTimeForType`、`SetGlobalRoomTempDecayTime` 和 `SetDecayTemperatureBool`，但它们调整衰减行为，不是把单个对象立即重置为室温的动作，因此此封装不以它们冒充温度 setter。

切片说明：`SliceObject` 可能把对象替换成多个派生对象。helper 在动作前后按 `objectType` 和新增 `objectId` 计算新切片 id；如果没有新 id 但原对象元数据有 `isSliced=True`，返回空列表，因为动作结果没有报告新对象 id。

## 依据与未验证范围

- [AI2-THOR object state changes](https://ai2thor.allenai.org/ithor/documentation/object-state-changes/)：开合、损坏、烹饪、切片、开关、清洁和液体动作。
- [AI2-THOR interactive physics](https://ai2thor.allenai.org/ithor/documentation/interactive-physics/)：`PickupObject`、`PutObject` 的 `forceAction`/`placeStationary`、`PlaceObjectAtPoint`、`GetSpawnCoordinatesAboveReceptacle`。官方文档没有列出 `PlaceObjectAtPoint` 或 spawn 查询的 `forceAction` 参数，因此 helper 不传该参数。
- [AI2-THOR 官方仓库的动作签名错误示例](https://github.com/allenai/procthor-10k/issues/7)：Unity 报错列出的 `PutObject` 原生签名包含 `randomSeed` 参数。
- [AI2-THOR object types](https://ai2thor.allenai.org/ithor/documentation/objects/object-types/)：对象能力标记、父子容器关系和温度语义。
- [AI2-THOR set object states](https://ai2thor.allenai.org/ithor/documentation/objects/set-object-states/)：温度衰减配置动作。

这些接口尚未在本任务指定的 AI2-THOR 5.0.0 Linux runtime 中执行验证。不同场景可能拒绝合法动作、没有可用 spawn 坐标，或不会产生设计中的清洁、填充、加热等效果；这些情形会作为动作失败或元数据不匹配暴露出来，而不会被推断为成功。`look` 也不保证存在可交互 pose；回退的 `face_object` 只调整相机朝向，不代表对象一定在画面中，仍应审阅导出的帧。
