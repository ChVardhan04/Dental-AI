"""Seed patient-education library for the Evidence / Knowledge layer.

IMPORTANT: this is starter content written in general, non-diagnostic language consistent with widely published
public dental-health guidance. Before launch, DentEdge clinical reviewers must review, edit and re-approve every
document (the admin Knowledge Base screen supports versioning, reviewer and status for exactly this purpose).
"""

SOURCE = "DentEdge patient-education library — seed draft based on general public oral-health guidance (e.g. national dental association patient pages)"
REVIEWER = "DentEdge Clinical Content Board — seed approval, re-review before launch"
PUB = "2026-09-01"
REVIEW = "2027-03-01"

DOCS = [
    ("plaque-basics", "Plaque and the gum line", ["visible_plaque"], {
        "what_it_is": "Plaque is a soft, sticky film of bacteria that forms on teeth every day, often near the gum line.",
        "why_it_matters": "If plaque is not removed regularly it can harden and may contribute to gum irritation and tooth decay over time.",
        "factors": ["Brushing technique or frequency", "Areas that are hard to reach, such as between teeth", "Sugary foods and drinks"],
        "next_step": "Mention this at your next dental visit. A dentist or hygienist can check the area and show you cleaning techniques.",
        "questions": ["Are there areas I am missing when I brush?", "Would interdental brushes or floss help me?", "How often should I have a professional cleaning?"],
        "warning_signs": [],
    }),
    ("staining-basics", "Tooth staining and discoloration", ["visible_staining", "apparent_discoloration"], {
        "what_it_is": "Staining is a change in the colour of the tooth surface. Many stains are on the outer surface and are cosmetic.",
        "why_it_matters": "Most surface staining is not harmful, but some colour changes can have other causes that a dentist should look at.",
        "factors": ["Coffee, tea, red wine and some foods", "Tobacco use", "Some mouth rinses or medicines", "Tartar build-up"],
        "next_step": "Ask your dentist whether the colour change is a surface stain or something that needs further assessment.",
        "questions": ["Is this a surface stain?", "Could professional cleaning remove it?", "Is there anything I should change in my routine?"],
        "warning_signs": ["A dark spot that is painful or getting larger"],
    }),
    ("gum-changes-basics", "Changes in gum appearance", ["visible_gingival_changes", "bleeding_gums"], {
        "what_it_is": "Healthy gums are usually firm and pink. Redness, puffiness or bleeding can be signs of irritation or inflammation.",
        "why_it_matters": "Gum changes are common and often improve with good cleaning, but a dentist should check them because they can also indicate gum disease.",
        "factors": ["Plaque build-up along the gum line", "Brushing too hard", "Hormonal changes", "Smoking", "Some medical conditions or medicines"],
        "next_step": "Book a routine dental check-up so a dentist can examine your gums and measure gum health if needed.",
        "questions": ["Are my gums healthy?", "Do I need a gum assessment?", "Is my brushing technique right for my gums?"],
        "warning_signs": ["Gums that bleed heavily and do not stop", "Swelling that spreads to the face"],
    }),
    ("recession-basics", "Gum recession", ["apparent_recession"], {
        "what_it_is": "Gum recession is when the gum line moves back and more of the tooth (sometimes the root) becomes visible.",
        "why_it_matters": "Exposed root surfaces can be more sensitive and may need monitoring by a dentist.",
        "factors": ["Brushing too hard", "Gum disease", "Tooth position", "Teeth grinding"],
        "next_step": "Ask your dentist to check your gum levels at your next visit.",
        "questions": ["Has my gum line changed?", "Could my brushing be contributing?", "Do I need to monitor this?"],
        "warning_signs": [],
    }),
    ("chip-fracture-basics", "Chips and cracks in teeth", ["visible_chip", "visible_fracture"], {
        "what_it_is": "A chip or crack is damage to the hard outer layers of a tooth.",
        "why_it_matters": "Some chips are small and cosmetic, while cracks can extend deeper. Only a dentist can determine how deep the damage is.",
        "factors": ["Biting hard objects", "Teeth grinding", "Large existing fillings", "Injury"],
        "next_step": "Arrange a dental appointment soon so the tooth can be examined, especially if it is sensitive or painful.",
        "questions": ["How deep is the damage?", "Should I avoid chewing on that side?", "What options are there to protect the tooth?"],
        "warning_signs": ["Severe pain", "A tooth that has been knocked loose or out after an injury"],
    }),
    ("alignment-basics", "Crowding, spacing and alignment", ["visible_crowding", "visible_spacing", "alignment_characteristics", "cosmetic_characteristics"], {
        "what_it_is": "Teeth can overlap (crowding), have gaps (spacing), or sit at different angles. These are common and often cosmetic.",
        "why_it_matters": "Crowded areas can be harder to clean, and some people have cosmetic or bite concerns they want to discuss.",
        "factors": ["Jaw and tooth size", "Genetics", "Missing teeth", "Habits during childhood"],
        "next_step": "If you have concerns about appearance or cleaning, discuss them at your next check-up.",
        "questions": ["Does my alignment affect cleaning?", "Is this something to monitor?", "What cosmetic options exist if I want them?"],
        "warning_signs": [],
    }),
    ("xray-radiolucency-basics", "Darker areas on dental X-rays", ["radiolucent_area_for_review", "possible_caries", "possible_periapical_radiolucency"], {
        "what_it_is": "On an X-ray, dense structures look bright and less dense areas look darker. Darker areas can have many explanations, including normal anatomy.",
        "why_it_matters": "Some darker areas may need a closer look by a dentist, who interprets the X-ray together with a clinical examination.",
        "factors": ["Normal anatomy such as nerve canals and spaces", "Tooth decay", "Changes around tooth roots", "Image angle and exposure"],
        "next_step": "Your dentist will review the highlighted area and explain whether anything needs attention.",
        "questions": ["Is this area normal anatomy?", "Does this need treatment or monitoring?", "Should we compare it with a future X-ray?"],
        "warning_signs": ["Facial swelling", "Severe or throbbing pain"],
    }),
    ("xray-bone-basics", "Bone levels on X-rays", ["possible_bone_level_change"], {
        "what_it_is": "Dental X-rays show the bone that supports the teeth.",
        "why_it_matters": "Changes in bone level can be related to gum health and are assessed by a dentist using X-rays and gum measurements.",
        "factors": ["Gum disease", "Age", "Previous dental treatment"],
        "next_step": "Your dentist may combine the X-ray with a periodontal (gum) chart to understand your gum health.",
        "questions": ["Are my bone levels stable?", "Do I need a periodontal chart?"],
        "warning_signs": [],
    }),
    ("restoration-basics", "Existing fillings and crowns on X-rays", ["restoration_present"], {
        "what_it_is": "Fillings, crowns and other restorations often appear very bright on X-rays because they are dense.",
        "why_it_matters": "This is usually expected. Your dentist checks the edges of restorations for any changes over time.",
        "factors": ["Previous dental treatment"],
        "next_step": "No action is needed from you; your dentist will review the X-ray.",
        "questions": ["Are my existing fillings in good condition?"],
        "warning_signs": [],
    }),
    ("xray-comparison-basics", "Comparing X-rays over time", ["potential_change_for_review"], {
        "what_it_is": "Comparing a new X-ray with an older one helps your dentist see whether areas look the same or different.",
        "why_it_matters": "A difference between images does not automatically mean a condition has progressed. Angle, exposure and positioning also change images.",
        "factors": ["Different image angle or exposure", "Dental treatment between visits", "Changes in tooth or bone"],
        "next_step": "Your dentist will review both images side by side before drawing any conclusion.",
        "questions": ["Is the difference due to the image angle?", "Does anything need monitoring?"],
        "warning_signs": [],
    }),
    ("sensitivity-basics", "Tooth sensitivity", ["sensitivity"], {
        "what_it_is": "Tooth sensitivity is a short, sharp feeling when teeth are exposed to cold, heat, sweet or acidic foods, or brushing.",
        "why_it_matters": "Sensitivity is common and often manageable, but it can also be a sign of a problem that a dentist should check.",
        "factors": ["Exposed root surfaces", "Worn enamel", "Tooth decay", "Recent dental treatment", "Cracked teeth"],
        "next_step": "If sensitivity lasts more than a couple of weeks or is getting worse, book a dental appointment.",
        "questions": ["What is causing my sensitivity?", "Is there a toothpaste or routine you recommend for me?"],
        "warning_signs": ["Pain that lingers for a long time after the trigger", "Swelling"],
    }),
    ("toothache-basics", "Toothache", ["pain", "toothache"], {
        "what_it_is": "Toothache is pain in or around a tooth. It can be dull, sharp, constant or come and go.",
        "why_it_matters": "Tooth pain usually has a cause that a dentist should identify, especially if it persists or is severe.",
        "factors": ["Tooth decay", "Cracked tooth", "Gum problems", "Infection", "Grinding"],
        "next_step": "Contact your dentist to arrange an examination. Seek urgent care if you develop swelling, fever or difficulty swallowing.",
        "questions": ["What is causing the pain?", "What should I avoid until my appointment?"],
        "warning_signs": ["Facial swelling", "Fever", "Difficulty swallowing or breathing"],
    }),
    ("bad-breath-basics", "Bad breath", ["bad_breath"], {
        "what_it_is": "Bad breath (halitosis) is an unpleasant odour from the mouth.",
        "why_it_matters": "It is often related to oral hygiene, but a dentist can check for gum or tooth causes.",
        "factors": ["Plaque on teeth and tongue", "Dry mouth", "Certain foods", "Smoking", "Gum problems"],
        "next_step": "Mention it at your next dental visit.",
        "questions": ["Could my gums be contributing?", "Should I clean my tongue?"],
        "warning_signs": [],
    }),
    ("general-no-findings", "When no visual findings are reported", ["no_findings"], {
        "what_it_is": "No visual observations were generated from the images provided.",
        "why_it_matters": "This does not mean your mouth is healthy. Photos cannot show everything, such as decay between teeth or below the gum line.",
        "factors": [],
        "next_step": "Keep up regular dental check-ups and contact your dentist if you have any symptoms.",
        "questions": ["Is there anything photos cannot show that I should know about?", "When is my next check-up due?"],
        "warning_signs": [],
    }),
    ("smile-cosmetic-basics", "Understanding your Smile Score", ["smile"], {
        "what_it_is": "The Smile Score summarises visual, cosmetic characteristics of a smile photo, such as symmetry and visible staining.",
        "why_it_matters": "It is a cosmetic, visual assessment only. It is not a medical score and does not assess dental health.",
        "factors": ["Photo angle and lighting", "Lip position", "Tooth colour and position"],
        "next_step": "If you are interested in cosmetic options, discuss your goals with your dentist.",
        "questions": ["Which cosmetic options would suit my goals?", "Are there any health considerations first?"],
        "warning_signs": [],
    }),
]
