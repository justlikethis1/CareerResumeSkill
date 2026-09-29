# Master CV Template

The Master CV is the fact authority used by JD tailoring. It is not the one-page resume: it should contain every verified education item, research activity, publication, internship, project, competition, skill, and measurable result that may be selected for a target role.

Start from [examples/master_cv.template.json](../examples/master_cv.template.json). Do not use `examples/master_cv.json` as a personal document; that file is only a synthetic test fixture.

## Required contract

```json
{
  "name": "Real candidate name",
  "contact": {
    "email": "real@example.com",
    "phone": "",
    "location": "",
    "linkedin": "",
    "github": ""
  },
  "profile": "Only verified summary facts.",
  "sections": [
    {
      "type": "experience",
      "title": "Experience",
      "items": [
        {
          "title": "Role title",
          "organization": "Organization",
          "location": "Location",
          "dates": "YYYY-MM--YYYY-MM",
          "bullets": [
            "One factual statement supported by the source material."
          ]
        }
      ]
    }
  ],
  "skills": {
    "Languages": ["Python"],
    "Frameworks": [],
    "ML Systems": [],
    "Methods": [],
    "Tools": []
  }
}
```

## Evidence rules

- Keep source numbers, dates, employers, titles, paper names, and technologies exactly as verified.
- Do not convert coursework into employment or research responsibility.
- Do not turn “participated in” into “led” or “architected” unless the source explicitly supports that scope.
- Store missing JD requirements as gaps; never add them to `skills` to improve a score.
- Keep one claim per bullet where possible so the system can map a rewritten bullet back to an evidence ID.
- Use complete source content here. Page length and section ordering belong to the tailored output, not the Master CV.

## DOCX workflow

For an existing Word resume:

1. Run `inspect_docx_layout` or `career-resume-docx inspect`.
2. Map paragraph IDs to the corresponding Master CV item/bullet during ingestion.
3. Validate the Master CV before calling DeepSeek.
4. Generate tailored content only from that Master CV.
5. Apply approved replacements back to the original DOCX paragraph IDs.

A DOCX layout report by itself is not a semantic Master CV. It tells the system where text and styles are; it does not prove whether a paragraph is education, research, or an employment result.
