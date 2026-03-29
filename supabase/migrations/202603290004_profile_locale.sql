alter table public.profiles
add column if not exists locale text not null default 'ja';

alter table public.profiles
drop constraint if exists profiles_locale_check;

alter table public.profiles
add constraint profiles_locale_check
check (
  locale in (
    'ja',
    'en',
    'ko',
    'zh-CN',
    'zh-TW',
    'es',
    'fr',
    'de',
    'pt-BR',
    'it',
    'id',
    'th',
    'vi'
  )
);
