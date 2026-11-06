"""Interactive CLI editor for languages, tasks, weekdays, settings."""

from __future__ import annotations


class Editor:
    def __init__(self, db):
        self.db = db

    def run(self):
        while True:
            print()
            print("=" * 50)
            print(" LANGUAGE PLANNER - EDITOR")
            print("=" * 50)
            print()
            print("1. Languages")
            print("2. Tasks")
            print("3. Availability")
            print("4. Settings")
            print("5. Quit")
            print()

            choice = input("> ").strip()

            if choice == "1":
                self.languages_menu()
            elif choice == "2":
                self.tasks_menu()
            elif choice == "3":
                self.weekdays_menu()
            elif choice == "4":
                self.settings_menu()
            elif choice == "5":
                return

    # -- Languages ------------------------------------------------------

    def languages_menu(self):
        while True:
            print()
            print("LANGUAGES")
            print("-" * 50)

            for language in self.db.languages():
                print(f"{language['id']:>2} "
                      f"{language['name']:<15} "
                      f"{language['level']} -> "
                      f"{language['objective']:<8} "
                      f"{language['status']}")

            print()
            print("A = add   M = modify   D = delete   B = back")
            choice = input("> ").strip().lower()

            if choice == "a":
                self.add_language()
            elif choice == "m":
                self.edit_language()
            elif choice == "d":
                self.delete_language()
            elif choice == "b":
                return

    def add_language(self):
        print()
        print("NEW LANGUAGE")

        name = input("Name: ").strip()
        code = input("ISO code: ").strip()
        level = input("Current level: ").strip()
        objective = input("Goal: ").strip()
        status = (input(
            "Status [active/maintenance/waiting/paused]"
            " [active]: ").strip() or "active")
        priority = int(input("Priority [1]: ").strip() or "1")
        weight = float(input("Weight [1.0]: ").strip() or "1.0")
        target = int(input("Minutes/week [60]: ").strip() or "60")
        min_contacts = int(
            input("Min contacts/week [2]: ").strip() or "2")
        max_contacts = int(
            input("Max contacts/week [7]: ").strip() or "7")
        session = int(
            input("Main session minutes [45]: ").strip() or "45")

        self.db.execute(
            """
            INSERT INTO languages
            (name, code, level, objective, status, priority,
             weight, target_minutes_week, min_contacts_week,
             max_contacts_week, preferred_session_minutes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (name, code, level, objective, status, priority,
             weight, target, min_contacts, max_contacts, session),
        )
        self.db.commit()

    def edit_language(self):
        language_id = int(input("Language ID: "))
        row = self.db.execute(
            "SELECT * FROM languages WHERE id = ?",
            (language_id,)).fetchone()

        if not row:
            print("Unknown language.")
            return

        def value(field, cast=str):
            current = row[field]
            answer = input(f"{field} [{current}]: ").strip()
            return cast(answer) if answer else current

        self.db.execute(
            """
            UPDATE languages SET
                name = ?, code = ?, level = ?, objective = ?,
                status = ?, priority = ?, weight = ?,
                target_minutes_week = ?, min_contacts_week = ?,
                max_contacts_week = ?, preferred_session_minutes = ?
            WHERE id = ?
            """,
            (value("name"), value("code"), value("level"),
             value("objective"), value("status"),
             value("priority", int), value("weight", float),
             value("target_minutes_week", int),
             value("min_contacts_week", int),
             value("max_contacts_week", int),
             value("preferred_session_minutes", int),
             language_id),
        )
        self.db.commit()

    def delete_language(self):
        language_id = int(input("Language ID: "))
        if input("Delete? [y/N]: ").lower() != "y":
            return
        self.db.execute("DELETE FROM languages WHERE id = ?",
                        (language_id,))
        self.db.commit()

    # -- Tasks ------------------------------------------------------------

    def tasks_menu(self):
        while True:
            print()
            print("TASKS")
            print("-" * 50)

            for task in self.db.tasks():
                print(f"{task['id']:>2} {task['name']:<25} "
                      f"{task['duration_min']} min "
                      f"priority={task['priority']}")

            print()
            print("A = add   M = modify   D = delete   B = back")
            choice = input("> ").strip().lower()

            if choice == "a":
                self.add_task()
            elif choice == "m":
                self.edit_task()
            elif choice == "d":
                self.delete_task()
            elif choice == "b":
                return

    def add_task(self):
        name = input("Name: ")
        kind = input("Type: ")
        duration = int(input("Duration (minutes): "))
        minimum = int(input("Min/week [0]: ") or "0")
        maximum = int(input("Max/week [7]: ") or "7")
        priority = int(input("Priority [1]: ") or "1")
        main = int(input("Main session? [0/1]: ") or "0")
        description = input("Description: ")

        self.db.execute(
            """
            INSERT INTO tasks
            (name, kind, duration_min, min_per_week, max_per_week,
             priority, requires_main_session, description)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (name, kind, duration, minimum, maximum,
             priority, main, description),
        )
        self.db.commit()

    def edit_task(self):
        task_id = int(input("Task ID: "))
        row = self.db.execute(
            "SELECT * FROM tasks WHERE id = ?",
            (task_id,)).fetchone()

        if not row:
            print("Unknown task.")
            return

        fields = ["name", "kind", "duration_min", "min_per_week",
                  "max_per_week", "priority", "requires_main_session",
                  "description"]

        values = {}
        for field in fields:
            answer = input(f"{field} [{row[field]}]: ").strip()
            values[field] = answer if answer else row[field]

        self.db.execute(
            """
            UPDATE tasks SET
                name = ?, kind = ?, duration_min = ?,
                min_per_week = ?, max_per_week = ?, priority = ?,
                requires_main_session = ?, description = ?
            WHERE id = ?
            """,
            (values["name"], values["kind"],
             int(values["duration_min"]),
             int(values["min_per_week"]),
             int(values["max_per_week"]),
             int(values["priority"]),
             int(values["requires_main_session"]),
             values["description"], task_id),
        )
        self.db.commit()

    def delete_task(self):
        task_id = int(input("Task ID: "))
        if input("Delete? [y/N]: ").lower() != "y":
            return
        self.db.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        self.db.commit()

    # -- Weekdays -----------------------------------------------------------

    def weekdays_menu(self):
        while True:
            print()
            print("AVAILABILITY")

            for row in self.db.weekdays():
                print(f"{row['weekday']} {row['name']:<10} "
                      f"{row['available_minutes']} min"
                      f" at {row['start_time']}")

            print()
            print("M = modify   B = back")
            choice = input("> ").strip().lower()

            if choice == "m":
                self.edit_weekday()
            elif choice == "b":
                return

    def edit_weekday(self):
        weekday = int(input("Day [0=Monday ... 6=Sunday]: "))
        row = self.db.execute(
            "SELECT * FROM weekdays WHERE weekday = ?",
            (weekday,)).fetchone()
        if not row:
            return

        minutes = input(
            f"Minutes [{row['available_minutes']}]: ").strip()
        start = input(
            f"Start time [{row['start_time']}]: ").strip()
        enabled = input(f"Enabled [{row['enabled']}]: ").strip()
        main = input(
            f"Main session [{row['main_session_allowed']}]: ").strip()
        micro = input(
            f"Micro sessions [{row['micro_sessions_allowed']}]: "
        ).strip()

        self.db.execute(
            """
            UPDATE weekdays SET
                available_minutes = ?, start_time = ?,
                enabled = ?, main_session_allowed = ?,
                micro_sessions_allowed = ?
            WHERE weekday = ?
            """,
            (int(minutes or row["available_minutes"]),
             start or row["start_time"],
             int(enabled or row["enabled"]),
             int(main or row["main_session_allowed"]),
             int(micro or row["micro_sessions_allowed"]),
             weekday),
        )
        self.db.commit()

    # -- Settings --------------------------------------------------------

    def settings_menu(self):
        for key, current in self.db.settings().items():
            value = input(f"{key} [{current}]: ").strip()
            if value:
                self.db.set_setting(key, value)