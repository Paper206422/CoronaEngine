import assert from 'node:assert/strict';
import {
  buildGmDisclosureActionMessage,
  buildGmDecisionMessage,
  buildManualGmMessageOptions,
  buildParticipantDisclosureDraft,
  disclosureVisibleForRoom,
  disclosureVisibleForRole,
  extractDisclosureFromMessage,
} from './lanchatDisclosure.js';

{
  const disclosure = extractDisclosureFromMessage({
    message_id: 'm-1',
    room_id: 'room-a',
    text: '内部原始文本不应覆盖 public_message',
    metadata_json: JSON.stringify({
      disclosure: {
        event_id: 'disc-1',
        room_id: 'room-a',
        audience: 'participant',
        stage: '可介入窗口',
        progress: 45,
        public_message: '第一批已完成，可以补充下一批要求。',
        available_actions: ['request_add', 'request_modify'],
        requires_confirmation: false,
        metadata: {
          apply_policy: 'next_batch',
          prompt: 'do not leak',
          tool_name: 'internal-tool',
          provider: 'internal-provider',
          batch_id: 'r1_OBJECTS_b1',
        },
      },
    }),
  });

  assert.equal(disclosure.event_id, 'disc-1');
  assert.equal(disclosure.stage, '可介入窗口');
  assert.equal(disclosure.progress, 45);
  assert.equal(disclosure.public_message, '第一批已完成，可以补充下一批要求。');
  assert.deepEqual(disclosure.available_actions, ['request_add', 'request_modify']);
  assert.equal(disclosure.metadata.apply_policy, 'next_batch');
  assert.equal('prompt' in disclosure.metadata, false);
  assert.equal('tool_name' in disclosure.metadata, false);
  assert.equal('provider' in disclosure.metadata, false);
  assert.equal('batch_id' in disclosure.metadata, false);
}

{
  const disclosure = extractDisclosureFromMessage({
    message_id: 'm-host-1',
    room_id: 'room-a',
    text: 'GM 建议采用折中方案，等待房主确认。',
    metadata_json: JSON.stringify({
      disclosure: {
        event_id: 'disc-host-1',
        room_id: 'room-a',
        audience: 'host',
        stage: '冲突仲裁',
        progress: 20,
        public_message: 'GM 建议采用折中方案，等待房主确认。',
        available_actions: ['confirm_conflict_resolution', 'reject_conflict_resolution', 'request_clarification'],
        requires_confirmation: true,
        hidden_debug_ref: 'trace-hidden',
        job_id: 'hidden-job',
        raw_prompt: 'hidden raw prompt',
        metadata: {
          apply_policy: 'host_confirmation',
          proposal_id: 'conflict-proposal-1',
          requires_conflict_resolution: true,
          chain: 'hidden',
        },
      },
    }),
  });

  assert.equal(disclosure.audience, 'host');
  assert.equal(disclosure.requires_confirmation, true);
  assert.equal(disclosure.proposal_id, 'conflict-proposal-1');
  assert.equal(disclosure.requires_conflict_resolution, true);
  assert.deepEqual(disclosure.available_actions, [
    'confirm_conflict_resolution',
    'reject_conflict_resolution',
    'request_clarification',
  ]);
  assert.equal(disclosure.metadata.proposal_id, 'conflict-proposal-1');
  assert.equal('hidden_debug_ref' in disclosure, false);
  assert.equal('job_id' in disclosure, false);
  assert.equal('raw_prompt' in disclosure, false);
  assert.equal('chain' in disclosure.metadata, false);
  assert.equal(disclosureVisibleForRole(disclosure, 'host'), true);
  assert.equal(disclosureVisibleForRole(disclosure, 'guest'), false);
}

{
  const message = {
    message_id: 'm-host-fallback-1',
    room_id: 'room-a',
    text: '有一项需要房主确认的事项。',
    message_kind: 'action_status',
    metadata_json: JSON.stringify({
      disclosure: {
        event_id: 'disc-host-fallback-1',
        room_id: 'room-a',
        audience: 'participant',
        stage: '冲突仲裁',
        progress: 20,
        public_message: '有一项需要房主确认的事项。',
        available_actions: [],
        requires_confirmation: false,
        metadata: {
          proposal_id: 'conflict-proposal-1',
          prompt: 'do not leak',
        },
      },
      host_disclosure: {
        event_id: 'disc-host-fallback-1',
        room_id: 'room-a',
        audience: 'host',
        stage: '冲突仲裁',
        progress: 20,
        public_message: 'GM 建议采用折中方案，等待房主确认。',
        available_actions: ['confirm_conflict_resolution', 'request_clarification'],
        requires_confirmation: true,
        requires_conflict_resolution: true,
        proposal_id: 'conflict-proposal-1',
        metadata: {
          apply_policy: 'host_confirmation',
          proposal_id: 'conflict-proposal-1',
          provider: 'hidden-provider',
          raw_prompt: 'hidden raw prompt',
        },
      },
    }),
  };

  const guestDisclosure = extractDisclosureFromMessage(message, 'room-a', 'guest');
  assert.equal(guestDisclosure.audience, 'participant');
  assert.equal(guestDisclosure.public_message, '有一项需要房主确认的事项。');
  assert.equal(guestDisclosure.requires_confirmation, false);
  assert.deepEqual(guestDisclosure.available_actions, []);
  assert.equal('prompt' in guestDisclosure.metadata, false);

  const hostDisclosure = extractDisclosureFromMessage(message, 'room-a', 'host');
  assert.equal(hostDisclosure.audience, 'host');
  assert.equal(hostDisclosure.public_message, 'GM 建议采用折中方案，等待房主确认。');
  assert.equal(hostDisclosure.requires_confirmation, true);
  assert.equal(hostDisclosure.requires_conflict_resolution, true);
  assert.equal(hostDisclosure.proposal_id, 'conflict-proposal-1');
  assert.deepEqual(hostDisclosure.available_actions, [
    'confirm_conflict_resolution',
    'request_clarification',
  ]);
  assert.equal(hostDisclosure.metadata.apply_policy, 'host_confirmation');
  assert.equal('provider' in hostDisclosure.metadata, false);
  assert.equal('raw_prompt' in hostDisclosure.metadata, false);
}

{
  const disclosure = extractDisclosureFromMessage({
    message_id: 'm-final-conflict-1',
    room_id: 'room-a',
    text: '有一项需要房主确认的事项。',
    message_kind: 'action_status',
    metadata_json: JSON.stringify({
      disclosure: {
        event_id: 'disc-final-conflict-1',
        room_id: 'room-a',
        audience: 'host',
        stage: '最终调整中',
        progress: 0,
        public_message: '最终调整中：当前协作状态已更新。',
        available_actions: ['confirm_conflict_resolution', 'request_clarification'],
        requires_confirmation: true,
        metadata: {
          intervention: {
            apply_policy: 'host_confirmation',
            proposal_id: 'fa-plan-1-abc123',
            requires_conflict_resolution: true,
          },
        },
      },
    }),
  });

  assert.equal(disclosure.requires_confirmation, true);
  assert.equal(disclosure.proposal_id, 'fa-plan-1-abc123');
  assert.equal(disclosure.requires_conflict_resolution, true);
  assert.equal(disclosure.metadata.intervention.proposal_id, 'fa-plan-1-abc123');
}

{
  const disclosure = extractDisclosureFromMessage({
    message_id: 'm-2',
    room_id: 'room-a',
    text: '审查中：正在检查摆放。',
    metadata: {
      stage: '审查中',
      progress: 120,
      available_actions: ['request_repair'],
      trace: 'hidden',
    },
  });

  assert.equal(disclosure.stage, '审查中');
  assert.equal(disclosure.progress, 100);
  assert.equal(disclosure.public_message, '审查中：正在检查摆放。');
  assert.deepEqual(disclosure.available_actions, ['request_repair']);
  assert.equal('trace' in disclosure.metadata, false);
}

{
  const disclosure = extractDisclosureFromMessage({
    message_id: 'scheduler-1',
    room_id: 'room-a',
    text: '生成任务已进入队列，系统会按批次和优先级继续处理。',
    message_kind: 'action_status',
    metadata_json: JSON.stringify({
      disclosure: {
        event_id: 'scheduler-1',
        room_id: 'room-a',
        audience: 'participant',
        stage: '资源调度',
        progress: 50,
        public_message: '生成任务已进入队列，系统会按批次和优先级继续处理。',
        available_actions: ['add_note', 'pause_after_batch'],
        metadata: {
          queue_pressure: 0.5,
          queued_count: 1,
          active_count: 0,
          paused_session_count: 1,
          recent_event_types: ['pause_session', 'submit'],
          diagnosis: {
            state: 'paused',
            reasons: ['paused_sessions', 'recent_queue_full'],
            recommended_actions: ['resume_or_cancel_paused_sessions'],
          },
          job_id: 'gen-hidden',
          session_id: 'exec-hidden',
          prompt: 'hidden prompt',
          token: 'hidden-token',
          runtime_context: { secret: true },
          stage_handlers: { submit: 'hidden' },
        },
      },
    }),
  });

  assert.equal(disclosure.stage, '资源调度');
  assert.equal(disclosure.progress, 50);
  assert.equal(disclosure.metadata.queue_pressure, 0.5);
  assert.deepEqual(disclosure.metadata.recent_event_types, ['pause_session', 'submit']);
  assert.equal(disclosure.metadata.diagnosis.state, 'paused');
  assert.deepEqual(disclosure.metadata.diagnosis.reasons, ['paused_sessions', 'recent_queue_full']);
  assert.equal('job_id' in disclosure.metadata, false);
  assert.equal('session_id' in disclosure.metadata, false);
  assert.equal('prompt' in disclosure.metadata, false);
  assert.equal('token' in disclosure.metadata, false);
  assert.equal('runtime_context' in disclosure.metadata, false);
  assert.equal('stage_handlers' in disclosure.metadata, false);
  assert.equal(disclosureVisibleForRoom(disclosure, 'room-a'), true);
  assert.equal(disclosureVisibleForRoom(disclosure, 'room-b'), false);
  assert.equal(disclosureVisibleForRoom({ ...disclosure, room_id: '' }, 'room-a'), true);
}

{
  const disclosure = extractDisclosureFromMessage({
    message_id: 'intervention-next-batch-1',
    room_id: 'room-a',
    text: '可介入窗口：已记录补充，会优先进入下一批。',
    message_kind: 'action_status',
    metadata_json: JSON.stringify({
      disclosure: {
        event_id: 'intervention-next-batch-1',
        room_id: 'room-a',
        audience: 'participant',
        stage: '可介入窗口',
        progress: 0,
        public_message: '可介入窗口：已记录补充，会优先进入下一批。',
        available_actions: ['add_note', 'request_modify'],
        metadata: {
          intervention: {
            apply_policy: 'next_batch',
            target_hint: '一个天使雕塑',
            scheduler_update_summary: {
              attempted_count: 1,
              updated_count: 1,
              failed_count: 0,
              deferred_to_pending: false,
              reason: 'queued future generation job accepted the intervention update',
            },
            scheduler_updates: [{ job_id: 'gen-hidden', success: true }],
            job_id: 'gen-hidden',
            session_id: 'exec-hidden',
            token: 'hidden-token',
            finding_details: {
              actor_id: 'angel-1',
              fix_suggestion: '缩小一点',
              vlm_raw: 'hidden-vlm-raw',
            },
          },
        },
      },
    }),
  });

  assert.equal(disclosure.stage, '可介入窗口');
  assert.equal(disclosure.metadata.intervention.target_hint, '一个天使雕塑');
  assert.equal(disclosure.metadata.intervention.scheduler_update_summary.updated_count, 1);
  assert.equal(disclosure.metadata.intervention.scheduler_update_summary.deferred_to_pending, false);
  assert.equal('scheduler_updates' in disclosure.metadata.intervention, false);
  assert.equal('job_id' in disclosure.metadata.intervention, false);
  assert.equal('session_id' in disclosure.metadata.intervention, false);
  assert.equal('token' in disclosure.metadata.intervention, false);
  assert.equal(disclosure.metadata.intervention.finding_details.actor_id, 'angel-1');
  assert.equal(disclosure.metadata.intervention.finding_details.fix_suggestion, '缩小一点');
  assert.equal('vlm_raw' in disclosure.metadata.intervention.finding_details, false);
}

{
  assert.equal(extractDisclosureFromMessage({ message_id: 'plain', text: '普通聊天' }), null);
}

{
  const confirm = buildGmDecisionMessage(' conflict-proposal-1 ', 'confirm');
  assert.equal(confirm.text, '@GM 确认 conflict-proposal-1');
  assert.equal(confirm.options.message_kind, 'confirmation');
  assert.equal(confirm.options.target_agent_id, 'gm');
  assert.equal(confirm.options.correlation_id, 'conflict-proposal-1');
  assert.equal(confirm.options.sender_role, 'host');
  assert.equal(confirm.options.is_host, true);
  assert.deepEqual(confirm.options.metadata, {
    decision: 'confirm',
    proposal_id: 'conflict-proposal-1',
    sender_role: 'host',
    is_host: true,
  });

  const reject = buildGmDecisionMessage('gm-42', 'reject');
  assert.equal(reject.text, '@GM 拒绝 gm-42');
  assert.equal(reject.options.metadata.decision, 'reject');
  const rejectConflict = buildGmDecisionMessage('cr-plan-1-abc123', 'reject');
  assert.equal(rejectConflict.text, '@GM 拒绝 cr-plan-1-abc123');
  assert.equal(rejectConflict.options.correlation_id, 'cr-plan-1-abc123');
  assert.deepEqual(rejectConflict.options.metadata, {
    decision: 'reject',
    proposal_id: 'cr-plan-1-abc123',
    sender_role: 'host',
    is_host: true,
  });
  assert.equal(buildGmDecisionMessage('', 'confirm'), null);
}

{
  const clarify = buildGmDisclosureActionMessage('request_clarification');
  assert.equal(clarify.text.includes('@GM'), true);
  assert.equal(clarify.text.includes('澄清'), true);
  assert.equal(clarify.options.message_kind, 'chat');
  assert.equal(clarify.options.target_agent_id, 'gm');
  assert.equal(clarify.options.sender_role, 'host');
  assert.equal(clarify.options.is_host, true);
  assert.deepEqual(clarify.options.metadata, {
    action: 'request_clarification',
    sender_role: 'host',
    is_host: true,
  });

  const pause = buildGmDisclosureActionMessage('pause_discussion');
  assert.equal(pause.text, '@GM 先讨论，不要生成');
  assert.equal(pause.options.metadata.action, 'pause_discussion');
  assert.equal(pause.options.sender_role, 'host');
  assert.equal(pause.options.metadata.sender_role, 'host');

  const continueGeneration = buildGmDisclosureActionMessage('continue_generation');
  assert.equal(continueGeneration.text, '@GM 继续');
  assert.equal(buildGmDisclosureActionMessage('add_note'), null);
}

{
  const hostOptions = buildManualGmMessageOptions('host');
  assert.equal(hostOptions.message_kind, 'chat');
  assert.equal(hostOptions.target_agent_id, 'gm');
  assert.equal(hostOptions.sender_role, 'host');
  assert.equal(hostOptions.is_host, true);
  assert.deepEqual(hostOptions.metadata, {
    sender_role: 'host',
    is_host: true,
  });

  const participantOptions = buildManualGmMessageOptions('guest');
  assert.equal(participantOptions.message_kind, 'chat');
  assert.equal(participantOptions.target_agent_id, 'gm');
  assert.equal(participantOptions.sender_role, 'participant');
  assert.equal(participantOptions.is_host, false);
  assert.deepEqual(participantOptions.metadata, {
    sender_role: 'participant',
    is_host: false,
  });
}

{
  const disclosure = {
    metadata: {
      intervention: {
        target_hint: '入口右侧摊位',
      },
    },
  };
  assert.equal(buildParticipantDisclosureDraft('add_note', disclosure), '说明：入口右侧摊位，');
  assert.equal(buildParticipantDisclosureDraft('request_add', disclosure), '新增：入口右侧摊位，');
  assert.equal(buildParticipantDisclosureDraft('request_modify', disclosure), '调整：入口右侧摊位，');
  assert.equal(buildParticipantDisclosureDraft('report_issue', disclosure), '问题：入口右侧摊位，');
  assert.equal(buildParticipantDisclosureDraft('pause_after_batch', disclosure), '');
}

{
  const disclosure = extractDisclosureFromMessage({
    message_id: 'progress-1',
    room_id: 'room-a',
    text: '生成进度  35% [███░░░░░░░] 完成：摆放物件。',
    message_kind: 'progress',
    metadata: {
      phase: 'progress',
      prompt: 'hidden',
      tool_name: 'hidden-tool',
    },
  });

  assert.equal(disclosure.stage, '生成中');
  assert.equal(disclosure.progress, 35);
  assert.deepEqual(disclosure.available_actions, ['request_modify', 'report_issue']);
  assert.equal('prompt' in disclosure.metadata, false);
  assert.equal('tool_name' in disclosure.metadata, false);
}

console.log('[OK] LANChat disclosure metadata is sanitized and extractable');
