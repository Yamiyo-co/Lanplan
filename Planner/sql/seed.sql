-- Default dataset (English names throughout the repo).
INSERT OR IGNORE INTO languages
(name, code, level, objective, status, priority, weight,
 target_minutes_week, min_contacts_week, max_contacts_week,
 preferred_session_minutes)
VALUES
('Japanese', 'ja', 'B1', 'B2', 'active',      5, 1.5, 150, 4, 7, 50),
('Farsi',    'fa', 'A2', 'B1', 'active',      4, 1.2, 120, 4, 7, 45),
('Chinese',     'zh', 'beginner', 'A2', 'active',      4, 1.2, 120, 4, 7, 45),
('Korean',   'ko', 'A1', 'A2', 'maintenance', 2, 0.8,  60, 2, 4, 30),
('Russian',   'ru', 'A1', 'A2', 'maintenance', 2, 0.8,  60, 2, 4, 30),
('Thai',     'th', 'beginner', 'A1', 'waiting', 1, 0.5,  0, 0, 0, 30),
('Tagalog',     'tl', 'beginner', 'A1', 'waiting', 1, 0.5,  0, 0, 0, 30),
('Indonesian',  'id', 'beginner', 'A1', 'waiting', 1, 0.5,  0, 0, 0, 30);

INSERT OR IGNORE INTO tasks
(name, kind, duration_min, min_per_week, max_per_week,
 priority, requires_main_session, description)
VALUES
('Main session', 'main',       45, 1, 1, 5, 1, 'New vocabulary, grammar and guided practice.'),
('Active recall', 'retrieval', 10, 2, 7, 5, 0, 'Recall without looking at answers.'),
('Conversation',  'speaking',  20, 1, 3, 5, 0, 'Active oral production.'),
('Listening',     'listening', 15, 1, 4, 4, 0, 'Oral comprehension.'),
('Reading',       'reading',   15, 1, 3, 3, 0, 'Active reading.'),
('Writing',       'writing',   15, 1, 2, 3, 0, 'Written production.');

INSERT OR IGNORE INTO weekdays
(weekday, name, enabled, available_minutes, main_session_allowed,
 micro_sessions_allowed, start_time)
VALUES
(0, 'Monday',    1, 60, 1, 1, '18:00'),
(1, 'Tuesday',   1, 60, 1, 1, '18:00'),
(2, 'Wednesday', 1, 60, 1, 1, '18:00'),
(3, 'Thursday',  1, 60, 1, 1, '18:00'),
(4, 'Friday',    1, 60, 1, 1, '18:00'),
(5, 'Saturday',  1, 60, 1, 1, '10:00'),
(6, 'Sunday',    1, 30, 0, 1, '10:00');

INSERT OR IGNORE INTO settings (key, value) VALUES
('planning_horizon_months', '3'),
('sunday_anki_only', '1'),
('calendar_name', 'Language Planner'),
('timezone', 'Europe/Paris'),
-- Cognitive-load guards (see README).
('max_languages_per_day', '2'),
('max_minutes_per_day', '110'),
('flex_weekday', '5'),
('anki_minutes', '20'),
('interference_penalty', '40'),
('interference_groups', 'japanese,chinese');

-- Anki routine languages, aligned with the planner by default.
INSERT OR IGNORE INTO anki_langues (name, code, status, lv_daily) VALUES
('Japanese', 'ja', 'active', 8),
('Farsi',    'fa', 'active', 8),
('Chinese',     'zh', 'active', 8),
('Korean',   'ko', 'maintenance', 6),
('Russian',  'ru', 'maintenance', 6),
('Thai',    'th', 'waiting', 0),
('Tagalog',    'tl', 'waiting', 0),
('Indonesian', 'id', 'waiting', 0);
