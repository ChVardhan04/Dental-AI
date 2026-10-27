# Go-live checklist

The software is production-ready as a platform. Using it **clinically** still requires the steps below (Plan §37–42, §53–54, §69, §75), which cannot be done in code.

## Must do before real patients
1. **Replace research models.** The bundled photo/X-ray finding models are classical computer-vision measurements registered as `research`. Train/validate real models on licensed, patient-level-split datasets, register them (`Admin → Model registry`), approve, then set `ALLOWED_MODEL_STATUSES=production`.
2. **Clinical sign-off** of: rules thresholds (`clinical_rules.py`, `CONFIDENCE_THRESHOLD`), emergency rule set (`emergency.py`), finding vocabulary (`taxonomy.py`), and every knowledge document (re-approve each in `Admin → Knowledge base`).
3. **Regulatory assessment** of intended use per target market (FDA CDS guidance, CDSCO/MDR as applicable). Keep marketing to “AI-assisted screening and education”.
4. **Secrets & infrastructure:** strong `JWT_SECRET_KEY`, `STORAGE_ENCRYPTION_KEY` held in a secret manager (losing it makes stored images unreadable), managed PostgreSQL with backups/PITR, S3 bucket with versioning, TLS termination, Redis for multi-replica rate limiting.
5. **Providers:** if using OpenAI/Anthropic for explanations, vision or speech, sign a BAA/DPA and confirm data residency. The default `template` explainer sends no data externally.
6. **Security assessment / penetration test** and privacy impact assessment.
7. **DentEdge integration:** set `APPOINTMENT_BOOKING_URL`; connect the existing RVG/X-ray viewer if X-rays should be pulled rather than uploaded.

## Operations
- Backups: database + object storage + the encryption key (separately).
- Monitoring: scrape `/ready`; review `Admin → Monitoring` weekly for quality-rejection rate, dentist override rate and drift alerts.
- Incident management: drift or rising override rates → investigate, never auto-retrain (Plan §57).
