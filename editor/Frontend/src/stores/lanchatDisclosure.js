const DISCLOSURE_INTERNAL_KEYS = new Set([
  'prompt',
  'raw_prompt',
  'tool',
  'tool_name',
  'provider',
  'model_provider',
  'api_key',
  'job_id',
  'batch_id',
  'session_id',
  'token',
  'runtime_context',
  'stage_handlers',
  'scheduler_updates',
  'vlm_raw',
  'debug',
  'trace',
  'chain',
  'messages',
  'hidden_debug_ref',
]);

const DISCLOSURE_PUBLIC_KEYS = new Set([
  'event_id',
  'room_id',
  'audience',
  'stage',
  'progress',
  'public_message',
  'available_actions',
  'requires_confirmation',
  'requires_conflict_resolution',
  'proposal_id',
  'metadata',
  'created_at',
]);

export function parseDisclosureMetadata(msg = {}) {
  if (msg.metadata && typeof msg.metadata === 'object') return msg.metadata;
  const raw = msg.metadata_json || '';
  if (!raw || typeof raw !== 'string') return {};
  try {
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch (e) {
    return {};
  }
}

export function safeDisclosureMetadata(input = {}) {
  if (Array.isArray(input)) {
    return input
      .map((item) => safeDisclosureMetadata(item))
      .filter((item) => item !== undefined);
  }
  const out = {};
  if (!input || typeof input !== 'object') return out;
  for (const [key, value] of Object.entries(input)) {
    if (DISCLOSURE_INTERNAL_KEYS.has(key)) continue;
    if (value === undefined || typeof value === 'function') continue;
    if (Array.isArray(value)) {
      out[key] = value
        .map((item) => (item && typeof item === 'object' ? safeDisclosureMetadata(item) : item))
        .filter((item) => item !== undefined && typeof item !== 'function');
    } else if (value && typeof value === 'object') {
      out[key] = safeDisclosureMetadata(value);
    } else {
      out[key] = value;
    }
  }
  return out;
}

function safeDisclosureSource(input = {}) {
  const out = {};
  if (!input || typeof input !== 'object') return out;
  for (const [key, value] of Object.entries(input)) {
    if (!DISCLOSURE_PUBLIC_KEYS.has(key)) continue;
    if (DISCLOSURE_INTERNAL_KEYS.has(key)) continue;
    if (value === undefined || typeof value === 'function') continue;
    out[key] = value;
  }
  return out;
}

export function extractDisclosureFromMessage(message = {}, fallbackRoom = '', role = '') {
  const metadata = parseDisclosureMetadata(message);
  const shouldUseHostDisclosure = String(role || '') === 'host'
    && metadata.host_disclosure
    && typeof metadata.host_disclosure === 'object';
  const rawSource = shouldUseHostDisclosure
    ? metadata.host_disclosure
    : (metadata.disclosure && typeof metadata.disclosure === 'object' ? metadata.disclosure : metadata);
  const source = safeDisclosureSource(rawSource);
  const hasDisclosure = Boolean(
    source.public_message ||
    source.stage ||
    source.progress !== undefined ||
    Array.isArray(source.available_actions) ||
    source.requires_confirmation !== undefined
  );
  if (!hasDisclosure) {
    return extractLegacyProgressDisclosure(message, metadata, fallbackRoom);
  }
  const progress = Math.max(0, Math.min(100, Number(source.progress || 0)));
  return {
    event_id: String(source.event_id || message.correlation_id || message.message_id || ''),
    room_id: String(source.room_id || message.room_id || fallbackRoom || ''),
    audience: String(source.audience || 'participant'),
    stage: String(source.stage || ''),
    progress: Number.isFinite(progress) ? progress : 0,
    public_message: String(source.public_message || message.text || ''),
    available_actions: Array.isArray(source.available_actions)
      ? source.available_actions.map((item) => String(item)).filter(Boolean)
      : [],
    requires_confirmation: Boolean(source.requires_confirmation),
    proposal_id: String(
      source.proposal_id ||
      source.metadata?.proposal_id ||
      source.metadata?.intervention?.proposal_id ||
      ''
    ),
    requires_conflict_resolution: Boolean(
      source.requires_conflict_resolution ||
      source.metadata?.requires_conflict_resolution ||
      source.metadata?.intervention?.requires_conflict_resolution
    ),
    metadata: safeDisclosureMetadata(source.metadata || source),
    created_at: Number(source.created_at || message.ts || Math.floor(Date.now() / 1000)),
  };
}

export function disclosureVisibleForRole(disclosure = {}, role = '') {
  const audience = String(disclosure?.audience || 'participant');
  const currentRole = String(role || '');
  if (audience === 'host') return currentRole === 'host';
  return true;
}

export function disclosureVisibleForRoom(disclosure = {}, currentRoom = '') {
  const disclosureRoom = String(disclosure?.room_id || '').trim();
  const room = String(currentRoom || '').trim();
  if (!disclosureRoom || !room) return true;
  return disclosureRoom === room;
}

export function buildGmDecisionMessage(proposalId = '', decision = 'confirm') {
  const id = String(proposalId || '').trim();
  if (!id) return null;
  const normalizedDecision = decision === 'reject' ? 'reject' : 'confirm';
  const verb = normalizedDecision === 'reject' ? '拒绝' : '确认';
  return {
    text: `@GM ${verb} ${id}`,
    options: {
      message_kind: 'confirmation',
      target_agent_id: 'gm',
      correlation_id: id,
      sender_role: 'host',
      is_host: true,
      metadata: {
        decision: normalizedDecision,
        proposal_id: id,
        sender_role: 'host',
        is_host: true,
      },
    },
  };
}

export function buildGmDisclosureActionMessage(action = '') {
  const normalizedAction = String(action || '').trim();
  const textByAction = {
    request_clarification: '@GM 需要补充关键意图，请先澄清后再确认。',
    pause_discussion: '@GM 先讨论，不要生成',
    pause_after_batch: '@GM 暂停',
    continue_generation: '@GM 继续',
  };
  const text = textByAction[normalizedAction];
  if (!text) return null;
  return {
    text,
    options: {
      message_kind: 'chat',
      target_agent_id: 'gm',
      sender_role: 'host',
      is_host: true,
      metadata: {
        action: normalizedAction,
        sender_role: 'host',
        is_host: true,
      },
    },
  };
}

export function buildManualGmMessageOptions(role = '') {
  const isHost = String(role || '') === 'host';
  const senderRole = isHost ? 'host' : 'participant';
  return {
    message_kind: 'chat',
    target_agent_id: 'gm',
    sender_role: senderRole,
    is_host: isHost,
    metadata: {
      sender_role: senderRole,
      is_host: isHost,
    },
  };
}

export function buildParticipantDisclosureDraft(action = '', disclosure = {}) {
  const normalizedAction = String(action || '').trim();
  const targetHint = String(
    disclosure?.metadata?.intervention?.target_hint ||
    disclosure?.metadata?.target_hint ||
    disclosure?.target_hint ||
    ''
  ).trim();
  const suffix = targetHint ? `${targetHint}，` : '';
  const textByAction = {
    add_note: `说明：${suffix}`,
    request_add: `新增：${suffix}`,
    request_modify: `调整：${suffix}`,
    report_issue: `问题：${suffix}`,
  };
  return textByAction[normalizedAction] || '';
}

function extractLegacyProgressDisclosure(message = {}, metadata = {}, fallbackRoom = '') {
  const kind = String(message.message_kind || '').toLowerCase();
  const phase = String(metadata.phase || '').toLowerCase();
  const status = String(metadata.status || '').toLowerCase();
  const text = String(message.text || '');
  const isProgress = kind === 'progress' || phase === 'progress' || text.includes('生成进度');
  const isActionStatus = kind === 'action_status' || Boolean(status);
  if (!isProgress && !isActionStatus) return null;
  const progressMatch = text.match(/生成进度\s*(\d{1,3})%/);
  const progress = progressMatch ? Math.max(0, Math.min(100, Number(progressMatch[1]))) : 0;
  let stage = isProgress ? '生成中' : '协作状态';
  if (status.includes('queued')) stage = '已排队';
  if (status.includes('executing')) stage = '执行中';
  if (status.includes('executed')) stage = '已完成';
  if (status.includes('failed')) stage = '执行失败';
  return {
    event_id: String(message.correlation_id || message.message_id || ''),
    room_id: String(message.room_id || fallbackRoom || ''),
    audience: 'participant',
    stage,
    progress,
    public_message: text,
    available_actions: isProgress ? ['request_modify', 'report_issue'] : [],
    requires_confirmation: false,
    metadata: safeDisclosureMetadata(metadata),
    created_at: Number(message.ts || Math.floor(Date.now() / 1000)),
  };
}
