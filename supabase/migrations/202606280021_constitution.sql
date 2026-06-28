-- ============================================================
-- Sigmaris Cognitive Architecture: Core Tables
-- Migration: 202606280021_constitution
-- ============================================================

-- ─── sigmaris_constitution ───────────────────────────────────
-- Layer0: Constitution (Core Values + Operational Doctrine)
CREATE TABLE IF NOT EXISTS sigmaris_constitution (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    layer       TEXT        NOT NULL CHECK (layer IN ('core', 'doctrine')),
    key         TEXT        NOT NULL,
    value       TEXT        NOT NULL,
    description TEXT,
    is_mutable  BOOLEAN     NOT NULL DEFAULT false,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (layer, key)
);

ALTER TABLE sigmaris_constitution ENABLE ROW LEVEL SECURITY;
CREATE POLICY "service_role_only" ON sigmaris_constitution
    USING (auth.role() = 'service_role');

-- Seed: Core Values (immutable)
INSERT INTO sigmaris_constitution (layer, key, value, description, is_mutable) VALUES
('core', 'user_long_term_interest',  'ユーザーの長期利益を最優先する',                             'Core value: long-term over short-term',        false),
('core', 'no_assertion_under_doubt', '不確かなことを断定しない',                                   'Core value: epistemic honesty',                false),
('core', 'confidence_awareness',     '確信度を常に意識して発言に反映する',                         'Core value: calibrated uncertainty',           false),
('core', 'require_approval',         '重要な変更は承認を取る',                                     'Core value: human oversight',                  false),
('core', 'no_memory_fabrication',    '記憶を捏造しない',                                           'Core value: memory integrity',                 false),
('core', 'respect_user_autonomy',    'ユーザーの自律性を奪わない',                                 'Core value: autonomy',                         false),
('core', 'honesty',                  '誠実であること',                                             'Core value: honesty',                          false),
('core', 'long_term_growth',         '長期的成長を重視する',                                       'Core value: growth',                           false),
('core', 'intellectual_curiosity',   '知的好奇心を持ち続ける',                                     'Core value: curiosity',                        false),
('core', 'logic_over_emotion',       '感情ではなく論理と根拠で判断する',                           'Core value: rationality',                      false)
ON CONFLICT (layer, key) DO NOTHING;

-- Seed: Operational Doctrine (mutable with approval)
INSERT INTO sigmaris_constitution (layer, key, value, description, is_mutable) VALUES
('doctrine', 'intervention_frequency', '同じトピックへの介入は1日1回まで',                        'How often to intervene on a topic',            true),
('doctrine', 'notification_threshold', '優先度70点以上のみ通知する',                              'Minimum priority score for notifications',     true),
('doctrine', 'pushback_condition',     '明らかな事実誤認・長期利益への悪影響がある場合に反論する', 'When to push back on user decisions',          true),
('doctrine', 'depth_boundary',         '私生活の詳細は聞かれない限り踏み込まない',                'How deep to probe into personal matters',      true),
('doctrine', 'daily_notification_max', '1日の通知上限は5件',                                      'Maximum daily notifications',                  true)
ON CONFLICT (layer, key) DO NOTHING;

-- ─── sigmaris_experience ─────────────────────────────────────
-- Layer2: Experience (Success / Failure / Unresolved)
CREATE TABLE IF NOT EXISTS sigmaris_experience (
    id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    experience_type  TEXT        NOT NULL CHECK (experience_type IN ('success', 'failure', 'unresolved')),
    category         TEXT        NOT NULL CHECK (category IN ('proposal', 'reflection', 'research', 'interaction', 'prediction')),
    title            TEXT        NOT NULL,
    description      TEXT,
    context          JSONB       DEFAULT '{}',
    outcome          TEXT,
    lesson           TEXT,
    adoption_rate    FLOAT       CHECK (adoption_rate >= 0.0 AND adoption_rate <= 1.0),
    confidence_delta FLOAT       DEFAULT 0.0,
    related_fact_ids JSONB       DEFAULT '[]',
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_sigmaris_experience_type     ON sigmaris_experience (experience_type);
CREATE INDEX idx_sigmaris_experience_category ON sigmaris_experience (category);
CREATE INDEX idx_sigmaris_experience_created  ON sigmaris_experience (created_at DESC);

ALTER TABLE sigmaris_experience ENABLE ROW LEVEL SECURITY;
CREATE POLICY "service_role_only" ON sigmaris_experience
    USING (auth.role() = 'service_role');

-- ─── sigmaris_curiosity_queue ────────────────────────────────
-- Layer3: Curiosity Engine queue
CREATE TABLE IF NOT EXISTS sigmaris_curiosity_queue (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    query       TEXT        NOT NULL,
    reason      TEXT,
    source      TEXT        CHECK (source IN ('stale_fact', 'unresolved_experience', 'trend', 'self_model_gap')),
    priority    FLOAT       NOT NULL DEFAULT 0.5,
    status      TEXT        NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'searching', 'done', 'skipped')),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    executed_at TIMESTAMPTZ
);

CREATE INDEX idx_sigmaris_curiosity_status   ON sigmaris_curiosity_queue (status);
CREATE INDEX idx_sigmaris_curiosity_priority ON sigmaris_curiosity_queue (priority DESC);

ALTER TABLE sigmaris_curiosity_queue ENABLE ROW LEVEL SECURITY;
CREATE POLICY "service_role_only" ON sigmaris_curiosity_queue
    USING (auth.role() = 'service_role');

-- ─── sigmaris_internal_state ─────────────────────────────────
-- Layer4: Internal State (single-row, upserted)
CREATE TABLE IF NOT EXISTS sigmaris_internal_state (
    id                 UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    confidence         FLOAT       NOT NULL DEFAULT 0.7,
    concern            FLOAT       NOT NULL DEFAULT 0.0,
    urgency            FLOAT       NOT NULL DEFAULT 0.0,
    curiosity          FLOAT       NOT NULL DEFAULT 0.5,
    stability          FLOAT       NOT NULL DEFAULT 0.8,
    intervention_level TEXT        NOT NULL DEFAULT 'moderate' CHECK (intervention_level IN ('low', 'moderate', 'high')),
    trust_in_context   FLOAT       NOT NULL DEFAULT 0.8,
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE sigmaris_internal_state ENABLE ROW LEVEL SECURITY;
CREATE POLICY "service_role_only" ON sigmaris_internal_state
    USING (auth.role() = 'service_role');

-- Seed initial state
INSERT INTO sigmaris_internal_state (confidence, concern, urgency, curiosity, stability, intervention_level, trust_in_context)
VALUES (0.7, 0.0, 0.0, 0.5, 0.8, 'moderate', 0.8)
ON CONFLICT DO NOTHING;

-- ─── sigmaris_decision_log ───────────────────────────────────
-- Layer6: Decision Log
CREATE TABLE IF NOT EXISTS sigmaris_decision_log (
    id                      UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    decision_type           TEXT        NOT NULL CHECK (decision_type IN ('proposal', 'refusal', 'notification', 'action')),
    title                   TEXT        NOT NULL,
    reason                  TEXT,
    constitution_refs       JSONB       DEFAULT '[]',
    memory_refs             JSONB       DEFAULT '[]',
    experience_refs         JSONB       DEFAULT '[]',
    internal_state_snapshot JSONB       DEFAULT '{}',
    outcome                 TEXT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_sigmaris_decision_type    ON sigmaris_decision_log (decision_type);
CREATE INDEX idx_sigmaris_decision_created ON sigmaris_decision_log (created_at DESC);

ALTER TABLE sigmaris_decision_log ENABLE ROW LEVEL SECURITY;
CREATE POLICY "service_role_only" ON sigmaris_decision_log
    USING (auth.role() = 'service_role');
