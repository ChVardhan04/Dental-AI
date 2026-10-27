"""Controlled finding vocabulary. Anything outside this list is rejected by the rules engine."""

PHOTO_FINDINGS: dict[str, dict] = {
    "visible_plaque": {"label": "Possible visible plaque", "patient": "areas that look like plaque build-up near the gum line"},
    "visible_staining": {"label": "Visible staining", "patient": "areas of visible staining on the tooth surface"},
    "apparent_discoloration": {"label": "Apparent discoloration", "patient": "areas where the tooth colour looks different"},
    "visible_gingival_changes": {"label": "Visible gum changes", "patient": "visual characteristics of the gums that may be consistent with gum inflammation"},
    "apparent_recession": {"label": "Apparent gum recession", "patient": "areas where the gum line may appear to have moved back"},
    "visible_chip": {"label": "Visible chip", "patient": "an area that looks like a small chip on a tooth edge"},
    "visible_fracture": {"label": "Visible fracture requiring professional assessment", "patient": "a line or break that should be assessed by a dentist"},
    "visible_crowding": {"label": "Visible crowding", "patient": "teeth that appear to overlap or be crowded"},
    "visible_spacing": {"label": "Visible spacing", "patient": "visible gaps between some teeth"},
    "alignment_characteristics": {"label": "Alignment characteristics", "patient": "visible characteristics of how the teeth line up"},
    "cosmetic_characteristics": {"label": "Cosmetic characteristics", "patient": "visible cosmetic characteristics of the smile"},
}

XRAY_FINDINGS: dict[str, dict] = {
    "radiolucent_area_for_review": {"label": "Area of reduced radiodensity (review required)", "patient": "a darker area on the X-ray that your dentist should look at"},
    "possible_caries": {"label": "Possible caries", "patient": "an area that may be consistent with tooth decay and needs dentist review"},
    "possible_periapical_radiolucency": {"label": "Possible periapical radiolucency", "patient": "a darker area near a tooth root that needs dentist review"},
    "possible_bone_level_change": {"label": "Possible bone level change", "patient": "an area where the bone level may look different and needs review"},
    "restoration_present": {"label": "Radiopaque material (e.g. existing restoration)", "patient": "a very bright area that often represents an existing filling or crown"},
    "potential_change_for_review": {"label": "Potential change since previous examination", "patient": "an area that looks different from your previous X-ray; this does not by itself mean a condition has progressed"},
}

ALL_FINDINGS = {**PHOTO_FINDINGS, **XRAY_FINDINGS}

# Findings that should prompt sooner (not emergency) professional review.
PROMPT_REVIEW_TYPES = {"visible_fracture", "possible_periapical_radiolucency"}


def label_for(finding_type: str) -> str:
    return ALL_FINDINGS.get(finding_type, {}).get("label", finding_type.replace("_", " ").capitalize())


def patient_phrase(finding_type: str) -> str:
    return ALL_FINDINGS.get(finding_type, {}).get("patient", finding_type.replace("_", " "))


def allowed_for(module: str) -> set[str]:
    if module in {"xray", "xray_comparison"}:
        return set(XRAY_FINDINGS)
    return set(PHOTO_FINDINGS)
