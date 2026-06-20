# Multiplayer Multi-Agent F5 Acceptance Manual

Date: 2026-06-17

Purpose:

```text
Verify demo-grade multiplayer + multi-agent closed loop:
LANChat discussion -> @Agent / @GM routing -> GM proposal -> host confirmation
-> host single-writer execution -> ActorAdded / ActorTransformUpdated visible on Guest
-> generation-time intervention notes affect later micro-batches.
```

Layer split:

```text
L1 routing:
  @Agent / @GM selection and trigger behavior.

L2 orchestration:
  role reply, GM summary/proposal, proposal_id/correlation_id confirmation.

L3 execution:
  confirmed action -> queued/executing/executed/failed/accepted_no_delta.

L4 sync:
  Host actor creation and transform changes appear on Guest.
```

First-pass environment:

```powershell
$env:LANCHAT_AGENT_ASYNC="1"
$env:CORONA_F5_DEMO_MODE="1"
$env:PROGRESSIVE_VLM_MAX_TARGETS="0"
$env:CORONA_RESOURCESEARCH_DISABLE_AUTO_REBUILD="1"
$env:CORONA_PROGRESSIVE_BATCH_SIZE="3"
$env:CORONA_MIN_SCENE_ITEMS="6"
```

## Experiment A: Roster And Explicit Routing

Steps:

```text
1. Host opens room.
2. Guest joins.
3. Host adds 山贼 / 学者 / 长者 / 小女孩.
4. Guest types "@".
5. Candidate list must include GM at top plus all role agents.
6. Guest sends: @学者 你会干什么
7. Host sends: @GM 整理一下大家的想法
```

Pass:

```text
@学者 only triggers 学者.
@GM only triggers GM.
No GM proposal appears for normal "你会干什么" / "整理一下".
```

Fail first checks:

```text
No GM candidate -> RoomPanel.vue / roster injection.
@学者 triggers GM proposal -> lanchat_agent_orchestrator.py routing.
progress/gm/action_status triggers agent -> C++ LANChatState message_kind gate.
```

## Experiment B: GM Proposal And Host Confirmation Status Chain

Steps:

```text
1. Guest sends an execution/conflict request through @GM.
2. Wait for gm_proposal.
3. Host uses confirmation button, not free text.
4. Watch LANChat messages/status events.
```

Pass:

```text
gm_proposal
confirmation
confirmed_gm_action
queued_host_action
executing_host_action
host_action_executed / host_action_failed / accepted_no_delta
```

Fail first checks:

```text
No proposal -> L2 orchestrator proposal boundary.
No confirmation -> RoomPanel.vue confirmation payload.
No queued/executing -> lanchat_agent_worker.py / lanchat_host_action_executor.py.
executed but no scene change on Host -> L3 host action callback did not mutate actor.
```

## Experiment C: ActorAdded Sync

Steps:

```text
1. Host executes/imports a visible model through the confirmed path or direct host action.
2. Confirm Host viewport shows the actor.
3. Confirm Guest viewport shows the same actor after pending create polling.
```

Pass:

```text
Guest sees the actor.
No duplicate actor appears on Host.
Guest actor has same actor_guid if visible in logs/debug payload.
```

Fail first checks:

```text
Host sees actor, Guest does not -> ACTOR_CREATE / actor-sync-broadcast / broadcast_actor_create / poll_pending_actor_create.
Guest receives file transfer error -> model dependency transfer path.
Guest creates duplicate -> actor_guid or _suppress_network_broadcast loop issue.
```

## Experiment D: ActorTransformUpdated Sync

Steps:

```text
1. Start from an actor already visible on both Host and Guest.
2. Host moves the actor by viewport drag or AI fast edit.
3. Host scales or rotates the same actor.
4. Guest observes the same actor.
```

Pass:

```text
Guest actor position changes after Host move.
Guest actor scale/rotation changes after Host edit.
No duplicate actor appears.
No bounce-back loop appears.
```

Fail first checks:

```text
Host changes, Guest unchanged -> ACTOR_TRANSFORM_UPDATE / CEF poll_pending_actor_transform / SceneTools.apply_actor_transform_internal.
Guest duplicate actor -> actor_guid matching or remote apply path.
Transform loops back -> actor.py if_init=True / _suppress_network_broadcast issue.
Rotation wrong by 57.3x -> degrees/radians violation.
```

Current implementation note:

```text
ACTOR_TRANSFORM_UPDATE code is present.
C++/Ninja/CMake build is intentionally not run in this Codex thread.
Compile/protocol verification must be done in the designated bottom-layer environment.
```

## Experiment E: Generation-Time Intervention

Steps:

```text
1. Host/Guest starts:
   @长者 我有一个计划，建立森林奇幻集市
2. Confirm planning gate returns proposal and does not generate immediately.
3. Send:
   @长者 确认开始，先生成前三个
4. During generation, Guest sends:
   @小女孩 后面再加灯串和发光蘑菇
   @学者 后续不要挡中央活动区
   @GM 暂停
   @GM 继续
```

Pass:

```text
Other agents reply quickly while active agent is composing.
pending notes are recorded as generation_delta/layout_constraint/edit_existing.
pause takes effect at a micro-batch boundary.
continue resumes later batches.
final report mentions applied/recorded/pending notes.
```

Fail first checks:

```text
Input box freezes -> CEF/UI/render main thread.
Message enters history but no quick reply -> LANChatAgentWorker busy path.
Quick reply appears but later batch ignores note -> scene_composer_progressive pending notes application.
Pause message ignored -> lanchat_scene_runtime mode / SceneSession runtime_mode_provider.
```

## Experiment F: Same-Actor Conflict

Steps:

```text
1. Host and Guest both see the same actor.
2. Host moves it.
3. Guest simultaneously asks @GM to move the same actor elsewhere.
4. Host confirms immediately.
```

Tonight pass criterion:

```text
System must not silently claim robust conflict resolution.
At minimum, status/proposal should make the conflict visible, or record actor version/lock as P1.
```

Known not complete:

```text
No full actor_version / expected_version / lock_owner protocol yet.
If last-write-wins silently overwrites, record as bottom-layer P1, not GM intelligence failure.
```
