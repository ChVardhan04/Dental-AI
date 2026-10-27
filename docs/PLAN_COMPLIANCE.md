# Production Plan → Implementation Traceability

Legend: ✅ implemented & tested · 🟡 implemented, needs clinical/organisational input before launch · ⛔ cannot be completed in code (requires data, people or regulators)

| Plan § | Requirement | Status | Where |
|---|---|---|---|
| 5, 28–29 | Core pipeline Input → Validation → Preprocessing → Model → Findings → Confidence/Quality → Rules → Evidence → LLM → Safety → Dentist → Report | ✅ | `services/orchestrator.py` (per-step `pipeline_trace` stored with every analysis) |
| 6, 48 | Multiple specialised models; provider abstraction (no vendor lock-in) | ✅ | `services/vision/models.py` (Heuristic / LLM / ONNX slot), `services/llm/providers.py` (Template / OpenAI / Anthropic / Local) |
| 7 | Oral photo inputs: front, upper, lower, left, right, close-up, problem area, multiple images; camera capture | ✅ | `POST /oral-images`, `POST /oral-analysis`, `pages/OralVision.tsx` (`CameraCapture`) |
| 7 | Visible-finding vocabulary; “visible finding” ≠ diagnosis | ✅ | `services/taxonomy.py`, rule R003, safety gateway |
| 7 | Dental vision model, tooth/gum/region detection, finding detection | 🟡 | Research model measures staining, possible plaque, gum redness, spacing with region mapping. **Not clinically validated** – replace via registry with a trained model |
| 8 | Mandatory Image Quality Gate (image? dental? resolution, lighting, blur, teeth visible, relevant area visible) with plain-language rejection messages | ✅ | `services/image_quality.py` (+ type spoofing, decompression-bomb, screenshot, metadata stripping) |
| 9 | Multi-image fusion (view/region association, multi-image patient view) | ✅ | `orchestrator._fuse`, “Multi-image view” table |
| 10–11 | X-ray pipeline: validation, type classification (periapical/bitewing/panoramic), quality, preprocessing (CLAHE), anatomy detection, tooth/region localisation (FDI approx.), finding models, confidence, rules, annotation | 🟡 | `services/xray/pipeline.py`; finding model is research-grade and gated per type (rule R010, registry `supported_types`) |
| 12 | Structured findings (finding_id, type, location, confidence, severity, model, version, requires_review) | ✅ | `AIFinding`, `finding_out()` |
| 13 | Annotated version; dentist accept/reject/edit/comment/mark uncertain | ✅ | `services/annotation.py`, SVG overlay viewer, `POST /clinical-review` |
| 14, 55 | AI findings never auto-confirmed; Confirm / Edit / Reject / Further evaluation → clinical record | ✅ | `api/review.py` → `ClinicalFinding`, immutable `ClinicalReview` history |
| 15 | Historical X-ray comparison with anatomy alignment; never implies progression | ✅ | ORB + RANSAC homography, exposure normalisation, `POST /xray-comparison` |
| 16 | Patient voice: STT, dental terminology, symptom extraction, missing info, follow-up questions, structured complaint | ✅ | `services/voice/dental_nlp.py`, `POST /voice/symptoms` (multi-turn), browser + server STT |
| 17, 33 | AI scribe: STT, speaker identification, terminology, extraction, SOAP draft, edit/approve/reject, save | ✅ | `services/voice/scribe.py`, `POST /voice/scribe`, `PATCH /voice/scribe/{id}` |
| 18–19 | Voice perio: probing depth, bleeding, plaque, mobility, furcation, recession, suppuration; Start/Pause/Resume/Repeat/Undo/Jump; state machine; validation; chart; confirmation; patient report | ✅ | `services/perio.py`, `api/perio.py`, `pages/Perio.tsx` (hands-free dictation + spoken read-back) |
| 20 | Smile score (symmetry, alignment, staining, visibility, gum display, balance, overall) described as cosmetic; progress comparison | 🟡 | `services/smile.py` – geometric/colour metrics; weights need cosmetic-dentistry calibration |
| 21 | Educate: observed / may indicate / why it matters / factors / next / questions / urgent signs | ✅ | `insight.education_report`, `POST /education/report` |
| 22 | Evidence-grounded LLM; versioned knowledge (source, version, publication, review date, reviewer, status) | 🟡 | `KnowledgeDocument/Version`, admin approval workflow. **Seed content must be re-reviewed by DentEdge clinicians** |
| 23 | Deterministic, versioned clinical rules engine | 🟡 | `services/clinical_rules.py` (R001–R010). Thresholds need clinical sign-off |
| 24, 45 | Safety layer: unsupported diagnosis/treatment, certainty, hallucinated findings, dangerous instructions, medication, missing escalation, contradictions | ✅ | `services/safety.py`; failing LLM output falls back to templates |
| 25 | Emergency escalation rule set (swelling, breathing, swallowing, bleeding, trauma) | 🟡 | `services/emergency.py` with negation handling; needs clinical approval |
| 26 | Oral Health Profile (photo, X-ray, symptoms, perio, smile, previous exam, next step) | ✅ | `insight.build_profile`, `GET /patients/{id}/oral-profile` |
| 27 | Longitudinal timeline | ✅ | `TimelineEvent`, `GET /patients/{id}/timeline` (grouped by year) |
| 34–35 | PostgreSQL + object storage; all §35 entities | ✅ | `models/records.py`, Alembic `0001_initial_schema` (verified on PostgreSQL 16) |
| 36, 58 | Model registry (name, version, datasets, metrics, deployment & approval status), change control | ✅ | `AIModel/AIModelVersion`; production requires approval + validation dataset; kill-switch by status |
| 43–44 | LLM downstream & structured JSON output | ✅ | `services/explainer.py` |
| 46 | Versioned REST API (all listed endpoints) | ✅ | `/api/v1/...` |
| 49 | Security: auth, RBAC, isolation, encryption in transit (Nginx/TLS) & at rest, secrets, audit, secure uploads, rate limiting, session security, retention, deletion | ✅ | lockout, token revocation, magic-byte checks, Fernet storage, per-user + per-IP limits, `/me/export`, `/me/delete`, retention purge |
| 50 | Patient: own data · Dentist: assigned only · Admin: no clinical content | ✅ | `core/security.ensure_patient_access`, tested |
| 51 | Audit trail incl. model, version, confidence, decision | ✅ | `AuditLog`, admin Audit log |
| 52 | Versioned consent before AI processing | ✅ | `require_consent` on every AI endpoint, consent gate UI, withdraw in Settings |
| 56–57 | Technical + AI monitoring; drift detection (no auto-retrain) | ✅ | `/admin/monitoring`, `services/monitoring.py` |
| 60–61 | Unit, integration, model, safety, security, failure & red-team tests | ✅ | `backend/tests` (55 tests) |
| 62–65 | Patient flow (4 choices → results → education → book); dentist flow; patient & dentist reports | ✅ | `pages/*`, printable reports |
| 37–42, 53–54, 69 | Datasets, patient-level splits, evaluation, bias testing, regulatory & clinical validation | ⛔ | Organisational work — see `docs/GO_LIVE.md` |
