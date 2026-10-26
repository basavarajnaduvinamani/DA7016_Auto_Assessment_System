"""Small, idempotent synthetic demo data."""

from autoassess.web.store import Store


def seed(store: Store, reset: bool = False):
    with store.connect() as db:
        if reset:
            db.execute("DELETE FROM classes")
            db.execute("DELETE FROM teachers")
        if db.execute("SELECT 1 FROM teachers LIMIT 1").fetchone():
            return
        teacher = db.execute("INSERT INTO teachers(name,email) VALUES(?,?)", ("Demo Teacher", "demo@redink.local")).lastrowid
        classroom = db.execute("INSERT INTO classes(teacher_id,name,subject,section) VALUES(?,?,?,?)",
                               (teacher, "DA7016 Generative AI, Section A", "Generative AI", "A")).lastrowid
        db.executemany("INSERT INTO students(class_id,roll_no,name) VALUES(?,?,?)",
                       [(classroom, f"S{i:03}", f"Sample Student {i:02}") for i in range(1, 11)])


def seed_assignment(store: Store):
    """Pre-grade only synthetic packaged samples, always with the offline fake."""
    import shutil

    from autoassess.config import Settings
    from autoassess.demo import SAMPLE
    from autoassess.spec_builder import load_spec
    from autoassess.web.grading import fake_settings, grade_submission

    teacher = store.teacher_by_email('demo@redink.local')
    if teacher is None:
        return
    classes = store.classes(teacher['id'])
    classroom = next((c for c in classes if c['name'] == 'DA7016 Generative AI, Section A'), None)
    if classroom is None or any(a['is_demo'] for a in store.assignments(classroom['id'])):
        return
    assignment_id = store.create_assignment(classroom['id'], 'Generative AI · Sample quiz', load_spec(SAMPLE / 'exam_spec.yaml'), is_demo=True)
    folder = store.root / 'files' / str(assignment_id)
    folder.mkdir(parents=True, exist_ok=True)
    students = {s['roll_no']: s['id'] for s in store.students(classroom['id'])}
    sources = [(f'S00{i}.txt', f'S00{i}') for i in (1, 2, 3)]
    settings = Settings.load()
    if settings.ocr_provider != 'text' or settings.ocr_key or settings.vision_model:
        sources.append(('S002_scan.pdf', 'S004'))
    for filename, roll in sources:
        source = SAMPLE / 'answer_sheets' / filename
        target = folder / filename
        shutil.copyfile(source, target)
        submission_id = store.add_submissions(assignment_id, [(students[roll], filename, target)])[0]
        store.queue_assignment(assignment_id)
        job_id = next(s['job_id'] for s in store.submissions(assignment_id) if s['id'] == submission_id)
        store.claim_job(job_id)
        # The optional synthetic scan uses its known paired transcript for seed
        # grading; startup must never send even a sample to a hosted OCR service.
        paired = SAMPLE / 'answer_sheets/S002.txt' if filename.endswith('.pdf') else source
        grade, run_json, artifacts = grade_submission(store, submission_id, settings=fake_settings(), source=paired)
        store.complete_job(job_id, grade, run_json, artifacts)
