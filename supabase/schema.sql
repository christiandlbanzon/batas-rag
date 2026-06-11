-- Batas — Supabase schema
-- Run in the Supabase SQL editor (or psql) against your free project.
-- Idempotent: safe to re-run.

create extension if not exists vector;

-- ---------------------------------------------------------------------------
-- Core corpus tables
-- ---------------------------------------------------------------------------

create table if not exists articles (
  id            bigint generated always as identity primary key,
  book          text not null,            -- e.g. "Book Three"
  book_title    text not null default '', -- e.g. "Conditions of Employment"
  title         text not null default '', -- Title within the book, e.g. "Title I — Working Conditions and Rest Periods"
  chapter       text not null default '',
  article_no    text not null,            -- renumbered number, e.g. "87"
  old_article_no text,                    -- pre-renumbering number when annotated, e.g. "87" / "287"
  heading       text not null default '', -- e.g. "Overtime Work"
  body          text not null,
  unique (article_no)
);

create table if not exists chunks (
  id            bigint generated always as identity primary key,
  article_id    bigint not null references articles(id) on delete cascade,
  chunk_index   int not null default 0,        -- position within the article
  content       text not null,                 -- breadcrumb header + chunk text (what gets embedded)
  content_hash  text not null,                 -- sha256 of content; embed.py skips unchanged rows
  embedding     vector(768),                   -- Gemini text-embedding-004
  tsv           tsvector generated always as (to_tsvector('english', content)) stored,
  unique (article_id, chunk_index)
);

-- ANN index for vector search; GIN for keyword search.
create index if not exists chunks_embedding_hnsw
  on chunks using hnsw (embedding vector_cosine_ops);

create index if not exists chunks_tsv_gin
  on chunks using gin (tsv);

-- ---------------------------------------------------------------------------
-- Demo plumbing: feedback + query log (rate limiting / recent questions)
-- ---------------------------------------------------------------------------

create table if not exists feedback (
  id          bigint generated always as identity primary key,
  question    text not null,
  answer      text not null,
  rating      smallint not null check (rating in (-1, 1)),
  created_at  timestamptz not null default now()
);

create table if not exists query_log (
  id          bigint generated always as identity primary key,
  ip_hash     text not null,        -- sha256(ip + server salt); raw IPs are never stored
  question    text not null,
  created_at  timestamptz not null default now()
);

create index if not exists query_log_ip_time on query_log (ip_hash, created_at desc);
create index if not exists query_log_time    on query_log (created_at desc);

-- ---------------------------------------------------------------------------
-- Hybrid search RPC: vector top-N + full-text top-N fused with
-- Reciprocal Rank Fusion. One round trip from the API route.
-- ---------------------------------------------------------------------------

create or replace function hybrid_search(
  query_text       text,
  query_embedding  vector(768),
  match_count      int   default 8,
  pool_size        int   default 20,    -- candidates taken from each retriever before fusion
  rrf_k            int   default 50,
  semantic_weight  float default 1.0,
  full_text_weight float default 1.0
)
returns table (
  chunk_id    bigint,
  article_id  bigint,
  article_no  text,
  heading     text,
  book        text,
  title       text,
  content     text,
  similarity  float,   -- cosine similarity from the vector arm (null if FTS-only hit)
  rrf_score   float
)
language sql stable
as $$
with semantic as (
  select c.id,
         1 - (c.embedding <=> query_embedding) as similarity,
         row_number() over (order by c.embedding <=> query_embedding) as rank
  from chunks c
  where c.embedding is not null
  order by c.embedding <=> query_embedding
  limit pool_size
),
keyword as (
  select c.id,
         row_number() over (order by ts_rank_cd(c.tsv, websearch_to_tsquery('english', query_text)) desc) as rank
  from chunks c
  where c.tsv @@ websearch_to_tsquery('english', query_text)
  order by ts_rank_cd(c.tsv, websearch_to_tsquery('english', query_text)) desc
  limit pool_size
),
fused as (
  select coalesce(s.id, k.id) as id,
         s.similarity,
         coalesce(semantic_weight / (rrf_k + s.rank), 0) +
         coalesce(full_text_weight / (rrf_k + k.rank), 0) as rrf_score
  from semantic s
  full outer join keyword k on s.id = k.id
)
select c.id          as chunk_id,
       a.id          as article_id,
       a.article_no,
       a.heading,
       a.book,
       a.title,
       c.content,
       f.similarity,
       f.rrf_score
from fused f
join chunks c   on c.id = f.id
join articles a on a.id = c.article_id
order by f.rrf_score desc
limit match_count;
$$;

-- ---------------------------------------------------------------------------
-- Row Level Security: the web app uses the service-role key server-side only,
-- which bypasses RLS. Enabling RLS with no policies blocks the anon key
-- entirely, so a leaked anon key exposes nothing.
-- ---------------------------------------------------------------------------

alter table articles  enable row level security;
alter table chunks    enable row level security;
alter table feedback  enable row level security;
alter table query_log enable row level security;
