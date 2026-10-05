# راهنمای کامل راه‌اندازی Graphiti به‌عنوان حافظه مشترک Codex و Claude Code

> **نسخه این راهنما:** 2026-10-05  
> **هدف:** ساخت یک حافظه بیرونی و قابل بازیابی برای Agentها با Graphiti + FalkorDB + Ollama + MCP  
> **ستاپ مستندشده در این فایل همان ستاپی است که امروز روی سیستم تست شد.**

---

## 1. معماری نهایی

در این معماری، Codex و Claude Code مستقیماً حافظه را مدیریت نمی‌کنند. هر دو از طریق MCP به Graphiti وصل می‌شوند.

```text
                         ┌─────────────────────┐
                         │      Ollama         │
                         │                     │
                         │ gpt-oss:20b         │
                         │ nomic-embed-text    │
                         │ localhost:11434     │
                         └─────────┬───────────┘
                                   │
                                   │ OpenAI-compatible API
                                   │
┌──────────────┐          ┌────────▼───────────┐          ┌─────────────────┐
│  Claude Code │ ──MCP──▶ │   Graphiti MCP    │ ───────▶ │    FalkorDB     │
└──────────────┘          │ localhost:8000    │          │ localhost:6379  │
                          │ group_id = main    │          └─────────────────┘
┌──────────────┐          │ BGE reranker      │
│    Codex     │ ──MCP──▶ │ local             │
└──────────────┘          └────────────────────┘
```

Graphiti در این معماری نقش **حافظه خارجی Agentها** را دارد.

جریان کاری موردنظر:

```text
شروع Task
   ↓
Agent اطلاعات مرتبط را از Graphiti می‌خواند
   ↓
کد و مستندات واقعی Repository را بررسی می‌کند
   ↓
Task را انجام می‌دهد
   ↓
دانش پایدار و تصمیم‌های جدید را در Graphiti ثبت می‌کند
   ↓
Task بعدی / Agent بعدی
```

بنابراین اگر وسط پروژه از Codex به Claude Code برویم، دانش مهم پروژه فقط داخل Conversation قبلی باقی نمی‌ماند.

---

# 2. اجزای این Setup

ستاپی که در این راهنما استفاده می‌کنیم:

| Component | مقدار |
|---|---|
| Graph Database | FalkorDB |
| FalkorDB image | `falkordb/falkordb:v4.18.8` |
| Graphiti Core | `>= 0.30.2` |
| MCP Transport | HTTP |
| MCP Endpoint | `http://localhost:8000/mcp/` |
| MCP Health | `http://localhost:8000/health` |
| Graphiti Group | `main` |
| Local LLM | Ollama |
| LLM Model | `gpt-oss:20b` |
| Embedding Model | `nomic-embed-text` |
| Embedding Dimensions | `768` |
| Reranker | Local BGE |
| Ollama OpenAI API | `http://localhost:11434/v1` |
| Episode Concurrency | `SEMAPHORE_LIMIT=1` |

> برای قابل تکرار بودن نصب، در این راهنما FalkorDB را روی نسخه `v4.18.8` Pin می‌کنیم و از `latest` استفاده نمی‌کنیم.

---

# 3. پیش‌نیازها

روی سیستم باید این ابزارها وجود داشته باشند:

- Git
- Docker / Docker Desktop
- Python 3.10+
- `uv`
- Ollama
- Codex CLI
- Claude Code

بررسی اولیه:

```bash
git --version
docker --version
python3 --version
uv --version
ollama --version
codex --version
claude --version
```

اگر `uv` نصب نیست:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

بعد Terminal را دوباره باز کنید یا PATH را Reload کنید.

---

# 4. نصب Ollama

روی macOS می‌توان Ollama را با برنامه رسمی یا Homebrew نصب کرد.

با Homebrew:

```bash
brew install --cask ollama
```

سپس Ollama را اجرا کنید.

اگر Ollama App نصب شده:

```bash
open -a Ollama
```

یا در حالتی که می‌خواهید Server را مستقیم اجرا کنید:

```bash
ollama serve
```

بررسی:

```bash
curl http://localhost:11434/api/tags
```

اگر Ollama بالا باشد، باید پاسخ JSON دریافت کنید.

> اگر Ollama App خودش Server را اجرا کرده، هم‌زمان `ollama serve` دیگری اجرا نکنید.

---

# 5. نصب مدل LLM

مدلی که در Setup امروز استفاده شد:

```text
gpt-oss:20b
```

دانلود:

```bash
ollama pull gpt-oss:20b
```

بررسی:

```bash
ollama list
```

تست Interactive:

```bash
ollama run gpt-oss:20b
```

مثلاً بنویسید:

```text
Return only: OK
```

برای خروج:

```text
/bye
```

---

# 6. تست gpt-oss از API

Graphiti قرار نیست از CLI اولاما استفاده کند. Graphiti از API اولاما استفاده می‌کند.

تست Native API:

```bash
curl http://localhost:11434/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-oss:20b",
    "messages": [
      {
        "role": "user",
        "content": "Return only OK"
      }
    ],
    "stream": false
  }'
```

تست OpenAI-compatible endpoint:

```bash
curl http://localhost:11434/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-oss:20b",
    "messages": [
      {
        "role": "user",
        "content": "Return only OK"
      }
    ],
    "stream": false
  }'
```

اگر هر دو پاسخ می‌دهند، LLM آماده است.

---

# 7. نصب Embedding Model

Graphiti برای Semantic Search نیاز به Embedding دارد.

مدلی که در Setup امروز استفاده شد:

```text
nomic-embed-text
```

دانلود:

```bash
ollama pull nomic-embed-text
```

بررسی:

```bash
ollama list
```

تست:

```bash
curl http://localhost:11434/api/embed \
  -H "Content-Type: application/json" \
  -d '{
    "model": "nomic-embed-text",
    "input": "CloudLearn uses Graphiti as an external memory layer."
  }'
```

باید یک آرایه Embedding دریافت کنید.

در Config گرافیتی Dimension این مدل را روی مقدار زیر قرار می‌دهیم:

```text
768
```

---

# 8. نصب FalkorDB با Docker

در این Setup فقط FalkorDB داخل Docker اجرا می‌شود و Graphiti MCP مستقیماً روی سیستم اجرا می‌شود.

ابتدا Image مورد استفاده را بگیرید:

```bash
docker pull falkordb/falkordb:v4.18.8
```

اگر Container قبلی با نام `falkordb` دارید:

```bash
docker rm -f falkordb 2>/dev/null || true
```

FalkorDB را اجرا کنید:

```bash
docker run -d \
  --name falkordb \
  --restart unless-stopped \
  -p 6379:6379 \
  falkordb/falkordb:v4.18.8
```

بررسی Container:

```bash
docker ps
```

بررسی Redis/FalkorDB:

```bash
docker exec falkordb redis-cli ping
```

خروجی مورد انتظار:

```text
PONG
```

برای دیدن Moduleها:

```bash
docker exec falkordb redis-cli MODULE LIST
```

---

## 8.1. FalkorDB UI اختیاری

اگر بخواهید UI مربوط به FalkorDB را هم Publish کنید، Container را می‌توانید با پورت `3000` نیز اجرا کنید:

```bash
docker rm -f falkordb

docker run -d \
  --name falkordb \
  --restart unless-stopped \
  -p 6379:6379 \
  -p 3000:3000 \
  falkordb/falkordb:v4.18.8
```

سپس:

```text
http://localhost:3000
```

---

# 9. نصب Graphiti

Repository اصلی:

```bash
git clone https://github.com/getzep/graphiti.git
```

ورود به MCP Server:

```bash
cd graphiti/mcp_server
```

در Setup امروز مسیر مشابه این بود:

```text
/Users/arezoo/Downloads/graphiti/mcp_server
```

Dependencies:

```bash
uv sync
```

برای Providerها و Dependencyهای اضافی:

```bash
uv sync --extra providers
```

---

# 10. بررسی graphiti-core

Setup امروز با نسخه زیر تست شد:

```text
graphiti-core >= 0.30.2
```

نسخه نصب‌شده را بررسی کنید:

```bash
uv run python -c "import importlib.metadata as m; print(m.version('graphiti-core'))"
```

اگر نسخه قدیمی‌تر است:

```bash
uv add "graphiti-core[falkordb]>=0.30.2"
```

برای Local BGE reranker باید `sentence-transformers` نیز موجود باشد:

```bash
uv add sentence-transformers
```

یا اگر از extras خود پروژه استفاده می‌کنید:

```bash
uv sync --extra providers
```

---

# 11. نکته مهم درباره Local Model Support

این راهنما **Setup تست‌شده امروز** را مستند می‌کند.

در این Setup:

```yaml
llm:
  provider: "openai_generic"
```

و:

```yaml
reranker:
  provider: "bge"
```

استفاده شده است.

اگر Graphiti MCP شما این دو گزینه را نمی‌شناسد، Build/Branch شما با Setup این راهنما یکسان نیست.

قبل از ادامه بررسی کنید که MCP Server شما از این موارد پشتیبانی کند:

```text
openai_generic
BGE reranker
```

هدف `openai_generic` این است که Graphiti بتواند به Providerهای OpenAI-compatible مثل Ollama متصل شود، بدون اینکه از OpenAI Cloud API استفاده کند.

---

# 12. Config کامل Graphiti

فایل زیر را باز کنید:

```text
graphiti/mcp_server/config/config.yaml
```

برای Setup امروز Config اصلی باید به شکل زیر باشد:

```yaml
server:
  transport: "http"
  host: "0.0.0.0"
  port: 8000

llm:
  provider: "openai_generic"
  model: "gpt-oss:20b"
  max_tokens: 4096
  structured_output_mode: "json_object"

  providers:
    openai:
      api_key: "ollama"
      api_url: "http://localhost:11434/v1"
      organization_id: ""

embedder:
  provider: "openai"
  model: "nomic-embed-text"
  dimensions: 768

  providers:
    openai:
      api_key: "ollama"
      api_url: "http://localhost:11434/v1"
      organization_id: ""

reranker:
  provider: "bge"

  providers:
    openai:
      api_key: ""

    gemini:
      api_key: ""

database:
  provider: "falkordb"

  providers:
    falkordb:
      uri: "redis://localhost:6379"
      password: ""
      database: "default_db"

graphiti:
  group_id: "main"
  episode_id_prefix: ""
  user_id: "mcp_user"
```

---

# 13. چرا structured_output_mode روی json_object است؟

Graphiti برای استخراج Entity و Relationship به Structured Output وابسته است.

مدل‌های Local ممکن است `json_schema` را قبول کنند ولی همیشه دقیقاً Schema مورد انتظار Graphiti را رعایت نکنند.

به همین دلیل در Setup Local ما از:

```yaml
structured_output_mode: "json_object"
```

استفاده می‌کنیم.

اگر Ingestion خطاهایی درباره Missing Field یا Schema Validation می‌دهد، یکی از اولین جاهایی که باید بررسی کنید همین بخش است.

---

# 14. چرا SEMAPHORE_LIMIT=1؟

هر Episode که وارد Graphiti می‌شود می‌تواند چندین LLM Call ایجاد کند:

- Entity extraction
- Relation extraction
- Deduplication
- Summarization
- Embedding
- Reranking

روی Local Ollama اگر چند Episode هم‌زمان Process شوند، RAM/GPU/Unified Memory به‌شدت درگیر می‌شود.

برای Setup فعلی:

```bash
SEMAPHORE_LIMIT=1
```

استفاده می‌کنیم.

---

# 15. اجرای Graphiti MCP

ابتدا سه چیز باید آماده باشند:

### Ollama

```bash
curl http://localhost:11434/api/tags
```

### FalkorDB

```bash
docker exec falkordb redis-cli ping
```

### Models

```bash
ollama list
```

باید حداقل این دو مدل را ببینید:

```text
gpt-oss:20b
nomic-embed-text
```

حالا از مسیر:

```bash
cd graphiti/mcp_server
```

Graphiti را اجرا کنید:

```bash
SEMAPHORE_LIMIT=1 uv run python main.py --config config/config.yaml
```

Setup موفق باید چیزی شبیه موارد زیر را در Log نشان دهد:

```text
LLM: openai_generic / gpt-oss:20b
Embedder: openai / nomic-embed-text
Database: falkordb
Reranker: BGE local
Group: main
HTTP MCP: 0.0.0.0:8000
```

---

# 16. Health Check

در Terminal دیگری:

```bash
curl http://localhost:8000/health
```

MCP endpoint:

```text
http://localhost:8000/mcp/
```

نکته:

```text
/mcp/
```

یک MCP Streamable HTTP endpoint است و مثل REST API معمولی قرار نیست با هر `curl GET` ساده‌ای خروجی معنی‌دار بدهد.

برای بررسی زنده بودن سرویس از:

```text
/health
```

استفاده کنید.

---

# 17. اتصال Codex به Graphiti MCP

Graphiti MCP Server همین Serverی است که روی پورت `8000` اجرا کردیم.

در Codex نیازی نیست MCP Server دیگری بنویسیم.

فقط آن را Register می‌کنیم:

```bash
codex mcp add graphiti --url http://localhost:8000/mcp/
```

بررسی:

```bash
codex mcp list
```

باید Server با نامی مشابه زیر دیده شود:

```text
graphiti
```

---

# 18. اتصال Claude Code به Graphiti MCP

برای Scope پروژه:

```bash
claude mcp add \
  --transport http \
  --scope project \
  graphiti \
  http://localhost:8000/mcp/
```

بررسی:

```bash
claude mcp list
```

داخل Claude Code نیز می‌توانید وضعیت MCPها را بررسی کنید:

```text
/mcp
```

در حالت Project Scope معمولاً فایل زیر در Root پروژه ساخته می‌شود:

```text
.mcp.json
```

نمونه:

```json
{
  "mcpServers": {
    "graphiti": {
      "type": "http",
      "url": "http://localhost:8000/mcp/"
    }
  }
}
```

---

# 19. ابزارهای مهم Graphiti MCP

Agent بعد از اتصال، Toolهای Graphiti را می‌بیند.

مهم‌ترین Toolهایی که در Workflow روزانه استفاده می‌کنیم:

### `add_memory`

ثبت یک Episode جدید در حافظه.

ورودی‌های مهم:

```text
name
episode_body
group_id
source
source_description
reference_time
```

### `search_memory_facts`

جست‌وجوی Factها و Relationshipها.

### `search_nodes`

جست‌وجوی Entityها.

### `get_episodes`

مشاهده Episodeهای قبلی.

### `get_entity_edge`

گرفتن یک Fact/Edge مشخص.

### `add_triplet`

ثبت مستقیم یک Fact به صورت:

```text
source entity
   ↓
relationship
   ↓
target entity
```

### `delete_episode`

حذف Episode.

### `clear_graph`

پاک کردن Graph یا Group.

> `clear_graph` را داخل Workflow عادی Agent قرار ندهید.

---

# 20. group_id در پروژه ما

در Setup فعلی:

```text
group_id = main
```

یعنی دانش اصلی CloudLearn داخل Group زیر نگهداری می‌شود:

```text
main
```

ما Microserviceها را با ساختن Groupهای جدا از هم جدا نمی‌کنیم؛ بلکه Episodeها و Entityهای مرتبط با هر سرویس را با Naming واضح داخل `main` ثبت می‌کنیم.

مثلاً:

```text
gateway-overview
gateway-authentication
lab-manager-overview
lab-manager-lifecycle
vm-manager-overview
student-portal-auth
wordpress-woocommerce-enrollment
wordpress-cloudlearn-sso
```

این روش باعث می‌شود Relationship بین سرویس‌ها داخل یک Knowledge Graph قابل کشف باشد.

---

# 21. چه چیزهایی را باید داخل Graphiti ذخیره کنیم؟

Graphiti قرار نیست Backup کل Repository باشد.

موارد مناسب:

- Architecture
- Service responsibilities
- Service boundaries
- Important endpoints
- Authentication flow
- Trust boundaries
- Database ownership
- Important tables
- Lifecycle rules
- Business rules
- Decisions
- Constraints
- Important file paths
- Integration flows
- Known problems
- Resolved problems
- Non-obvious implementation details
- Current project state
- Open questions
- Reasons behind architectural decisions

---

# 22. چه چیزهایی را نباید داخل Graphiti ذخیره کنیم؟

ذخیره نکنید:

- Password
- API Key
- Access Token
- JWT واقعی کاربر
- Private Key
- Secret
- Cookie
- Database credential
- کل Source Code
- فایل‌های Build
- node_modules
- Logهای حجیم
- اطلاعات موقتی بی‌ارزش
- Conversation کامل Agent

Graphiti باید **دانش فشرده و قابل استفاده مجدد** داشته باشد.

---

# 23. روش درست ارسال اطلاعات از Claude Code به Graphiti

وقتی Claude Code یک سرویس را بررسی کرده، از او نخواهید:

```text
Everything you know را در Graphiti ذخیره کن.
```

این کار Noise زیادی تولید می‌کند.

بهتر است بگویید:

```text
Persist the durable knowledge you learned about this service into Graphiti.

Use group_id: main.

Do not store secrets, raw logs, temporary debugging output, or large code blocks.

Split the knowledge into small, service-oriented memories.

Capture:
- responsibilities
- boundaries
- important flows
- important files
- important endpoints
- architectural decisions
- constraints
- confirmed current behavior
- unresolved questions

Avoid duplicating facts already present in Graphiti.
```

---

# 24. نمونه Prompt برای ثبت یک Microservice

مثلاً بعد از بررسی Gateway:

```text
Use the Graphiti MCP server and persist the durable knowledge from this task.

Group:
main

Focus only on the CloudLearn Gateway service.

Before writing, search existing Graphiti knowledge so you do not duplicate existing memories.

Store concise, reusable knowledge covering:
- responsibilities
- service boundaries
- authentication and trust boundaries
- important routes
- downstream services
- important files/functions
- configuration dependencies
- decisions and constraints
- confirmed current behavior
- unresolved questions

Do not store secrets, tokens, raw logs, full source files, or temporary debugging notes.

After writing, report the exact memory/episode names added or updated.
```

همین Prompt را می‌توان به Codex هم داد.

---

# 25. Workflow شروع Task

هدف این است که Agent در ابتدای هر Task کور شروع نکند.

قبل از دست زدن به کد:

```text
Graphiti
   ↓
Relevant project knowledge
   ↓
Repository verification
   ↓
Implementation
```

Agent باید ابتدا با Query مشخص حافظه را جست‌وجو کند.

مثلاً برای Task مربوط به WordPress authentication:

```text
Search Graphiti group `main` for existing knowledge related to:

- WordPress integration
- WooCommerce enrollment
- Gateway authentication
- JWT
- wp_user_id
- Student Portal login
- CloudLearn SSO

Use both `search_memory_facts` and `search_nodes`.

Only retrieve information relevant to this task.
Then verify important mutable facts against the current repository before making changes.
```

---

# 26. Workflow پایان Task

بعد از اتمام کار:

```text
Implementation complete
   ↓
Tests / verification
   ↓
Extract durable knowledge
   ↓
Compare with existing Graphiti knowledge
   ↓
add_memory
```

Prompt پیشنهادی:

```text
Before finishing this task, update Graphiti.

Use group_id: main.

First search existing Graphiti memories related to the service you changed.

Persist only durable new information:
- behavior that was confirmed
- architectural decisions
- changed flows
- new constraints
- important files/functions
- newly discovered service dependencies
- resolved issues
- remaining open questions

Do not dump the conversation.
Do not store secrets.
Do not duplicate existing memories unnecessarily.

If existing knowledge is now stale, add the new current fact with enough context for Graphiti's temporal model to supersede the old understanding.

Finally report what was stored.
```

---

# 27. CLAUDE.md برای Claude Code

در Root پروژه:

```text
CLAUDE.md
```

بخش زیر را اضافه کنید:

```markdown
## Graphiti Project Memory

This project uses the Graphiti MCP server as persistent external project memory.

Graphiti MCP server:
- name: graphiti
- group_id: main

### At the start of every non-trivial task

Before making implementation decisions:

1. Identify the service/component involved.
2. Query Graphiti group `main` for relevant existing knowledge.
3. Use both:
   - `search_memory_facts`
   - `search_nodes`
4. Retrieve only information relevant to the current task.
5. Treat Graphiti as project memory, not as the final source of truth for mutable code behavior.
6. Verify critical/current facts against the repository before changing code.

Do not perform a broad graph dump at the start of every task.

### During the task

Use Graphiti again when:
- an architectural decision needs historical context
- a service boundary is unclear
- a previous decision may explain current behavior
- another microservice dependency is discovered

Do not write temporary debugging noise to Graphiti.

### At the end of every meaningful task

After implementation and verification:

1. Search existing Graphiti knowledge for the affected component.
2. Persist only durable new knowledge using `add_memory`.
3. Use `group_id: main`.
4. Prefer small service-oriented episodes over one huge project dump.
5. Capture:
   - confirmed behavior
   - architecture
   - service responsibilities and boundaries
   - important flows
   - important endpoints
   - important files/functions
   - decisions and reasons
   - constraints
   - dependencies
   - resolved issues
   - unresolved questions
6. Avoid duplicating existing memories.
7. Never store secrets, credentials, tokens, private keys, cookies, or sensitive runtime values.
8. Report what memories were added or updated before finishing.

### Naming

Use descriptive memory names such as:

- gateway-authentication
- gateway-service-boundaries
- lab-manager-lifecycle
- vm-manager-lifecycle
- student-portal-auth
- wordpress-woocommerce-enrollment
- wordpress-cloudlearn-sso

### Context efficiency

Graphiti is used to reduce repeated rediscovery and unnecessary context loading.

Do not load all memory into the context.
Query narrowly for the current task.
Do not re-ingest the entire repository.
Do not store full source files when a concise architectural fact is sufficient.
```

---

# 28. AGENTS.md برای Codex

در Root پروژه:

```text
AGENTS.md
```

بخش زیر را اضافه کنید:

```markdown
## Graphiti Project Memory

This repository uses the Graphiti MCP server as persistent external project memory.

Graphiti MCP server:
- name: graphiti
- group_id: main

### Task startup

For every non-trivial task:

1. Determine which service or subsystem is involved.
2. Search Graphiti group `main` before making architectural assumptions.
3. Use:
   - `search_memory_facts`
   - `search_nodes`
4. Keep retrieval targeted to the current task.
5. Verify mutable implementation details against the repository.
6. If Graphiti conflicts with the current code, the current repository is authoritative and the stale memory should be corrected at task completion.

Do not query the entire graph without a task-specific reason.

### While working

Consult Graphiti when prior architecture, constraints, dependencies, or decisions may affect the implementation.

Do not persist speculative conclusions as facts.

### Task completion

After code changes and verification:

1. Search existing Graphiti knowledge for the affected component.
2. Persist durable confirmed knowledge with `add_memory`.
3. Always use `group_id: main`.
4. Store service-oriented memories rather than large conversation dumps.
5. Record:
   - confirmed current behavior
   - architecture and boundaries
   - important flows
   - important routes
   - important files/functions
   - decisions and rationale
   - constraints
   - dependencies
   - issues resolved
   - open questions
6. Do not duplicate existing knowledge unnecessarily.
7. Never store secrets or sensitive credentials.
8. Report which memories/episodes were created or updated.

### Memory naming

Prefer stable descriptive names, for example:

- gateway-overview
- gateway-authentication
- lab-manager-overview
- lab-manager-lifecycle
- vm-manager-overview
- student-portal-auth
- wordpress-woocommerce-enrollment
- wordpress-cloudlearn-sso

### Context management rule

Graphiti is not a replacement for the current working context or repository.

Use it to recover durable project knowledge.

Retrieve narrowly.
Verify against code.
Write back only durable findings.
```

---

# 29. چرا هم AGENTS.md و هم CLAUDE.md؟

وقتی Agent Harness عوض می‌شود، Instruction File هم ممکن است عوض شود.

برای Codex:

```text
AGENTS.md
```

برای Claude Code:

```text
CLAUDE.md
```

هر دو باید یک Memory Policy مشابه داشته باشند.

در نتیجه Workflow به Harness خاص وابسته نمی‌ماند.

```text
Codex
  ├── AGENTS.md
  └── Graphiti MCP
         │
         ▼
       main

Claude Code
  ├── CLAUDE.md
  └── Graphiti MCP
         │
         ▼
       main
```

---

# 30. نمونه Handoff از Codex به Claude Code

فرض کنید چند ساعت Codex روی Gateway کار کرده است.

قبل از پایان Session:

```text
Before finishing, persist all durable findings from this task into Graphiti group `main`.

Focus on:
- Gateway authentication
- JWT validation
- service trust boundaries
- routes inspected
- downstream service calls
- files changed
- decisions made
- remaining open questions

Search existing memories first and avoid duplicates.

Do not store raw conversation history or secrets.
```

بعد وارد Claude Code می‌شویم.

در شروع:

```text
Before doing any work, query Graphiti group `main` for the latest knowledge about:

- Gateway authentication
- JWT validation
- service trust boundaries
- relevant recent implementation decisions

Use `search_memory_facts` and `search_nodes`.

Then inspect the current repository and continue from the latest verified state.
```

این همان چیزی است که باعث می‌شود Handoff بین Agentها فقط به یک Markdown دستی وابسته نباشد.

---

# 31. نمونه برای WordPress / WooCommerce Integration

برای سناریوی فعلی CloudLearn:

در پایان Audit:

```text
Persist the confirmed WordPress/WooCommerce ↔ CloudLearn integration knowledge into Graphiti.

Use group_id: main.

Search existing memories first.

Create or update service-oriented memories covering:

- wordpress-woocommerce-enrollment
- gateway-enrollment-api
- lab-manager-enrollment
- student-portal-auth
- wordpress-cloudlearn-sso

Capture:
- implemented flow
- trust boundaries
- endpoints
- wp_user_id behavior
- JWT behavior
- important files/functions
- what is implemented
- what is incomplete
- architectural decisions
- unresolved questions

Do not store secrets.
Do not modify application code as part of this memory operation.
```

بعد Agent بعدی می‌تواند بگوید:

```text
Query Graphiti group `main` for all existing knowledge relevant to WordPress → CloudLearn authentication and SSO.

Use the results as prior architectural context, then verify the current implementation against the repository before proposing changes.
```

---

# 32. تست اینکه Agent واقعاً Graphiti را می‌بیند

## Codex

```bash
codex mcp list
```

سپس داخل Task:

```text
Use the Graphiti MCP server.
Search group `main` for facts related to CloudLearn Lab Manager.
Report only the top relevant facts.
Do not modify anything.
```

اگر MCP درست وصل باشد، Codex باید Graphiti Tools را Call کند.

---

## Claude Code

```bash
claude mcp list
```

داخل Session:

```text
/mcp
```

بعد:

```text
Use Graphiti and search group `main` for knowledge about CloudLearn Gateway.
Do not modify the repository.
```

---

# 33. تست End-to-End حافظه

اول به یکی از Agentها بگویید:

```text
Use Graphiti MCP and add this test memory to group `main`.

Name:
graphiti-e2e-test

Body:
Graphiti E2E memory test created successfully.

Source:
text

Source description:
Manual MCP integration test
```

نکته مهم:

`add_memory` در Graphiti می‌تواند Episode را Queue کند و Processing به شکل Background انجام شود.

بنابراین ممکن است Memory بلافاصله در Semantic Search ظاهر نشود.

بعد از اینکه Processing کامل شد، با Agent دیگر Query کنید:

```text
Search Graphiti group `main` for:
"Graphiti E2E memory test"

Use both search_memory_facts and search_nodes.
```

اگر Agent دوم آن را پیدا کرد، این زنجیره کار می‌کند:

```text
Claude Code / Codex
       ↓
      MCP
       ↓
    Graphiti
       ↓
   FalkorDB
       ↓
Agent دیگر
```

---

# 34. Context Management صحیح

Graphiti نباید تبدیل شود به این:

```text
Every task
   ↓
Read everything
   ↓
Put the whole graph in context
```

این کار عملاً مزیت Context Management را خراب می‌کند.

روش صحیح:

```text
Current task
   ↓
Determine relevant subsystem
   ↓
Targeted Graphiti query
   ↓
5-10 relevant facts/nodes
   ↓
Work
```

مثلاً:

بد:

```text
Give me everything stored in Graphiti.
```

خوب:

```text
Search group `main` for the current Lab Manager concurrency rules that affect formal lab and practice session start.
Return only the most relevant facts.
```

---

# 35. آیا Graphiti خودش Token مصرف را کم می‌کند؟

نه به صورت جادویی.

Graphiti کمک می‌کند مجبور نباشیم در هر Session:

- کل Conversation قبلی
- کل Architecture Doc
- تمام تصمیم‌های پروژه
- تمام Handoffها
- تمام Source فایل‌های مهم

را دوباره داخل Context قرار دهیم.

اگر Retrieval هدفمند باشد، Agent فقط Knowledge مرتبط را وارد Context می‌کند.

پس مزیت اصلی این است:

```text
Less repeated context
+ less rediscovery
+ better handoff
+ potentially lower token usage
```

اما اگر هر بار کل Graph را Query کنیم، این مزیت از بین می‌رود.

---

# 36. Memory Hygiene

برای پروژه بزرگ، Memory Hygiene مهم است.

قانون پیشنهادی:

### ذخیره کن

```text
Architecture
Confirmed behavior
Decisions
Constraints
Service boundaries
Important dependencies
Non-obvious fixes
Current implementation state
```

### ذخیره نکن

```text
Temporary shell output
Large logs
Speculation
Failed hypotheses with no future value
Repeated facts
Full source code
Secrets
```

---

# 37. Naming Convention پیشنهادی برای CloudLearn

همه داخل:

```text
group_id = main
```

ولی Memory Nameها Service-oriented باشند.

مثلاً:

```text
gateway-overview
gateway-components
gateway-authentication
gateway-service-relationships

lab-manager-overview
lab-manager-components
lab-manager-service-relationships
lab-manager-lab-lifecycle
lab-manager-vm-lifecycle
lab-manager-prewarm-and-capacity
lab-manager-verification-and-preflight
lab-manager-kubernetes-and-storage
lab-manager-redis-and-async-work
lab-manager-concurrency-and-failure-safety
lab-manager-requirements-and-decisions
lab-manager-important-files
lab-manager-open-questions

vm-manager-overview
vm-manager-lifecycle

student-portal-overview
student-portal-authentication

wordpress-woocommerce-enrollment
wordpress-cloudlearn-authentication
wordpress-cloudlearn-sso
```

---

# 38. Startup Checklist روزانه

هر بار که می‌خواهید کار را شروع کنید:

## 1. Ollama

```bash
curl http://localhost:11434/api/tags
```

## 2. Models

```bash
ollama list
```

## 3. FalkorDB

```bash
docker ps --filter name=falkordb
docker exec falkordb redis-cli ping
```

## 4. Graphiti

از مسیر:

```bash
cd graphiti/mcp_server
```

اجرا:

```bash
SEMAPHORE_LIMIT=1 uv run python main.py --config config/config.yaml
```

## 5. Health

```bash
curl http://localhost:8000/health
```

## 6. Codex

```bash
codex mcp list
```

## 7. Claude Code

```bash
claude mcp list
```

---

# 39. Stop / Start

## Stop FalkorDB

```bash
docker stop falkordb
```

## Start FalkorDB

```bash
docker start falkordb
```

## Restart

```bash
docker restart falkordb
```

## Logs

```bash
docker logs -f falkordb
```

Graphiti MCP اگر در Foreground اجرا شده با:

```text
Ctrl+C
```

متوقف می‌شود.

---

# 40. Troubleshooting

## مشکل: Connection refused روی 6379

بررسی:

```bash
docker ps
```

بعد:

```bash
docker exec falkordb redis-cli ping
```

اگر Container خاموش است:

```bash
docker start falkordb
```

---

## مشکل: Connection refused روی 11434

بررسی:

```bash
curl http://localhost:11434/api/tags
```

اگر بالا نیست:

```bash
open -a Ollama
```

یا:

```bash
ollama serve
```

---

## مشکل: model not found

```bash
ollama list
```

اگر `gpt-oss:20b` نیست:

```bash
ollama pull gpt-oss:20b
```

اگر `nomic-embed-text` نیست:

```bash
ollama pull nomic-embed-text
```

---

## مشکل: openai_generic شناخته نمی‌شود

Build فعلی Graphiti MCP شما Local Provider Support مورد استفاده این Setup را ندارد.

نسخه و Branch را بررسی کنید.

همچنین:

```bash
uv run python -c "import importlib.metadata as m; print(m.version('graphiti-core'))"
```

برای این Setup:

```text
graphiti-core >= 0.30.2
```

---

## مشکل: BGE reranker در دسترس نیست

Dependency را بررسی کنید:

```bash
uv run python -c "import sentence_transformers; print(sentence_transformers.__version__)"
```

اگر نصب نیست:

```bash
uv add sentence-transformers
```

اولین اجرای BGE ممکن است نیاز داشته باشد Model مربوطه را Download و Cache کند.

---

## مشکل: Graphiti بالا می‌آید ولی Search چیزی پیدا نمی‌کند

چند احتمال:

1. Episode هنوز Queue/Processing است.
2. `group_id` اشتباه است.
3. Memory در Group دیگری ثبت شده.
4. Query بیش از حد کلی است.
5. Ingestion در Log خطا داده است.

همه عملیات پروژه ما باید روی:

```text
main
```

انجام شوند.

---

## مشکل: اطلاعات Duplicate شده‌اند

قبل از `add_memory` همیشه:

```text
search_memory_facts
search_nodes
```

را برای همان موضوع اجرا کنید.

بعد فقط Delta یا Knowledge جدید را ثبت کنید.

---

## مشکل: Memory با کد فعلی تضاد دارد

Repository برای Behavior جاری Source of Truth است.

Flow:

```text
Graphiti says X
Repository says Y
   ↓
Verify Y
   ↓
Complete task
   ↓
Write current confirmed state back to Graphiti
```

Graphiti Temporal Knowledge Graph است، بنابراین Knowledge جدید باید با Context کافی ثبت شود تا وضعیت جدید قابل تشخیص باشد.

---

# 41. Security Rule

هیچ‌وقت این موارد را به Graphiti نفرستید:

```text
.env contents
JWT
Access Token
Refresh Token
API Key
Private Key
Password
Session Cookie
Production credential
Database password
SSH private key
```

در AGENTS.md و CLAUDE.md هم این قانون را صریح نگه دارید.

---

# 42. Workflow نهایی پیشنهادی

```text
┌──────────────────────────────┐
│ User gives task to Agent     │
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────┐
│ Read AGENTS.md / CLAUDE.md   │
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────┐
│ Query Graphiti group main    │
│ narrowly for relevant facts  │
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────┐
│ Verify against repository    │
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────┐
│ Implement / Debug / Analyze  │
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────┐
│ Test and verify              │
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────┐
│ Search existing memory       │
│ before writing               │
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────┐
│ add_memory durable findings  │
│ group_id = main              │
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────┐
│ Next task / next Agent       │
└──────────────────────────────┘
```

---

# 43. خلاصه Commandها

## Ollama

```bash
ollama pull gpt-oss:20b
ollama pull nomic-embed-text
ollama list
```

## FalkorDB

```bash
docker pull falkordb/falkordb:v4.18.8

docker run -d \
  --name falkordb \
  --restart unless-stopped \
  -p 6379:6379 \
  falkordb/falkordb:v4.18.8

docker exec falkordb redis-cli ping
```

## Graphiti

```bash
git clone https://github.com/getzep/graphiti.git
cd graphiti/mcp_server

uv sync --extra providers

SEMAPHORE_LIMIT=1 uv run python main.py --config config/config.yaml
```

## Health

```bash
curl http://localhost:8000/health
```

## Codex

```bash
codex mcp add graphiti --url http://localhost:8000/mcp/
codex mcp list
```

## Claude Code

```bash
claude mcp add \
  --transport http \
  --scope project \
  graphiti \
  http://localhost:8000/mcp/

claude mcp list
```

---

# 44. References

Graphiti:

```text
https://github.com/getzep/graphiti
https://github.com/getzep/graphiti/tree/main/mcp_server
```

Ollama gpt-oss:

```text
https://ollama.com/library/gpt-oss:20b
```

Ollama nomic-embed-text:

```text
https://ollama.com/library/nomic-embed-text
```

OpenAI Codex MCP documentation:

```text
https://developers.openai.com/learn/docs-mcp
```

---

# 45. نتیجه

بعد از این Setup، Graphiti بخشی از Workflow توسعه است، نه یک ابزار جانبی که فقط گاهی دستی استفاده شود.

قانون اصلی:

```text
Before task:
Retrieve relevant durable knowledge.

During task:
Verify against the repository.

After task:
Persist durable confirmed knowledge.
```

و در پروژه CloudLearn:

```text
Graphiti group_id = main
```

هم Codex و هم Claude Code به همین حافظه متصل می‌شوند.

به این ترتیب Knowledge مهم پروژه خارج از Context یک Agent باقی می‌ماند و Handoff بین Agentها با از دست دادن کامل Context شروع نمی‌شود.
