"""Spoken assistant replies for the TTS benchmark. Invented product names only.

Each item: (id, lang, text). lang: en, he, mix.
Numbers, dates and money are written as digits; the scorer normalises spoken forms.
"""

TTS_CORPUS = [
    ("en01", "en", "The build for Quillfox finished and all 212 tests passed."),
    ("en02", "en", "I opened a PR against dev and it is waiting for your review."),
    ("en03", "en", "Staging is healthy, but the Brindle API returned errors twice in the last 10 minutes."),
    ("en04", "en", "The invoice total is $4,250 and it is due on March 14th."),
    ("en05", "en", "Do you want me to deploy Nimbus Ledger to staging now, or wait until after lunch?"),
    ("en06", "en", "I found 3 failing checks. Two are flaky and one is a real type error in the pricing module."),
    ("en07", "en", "The migration will take about 45 seconds and will not lock the orders table."),
    ("en08", "en", "Done. I merged the branch and deleted it."),
    ("he01", "he", "הבנייה של הפרויקט הסתיימה בהצלחה וכל 212 הבדיקות עברו."),
    ("he02", "he", "פתחתי בקשת מיזוג והיא מחכה לסקירה שלך."),
    ("he03", "he", "הסביבה תקינה, אבל השרת החזיר שגיאות פעמיים ב-10 הדקות האחרונות."),
    ("he04", "he", "סכום החשבונית הוא 4,250 שקלים והיא לתשלום עד ה-14 במרץ."),
    ("he05", "he", "אתה רוצה שאעלה את הגרסה עכשיו, או שנחכה עד אחרי ארוחת הצהריים?"),
    ("he06", "he", "מצאתי 3 בדיקות שנכשלו. שתיים לא יציבות ואחת היא שגיאה אמיתית בחישוב המחיר."),
    ("he07", "he", "ההעברה תיקח בערך 45 שניות ולא תנעל את טבלת ההזמנות."),
    ("he08", "he", "סיימתי. מיזגתי את הענף ומחקתי אותו."),
    ("mx01", "mix", "ה-build של Quillfox הסתיים וכל 212 ה-tests עברו."),
    ("mx02", "mix", "פתחתי PR מול dev והוא מחכה ל-review שלך."),
    ("mx03", "mix", "ה-staging תקין, אבל ה-Brindle API החזיר שגיאות פעמיים ב-10 הדקות האחרונות."),
    ("mx04", "mix", "ה-invoice על $4,250 והוא לתשלום עד ה-14 במרץ."),
    ("mx05", "mix", "אתה רוצה שאעשה deploy של Nimbus Ledger ל-staging עכשיו או אחרי הצהריים?"),
    ("mx06", "mix", "מצאתי 3 checks שנכשלו, ואחד מהם הוא type error אמיתי ב-pricing module."),
    ("mx07", "mix", "ה-migration ייקח בערך 45 שניות ולא ינעל את ה-table של ההזמנות."),
    ("mx08", "mix", "עשיתי merge ל-branch של Orbitkit ומחקתי אותו, המחיר החדש הוא 1,200 שקלים לחודש."),
]
SAMPLE_IDS = {"en": "en04", "he": "he04", "mix": "mx04"}
