from datetime import datetime, timedelta

def calculate_sm2(quality: int, repetitions: int, easiness: float, interval: int):
    if quality < 3:
        repetitions = 0
        interval = 0
    else:
        if repetitions == 0:
            interval = 1
        elif repetitions == 1:
            interval = 3
        else:
            interval = round(interval * easiness)
        repetitions += 1

    easiness = easiness + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
    if easiness < 1.3:
        easiness = 1.3

    if interval == 0:
        next_review = datetime.utcnow() + timedelta(minutes=15)
    else:
        next_review = datetime.utcnow() + timedelta(days=interval)

    return repetitions, easiness, interval, next_review

def normalize_text(text: str) -> str:
    return " ".join(text.strip().lower().split())