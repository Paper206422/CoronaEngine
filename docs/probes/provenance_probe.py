"""provenance 载体探针 (B-P-1) — 只读诊断，零副作用。

目的：确认 scene.get_actors() 返回的 Actor 是否为稳定 Python 实例、
能否挂动态属性、actor_guid 是否可靠，从而定方案 A(挂属性) vs 方案 B(旁路字典)。

用法：引擎启动后(F5)，在场景里随便导入/已有几个物体，然后在
Python 控制台执行：
    exec(open(r"e:\corona\CoronaEngine\docs\probes\provenance_probe.py", encoding="utf-8").read())
或把本文件内容粘进控制台。结果直接 print，也写入同目录 provenance_probe_result.txt。
"""

import logging

logger = logging.getLogger("provenance_probe")


def _get_scene():
    from CoronaCore.core.managers import scene_manager
    sc = scene_manager.get("")
    if sc is None:
        routes = scene_manager.list_all()
        sc = scene_manager.get(routes[0]) if routes else None
    return sc


def run_probe():
    lines = []

    def out(msg):
        print(msg)
        lines.append(str(msg))

    out("=" * 60)
    out("provenance 载体探针 (B-P-1)")
    out("=" * 60)

    scene = _get_scene()
    if scene is None:
        out("[FAIL] 拿不到场景，请先打开/新建一个场景并导入至少 1 个物体")
        return

    actors1 = [a for a in scene.get_actors() if not a.name.startswith("__room_")]
    if not actors1:
        out("[WARN] 场景里没有非房间物体，请先导入几个模型再跑")
        return

    out(f"\n场景物体数(非房间): {len(actors1)}")

    # ── 测试1: actor_guid 是否填充且唯一 ──
    out("\n[测试1] actor_guid 填充 / 唯一性")
    guids = []
    for a in actors1:
        guid = getattr(a, "actor_guid", None)
        guids.append(guid)
        out(f"  - {a.name!r}: actor_guid={guid!r}")
    has_all_guid = all(guids) and len(set(guids)) == len(guids)
    out(f"  => {'PASS' if has_all_guid else 'FAIL'}: "
        f"{'全部填充且唯一' if has_all_guid else 'guid 缺失或重复'}")

    # ── 测试2: 实例身份是否跨 get_actors() 稳定 ──
    out("\n[测试2] 实例身份跨 get_actors() 调用稳定性")
    actors2 = [a for a in scene.get_actors() if not a.name.startswith("__room_")]
    by_name2 = {a.name: a for a in actors2}
    same_identity = True
    for a in actors1:
        b = by_name2.get(a.name)
        if b is None or id(a) != id(b):
            same_identity = False
            out(f"  - {a.name!r}: id 不一致 ({id(a)} vs {id(b) if b else 'None'})")
    out(f"  => {'PASS' if same_identity else 'FAIL'}: "
        f"{'同一 Python 实例(可挂属性)' if same_identity else '实例被重建(方案A不可用)'}")

    # ── 测试3: 挂动态属性并跨调用读回 ──
    out("\n[测试3] 动态属性挂载 + 读回")
    probe_actor = actors1[0]
    try:
        probe_actor._probe_provenance = "USER"
        probe_actor._probe_batch_id = "probe_batch_001"
        # 重新取一次，看属性是否还在
        actors3 = [a for a in scene.get_actors() if not a.name.startswith("__room_")]
        target = next((a for a in actors3 if a.name == probe_actor.name), None)
        readback = getattr(target, "_probe_provenance", None) if target else None
        ok = readback == "USER"
        out(f"  - 挂 _probe_provenance='USER' 到 {probe_actor.name!r}, 读回={readback!r}")
        out(f"  => {'PASS' if ok else 'FAIL'}: "
            f"{'属性持久(方案A可用)' if ok else '属性丢失(必须方案B旁路字典)'}")
        # 清理探针属性
        try:
            del probe_actor._probe_provenance
            del probe_actor._probe_batch_id
        except Exception:
            pass
    except AttributeError as e:
        ok = False
        out(f"  => FAIL: 无法挂属性(C++ slots?): {e}")

    # ── 结论 ──
    out("\n" + "=" * 60)
    out("结论")
    out("=" * 60)
    if has_all_guid and same_identity and ok:
        out("方案 A 在【同一会话内】可用：可直接往 Actor 实例挂 provenance 属性。")
        out("但跨场景保存/重载会丢属性(重建 Actor)，")
        out("=> 推荐：方案 B 旁路字典，key 用 actor_guid(已持久化、跨重载稳定)。")
        out("   actor_guid 既稳又持久，是比对象 id 更可靠的索引键。")
    elif has_all_guid and not same_identity:
        out("实例被重建 => 方案 A 不可用。")
        out("=> 必须方案 B 旁路字典，key 用 actor_guid。")
    else:
        out("基础假设不成立(guid 缺失/无法挂属性)，需进一步排查再定方案。")

    # 写文件
    try:
        import os
        result_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "provenance_probe_result.txt")
        with open(result_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        out(f"\n结果已写入: {result_path}")
    except Exception as e:
        out(f"\n(写结果文件失败，忽略: {e})")


run_probe()
