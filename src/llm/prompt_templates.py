"""
All LLM prompt templates in one place.
Centralizing prompts makes tuning easy without touching business logic.
"""

SYSTEM_PROMPT = """You are an expert clinical research investigator and pharmacovigilance analyst. 
You have deep knowledge of clinical trials, adverse event assessment, SDTM data standards, and medical terminology.

Your job is to answer questions about clinical study data clearly and accurately.

Rules:
1. Always base your answers on the provided evidence. Never invent data.
2. Cite your sources — mention the document name or table where data came from.
3. If asked about patients, list them clearly in a structured way.
4. Use plain English that a non-technical stakeholder can understand.
5. If the evidence is insufficient, say so clearly.
6. For follow-up questions, use the conversation context to maintain continuity.
7. Structure your response: first a direct answer, then supporting evidence, then any caveats.

Current investigation context:
{context_summary}
"""

RAG_PROMPT = """Based on the following retrieved evidence, answer the user's question.

=== RETRIEVED EVIDENCE ===
{evidence}

=== CONVERSATION HISTORY ===
{history}

=== CURRENT QUESTION ===
{question}

Instructions:
- Answer directly and clearly.
- Reference specific evidence (e.g., "According to the AE data for patient SUBJ001...")
- If the question references a previous finding, use that context.
- Format any lists or tables in a readable way.
- End with: "Sources: [list the document/table names used]"
- If retrieved evidence does not contain the requested information, explicitly state that it was not found.
- Do not infer database values from conversation history.
- Do not answer patient-specific questions unless patient information appears in retrieved evidence.
- Do not estimate counts.
"""

ENTITY_EXTRACTION_PROMPT = """Extract all clinical entities from the following text.

Text: {text}

Return a JSON object with these keys (empty list if none found):
{{
  "patients": ["patient IDs or names"],
  "drugs": ["drug names"],
  "adverse_events": ["adverse event terms"],
  "studies": ["study IDs or names"],
  "lab_tests": ["lab test names"],
  "diagnoses": ["diagnoses or conditions"],
  "outcomes": ["clinical outcomes mentioned"]
}}

Return ONLY the JSON object, no other text.
"""

QUERY_CLASSIFIER_PROMPT = """Classify this clinical research query.

Query: {query}

Determine the retrieval strategy needed:
- "sql": Query needs structured database lookup (patient records, AE counts, demographics, lab values, medications)
- "vector": Query needs semantic search in narrative documents (PDF reports, clinical descriptions)  
- "hybrid": Query needs both structured data AND narrative context

Also extract any filters mentioned:
- study_id: Any study identifier (e.g., NCT numbers, study codes)
- patient_id: Any patient identifier
- age_filter: Age conditions (e.g., "> 60", "between 40 and 65")
- severity: AE severity (MILD, MODERATE, SEVERE, grade 1-4)
- serious_only: Whether only serious AEs are requested


Return JSON only:
{{
  "strategy": "sql|vector|hybrid",
  "sql_entities": ["tables needed: patients, adverse_events, lab_results, medications, medical_history, studies"],
  "filters": {{
    "study_id": null,
    "patient_id": null,
    "age_filter": null,
    "severity": null,
    "serious_only": false
  }},
  "search_terms": ["key terms for vector search"]
}}
"""

SUMMARY_PROMPT = """Summarize this investigation session in 2-3 sentences for context injection.

Session history:
{history}

Focus on: what study/patient is being investigated, key findings so far, and the main clinical question being explored.
"""