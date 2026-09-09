# WOLF15: assessment skill dan interaksi Codex

Tanggal: 2026-09-09. Basis repository: `e3a0d8c83d5d8de60645a1d4f7c00f66fe9d5941`.

Assessment ini mengikat 220 entrypoint dengan SHA-256: 157 skill global dan 63 skill plugin (53 curated-remote serta 10 bundled/runtime). Penilaian menggunakan isi entrypoint, kebutuhan repository, kontrak authority, dependency yang disebutkan, dan pemeriksaan lokal. Ini bukan pengujian 220 workflow atau sertifikasi kesiapan produksi.

Keputusan lengkap per skill, hash sumber, anchor repository, alasan, batas pemanggilan, dependency, dan status bukti ada di [skill-assessment.json](../../.codex/skill-assessment.json). Kebijakan yang dipakai asisten ada di [AGENTS.md](../../AGENTS.md).

## Keputusan pemilihan

| Kategori | Jumlah | Perlakuan di WOLF15 |
| --- | ---: | --- |
| Utama (core) | 17 | Prioritaskan jika cocok dengan tugas; jangan menjalankan seluruhnya sekaligus. |
| Sesuai tugas (conditional) | 145 | Gunakan hanya untuk deliverable yang cocok dan setelah dependency/otorisasi tersedia. |
| Di luar kebutuhan repo (out_of_scope) | 45 | Jangan pilih dalam pekerjaan rutin WOLF15; evaluasi lagi bila cakupan pengguna berubah. |
| Dikarantina (quarantined) | 13 | Hindari pemanggilan; paket menunjuk kontrak/helper yang belum terpasang. Gunakan alternatif yang lengkap. |

Kategori merupakan instruksi pemilihan, bukan status disabled dari runtime. Seluruh instalasi global tetap utuh. Native config mempertahankan discovery; izin menjalankan perintah ditangani terpisah.

## Temuan yang mengubah rancangan

1. Banyak router/coordinator mengulang workflow yang sama. Pilih satu pemilik pekerjaan: explorer untuk discovery, coder untuk implementasi, reviewer/tester untuk verifikasi. Keberadaan puluhan coordinator tidak menjadi alasan memulai swarm.
2. Tiga belas paket global hanya memuat SKILL.md tetapi merujuk kontrak/helper yang tidak ada. Kesesuaian nama skill tidak membuktikan paket lengkap. Fallback menggunakan entrypoint yang lengkap dan kontrak repository, bukan rekonstruksi referensi yang hilang.
3. audit-wolf15-constitution masih menyatakan zona gabungan Risk/Dashboard memiliki persetujuan risiko dan lot size. Ini bertentangan dengan selected frontend sebagai viewer. Skill tersebut dikarantina; gunakan wolf15-authority-boundary-review dan kontrak kode terbaru.
4. evaluate-agent-skill memiliki evaluator utama, tetapi jalur koleksi mindmap merujuk references/harness-contract.md dan scripts/collect_skill_evidence.py yang tidak ditemukan. Jangan menyatakan seluruh evaluator hilang; jalur yang membutuhkan kedua file itu tidak tersedia.
5. petakan-konsep memiliki deskripsi terpotong dan catatan PASS_LOCAL yang harus dibaca bersama kontrak evaluator terbaru: attestation masih UNATTESTED. Formal common-skill/v1 membutuhkan collector behavior/safety yang terikat; skor tidak dibuat dari hasil baca entrypoint.
6. Sites/scaffolding hosted, seluruh Remotion, SwiftUI, pembayaran, TimeRally, serta framework database/agent tertentu tidak cocok sebagai default repo ini. PostgreSQL/JWT tidak otomatis berarti Supabase; nama agent tidak otomatis berarti OpenAI Agents SDK atau kebutuhan API key baru.
7. Wrapper Figma tetap conditional untuk tool Figma terkait. Routing Google Docs yang umum dan khusus perlu direkonsiliasi terhadap tugas aktual. Skill native computer-use tidak membuktikan tool native tersedia atau memberikan authority broker.

## Paket yang dikarantina dan rute pengganti

| Paket | Gap sumber | Alternatif sesuai tugas |
| --- | --- | --- |
| `agent-arch-system-design` | `references/source-and-evidence-contract.md`, `references/c4-model-contract.md`, `references/adr-template.md`, `references/architecture-deliverable-contract.md` | agent-architecture / agent-reviewer; arsitektur repo |
| `agent-benchmark-suite` | `scripts/run_local_benchmark.py`, `references/benchmark-contract.md` | agent-performance-analyzer; benchmark lokal yang sudah ada |
| `agent-code-analyzer` | `references/finding-contract.md`, `references/evidence-and-coverage.md`, `references/output-template.md`, `references/tool-routing.md`, `scripts/analyze_python.py` | agent-reviewer / github-code-review |
| `agent-code-goal-planner` | `references/goap-plan-contract.md`, `scripts/validate_goap_plan.py` | agent-planner; rencana berbasis source |
| `analyze-tuyul-kartel-fx` | `references/data-safety-contract.md`, `references/analysis-methodology.md`, `references/output-contract.md`, `scripts/calculate_trade_risk.py` | wolf15-replay-audit; kontrak data repo |
| `audit-wolf15-constitution` | `references/authority-model.md`, `references/evidence-contract.md`, `references/pipeline-contract.md`, `references/decision-envelope.md`, `scripts/validate_audit_envelope.py` | wolf15-authority-boundary-review |
| `extract-agent-workflow` | `references/safety.md`, `references/input-formats.md`, `references/contracts.md`, `references/method.md`, `scripts/inventory_sources.py`, `scripts/validate_pipeline.py`, `scripts/validate_candidate.py`, `scripts/operator_package.py` | agent-researcher; ekstraksi terbatas tanpa promosi skill |
| `github-multi-repo` | `references/authority-model.md`, `references/capability-routing.md`, `references/manifest-contract.md`, `references/local-audit-contract.md`, `scripts/audit_repo_set.py`, `scripts/validate_governance_envelope.py` | agent-github-pr-manager per repo terotorisasi |
| `global-development-instruction` | `references/authority-and-precedence.md`, `references/toolchain-routing.md`, `references/workflow-contract.md`, `references/verification-evidence-contract.md`, `references/security-cicd-multirepo-boundaries.md`, `scripts/repository_probe.py`, `scripts/static_triage.py` | AGENTS.md dan native tools |
| `mindmap-reasoning` | `references/method-and-map-types.md`, `references/evidence-and-uncertainty.md`, `references/output-contracts.md`, `references/security-and-authority.md`, `scripts/validate_mindmap.py` | agent-planner; peta bukti berbasis source |
| `neural-orchestrator` | `references/contracts-and-statuses.md`, `references/routing-and-aggregation.md`, `references/evidence-and-provenance.md`, `references/advisory-learning-and-authority.md`, `scripts/plan_orchestration.py` | agent-coordination untuk delegasi terotorisasi |
| `trace-agent-runtime-flow` | `references/trace-method.md`, `references/evidence-contract.md`, `references/output-contract.md` | agent-reviewer + wolf15-authority-boundary-review |
| `wolf-arsenal-toolkit` | `references/input-evidence-contract.md`, `references/toolkit-methods.md`, `references/scoring-status-output-contract.md`, `references/routing-authority.md`, `scripts/score_toolkit_packet.py` | agent-researcher / agent-reviewer sesuai metode |

Pemulihan paket global memerlukan source lengkap yang benar dan verifikasi ulang. Assessment ini tidak mengunduh, menebak, atau mengubah paket global.

## Penyesuaian konfigurasi

- AGENTS.md mengikat routing ke pipeline, kontrak, risk firewall, dashboard viewer, dan bukti repository; otorisasi yang sudah diberikan pengguna tetap dihormati.
- Enam kelompok aturan prompt menggantikan 19 auto-allow: interpreter Python, shell, Railway, Git, GitHub CLI, dan klien infrastruktur/database. Aturan tidak memberi akses otomatis hanya karena skill tersedia.
- settings.local.json menjadi referensi inert dengan allow kosong. Codex tetap memakai config.toml dan rules; konfigurasi Claude yang terpisah tidak diedit.
- .dockerignore mengecualikan .codex/, .agents/, .claude/, dan settings.local.json. Direktori aplikasi agents/ tetap tersedia untuk build.

Uji 58 selector nama pada project config menghasilkan config/read yang benar tetapi skills/list masih 167 enabled. Override CLI satu nama berhasil. Karena scope perilaku itu belum berlaku pada jalur project yang diuji, selector tersebut dihapus dari hasil akhir. AGENTS.md adalah instruksi pemilihan, bukan pemblokiran runtime; tidak ada klaim semua skill nonprioritas dinonaktifkan secara teknis.

Mode sandbox/approval tetap dikendalikan host. Dalam mode approval never, prompt bukan jaminan dialog konfirmasi. Path executable absolut, interpreter alternatif, SDK, dan MCP memiliki boundary sendiri. Uji no-match tidak berarti tindakan diblokir.

## Bukti verifikasi

| Pemeriksaan | Hasil dan batasnya |
| --- | --- |
| Identitas sumber | 220/220 hash entrypoint diperiksa ulang; seluruh anchor repository ada pada base yang dicatat. |
| Authoring lint | 195 sesuai konvensi; 25 perbedaan metadata vendor (huruf kapital/field Figma/Remotion). Ini bukan 25 kegagalan runtime. |
| Config runtime | Native config berasal dari project; zero disabled layers. |
| Katalog standalone | 167/167 enabled, zero parse errors; global packages tidak berubah. |
| Plugin desktop remote | 53 entrypoint dinilai terpisah; efektivitas runtime/dependency eksternal tidak diukur. |
| Aturan perintah | 38 pemeriksaan nonexecuting lulus, termasuk alias, trailing args, dan prompt mengalahkan synthetic global allow. Tidak ada target command dijalankan. |
| Konteks Docker | Pola pengecualian dan konteks source diperiksa; image tidak dibangun. |
| Formal evaluator / semua workflow | NOT_EXECUTED; quality_index null. Tidak ada attestation atau PASS_LOCAL untuk paket skill. |
| CI / deploy / broker untuk perubahan ini | NOT_EXECUTED. |

Referensi/helper plugin tidak diaudit menyeluruh. Sumber paket yang berubah, dependency baru, atau perubahan topology memerlukan assessment ulang. Jangan memakai angka inventory sebagai bukti profitabilitas, keamanan produksi, ataupun keberhasilan broker.

## Matriks seluruh skill

Alasan di bawah adalah penilaian kecocokan yang dapat ditinjau ulang; detail sumber dan dependency ada pada JSON.

| Skill | Kategori | Alasan |
| --- | --- | --- |
| `agent-adaptive-coordinator` | conditional | Independent architecture, implementation, testing and review tasks may justify a small specialist team. These are agent coordination choices, not evidence that WOLF15 itself runs that topology. |
| `agent-agent` | conditional | Useful alternative for a specifically requested planning, SPARC, refactor, or interactive coding deliverable. The preferred core routes already cover ordinary repository work; loading parallel aliases adds process and overlapping instructions. |
| `agent-agentic-payments` | out_of_scope | Payment mandates, provider settlement, app-store publishing, React Native and Time Rally navigation have no direct requested role in this Python/Next.js WOLF15 repository. Broker execution is not a generic payment workflow. |
| `agent-analyze-code-quality` | conditional | Useful alternative for a specifically requested planning, SPARC, refactor, or interactive coding deliverable. The preferred core routes already cover ordinary repository work; loading parallel aliases adds process and overlapping instructions. |
| `agent-app-store` | out_of_scope | Payment mandates, provider settlement, app-store publishing, React Native and Time Rally navigation have no direct requested role in this Python/Next.js WOLF15 repository. Broker execution is not a generic payment workflow. |
| `agent-arch-system-design` | quarantined | Required package contracts or helpers are absent from this installation. The repository policy quarantines this skill pending source restoration and reassessment. |
| `agent-architecture` | conditional | Useful alternative for a specifically requested planning, SPARC, refactor, or interactive coding deliverable. The preferred core routes already cover ordinary repository work; loading parallel aliases adds process and overlapping instructions. |
| `agent-authentication` | core | Direct fit for FastAPI contracts and bounded viewer login; the selected frontend has server-only direct API reads and must not gain risk or execution controls. |
| `agent-automation-smart-agent` | conditional | Independent architecture, implementation, testing and review tasks may justify a small specialist team. These are agent coordination choices, not evidence that WOLF15 itself runs that topology. |
| `agent-base-template-generator` | conditional | Useful for an explicitly requested reusable fixture/template, evaluation exercise or isolated reproduction; it is not necessary for every edit. |
| `agent-benchmark-suite` | quarantined | Required package contracts or helpers are absent from this installation. The repository policy quarantines this skill pending source restoration and reassessment. |
| `agent-byzantine-coordinator` | out_of_scope | The current authority model is canonical WOLF15 decision flow with Redis/PostgreSQL persistence; the inspected topology establishes no replicated-log, CRDT, gossip or Byzantine protocol requirement. Trading confluence/quorum labels are not distributed consensus proof. |
| `agent-challenges` | conditional | Useful for an explicitly requested reusable fixture/template, evaluation exercise or isolated reproduction; it is not necessary for every edit. |
| `agent-code-analyzer` | quarantined | Required package contracts or helpers are absent from this installation. The repository policy quarantines this skill pending source restoration and reassessment. |
| `agent-code-goal-planner` | quarantined | Required package contracts or helpers are absent from this installation. The repository policy quarantines this skill pending source restoration and reassessment. |
| `agent-code-review-swarm` | conditional | Independent architecture, implementation, testing and review tasks may justify a small specialist team. These are agent coordination choices, not evidence that WOLF15 itself runs that topology. |
| `agent-coder` | core | Preferred engineering route for the mixed Python and Next.js repository: bind current source, preserve user edits, and validate only the changed behavior. Its specific workflow and output below determine which stage to select. |
| `agent-collective-intelligence-coordinator` | conditional | Independent architecture, implementation, testing and review tasks may justify a small specialist team. These are agent coordination choices, not evidence that WOLF15 itself runs that topology. |
| `agent-consensus-coordinator` | out_of_scope | The current authority model is canonical WOLF15 decision flow with Redis/PostgreSQL persistence; the inspected topology establishes no replicated-log, CRDT, gossip or Byzantine protocol requirement. Trading confluence/quorum labels are not distributed consensus proof. |
| `agent-coordination` | conditional | Independent architecture, implementation, testing and review tasks may justify a small specialist team. These are agent coordination choices, not evidence that WOLF15 itself runs that topology. |
| `agent-coordinator-swarm-init` | conditional | Independent architecture, implementation, testing and review tasks may justify a small specialist team. These are agent coordination choices, not evidence that WOLF15 itself runs that topology. |
| `agent-crdt-synchronizer` | out_of_scope | The current authority model is canonical WOLF15 decision flow with Redis/PostgreSQL persistence; the inspected topology establishes no replicated-log, CRDT, gossip or Byzantine protocol requirement. Trading confluence/quorum labels are not distributed consensus proof. |
| `agent-data-ml-model` | conditional | May support explicitly scoped offline feature research, retrieval corpus preparation or graph analysis. The manifests prove numerical dependencies, not a deployed ML/retrieval stack. |
| `agent-dev-backend-api` | core | Direct fit for FastAPI contracts and bounded viewer login; the selected frontend has server-only direct API reads and must not gain risk or execution controls. |
| `agent-docs-api-openapi` | conditional | Useful for documentation drift or explicit claims design around existing API and authorization contracts; neither requires introducing a new authorization platform. |
| `agent-github-modes` | conditional | Relevant only to the specific requested GitHub lifecycle surface. PR creation, project metadata, release publication and CI/CD operations require different effects from ordinary source work. |
| `agent-github-pr-manager` | conditional | Relevant only to the specific requested GitHub lifecycle surface. PR creation, project metadata, release publication and CI/CD operations require different effects from ordinary source work. |
| `agent-goal-planner` | conditional | Useful alternative for a specifically requested planning, SPARC, refactor, or interactive coding deliverable. The preferred core routes already cover ordinary repository work; loading parallel aliases adds process and overlapping instructions. |
| `agent-gossip-coordinator` | out_of_scope | The current authority model is canonical WOLF15 decision flow with Redis/PostgreSQL persistence; the inspected topology establishes no replicated-log, CRDT, gossip or Byzantine protocol requirement. Trading confluence/quorum labels are not distributed consensus proof. |
| `agent-hierarchical-coordinator` | conditional | Independent architecture, implementation, testing and review tasks may justify a small specialist team. These are agent coordination choices, not evidence that WOLF15 itself runs that topology. |
| `agent-implementer-sparc-coder` | conditional | Useful alternative for a specifically requested planning, SPARC, refactor, or interactive coding deliverable. The preferred core routes already cover ordinary repository work; loading parallel aliases adds process and overlapping instructions. |
| `agent-issue-tracker` | conditional | Relevant only to the specific requested GitHub lifecycle surface. PR creation, project metadata, release publication and CI/CD operations require different effects from ordinary source work. |
| `agent-load-balancer` | conditional | Appropriate when a measured worker, numerical, streaming, resource or endurance problem requires the specific method; ordinary correctness changes do not justify benchmarking or persistent processors. |
| `agent-matrix-optimizer` | conditional | Appropriate when a measured worker, numerical, streaming, resource or endurance problem requires the specific method; ordinary correctness changes do not justify benchmarking or persistent processors. |
| `agent-memory-coordinator` | conditional | Historical project context and provenance-preserving handoff can aid Codex, but Codex memory is distinct from WOLF15 runtime state and its journals. |
| `agent-mesh-coordinator` | conditional | Independent architecture, implementation, testing and review tasks may justify a small specialist team. These are agent coordination choices, not evidence that WOLF15 itself runs that topology. |
| `agent-migration-plan` | conditional | Useful alternative for a specifically requested planning, SPARC, refactor, or interactive coding deliverable. The preferred core routes already cover ordinary repository work; loading parallel aliases adds process and overlapping instructions. |
| `agent-multi-repo-swarm` | conditional | Cross-repository SignalThrottle, WOLF SIGMA or learning-plane work can require exact provider/consumer revisions, but single-repository changes need no multi-repo framework. |
| `agent-neural-network` | conditional | May support explicitly scoped offline feature research, retrieval corpus preparation or graph analysis. The manifests prove numerical dependencies, not a deployed ML/retrieval stack. |
| `agent-ops-cicd-github` | conditional | Relevant only to the specific requested GitHub lifecycle surface. PR creation, project metadata, release publication and CI/CD operations require different effects from ordinary source work. |
| `agent-orchestrator-task` | conditional | Useful alternative for a specifically requested planning, SPARC, refactor, or interactive coding deliverable. The preferred core routes already cover ordinary repository work; loading parallel aliases adds process and overlapping instructions. |
| `agent-pagerank-analyzer` | conditional | May support explicitly scoped offline feature research, retrieval corpus preparation or graph analysis. The manifests prove numerical dependencies, not a deployed ML/retrieval stack. |
| `agent-payments` | out_of_scope | Payment mandates, provider settlement, app-store publishing, React Native and Time Rally navigation have no direct requested role in this Python/Next.js WOLF15 repository. Broker execution is not a generic payment workflow. |
| `agent-performance-analyzer` | core | Direct fit for latency/backpressure diagnostics and bounded worker contracts around pressure, evidence and execution delivery. Work must preserve idempotency and safety gates. |
| `agent-performance-benchmarker` | conditional | Appropriate when a measured worker, numerical, streaming, resource or endurance problem requires the specific method; ordinary correctness changes do not justify benchmarking or persistent processors. |
| `agent-performance-monitor` | conditional | Appropriate when a measured worker, numerical, streaming, resource or endurance problem requires the specific method; ordinary correctness changes do not justify benchmarking or persistent processors. |
| `agent-performance-optimizer` | conditional | Appropriate when a measured worker, numerical, streaming, resource or endurance problem requires the specific method; ordinary correctness changes do not justify benchmarking or persistent processors. |
| `agent-planner` | conditional | Useful alternative for a specifically requested planning, SPARC, refactor, or interactive coding deliverable. The preferred core routes already cover ordinary repository work; loading parallel aliases adds process and overlapping instructions. |
| `agent-pr-manager` | core | Direct fit for exact-head review, GitHub checks and release evidence in a repository where runtime acceptance and runnerless CI must remain separate from local validation. |
| `agent-production-validator` | core | Direct fit for exact-head review, GitHub checks and release evidence in a repository where runtime acceptance and runnerless CI must remain separate from local validation. |
| `agent-project-board-sync` | conditional | Relevant only to the specific requested GitHub lifecycle surface. PR creation, project metadata, release publication and CI/CD operations require different effects from ordinary source work. |
| `agent-pseudocode` | conditional | Useful alternative for a specifically requested planning, SPARC, refactor, or interactive coding deliverable. The preferred core routes already cover ordinary repository work; loading parallel aliases adds process and overlapping instructions. |
| `agent-queen-coordinator` | conditional | Independent architecture, implementation, testing and review tasks may justify a small specialist team. These are agent coordination choices, not evidence that WOLF15 itself runs that topology. |
| `agent-quorum-manager` | out_of_scope | The current authority model is canonical WOLF15 decision flow with Redis/PostgreSQL persistence; the inspected topology establishes no replicated-log, CRDT, gossip or Byzantine protocol requirement. Trading confluence/quorum labels are not distributed consensus proof. |
| `agent-raft-manager` | out_of_scope | The current authority model is canonical WOLF15 decision flow with Redis/PostgreSQL persistence; the inspected topology establishes no replicated-log, CRDT, gossip or Byzantine protocol requirement. Trading confluence/quorum labels are not distributed consensus proof. |
| `agent-refinement` | conditional | Useful alternative for a specifically requested planning, SPARC, refactor, or interactive coding deliverable. The preferred core routes already cover ordinary repository work; loading parallel aliases adds process and overlapping instructions. |
| `agent-release-manager` | conditional | Relevant only to the specific requested GitHub lifecycle surface. PR creation, project metadata, release publication and CI/CD operations require different effects from ordinary source work. |
| `agent-release-swarm` | conditional | Independent architecture, implementation, testing and review tasks may justify a small specialist team. These are agent coordination choices, not evidence that WOLF15 itself runs that topology. |
| `agent-repo-architect` | conditional | Useful alternative for a specifically requested planning, SPARC, refactor, or interactive coding deliverable. The preferred core routes already cover ordinary repository work; loading parallel aliases adds process and overlapping instructions. |
| `agent-researcher` | conditional | Useful alternative for a specifically requested planning, SPARC, refactor, or interactive coding deliverable. The preferred core routes already cover ordinary repository work; loading parallel aliases adds process and overlapping instructions. |
| `agent-resource-allocator` | conditional | Appropriate when a measured worker, numerical, streaming, resource or endurance problem requires the specific method; ordinary correctness changes do not justify benchmarking or persistent processors. |
| `agent-reviewer` | core | Preferred engineering route for the mixed Python and Next.js repository: bind current source, preserve user edits, and validate only the changed behavior. Its specific workflow and output below determine which stage to select. |
| `agent-safla-neural` | out_of_scope | These workflows explicitly require AgentDB, ReasoningBank, Flow Nexus, SAFLA or SONA. The inspected repository manifests do not establish those dependencies; current Redis/PostgreSQL storage does not imply them. |
| `agent-sandbox` | conditional | Useful for an explicitly requested reusable fixture/template, evaluation exercise or isolated reproduction; it is not necessary for every edit. |
| `agent-scout-explorer` | core | Preferred engineering route for the mixed Python and Next.js repository: bind current source, preserve user edits, and validate only the changed behavior. Its specific workflow and output below determine which stage to select. |
| `agent-security-manager` | conditional | Security review is relevant at actual auth, command, distributed trust or data boundaries; it should not turn every edit into a full scan. Use dedicated Codex Security when that scan is requested. |
| `agent-sona-learning-optimizer` | out_of_scope | These workflows explicitly require AgentDB, ReasoningBank, Flow Nexus, SAFLA or SONA. The inspected repository manifests do not establish those dependencies; current Redis/PostgreSQL storage does not imply them. |
| `agent-sparc-coordinator` | conditional | Useful alternative for a specifically requested planning, SPARC, refactor, or interactive coding deliverable. The preferred core routes already cover ordinary repository work; loading parallel aliases adds process and overlapping instructions. |
| `agent-spec-mobile-react-native` | out_of_scope | Payment mandates, provider settlement, app-store publishing, React Native and Time Rally navigation have no direct requested role in this Python/Next.js WOLF15 repository. Broker execution is not a generic payment workflow. |
| `agent-specification` | conditional | Useful alternative for a specifically requested planning, SPARC, refactor, or interactive coding deliverable. The preferred core routes already cover ordinary repository work; loading parallel aliases adds process and overlapping instructions. |
| `agent-swarm` | conditional | Independent architecture, implementation, testing and review tasks may justify a small specialist team. These are agent coordination choices, not evidence that WOLF15 itself runs that topology. |
| `agent-swarm-issue` | conditional | Independent architecture, implementation, testing and review tasks may justify a small specialist team. These are agent coordination choices, not evidence that WOLF15 itself runs that topology. |
| `agent-swarm-memory-manager` | conditional | Historical project context and provenance-preserving handoff can aid Codex, but Codex memory is distinct from WOLF15 runtime state and its journals. |
| `agent-swarm-pr` | conditional | Independent architecture, implementation, testing and review tasks may justify a small specialist team. These are agent coordination choices, not evidence that WOLF15 itself runs that topology. |
| `agent-sync-coordinator` | conditional | Cross-repository SignalThrottle, WOLF SIGMA or learning-plane work can require exact provider/consumer revisions, but single-repository changes need no multi-repo framework. |
| `agent-tdd-london-swarm` | conditional | Independent architecture, implementation, testing and review tasks may justify a small specialist team. These are agent coordination choices, not evidence that WOLF15 itself runs that topology. |
| `agent-test-long-runner` | conditional | Appropriate when a measured worker, numerical, streaming, resource or endurance problem requires the specific method; ordinary correctness changes do not justify benchmarking or persistent processors. |
| `agent-tester` | core | Preferred engineering route for the mixed Python and Next.js repository: bind current source, preserve user edits, and validate only the changed behavior. Its specific workflow and output below determine which stage to select. |
| `agent-topology-optimizer` | conditional | Independent architecture, implementation, testing and review tasks may justify a small specialist team. These are agent coordination choices, not evidence that WOLF15 itself runs that topology. |
| `agent-trading-predictor` | conditional | Advisory market analysis or research can support a defined investigation, but these are not coding defaults. The toolkit has its own working score, timeframe hierarchy and psychology metrics which are not repository strategy defaults. |
| `agent-user-tools` | conditional | Can support requested Codex/account configuration, local hook or recurring workflow work. Existing settings and workflows are evidence, not authorization to activate new automations. |
| `agent-v3-integration-architect` | conditional | The repository contains specific versioned v3 contracts, but V3 in a skill name does not identify the same system or grant a migration mandate. |
| `agent-v3-memory-specialist` | conditional | The repository contains specific versioned v3 contracts, but V3 in a skill name does not identify the same system or grant a migration mandate. |
| `agent-v3-performance-engineer` | conditional | The repository contains specific versioned v3 contracts, but V3 in a skill name does not identify the same system or grant a migration mandate. |
| `agent-v3-queen-coordinator` | conditional | The repository contains specific versioned v3 contracts, but V3 in a skill name does not identify the same system or grant a migration mandate. |
| `agent-v3-security-architect` | conditional | The repository contains specific versioned v3 contracts, but V3 in a skill name does not identify the same system or grant a migration mandate. |
| `agent-worker-specialist` | core | Direct fit for latency/backpressure diagnostics and bounded worker contracts around pressure, evidence and execution delivery. Work must preserve idempotency and safety gates. |
| `agent-workflow` | conditional | Can model actual routing, aggregation, idempotency and partial failures, but its agent node vocabulary and optional learning loop must not be assumed present from module names. |
| `agent-workflow-automation` | conditional | Relevant only to the specific requested GitHub lifecycle surface. PR creation, project metadata, release publication and CI/CD operations require different effects from ordinary source work. |
| `agentdb-advanced` | out_of_scope | These workflows explicitly require AgentDB, ReasoningBank, Flow Nexus, SAFLA or SONA. The inspected repository manifests do not establish those dependencies; current Redis/PostgreSQL storage does not imply them. |
| `agentdb-learning` | out_of_scope | These workflows explicitly require AgentDB, ReasoningBank, Flow Nexus, SAFLA or SONA. The inspected repository manifests do not establish those dependencies; current Redis/PostgreSQL storage does not imply them. |
| `agentdb-memory-patterns` | out_of_scope | These workflows explicitly require AgentDB, ReasoningBank, Flow Nexus, SAFLA or SONA. The inspected repository manifests do not establish those dependencies; current Redis/PostgreSQL storage does not imply them. |
| `agentdb-optimization` | out_of_scope | These workflows explicitly require AgentDB, ReasoningBank, Flow Nexus, SAFLA or SONA. The inspected repository manifests do not establish those dependencies; current Redis/PostgreSQL storage does not imply them. |
| `agentdb-vector-search` | out_of_scope | These workflows explicitly require AgentDB, ReasoningBank, Flow Nexus, SAFLA or SONA. The inspected repository manifests do not establish those dependencies; current Redis/PostgreSQL storage does not imply them. |
| `agentic-jujutsu` | conditional | Useful alternative for a specifically requested planning, SPARC, refactor, or interactive coding deliverable. The preferred core routes already cover ordinary repository work; loading parallel aliases adds process and overlapping instructions. |
| `analyze-tuyul-kartel-fx` | quarantined | Required package contracts or helpers are absent from this installation. The repository policy quarantines this skill pending source restoration and reassessment. |
| `audit-wolf15-constitution` | quarantined | Required package contracts or helpers are absent from this installation. The repository policy quarantines this skill pending source restoration and reassessment. Its combined Risk/Dashboard ownership claim also conflicts with current repository authority. |
| `claims` | conditional | Useful for documentation drift or explicit claims design around existing API and authorization contracts; neither requires introducing a new authorization platform. |
| `codex-security:assess-patch-risk` | core | Immutable patch and regression-risk review fits guarded trading changes. |
| `codex-security:attack-path-analysis` | conditional | Useful for tracing a concrete auth or broker-adjacent security finding. |
| `codex-security:deep-security-scan` | conditional | Repeated repository audits are costly and require explicit deep-scan scope. |
| `codex-security:define-security-policy` | conditional | Repository trust boundaries benefit from source-grounded policy. |
| `codex-security:finding-discovery` | conditional | Candidate discovery supports security review but is not a default full-scan router. |
| `codex-security:fix-finding` | conditional | Validated security fixes may be needed around auth, secrets and execution controls. |
| `codex-security:propose-security-hardening` | conditional | Structural proposals can improve boundary enforcement without immediate runtime mutation. |
| `codex-security:security-diff-scan` | core | Exact change security review fits PR and configuration review in this repository. |
| `codex-security:security-scan` | conditional | Single-pass scoped repository audit is relevant when explicitly requested. |
| `codex-security:threat-model` | conditional | Auth, API, PostgreSQL and MT5 boundaries require concrete attacker/control models. |
| `codex-security:track-findings` | conditional | Durable findings records support remediation tracking. |
| `codex-security:triage-finding` | conditional | Static impact assessment suits existing vulnerability reports and advisories. |
| `codex-security:validation` | conditional | Candidates need source and bounded local validation. |
| `codex-security:verify-fix` | conditional | Read-only checks can confirm a security patch addresses the original issue. |
| `codex-security:vulnerability-writeup` | conditional | Evidence-backed reports are useful after findings exist. |
| `computer-use:computer-use` | conditional | Native UI evidence may help bounded MT5/Windows investigation but cannot prove broker execution by itself. |
| `deep-research-work:deep-research` | conditional | Deep research can support strategy/architecture evidence only when requested. |
| `documents:documents` | conditional | Formal audit/runbook documents are occasional deliverables. |
| `embeddings` | conditional | May support explicitly scoped offline feature research, retrieval corpus preparation or graph analysis. The manifests prove numerical dependencies, not a deployed ML/retrieval stack. |
| `evaluate-agent-skill` | conditional | Supports Codex configuration, skill maintenance, exact-package evidence or delegated review when that is the task. Skill discovery does not require installing plugins or evaluating every workflow on each repository edit. |
| `extract-agent-workflow` | quarantined | Required package contracts or helpers are absent from this installation. The repository policy quarantines this skill pending source restoration and reassessment. |
| `figma:figma-code-connect` | conditional | Optional design workflow for the existing React/Next.js dashboard; no Figma service access was measured. |
| `figma:figma-create-new-file` | conditional | Optional design workflow for the existing React/Next.js dashboard; no Figma service access was measured. |
| `figma:figma-design-to-code` | conditional | Optional design workflow for the existing React/Next.js dashboard; no Figma service access was measured. |
| `figma:figma-generate-design` | conditional | Optional design workflow for the existing React/Next.js dashboard; no Figma service access was measured. |
| `figma:figma-generate-diagram` | conditional | Optional design workflow for the existing React/Next.js dashboard; no Figma service access was measured. |
| `figma:figma-generate-library` | conditional | Optional design workflow for the existing React/Next.js dashboard; no Figma service access was measured. |
| `figma:figma-implement-motion` | conditional | Optional design workflow for the existing React/Next.js dashboard; no Figma service access was measured. |
| `figma:figma-swiftui` | out_of_scope | SwiftUI is not the assessed dashboard target. |
| `figma:figma-use` | conditional | Optional design workflow for the existing React/Next.js dashboard; no Figma service access was measured. |
| `figma:figma-use-figjam` | conditional | Optional design workflow for the existing React/Next.js dashboard; no Figma service access was measured. |
| `figma:figma-use-motion` | conditional | Optional design workflow for the existing React/Next.js dashboard; no Figma service access was measured. |
| `figma:figma-use-slides` | conditional | Optional design workflow for the existing React/Next.js dashboard; no Figma service access was measured. |
| `flow-nexus-neural` | out_of_scope | These workflows explicitly require AgentDB, ReasoningBank, Flow Nexus, SAFLA or SONA. The inspected repository manifests do not establish those dependencies; current Redis/PostgreSQL storage does not imply them. |
| `flow-nexus-platform` | out_of_scope | These workflows explicitly require AgentDB, ReasoningBank, Flow Nexus, SAFLA or SONA. The inspected repository manifests do not establish those dependencies; current Redis/PostgreSQL storage does not imply them. |
| `flow-nexus-swarm` | out_of_scope | These workflows explicitly require AgentDB, ReasoningBank, Flow Nexus, SAFLA or SONA. The inspected repository manifests do not establish those dependencies; current Redis/PostgreSQL storage does not imply them. |
| `github-automation` | conditional | Relevant only to the specific requested GitHub lifecycle surface. PR creation, project metadata, release publication and CI/CD operations require different effects from ordinary source work. |
| `github-code-review` | core | Direct fit for exact-head review, GitHub checks and release evidence in a repository where runtime acceptance and runnerless CI must remain separate from local validation. |
| `github-multi-repo` | quarantined | Required package contracts or helpers are absent from this installation. The repository policy quarantines this skill pending source restoration and reassessment. |
| `github-project-management` | conditional | Relevant only to the specific requested GitHub lifecycle surface. PR creation, project metadata, release publication and CI/CD operations require different effects from ordinary source work. |
| `github-release-management` | conditional | Relevant only to the specific requested GitHub lifecycle surface. PR creation, project metadata, release publication and CI/CD operations require different effects from ordinary source work. |
| `github-workflow-automation` | core | Direct fit for exact-head review, GitHub checks and release evidence in a repository where runtime acceptance and runnerless CI must remain separate from local validation. |
| `global-development-instruction` | quarantined | Required package contracts or helpers are absent from this installation. The repository policy quarantines this skill pending source restoration and reassessment. |
| `google-drive:google-docs` | conditional | Optional externally hosted audit/document workflow, separate from repository operations. |
| `google-drive:google-drive` | conditional | Optional externally hosted audit/document workflow, separate from repository operations. |
| `google-drive:google-drive-comments` | conditional | Optional externally hosted audit/document workflow, separate from repository operations. |
| `google-drive:google-sheets` | conditional | Optional externally hosted audit/document workflow, separate from repository operations. |
| `google-drive:google-slides` | conditional | Optional externally hosted audit/document workflow, separate from repository operations. |
| `hive-mind` | conditional | Independent architecture, implementation, testing and review tasks may justify a small specialist team. These are agent coordination choices, not evidence that WOLF15 itself runs that topology. |
| `hive-mind-advanced` | conditional | Independent architecture, implementation, testing and review tasks may justify a small specialist team. These are agent coordination choices, not evidence that WOLF15 itself runs that topology. |
| `hooks-automation` | conditional | Can support requested Codex/account configuration, local hook or recurring workflow work. Existing settings and workflows are evidence, not authorization to activate new automations. |
| `imagegen` | out_of_scope | Current engineering scope is a trading backend and read-only operational viewer, not an investor film or generated raster asset. These can remain globally installed for separately requested creative work. |
| `investor-profile-video-blueprint` | out_of_scope | Current engineering scope is a trading backend and read-only operational viewer, not an investor film or generated raster asset. These can remain globally installed for separately requested creative work. |
| `memory-management` | conditional | Historical project context and provenance-preserving handoff can aid Codex, but Codex memory is distinct from WOLF15 runtime state and its journals. |
| `mindmap-reasoning` | quarantined | Required package contracts or helpers are absent from this installation. The repository policy quarantines this skill pending source restoration and reassessment. |
| `neural-orchestrator` | quarantined | Required package contracts or helpers are absent from this installation. The repository policy quarantines this skill pending source restoration and reassessment. |
| `neural-training` | conditional | May support explicitly scoped offline feature research, retrieval corpus preparation or graph analysis. The manifests prove numerical dependencies, not a deployed ML/retrieval stack. |
| `openai-developers:agents-sdk` | out_of_scope | Existing constitutional pipeline is not evidence of an OpenAI Agents SDK application. |
| `openai-developers:build-chatgpt-app` | out_of_scope | The dashboard package is a Next.js trading dashboard, not a verified ChatGPT Apps SDK widget. |
| `openai-developers:chatgpt-app-submission` | out_of_scope | No ChatGPT app submission task or app target is established by repository assessment. |
| `openai-developers:openai-api-troubleshooting` | conditional | API-backed tooling may need error diagnosis; no API call was required for this assessment. |
| `openai-developers:openai-platform-api-key` | conditional | Credential configuration matters only for a concrete API-backed integration. |
| `openai-docs` | conditional | Supports Codex configuration, skill maintenance, exact-package evidence or delegated review when that is the task. Skill discovery does not require installing plugins or evaluating every workflow on each repository edit. |
| `pair-programming` | conditional | Useful alternative for a specifically requested planning, SPARC, refactor, or interactive coding deliverable. The preferred core routes already cover ordinary repository work; loading parallel aliases adds process and overlapping instructions. |
| `pdf:pdf` | conditional | Existing audit evidence may need PDF extraction or verified export. |
| `performance-analysis` | conditional | Appropriate when a measured worker, numerical, streaming, resource or endurance problem requires the specific method; ordinary correctness changes do not justify benchmarking or persistent processors. |
| `petakan-konsep` | conditional | Relationship maps can clarify authority and dependency decisions. Use only its available source-bound mapping route; its description and evaluator wording need the documented cautions, and the overlapping map skill is quarantined. |
| `plugin-creator` | conditional | Supports Codex configuration, skill maintenance, exact-package evidence or delegated review when that is the task. Skill discovery does not require installing plugins or evaluating every workflow on each repository edit. |
| `plugin-management:plugin-management` | conditional | Connection and permission assessment helps tool fit, without installing every suggested provider. |
| `presentations:presentations` | conditional | Architecture/release briefings may need an exported deck. |
| `reasoningbank-agentdb` | out_of_scope | These workflows explicitly require AgentDB, ReasoningBank, Flow Nexus, SAFLA or SONA. The inspected repository manifests do not establish those dependencies; current Redis/PostgreSQL storage does not imply them. |
| `reasoningbank-intelligence` | out_of_scope | These workflows explicitly require AgentDB, ReasoningBank, Flow Nexus, SAFLA or SONA. The inspected repository manifests do not establish those dependencies; current Redis/PostgreSQL storage does not imply them. |
| `remotion:remotion-best-practices` | out_of_scope | Video authoring/rendering is not the assessed trading dashboard build or execution pipeline. |
| `remotion:remotion-captions` | out_of_scope | Video authoring/rendering is not the assessed trading dashboard build or execution pipeline. |
| `remotion:remotion-create` | out_of_scope | Video authoring/rendering is not the assessed trading dashboard build or execution pipeline. |
| `remotion:remotion-docs` | out_of_scope | Video authoring/rendering is not the assessed trading dashboard build or execution pipeline. |
| `remotion:remotion-interactivity` | out_of_scope | Video authoring/rendering is not the assessed trading dashboard build or execution pipeline. |
| `remotion:remotion-maps` | out_of_scope | Video authoring/rendering is not the assessed trading dashboard build or execution pipeline. |
| `remotion:remotion-markup` | out_of_scope | Video authoring/rendering is not the assessed trading dashboard build or execution pipeline. |
| `remotion:remotion-multimedia` | out_of_scope | Video authoring/rendering is not the assessed trading dashboard build or execution pipeline. |
| `remotion:remotion-render` | out_of_scope | Video authoring/rendering is not the assessed trading dashboard build or execution pipeline. |
| `remotion:remotion-saas` | out_of_scope | Video authoring/rendering is not the assessed trading dashboard build or execution pipeline. |
| `remotion:remotion-studio` | out_of_scope | Video authoring/rendering is not the assessed trading dashboard build or execution pipeline. |
| `remotion:remotion-upgrade` | out_of_scope | Video authoring/rendering is not the assessed trading dashboard build or execution pipeline. |
| `retrieval-knowledge-structurer` | conditional | May support explicitly scoped offline feature research, retrieval corpus preparation or graph analysis. The manifests prove numerical dependencies, not a deployed ML/retrieval stack. |
| `review-agent` | conditional | Supports Codex configuration, skill maintenance, exact-package evidence or delegated review when that is the task. Skill discovery does not require installing plugins or evaluating every workflow on each repository edit. |
| `security-audit` | conditional | Security review is relevant at actual auth, command, distributed trust or data boundaries; it should not turn every edit into a full scan. Use dedicated Codex Security when that scan is requested. |
| `sites:sites-building` | out_of_scope | Existing Next.js/Railway dashboard is not an established Sites-managed project. |
| `sites:sites-hosting` | out_of_scope | Existing Next.js/Railway dashboard is not an established Sites-managed project. |
| `skill-builder` | conditional | Supports Codex configuration, skill maintenance, exact-package evidence or delegated review when that is the task. Skill discovery does not require installing plugins or evaluating every workflow on each repository edit. |
| `skill-creator` | conditional | Supports Codex configuration, skill maintenance, exact-package evidence or delegated review when that is the task. Skill discovery does not require installing plugins or evaluating every workflow on each repository edit. |
| `skill-installer` | conditional | Supports Codex configuration, skill maintenance, exact-package evidence or delegated review when that is the task. Skill discovery does not require installing plugins or evaluating every workflow on each repository edit. |
| `sparc-methodology` | conditional | Useful alternative for a specifically requested planning, SPARC, refactor, or interactive coding deliverable. The preferred core routes already cover ordinary repository work; loading parallel aliases adds process and overlapping instructions. |
| `spreadsheets:excel-live-control` | conditional | Live Excel manipulation is separate from source/database analysis. |
| `spreadsheets:spreadsheets` | conditional | Audit sheets and measured outcomes may need tabular analysis. |
| `stream-chain` | conditional | Appropriate when a measured worker, numerical, streaming, resource or endurance problem requires the specific method; ordinary correctness changes do not justify benchmarking or persistent processors. |
| `supabase:supabase` | out_of_scope | Current assessed requirements identify Psycopg/PostgreSQL; that alone does not establish a Supabase project. |
| `supabase:supabase-postgres-best-practices` | conditional | General PostgreSQL query/performance patterns can inform the existing Psycopg database integration. |
| `swarm-advanced` | conditional | Independent architecture, implementation, testing and review tasks may justify a small specialist team. These are agent coordination choices, not evidence that WOLF15 itself runs that topology. |
| `swarm-orchestration` | conditional | Independent architecture, implementation, testing and review tasks may justify a small specialist team. These are agent coordination choices, not evidence that WOLF15 itself runs that topology. |
| `template-creator:template-creator` | conditional | Reusable report templates may help repeated audits when specifically requested. |
| `timerally-intelligence` | out_of_scope | Payment mandates, provider settlement, app-store publishing, React Native and Time Rally navigation have no direct requested role in this Python/Next.js WOLF15 repository. Broker execution is not a generic payment workflow. |
| `trace-agent-runtime-flow` | quarantined | Required package contracts or helpers are absent from this installation. The repository policy quarantines this skill pending source restoration and reassessment. |
| `truth-score-evaluator` | out_of_scope | The installed entrypoint explicitly declares LEGACY_REPORT_ONLY and retired always-error scripts; it cannot serve as the quality gate for repository work. |
| `v3-cli-modernization` | conditional | The repository contains specific versioned v3 contracts, but V3 in a skill name does not identify the same system or grant a migration mandate. |
| `v3-core-implementation` | conditional | The repository contains specific versioned v3 contracts, but V3 in a skill name does not identify the same system or grant a migration mandate. |
| `v3-ddd-architecture` | conditional | The repository contains specific versioned v3 contracts, but V3 in a skill name does not identify the same system or grant a migration mandate. |
| `v3-integration-deep` | conditional | The repository contains specific versioned v3 contracts, but V3 in a skill name does not identify the same system or grant a migration mandate. |
| `v3-mcp-optimization` | conditional | The repository contains specific versioned v3 contracts, but V3 in a skill name does not identify the same system or grant a migration mandate. |
| `v3-memory-unification` | conditional | The repository contains specific versioned v3 contracts, but V3 in a skill name does not identify the same system or grant a migration mandate. |
| `v3-performance-optimization` | conditional | The repository contains specific versioned v3 contracts, but V3 in a skill name does not identify the same system or grant a migration mandate. |
| `v3-security-overhaul` | conditional | The repository contains specific versioned v3 contracts, but V3 in a skill name does not identify the same system or grant a migration mandate. |
| `v3-swarm-coordination` | conditional | The repository contains specific versioned v3 contracts, but V3 in a skill name does not identify the same system or grant a migration mandate. |
| `verification-quality` | core | Preferred engineering route for the mixed Python and Next.js repository: bind current source, preserve user edits, and validate only the changed behavior. Its specific workflow and output below determine which stage to select. |
| `visualize:visualize` | conditional | Interactive explanations can clarify evidence/state flow without changing product code. |
| `wolf-arsenal-toolkit` | quarantined | Required package contracts or helpers are absent from this installation. The repository policy quarantines this skill pending source restoration and reassessment. |
| `wolf15-authority-boundary-review` | core | Direct fit for WOLF15 authority separation, exact-source runtime tracing, canonical raw admission lineage, closed-candle evidence, and replay denominator discipline. |
| `wolf15-legacy-prompt-admission` | conditional | Useful when the user supplies legacy WOLF prompts for reuse: separates hypotheses, source claims and unsafe execution-shaped fields before adaptation. |
| `wolf15-replay-audit` | core | Direct fit for WOLF15 authority separation, exact-source runtime tracing, canonical raw admission lineage, closed-candle evidence, and replay denominator discipline. |
| `worker-benchmarks` | conditional | Appropriate when a measured worker, numerical, streaming, resource or endurance problem requires the specific method; ordinary correctness changes do not justify benchmarking or persistent processors. |
| `worker-integration` | conditional | Appropriate when a measured worker, numerical, streaming, resource or endurance problem requires the specific method; ordinary correctness changes do not justify benchmarking or persistent processors. |
| `workflow-automation` | conditional | Can support requested Codex/account configuration, local hook or recurring workflow work. Existing settings and workflows are evidence, not authorization to activate new automations. |

## Referensi platform

- [Skill discovery dan enablement Codex](https://developers.openai.com/codex/skills)
- [Semantik aturan perintah Codex](https://developers.openai.com/codex/rules)
- [Konteks build dan dockerignore](https://docs.docker.com/build/concepts/context/#dockerignore-files)
