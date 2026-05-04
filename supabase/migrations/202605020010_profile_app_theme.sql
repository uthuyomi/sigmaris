alter table public.profiles
add column if not exists app_theme text not null default 'light';

alter table public.profiles
drop constraint if exists profiles_app_theme_check;

alter table public.profiles
add constraint profiles_app_theme_check
check (app_theme in ('light', 'dark'));
