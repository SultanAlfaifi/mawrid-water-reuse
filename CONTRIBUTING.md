# المساهمة في مورد · Contributing to MAWRID

نرحب بمساهمات البرمجيات، وتجربة الاستخدام، والتحكم، ومعالجة المياه والبيانات. ابدأ من [مرجع المشروع](docs/project-brief.md) و[دليل التطوير](docs/development.md)، وحدد هل التغيير يخص الموقع العام، النظام المحلي، أم البحث التجريبي.

MAWRID welcomes engineering, water-quality, controls, data and design contributions. Describe the problem and the affected product surface before changing it. Software verification, model evaluation and physical water-treatment validation are separate evidence tracks.

## قواعد الأدلة · Evidence rules

- Label external findings `LITERATURE` and cite their primary source; a citation is not a partnership or endorsement.
- Label unmeasured acceptance criteria `TARGET` and design assumptions `DESIGN`.
- Keep simulated readings, screenshots and exports explicitly `SIMULATED`; do not present them as field measurements.
- Use `RESULT` only with a method, sample size, uncertainty, quality controls and a publishable raw-data path. Preserve failures and inconclusive findings.
- Report model metrics with their dataset, time split, event definition and denominator. Do not tune against disclosed test periods and call them fresh validation.
- Do not claim water safety, compliance, certification, superiority, field savings or price leadership without appropriate evidence.
- Review changes to release logic, disinfection, plumbing, critical-data handling and safety limits with the relevant domain specialist. AI cannot authorize opening the reuse outlet.

## التغيير والتحقق · Change and verification

1. Keep a contribution focused and explain its effect on users and evidence. For a behavior change, describe a concrete before/after case.
2. Edit source files first. Regenerate the affected website or local-client bundle using the instructions in the development guide; retain the matching build receipt when applicable.
3. Run checks appropriate to the changed component. Public-site checks do not exercise the local service, 3D camera or model inference.
4. For interface changes, check Arabic RTL, keyboard controls, a narrow viewport, reduced motion and unavailable/offline states. Preserve explicit simulation disclosures.
5. In a pull request, state the problem, final behavior, verification actually completed and any unresolved limitation. Link supporting evidence without changing historical results to match a new claim.

## الخصوصية والملكية · Privacy and rights

Do not commit credentials, `.env` files, databases, device identifiers, participant or customer data, private contacts, approvals, supplier quotations, copyrighted papers, or reference attachments without redistribution permission. Use synthetic fixtures for software tests. Keep private submission material outside the repository and publish a redacted evidence description only when authorized.

Public dataset access does not automatically permit redistribution. Record the source, license, required attribution and acquisition steps. Preserve third-party notices for fonts, libraries and assets; the repository license does not replace their terms. Do not load untrusted serialized model files.

## مواءمة التسليم · Submission alignment

[خريطة المخرجات](docs/judging-map.md) records the nine documented camp outputs and remaining gaps. It is a checklist of evidence, not a claim of submission, approval, scoring or completion. Do not add team details, customer interest, a confirmed site or a deadline that the evidence does not establish.
