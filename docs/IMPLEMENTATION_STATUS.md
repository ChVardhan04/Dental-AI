# Implementation status and production gates

## Built in the starter foundation
- Responsive React workspace with patient/dentist navigation and login/register screens.
- FastAPI v1 routes and JWT sessions.
- SQLAlchemy models for users, patient profiles, consent, images, analyses, findings, voice sessions, perio charts, smile records and audit logs.
- Image upload validation, size/type restrictions, SHA-256 metadata and technical quality heuristics.
- Prototype vision provider that intentionally emits no clinical findings until a validated model is configured.
- Deterministic confidence/review rule interface and dentist review endpoint.
- Timeline/profile endpoints, text-based voice draft endpoint, perio chart draft endpoint, smile workflow placeholder and patient education framework UI.
- Docker Compose development environment.

## Not yet production-complete
- No clinically validated oral-image or X-ray model.
- Dental image suitability/classification is not implemented by the technical quality heuristic.
- No speech-to-text provider, speaker diarization, dental NLP or real-time microphone capture.
- No approved clinical evidence corpus or retrieval-augmented generation.
- No real patient/dentist assignment and consent authorization policy; dentist routes are deliberately restricted where the relationship cannot be verified.
- No S3/Azure Blob integration, encryption/key management configuration, malware scanning or retention/deletion workflows.
- No Alembic migration history, rate limiting, refresh-token/revocation flow, MFA, password reset, email verification or admin provisioning workflow.
- No PDF report generator, appointment integration, multi-image fusion, longitudinal image registration, model registry UI, monitoring/drift detection or MLOps deployment pipeline.
- Automated tests are scaffolding to be expanded before any deployment.

## Must-pass release gates
1. Security review: authentication, authorization, patient isolation, secrets, upload handling, dependency scan, rate limiting, auditability and encryption.
2. Clinical review: intended use, dataset provenance/licensing, ground-truth annotations, locked patient-level test split, external evaluation, sensitivity/specificity, calibration and false-negative review.
3. Safety review: deterministic clinical rules, approved emergency escalation, grounded content, uncertainty handling, red-team tests and clinician approval.
4. Privacy/legal review: consent wording/versioning, data retention, deletion, access requests, data processing agreements and jurisdiction-specific regulatory classification.
5. Operational review: managed infrastructure, HTTPS, backups/restore drills, incident response, monitoring, controlled model rollout and rollback.
