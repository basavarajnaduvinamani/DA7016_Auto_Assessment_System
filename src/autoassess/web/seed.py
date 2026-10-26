"""Small, idempotent synthetic demo data."""

from autoassess.web.store import Store


def seed(store: Store, reset: bool = False):
    with store.connect() as db:
        if reset:
            db.execute("DELETE FROM students")
            db.execute("DELETE FROM classes")
            db.execute("DELETE FROM teachers")
        if db.execute("SELECT 1 FROM teachers LIMIT 1").fetchone():
            return
        teacher = db.execute("INSERT INTO teachers(name,email) VALUES(?,?)", ("Demo Teacher", "demo@redink.local")).lastrowid
        classroom = db.execute("INSERT INTO classes(teacher_id,name,subject,section) VALUES(?,?,?,?)",
                               (teacher, "DA7016 Generative AI, Section A", "Generative AI", "A")).lastrowid
        db.executemany("INSERT INTO students(class_id,roll_no,name) VALUES(?,?,?)",
                       [(classroom, f"S{i:03}", f"Sample Student {i:02}") for i in range(1, 11)])
