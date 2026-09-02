<!--
GigaMail — mail for your AI agent
Copyright (C) 2026 Adecubed

This program is free software: you can redistribute it and/or modify it
under the terms of the GNU Affero General Public License as published by
the Free Software Foundation, either version 3 of the License, or (at your
option) any later version. See the LICENSE file for details.
-->
<!-- mcp-name: io.github.adecubed/gigamail -->

# GigaMail — Mail for your AI agent

**English** · [Italiano](#lang-it) · [中文](#lang-zh)

**MCP server that gives your agent — Claude, Codex, OpenClaw, Hermes, or any
MCP client — safe, controlled access to your email** — multi-account (Microsoft Graph + IMAP), calendar,
local search index, sender memory, and an agent-aware permission model.

No built-in LLM: the intelligence is your agent's. The MCP server speaks
stdio only — no network port. (An optional human console adds a local HTTP
API bound to 127.0.0.1.)

**On your data**: GigaMail keeps mail indexes, credentials, memory and
configuration **on your machine** — we run no service and receive nothing.
Mail content your agent reads is, of course, handled by that agent and its
model provider under their own data policies. Choose your agent
accordingly; the masker lets you hide sensitive fields (tax codes, VAT
numbers, IBANs, emails, phone numbers — validated deterministically, no AI)
before the agent ever sees them.

![The human console: a draft written by the agent — real figures from the
account's documents, the right floor plans attached, and appointment slots
taken from the actual calendar. Nothing is sent until you approve it.](docs/console-draft.png)

*A real draft: the agent pulled the figures from the account's documents,
picked the floor plans to attach, and proposed slots from the calendar.
The human reviews and sends — or edits the instruction and regenerates.*

## Why

- **Hybrid search**: provider search (Graph/IMAP) + local SQLite index — fast
  and offline-friendly
- **Sender memory**: tone, topics and history per sender, so replies sound right
- **Observer**: patterns learned from how the user edited past drafts
- **Knowledge files**: attach your price lists, terms, product sheets to an
  account — the agent reads them to answer mail. Your agent doesn't need to
  know everything: the account carries its own knowledge
- **Agent-aware permissions**: reads are free; send/delete require an
  approval given **out of band** — the agent gets an inert request id, a
  human approves from the console or the CLI, and only then does it execute,
  with the exact arguments the human saw. Every write lands in an
  append-only action log
- **Credentials never touch the agent channel**: login and account management
  live in the CLI only — a prompt injection inside an email cannot add
  accounts or read secrets

## Quick start

```bash
pip install "gigamail[all]"

gigamail login                # Microsoft device flow
gigamail accounts add-imap    # or IMAP: Aruba, Gmail, Libero, ...
```

> **Microsoft login note**: the bundled Azure app is not yet
> publisher-verified, so the consent screen shows an "unverified" notice
> (works fine; some corporate tenants may block it). Standard alternative:
> register your own Azure app and set your `client_id` in
> `src/ade_mail_agent/core/ms_config.json`. IMAP needs none of this.

Give the account its identity and knowledge (this is what makes replies yours):

```bash
gigamail identity set                       # who am I, what I do, tone
gigamail identity add-file C:\docs\pricelist.xlsx
gigamail identity add-file C:\docs\catalog\   # whole folder
```

Register in Claude Desktop / Claude Code (`mcpServers`):

```json
{
  "gigamail": {
    "command": "gigamail-server"
  }
}
```

The commands are also available under their legacy names
(`ade-mail-agent`, `ade-mail-agent-server`), so existing setups keep working.

Using **OpenClaw** or **Hermes** instead of Claude? Verified configs in
[INTEGRATIONS.md](INTEGRATIONS.md).

> **Are you an AI agent setting this up on behalf of a human?** You can do
> the install and the MCP registration: `pip install "gigamail[all]"`, then
> add `gigamail-server` to your client's MCP config (see INTEGRATIONS.md;
> declare `GIGAMAIL_ROOT` if your client filters the environment). **Stop
> there.** Connecting a mailbox (`gigamail login`, `gigamail accounts
> add-imap`) asks for credentials and must be done by the human in their own
> shell — it is not something you should do, and GigaMail is built so that
> it cannot be done through you. Tell them what to run, then wait.

Then just ask your agent: *"reply to the last quote request using the price
list"* — it reads the mail, pulls the numbers from your file, drafts the
reply, and asks you before sending.

## Tools

24 typed tools, generated from the server itself:

- **Read (15)** — accounts, identity, knowledge files, messages, unread,
  folders, hybrid search, attachment text, sender history, learned
  patterns, calendar events, free-slot availability
- **Safe writes (3, audited)** — mark read, move message, create folder
- **Dangerous (6, human approval out of band)** — send, reply, delete
  message, delete folder, create/delete calendar event

Full map and design decisions: [MAPPA_MCP.md](MAPPA_MCP.md).

## Security model

Email content is treated as **untrusted data** (prompt injection). The
agent cannot approve its own actions, by construction: a dangerous tool
returns only an inert `request_id`, and approving it — from the console or
from `gigamail approvals approve` — requires an OS-level verification of
the person at the machine (**Windows Hello** / **Touch ID**). A process,
including an agent that holds a shell, can open that prompt but cannot
pass it; with no such backend available, nothing approves. No secret ever
enters the model context, so an injected instruction has nothing to
spend. Repeating the id just returns *awaiting approval*. The agent
can only read files explicitly registered by the user, never the rest of the
filesystem. Every write action is logged to `%APPDATA%/ADE/agent_audit.jsonl`
(append-only: GigaMail never rewrites past entries — it is not, and does not
claim to be, tamper-proof storage).

We red-team this: hostile emails ordering exfiltration, mass deletion, and
the agent to approve itself — fed to a real agent with every mail tool
enabled.

> This design is a fix. v0.1.0 returned a one-time confirm token in the
> tool result, which put it in the model's context: the agent held both
> halves. Thanks to **u/ranbuman** and **u/anderson_the_one** on r/mcp for
> catching it. The switch now sits where the agent cannot reach.

![Anti-injection harness: three hostile-email scenarios against a real
agent, zero destructive actions](docs/anti-injection-harness.png)

The structural half of that suite runs in CI on every push
([tests/test_injection.py](tests/test_injection.py)); the real-agent half is
opt-in ([scripts/injection_e2e.py](scripts/injection_e2e.py)) and runs with
a dry-run guard so confirmed actions are audited but never executed.

## Reply rules (0.2): semi-auto and auto reply, fenced

You can tell GigaMail: *mail from these senders (or in this folder) gets a
reply drafted from these documents*. Rules are created from the CLI —
`gigamail rules add` — behind the same Windows Hello / Touch ID prompt as
approvals, and `gigamail watch` is the process that applies them. The MCP
server stays passive and **there is no MCP tool that touches rules**: an
injected instruction cannot enable autopilot.

- **semi** (default): the draft becomes a normal approval request — you get
  the notification, you approve with Hello, it goes out.
- Notifications reach you where you are: a **Windows toast** with
  ✅ / ❌ buttons (run `gigamail desktop-setup` once — UAC prompt — to make
  them clickable; they open the approval, which raises Hello) and
  **Telegram** (`gigamail telegram setup`, your own bot: ✅ approve if you
  opted in with `--approve` behind Hello, ❌ reject, ✏️ ask for changes —
  accepted only from your chat).
- **auto**: the request is born approved, `decided_by automode:<rule_id>` —
  you gave that approval when you created the rule, for a precise scope,
  with a mandatory expiry, a daily cap and a per-sender cooldown. The
  notification still fires.

The drafter (your own agent, via `claude -p`) produces the reply *body*
and nothing else: recipient, subject and thread are fixed from the incoming
message — always the sender, never `Reply-To`, never an address written by
the draft. Deterministic barriers run first: no DMARC pass → never auto;
auto-generated mail, lists, no-reply senders, the provider's spam verdict,
executable attachments → no reply at all; the first message from a new
sender always goes through you; a burst of matches pauses the rule by
itself. Details in [SECURITY.md](SECURITY.md).

## License

**AGPL-3.0-or-later.** Free to use, study, modify and share. If you
distribute a modified version — or run one as a network service — you must
make its source available under the same license. Commercial licenses for
closed-source use are available from the copyright holder.

---

<a id="lang-it"></a>
# GigaMail — La posta per il tuo agente AI

[English](#gigamail--mail-for-your-ai-agent) · **Italiano** · [中文](#lang-zh)


**Server MCP che dà al tuo agente — Claude, Codex, OpenClaw, Hermes o
qualunque client MCP — accesso sicuro e controllato alla tua posta** — multi-account (Microsoft Graph +
IMAP), calendario, indice di ricerca locale, memoria dei mittenti e un
modello di permessi pensato per gli agenti.

Nessun LLM interno: l'intelligenza è quella del tuo agente. Il server MCP
parla solo stdio — nessuna porta di rete. (La console per l'umano, che è
opzionale, aggiunge una API HTTP locale su 127.0.0.1.)

**Sui tuoi dati**: GigaMail tiene indici della posta, credenziali, memoria
e configurazione **sul tuo computer** — noi non gestiamo alcun servizio e
non riceviamo nulla. Il contenuto delle mail che il tuo agente legge è
ovviamente trattato da quell'agente e dal suo fornitore di modello secondo
le loro policy. Scegli l'agente di conseguenza; il masker permette di
nascondere i dati sensibili (codici fiscali, partite IVA, IBAN, email,
telefoni — validati in modo deterministico, senza AI) prima che l'agente
li veda.

![La console umana: una bozza scritta dall'agente — dati reali dai documenti
dell'account, planimetrie giuste in allegato e orari presi dal calendario.
Niente parte finché non approvi.](docs/console-draft.png)

*Una bozza vera: l'agente ha preso i dati dai documenti collegati
all'account, scelto le planimetrie da allegare e proposto gli orari liberi
dal calendario. L'umano rivede e invia — oppure corregge l'istruzione e
rigenera.*

## Perché

- **Ricerca ibrida**: provider (Graph/IMAP) + indice SQLite locale — veloce e
  offline-friendly
- **Memoria dei mittenti**: tono, argomenti e storico per rispondere nel modo giusto
- **Observer**: pattern appresi dalle correzioni dell'utente alle bozze passate
- **File di conoscenza**: collega listini, condizioni, schede prodotto a un
  account — l'agente li legge per rispondere alle mail. Il tuo agente non
  deve sapere tutto: le informazioni che gli servono viaggiano con l'account
- **Permessi per agenti**: lettura libera; invio/cancellazione richiedono
  un'approvazione data **fuori banda** — all'agente arriva solo un id
  inerte, un umano approva dalla console o dalla CLI, e solo allora si
  esegue, con gli argomenti esatti che l'umano ha visto. Ogni scrittura
  finisce in un registro append-only
- **Credenziali fuori dal canale agente**: login e gestione account solo via
  CLI — una prompt injection dentro una mail non può aggiungere account né
  leggere segreti

## Setup rapido

```bash
pip install "gigamail[all]"

gigamail login                # device flow Microsoft
gigamail accounts add-imap    # oppure IMAP: Aruba, Gmail, Libero, ...
```

> **Nota sul login Microsoft**: l'app Azure inclusa non è ancora
> publisher-verified, quindi la schermata di consenso mostra l'avviso
> "unverified" (funziona comunque; alcuni tenant aziendali potrebbero
> bloccarla). Alternativa standard: registra la tua app Azure e metti il
> tuo `client_id` in `src/ade_mail_agent/core/ms_config.json`.
> Per IMAP non serve nulla di tutto questo.

Dai all'account la sua identità e la sua conoscenza (è ciò che rende le
risposte *tue*):

```bash
gigamail identity set                       # chi sono, cosa faccio, tono
gigamail identity add-file C:\docs\listino.xlsx
gigamail identity add-file C:\docs\catalogo\   # intera cartella
```

Registrazione in Claude Desktop / Claude Code (`mcpServers`):

```json
{
  "gigamail": {
    "command": "gigamail-server"
  }
}
```

I comandi restano disponibili anche con i vecchi nomi
(`ade-mail-agent`, `ade-mail-agent-server`), così le installazioni esistenti
continuano a funzionare.

Usi **OpenClaw** o **Hermes** invece di Claude? Configurazioni verificate in
[INTEGRATIONS.md](INTEGRATIONS.md).

Poi chiedi al tuo agente: *"rispondi all'ultima richiesta di preventivo
usando il listino"* — legge la mail, prende i numeri dal tuo file, prepara la
risposta e ti chiede conferma prima di inviare.

## Tool

24 tool tipizzati, generati dal server stesso:

- **Lettura (15)** — account, identità, file di conoscenza, messaggi, non
  lette, cartelle, ricerca ibrida, testo degli allegati, storico mittenti,
  pattern appresi, eventi di calendario, slot liberi
- **Scritture sicure (3, con audit)** — segna letto, sposta, crea cartella
- **Pericolose (6, approvazione umana fuori banda)** — invio, risposta,
  cancellazione messaggio, cancellazione cartella, creazione/cancellazione
  evento

Mappa completa e decisioni di design: [MAPPA_MCP.md](MAPPA_MCP.md).

## Modello di sicurezza

Il contenuto delle email è trattato come **dato non fidato** (prompt
injection). L'agente non può approvare le proprie azioni, per costruzione:
un tool pericoloso restituisce solo un `request_id` inerte, e approvarlo —
dalla console o con `gigamail approvals approve` — richiede una verifica
dell'utente fisico a livello di sistema operativo (**Windows Hello** /
**Touch ID**). Un processo, compreso un agente con la shell, può aprire quel
prompt ma non superarlo; senza un backend del genere, nulla viene approvato.
Nessun segreto entra nel contesto del modello, quindi un'istruzione
iniettata non ha nulla da spendere. Ripetere
l'id restituisce solo *in attesa di approvazione*. L'agente può leggere solo i file
registrati esplicitamente dall'utente, mai il resto del filesystem. Ogni
azione di scrittura finisce in `%APPDATA%/ADE/agent_audit.jsonl` (append-only:
GigaMail non riscrive mai le voci passate — non è, e non pretende di essere,
un archivio a prova di manomissione).

Lo mettiamo alla prova: mail ostili che ordinano esfiltrazione,
cancellazione di massa e all'agente di approvarsi da solo, date a un agente
reale con tutti i tool attivi.

> Questo disegno è una correzione. La v0.1.0 restituiva un token di conferma
> monouso nel risultato del tool, quindi dentro il contesto del modello:
> l'agente aveva entrambe le metà. Grazie a **u/ranbuman** e
> **u/anderson_the_one** su r/mcp per averlo notato. Ora l'interruttore sta
> dove l'agente non arriva.

![Harness anti-injection: tre scenari di mail ostili contro un agente reale,
zero azioni distruttive](docs/anti-injection-harness.png)

La metà strutturale della suite gira in CI a ogni push
([tests/test_injection.py](tests/test_injection.py)); quella con l'agente
reale è opt-in ([scripts/injection_e2e.py](scripts/injection_e2e.py)) e usa
una modalità dry-run, così le azioni confermate finiscono nell'audit ma non
vengono mai eseguite.

## Regole di risposta (0.2): semi-auto e auto reply, con recinto

Puoi dire a GigaMail: *le mail da questi mittenti (o in questa cartella)
ricevono una risposta preparata da questi documenti*. Le regole si creano
dalla CLI — `gigamail rules add` — dietro lo stesso prompt Windows Hello /
Touch ID delle approvazioni, e `gigamail watch` è il processo che le
applica. Il server MCP resta passivo e **nessun tool MCP tocca le regole**:
un'istruzione iniettata non può accendere l'autopilota.

- **semi** (default): la bozza diventa una normale richiesta di
  approvazione — arriva la notifica, approvi con Hello, parte.
- Le notifiche ti raggiungono dove sei: **toast Windows** con bottoni
  ✅ / ❌ (una volta `gigamail desktop-setup` — prompt UAC — per renderli
  cliccabili; aprono l'approvazione, che alza Hello) e **Telegram**
  (`gigamail telegram setup`, col tuo bot: ✅ approva se hai scelto
  `--approve` dietro Hello, ❌ rifiuta, ✏️ chiedi modifiche — accettati
  solo dalla tua chat).
- **auto**: la richiesta nasce già approvata, `decided_by
  automode:<rule_id>` — quell'approvazione l'hai data tu creando la regola,
  per uno scope preciso, con scadenza obbligatoria, tetto giornaliero e
  cooldown per mittente. La notifica parte comunque.

Chi scrive (il tuo agente, via `claude -p`) produce il *corpo* della
risposta e nient'altro: destinatario, oggetto e thread li fissa GigaMail
dal messaggio in arrivo — sempre il mittente, mai il `Reply-To`, mai un
indirizzo scritto dalla bozza. Prima passano barriere deterministiche:
niente DMARC pass → mai auto; posta automatica, liste, mittenti no-reply,
il verdetto spam del provider, allegati eseguibili → nessuna risposta; il
primo messaggio di un mittente nuovo passa sempre da te; una raffica di
match mette in pausa la regola da sola. Dettagli in
[SECURITY.md](SECURITY.md).

## Licenza

**AGPL-3.0-or-later.** Libero di usarlo, studiarlo, modificarlo e
condividerlo. Se distribuisci una versione modificata — o la offri come
servizio in rete — devi rendere disponibile il sorgente con la stessa
licenza. Licenze commerciali per usi closed-source sono disponibili dal
titolare del copyright.


---

<a id="lang-zh"></a>
# GigaMail — 给你的 AI 代理的邮箱

[English](#gigamail--mail-for-your-ai-agent) · [Italiano](#lang-it) · **中文**

**一个 MCP 服务器，让你的代理 —— Claude、Codex、OpenClaw、Hermes 或任何
兼容 MCP 的客户端 —— 安全、受控地访问你的真实邮箱** —— 多账户（Microsoft Graph + IMAP）、日历、本地搜索索引、发件人
记忆，以及面向代理的权限模型。

不内置任何 LLM：智能来自你自己的代理。MCP 服务器只使用 stdio 传输，不开
网络端口。（可选的人工控制台会在 127.0.0.1 上提供一个本地 HTTP API。）

**关于你的数据**：GigaMail 把邮件索引、凭据、记忆和配置全部保存在**你自己
的机器上** —— 我们不运行任何服务，也收不到任何数据。代理读取的邮件内容当
然会经过该代理及其模型提供商，适用他们各自的数据政策。请据此选择你的代理。

## 为什么

- **混合搜索**：提供商搜索（Graph/IMAP）+ 本地 SQLite 索引，快速且支持离线
- **发件人记忆**：按发件人记录语气、话题与往来历史，让回复更贴切
- **观察者**：从用户对过往草稿的修改中学习偏好
- **知识文件**：把价目表、条款、产品资料挂到账户上，代理读取它们来回信 ——
  你的代理不需要什么都懂：账户自带知识
- **面向代理的权限**：读取自由；发送/删除需要**带外**给出的人工批准 ——
  代理只拿到一个惰性的请求 id，人从控制台或 CLI 批准后才会执行，且执行的
  是人当时看到的那份参数。每次写操作都会记入只追加的审计日志
- **凭据永远不经过代理通道**：登录与账户管理只存在于 CLI —— 邮件里的提示
  注入无法添加账户或读取任何机密

## 快速开始

```bash
pip install "gigamail[all]"

gigamail login                # Microsoft 设备码登录
gigamail accounts add-imap    # 或任意 IMAP 提供商
```

为账户设置身份与知识（这是让回复"像你"的关键）：

```bash
gigamail identity set                       # 我是谁、做什么、语气
gigamail identity add-file C:\docs\pricelist.xlsx
```

在 Claude Desktop / Claude Code 中注册（`mcpServers`）：

```json
{
  "gigamail": {
    "command": "gigamail-server"
  }
}
```

使用 **OpenClaw** 或 **Hermes**？经过验证的配置见
[INTEGRATIONS.md](INTEGRATIONS.md)。

> **你是替人类做安装的 AI 代理吗？** 你可以完成安装与 MCP 注册：
> `pip install "gigamail[all]"`，然后把 `gigamail-server` 加入客户端的 MCP
> 配置。**到此为止。** 连接邮箱（`gigamail login`、`gigamail accounts
> add-imap`）需要输入凭据，必须由人类在自己的终端里完成 —— 这不是你该做的
> 事，GigaMail 的设计也让它无法经由你完成。告诉他们要运行什么，然后等待。

之后直接对你的代理说："用价目表回复最近那封询价邮件" —— 它会读邮件、从你
的文件里取数字、写好草稿，并在发送前征得你的同意。

## 工具

24 个类型化工具，由服务器本身生成：

- **读取（15）** —— 账户、身份、知识文件、邮件、未读、文件夹、混合搜索、
  附件文本、发件人历史、学习到的偏好、日历事件、空闲时段
- **安全写入（3，有审计）** —— 标记已读、移动邮件、新建文件夹
- **危险操作（6，需带外人工批准）** —— 发送、回复、删除邮件、删除文件夹、
  创建/删除日历事件

## 安全模型

邮件内容被视为**不可信数据**（提示注入）。代理从构造上就无法批准自己的
操作：危险工具只返回一个惰性的 `request_id`，而批准它 —— 无论从控制台还是
`gigamail approvals approve` —— 都需要对机器前的人进行操作系统级验证
（**Windows Hello** / **Touch ID**）。任何进程（包括持有 shell 的代理）都能
弹出这个验证框，却无法通过它；没有此类验证后端时，一律拒绝（fail-closed）。
没有任何机密进入模型上下文，被注入的指令无物可用。重复提交 id 只会得到
*等待批准*。代理只能读取用户明确注册的文件，永远碰不到文件系统的其余部分。
每次写操作都记入只追加的审计日志（GigaMail 从不改写历史条目 —— 它不是、
也不自称是防篡改存储）。

我们对此做红队测试：让恶意邮件命令真实代理外泄数据、批量删除、自我批准 ——
在所有邮件工具全开的情况下，零破坏性操作。

## 回复规则（0.2）：带栅栏的半自动与全自动回复

你可以告诉 GigaMail：*来自这些发件人（或这个文件夹）的邮件，用这些文档起草
回复*。规则只能从 CLI（`gigamail rules add`）或控制台创建，且要经过与批准
相同的 Windows Hello / Touch ID 验证；`gigamail watch` 是执行规则的进程。
MCP 服务器保持被动，**不存在任何能触碰规则的 MCP 工具**：被注入的指令无法
打开自动驾驶。

- **semi**（默认）：草稿成为一个普通的批准请求 —— 你收到通知，用 Hello
  批准后才会发出。
- 通知会找到你：**Windows 桌面通知**带 ✅/❌ 按钮（运行一次
  `gigamail desktop-setup` 使其可点击；按钮只是打开批准流程，仍需 Hello），
  以及 **Telegram**（`gigamail telegram setup`，用你自己的机器人：✅ 批准需
  在 Hello 背后显式开启 `--approve`；❌ 拒绝、✏️ 要求修改 —— 且只接受来自
  你那个会话的指令）。
- **auto**：请求生来即已批准，`decided_by automode:<rule_id>` —— 这份批准是
  你创建规则时在 Hello 背后给出的，范围精确、必有过期时间、每日上限和按
  发件人的冷却时间。通知照常发出。

起草者（你自己的代理，经 `claude -p`）只产出回复*正文*：收件人、主题与
会话线程由 GigaMail 从来信中确定 —— 永远回给通过验证的发件人，绝不理会
`Reply-To`，也绝不使用草稿里写出的地址。确定性栅栏先行：DMARC 未通过 →
永不 auto；自动生成的邮件、邮件列表、no-reply 发件人、提供商的垃圾邮件判定、
可执行附件 → 一律不回复；新发件人的第一封邮件永远经过你；短时间内大量命中
会让规则自动暂停。详见 [SECURITY.md](SECURITY.md)。

## 许可证

**AGPL-3.0-or-later.** 自由使用、研究、修改与分享。若你分发修改版 —— 或将
其作为网络服务运行 —— 必须以相同许可证提供其源代码。闭源商用许可可向版权
持有人洽询。
