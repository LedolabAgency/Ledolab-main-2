create extension if not exists pgcrypto;

create table if not exists public.users (
  id uuid primary key default gen_random_uuid(),
  telegram_id bigint unique not null,
  username text,
  first_name text,
  phone_number text,
  language_code text default 'ru',
  business_level text,
  warnings_count integer default 0,
  is_banned boolean default false,
  created_at timestamptz default now(),
  is_active boolean default true
);

create table if not exists public.goals (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.users(id) on delete cascade,
  goal_text text not null,
  milestones text[] not null default '{}',
  status text not null default 'active',
  created_at timestamptz default now()
);

create table if not exists public.daily_tasks (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.users(id) on delete cascade,
  goal_id uuid references public.goals(id) on delete set null,
  task_text text not null,
  task_type text not null default 'main',
  date date not null,
  status text not null default 'waiting_report',
  created_at timestamptz default now()
);

create unique index if not exists idx_daily_tasks_unique
on public.daily_tasks(user_id, date, task_type);

create table if not exists public.reports (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.users(id) on delete cascade,
  task_id uuid not null references public.daily_tasks(id) on delete cascade,
  report_text text,
  proof_type text,
  file_id text,
  created_at timestamptz default now()
);

create table if not exists public.daily_reports (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.users(id) on delete cascade,
  report_date date not null,
  tasks_snapshot text[] not null default '{}',
  report_payload jsonb not null default '[]'::jsonb,
  summary_text text,
  status text not null default 'approved',
  flags integer not null default 0,
  score_awarded integer not null default 30,
  group_message_id bigint,
  group_chat_id bigint,
  admin_comment text,
  created_at timestamptz default now(),
  reviewed_at timestamptz,
  unique(user_id, report_date)
);

create table if not exists public.daily_report_votes (
  id uuid primary key default gen_random_uuid(),
  report_id uuid not null references public.daily_reports(id) on delete cascade,
  voter_telegram_id bigint not null,
  vote_type text not null,
  created_at timestamptz default now(),
  unique(report_id, voter_telegram_id)
);

create table if not exists public.scores (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.users(id) on delete cascade,
  points integer not null,
  reason text not null,
  created_at timestamptz default now()
);

create table if not exists public.daily_statuses (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.users(id) on delete cascade,
  status_date date not null,
  status text not null,
  created_at timestamptz default now()
);

create unique index if not exists idx_daily_statuses_unique
on public.daily_statuses(user_id, status_date);
