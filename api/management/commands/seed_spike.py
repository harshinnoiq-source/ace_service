from django.core.management.base import BaseCommand
from django.db import transaction
from api.models import SpikeQuestion as Q, SpikeOption as O

NS = ("not_sure", "Not sure")

# option_id -> icon URL (replace with your real URLs)
ICONS = {
    "low.root.meal":        "meal",
    "low.root.medication":  "medication",
    "low.root.activity":    "activity",
    "low.root.alcohol":     "alcohol",
    "low.root.other":       "other",
    "high.root.meal":       "meal",
    "high.root.medication": "medication",
    "high.root.inactivity": "inactivity",
    "high.root.stress":     "stress",
    "high.root.other":      "other",
}

# questions that appear only after a specific answer
FOLLOW_UPS = {"low.med.which", "high.stress.level"}

FLOW = {
    # ---------------- LOW ----------------
    "low.root": dict(q="What was happening before this reading?", start=True, opts=[
         #short name   "label                                    next question
        ("meal", "Delayed/skipped meal or ate less than usual", "low.meal.last_eaten"),
        ("medication", "Insulin or glucose-lowering medication", "low.med.type"),
        ("activity", "More activity than usual", "low.activity.type"),
        ("alcohol", "Alcohol", "low.alcohol.last_drink"),
        ("other", "Other", "low.other.details")]),
    "low.meal.last_eaten": dict(q="When did you last eat before this reading?", opts=[
        ("lt_2h", "Less than 2 hours before", "low.meal.changed"),
        ("2_4h", "2-4 hours before", "low.meal.changed"),
        ("gt_4h", "More than 4 hours before", "low.meal.changed"),
        NS + ("low.meal.changed",)]),
    "low.meal.changed": dict(q="What changed about your meal?", opts=[
        ("skipped", "Skipped a meal", "low.meal.carbs"),
        ("late", "Ate later than usual", "low.meal.carbs"),
        ("less", "Ate less than usual", "low.meal.carbs"),
        ("other", "Other", "low.meal.carbs"),
        NS + ("low.meal.carbs",)]),
    "low.meal.carbs": dict(q="Was the meal lower in carbohydrates than usual?", opts=[
        ("yes", "Yes", None), ("no", "No", None),
        ("no_meal", "I did not eat", None), NS + (None,)]),
    "low.med.type": dict(q="What medication did you take before this reading?", opts=[
        ("insulin", "Insulin", "low.med.routine"),
        ("other_med", "Another glucose-lowering medication", "low.med.routine"),
        ("both", "Both", "low.med.which"),
        NS + ("low.med.routine",),
        ("prefer_not", "Prefer not to answer", "low.med.routine")]),
    "low.med.which": dict(q="Which medication?", text=True, nxt="low.med.routine"),
    "low.med.routine": dict(q="Was anything different from your usual medication routine?", opts=[
        ("no_change", "No change", None), ("timing", "Different timing", None),
        ("amount", "Different amount", None), ("extra", "Possible extra dose", None),
        NS + (None,)]),
    "low.activity.type": dict(q="What activity did you do before this reading?", opts=[
        ("walking", "Walking", "low.activity.finished"),
        ("exercise", "Exercise or sport", "low.activity.finished"),
        ("work", "Physical work or housework", "low.activity.finished"),
        ("other", "Other", "low.activity.finished"),
        NS + ("low.activity.finished",)]),
    "low.activity.finished": dict(q="When did the activity finish?", opts=[
        ("lt_2h", "Less than 2 hours before", None), ("2_6h", "2-6 hours before", None),
        ("gt_6h", "More than 6 hours before", None), ("ongoing", "Still active at the time", None),
        NS + (None,)]),
    "low.alcohol.last_drink": dict(q="When did you last drink alcohol before this reading?", opts=[
        ("lt_2h", "Within 2 hours", "low.alcohol.food"),
        ("2_12h", "2-12 hours before", "low.alcohol.food"),
        ("gt_12h", "More than 12 hours before", "low.alcohol.food"),
        NS + ("low.alcohol.food",)]),
    "low.alcohol.food": dict(q="Did you eat while or after drinking?", opts=[
        ("yes", "Yes", "low.alcohol.amount"), ("no", "No", "low.alcohol.amount"),
        NS + ("low.alcohol.amount",)]),
    "low.alcohol.amount": dict(q="Approximately how much did you drink?", text=True),
    "low.other.details": dict(q="What else was happening before this reading?", text=True,
                              nxt="low.other.when"),
    "low.other.when": dict(q="When did this happen relative to the reading?", opts=[
        ("lt_2h", "Less than 2 hours before", None), ("2_6h", "2-6 hours before", None),
        NS + (None,)]),
    # ---------------- HIGH ----------------
    # ---------------- HIGH ----------------
    "high.root": dict(q="What was happening before this reading?", start=True, opts=[
        ("meal", "Meal, snack, or sugary drink", "high.meal.when"),
        ("medication", "Missed/delayed medication", "high.med.which"),
        ("inactivity", "Less activity than usual", "high.activity.what"),
        ("stress", "Stress, illness, or poor sleep", "high.stress.which"),
        ("other", "Other", "high.other.details")]),

    # --- Meal ---
    "high.meal.when": dict(q="When did you eat or drink relative to this reading?", opts=[
        ("lt_1h", "Less than 1 hour before", "high.meal.what"),
        ("1_2h", "1-2 hours before", "high.meal.what"),
        ("gt_2h", "More than 2 hours before", "high.meal.what"),
        ("after", "After this reading", "high.meal.what"),
        NS + ("high.meal.what",)]),
    "high.meal.what": dict(q="What did you eat or drink?", text=True, nxt="high.meal.carbs", opts=[
        NS + ("high.meal.carbs",)]),
    "high.meal.carbs": dict(q="Approximately how much carbohydrate did it contain?", opts=[
        ("low", "Low (<20 g)", None),
        ("moderate", "Moderate (20-60 g)", None),
        ("high", "High (>60 g)", None),
        NS + (None,)]),

    # --- Medication ---
    "high.med.which": dict(q="Which medication was missed or delayed?", opts=[
        ("insulin", "Insulin", "high.med.dose"),
        ("other_med", "Another glucose-lowering medication", "high.med.dose"),
        ("both", "Both", "high.med.dose"),
        NS + ("high.med.dose",)]),
    "high.med.dose": dict(q="What happened with the planned dose?", opts=[
        ("not_taken", "Not taken", "high.med.scheduled"),
        ("late", "Taken later than planned", "high.med.scheduled"),
        ("unsure", "Unsure whether it was taken", "high.med.scheduled"),
        ("other", "Other", "high.med.scheduled")]),
    "high.med.scheduled": dict(q="When was it scheduled relative to this reading?",
                               text=True, nxt="high.med.actual"),
    "high.med.actual": dict(q="If taken later: When did you actually take it?", text=True, opts=[
        NS + (None,)]),

    # --- Less activity ---
    "high.activity.what": dict(q="What changed about your activity before this reading?", opts=[
        ("skipped", "Skipped usual exercise", "high.activity.when"),
        ("less_walk", "Less walking or movement", "high.activity.when"),
        ("sitting", "More sitting than usual", "high.activity.when"),
        ("other", "Other", "high.activity.when"),
        NS + ("high.activity.when",)]),
    "high.activity.when": dict(q="When did this change happen?", opts=[
        ("today", "Earlier that day", "high.activity.why"),
        ("yesterday", "Previous day", "high.activity.why"),
        ("days", "Over several days", "high.activity.why"),
        NS + ("high.activity.why",)]),
    "high.activity.why": dict(q="What contributed to the change?", opts=[
        ("schedule", "Schedule", None),
        ("unwell", "Feeling unwell", None),
        ("injury", "Injury or pain", None),
        ("travel", "Travel", None),
        ("other", "Other", None),
        ("prefer_not", "Prefer not to answer", None)]),

    # --- Stress, illness, or poor sleep ---
    "high.stress.which": dict(q="Which were you experiencing before this reading?",
                              desc="Select all that apply",
                              multi=True, nxt="high.stress.level", opts=[
            ("stress", "Stress", None), ("illness", "Illness", None),
            ("sleep", "Poor sleep", None), ("other", "Other", None)]),
    "high.stress.level": dict(q="If stress: How stressed did you feel?", opts=[
        ("little", "A little", "high.stress.symptoms"),
        ("moderate", "Moderately", "high.stress.symptoms"),
        ("very", "Very", "high.stress.symptoms")]),
    "high.stress.symptoms": dict(q="If illness: What symptoms were you experiencing?",
                                 desc="Select all that apply",
                                 multi=True, nxt="high.stress.sleep", opts=[
            ("fever", "Fever", None), ("cold", "Cold or flu symptoms", None),
            ("pain", "Pain", None), ("stomach", "Stomach symptoms", None),
            ("other", "Other", None)]),
    "high.stress.sleep": dict(q="If poor sleep: How was your sleep compared with usual?", opts=[
        ("shorter", "Shorter", "high.stress.start"),
        ("interrupted", "More interrupted", "high.stress.start"),
        ("both", "Both", "high.stress.start"),
        ("same", "About the same", "high.stress.start"),
        NS + ("high.stress.start",)]),
    "high.stress.start": dict(q="When did this start?", text=True),

    # --- Other ---
    "high.other.details": dict(q="What else was happening before this reading?", text=True,
                               nxt="high.other.when", opts=[
            ("prefer_not", "Prefer not to answer", "high.other.when")]),
    "high.other.when": dict(q="When did this happen relative to the reading?", text=True, opts=[
        NS + (None,)]),
}

DESC = "This helps us provide more accurate insights"


class Command(BaseCommand):
    help = "Seed the LOW/HIGH spike questionnaires (safe to run repeatedly)"

    @transaction.atomic
    def handle(self, *args, **opts):
        objs = {}
        for qid, d in FLOW.items():                       # pass 1: questions
            objs[qid], _ = Q.objects.update_or_create(
                question_id=qid,
                defaults=dict(
                    event_type=qid.split(".")[0].upper(), question=d["q"], desc=DESC,
                    is_text_allow=d.get("text", False),
                    is_multiple_choice_allow=d.get("multi", False),
                    is_follow_up=qid in FOLLOW_UPS,
                    is_start=d.get("start", False), is_active=True, next_question=None))
        for qid, d in FLOW.items():                       # pass 2: links + options
            if d.get("nxt"):
                objs[qid].next_question = objs[d["nxt"]]
                objs[qid].save()
            for i, (key, label, nxt) in enumerate(d.get("opts", [])):
                oid = f"{qid}.{key}"
                defaults = dict(question=objs[qid], label=label, desc="", order=i,
                                next_question=objs[nxt] if nxt else None)
                if oid in ICONS:
                    defaults["icon_url"] = ICONS[oid]
                O.objects.update_or_create(option_id=oid, defaults=defaults)
        self.stdout.write(self.style.SUCCESS(
            f"{Q.objects.count()} questions, {O.objects.count()} options"))