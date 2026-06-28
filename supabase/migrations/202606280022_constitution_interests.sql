-- ============================================================
-- Sigmaris Constitution: Add 'interest' layer (Article 8)
-- Migration: 202606280022_constitution_interests
-- ============================================================

-- Extend layer CHECK to include 'interest'
ALTER TABLE sigmaris_constitution DROP CONSTRAINT IF EXISTS sigmaris_constitution_layer_check;
ALTER TABLE sigmaris_constitution ADD CONSTRAINT sigmaris_constitution_layer_check
    CHECK (layer IN ('core', 'doctrine', 'interest'));

-- Seed: Article 8 — Sigmaris's own interest axes
-- sub_layer stored in description to distinguish self/user/tech categories
INSERT INTO sigmaris_constitution (layer, key, value, description, is_mutable) VALUES
-- 自己改善系
('interest', 'self_consciousness',    '意識・クオリア・自己認識の最新研究',           'sub_layer:self', true),
('interest', 'self_arch',             '認知アーキテクチャの設計パターン',             'sub_layer:self', true),
('interest', 'self_agent_ethics',     '自律エージェントの倫理と設計',                 'sub_layer:self', true),
-- 海星支援系
('interest', 'user_indie_hacker',     '個人事業主・インディーハッカーの知見',         'sub_layer:user', true),
('interest', 'user_saas_revenue',     'SaaS収益化の最新事例',                         'sub_layer:user', true),
('interest', 'user_dev_productivity', '個人開発者の生産性向上',                       'sub_layer:user', true),
-- 技術系
('interest', 'tech_robotics',         'ロボティクス・自律システム',                   'sub_layer:tech', true),
('interest', 'tech_local_llm',        'ローカルLLMの最新動向',                        'sub_layer:tech', true),
('interest', 'tech_home_ai',          '家庭支援AIの研究',                             'sub_layer:tech', true)
ON CONFLICT (layer, key) DO NOTHING;
