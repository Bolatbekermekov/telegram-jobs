# Role-specific CV subsystem
- Canonical roles: ai, backend-node, backend-go, backend-python, frontend, mobile, qa, fullstack; fullstack is the default/fallback.
- Role prompt and normalization live in app/domain/cv_role.py and app/application/classify_role.py; OpenAIRoleClassifier uses OPENAI_MODEL_CHEAP.
- CvLibrary resolves requested role -> fullstack -> configured fallback, caches by role and parsed path, and treats missing/unreadable/empty text as a failed tier.
- Core invariant: the same CvVariant must supply both the text used to generate the letter and the PDF path attached/uploaded for that lead.
- Local ignored artifacts live in sender/cv/<role>/cv.tex and role-named PDF files. sender/build_cvs.sh builds all eight and rejects multi-page output.
- PDF and TeX files contain PII and are intentionally ignored; only sender/cv/.gitkeep and the build script are versioned.
- Direct messaging support differs by channel: Telegram/email attach files; LinkedIn can upload or message-attach depending on flow; HeadHunter normally uses its online resume and optionally sends the PDF in chat; Threads intentionally drops attachments.