"""
Challenge phrases for voice biometrics enrollment and verification.

These are used in challenge-response authentication:
  1. System randomly picks a phrase and plays it via Sarvam TTS
  2. User repeats the phrase
  3. System checks: (a) did they say the right words? (b) is it their voice?

Phrases are chosen to:
  - Be phonetically diverse (different vowels, consonants, prosody)
  - Be natural and memorable for rural Indian users
  - Be short enough to speak in under 5 seconds
  - Cover a range of common sounds in each language
"""

import random

# Phrases stored as romanised transliteration (for STT comparison)
# and in Devanagari/native script (for TTS rendering via Sarvam)
CHALLENGE_PHRASES = {
    "hi": [
        {"text": "aaj mausam bahut achha hai", "display": "आज मौसम बहुत अच्छा है"},
        {"text": "mujhe apne ghar se pyaar hai", "display": "मुझे अपने घर से प्यार है"},
        {"text": "hamaara desh bahut sundar hai", "display": "हमारा देश बहुत सुंदर है"},
        {"text": "subah jaldi uthna achha hota hai", "display": "सुबह जल्दी उठना अच्छा होता है"},
        {"text": "paani peena sehat ke liye zaroori hai", "display": "पानी पीना सेहत के लिए जरूरी है"},
        {"text": "mehnat karna safalta ki kunji hai", "display": "मेहनत करना सफलता की कुंजी है"},
        {"text": "phool baag mein khilte hain", "display": "फूल बाग में खिलते हैं"},
        {"text": "bachche padhne mein hoshiyaar hain", "display": "बच्चे पढ़ने में होशियार हैं"},
        {"text": "naya din nayi umeed laata hai", "display": "नया दिन नई उम्मीद लाता है"},
        {"text": "khana khaakar so jaana chahiye", "display": "खाना खाकर सो जाना चाहिए"},
        {"text": "gaon mein ped bahut hain", "display": "गांव में पेड़ बहुत हैं"},
        {"text": "baarish mein bheegna achha lagta hai", "display": "बारिश में भीगना अच्छा लगता है"},
    ],
    "en": [
        {"text": "the weather is very pleasant today", "display": "the weather is very pleasant today"},
        {"text": "I love spending time with my family", "display": "I love spending time with my family"},
        {"text": "hard work always pays off in the end", "display": "hard work always pays off in the end"},
        {"text": "the sun rises in the east every morning", "display": "the sun rises in the east every morning"},
        {"text": "drinking clean water is good for health", "display": "drinking clean water is good for health"},
        {"text": "flowers bloom beautifully in the garden", "display": "flowers bloom beautifully in the garden"},
        {"text": "children learn quickly when they are happy", "display": "children learn quickly when they are happy"},
        {"text": "a new day brings new opportunities for everyone", "display": "a new day brings new opportunities for everyone"},
        {"text": "the village has many tall trees around it", "display": "the village has many tall trees around it"},
        {"text": "rain makes the fields green and lush", "display": "rain makes the fields green and lush"},
    ],
    "ta": [
        {"text": "inru vaanam miga azhagaaga irukkirathu", "display": "இன்று வானம் மிக அழகாக இருக்கிறது"},
        {"text": "en kudumbam enakku romba piriyam", "display": "என் குடும்பம் எனக்கு ரொம்ப பிரியம்"},
        {"text": "kattumai vaazhkaikku vazhivaakkum", "display": "கட்டுமை வாழ்க்கைக்கு வழிவாக்கும்"},
        {"text": "pookkal thottathil malarum", "display": "பூக்கள் தோட்டத்தில் மலரும்"},
        {"text": "thaaniyam kudippathu udalukkku nallathu", "display": "தண்ணீர் குடிப்பது உடலுக்கு நல்லது"},
    ],
    "te": [
        {"text": "nenu naa kutumbaanni prema istanu", "display": "నేను నా కుటుంబాన్ని ప్రేమిస్తాను"},
        {"text": "indu champula vana chala azhangaa undi", "display": "ఇందు చంపుల వనం చాలా అందంగా ఉంది"},
        {"text": "kasi cheyyatam vijayaniki chaabhi", "display": "కష్టపడటం విజయానికి చాబీ"},
        {"text": "paata roju kaaveri aandi", "display": "పాత రోజు కావేరి అంది"},
        {"text": "tagina neellu tagadam arogyaniki manchidi", "display": "తగినంత నీళ్ళు తాగడం ఆరోగ్యానికి మంచిది"},
    ],
    "kn": [
        {"text": "namma ooru thumba chenna agi ide", "display": "ನಮ್ಮ ಊರು ತುಂಬ ಚೆನ್ನಾಗಿ ಇದೆ"},
        {"text": "kashta padodu yashassige daari", "display": "ಕಷ್ಟ ಪಡೋದು ಯಶಸ್ಸಿಗೆ ದಾರಿ"},
        {"text": "neeru kudiyuvudu arogyakke olleidu", "display": "ನೀರು ಕುಡಿಯುವುದು ಆರೋಗ್ಯಕ್ಕೆ ಒಳ್ಳೆಯದು"},
    ],
    "ml": [
        {"text": "ente veettu priyappettathu", "display": "എൻ്റെ വീടിനോട് ഇഷ്ടമാണ്"},
        {"text": "arogyanikku vellam kudikkuka", "display": "ആരോഗ്യത്തിനു വെള്ളം കുടിക്കുക"},
    ],
    "mr": [
        {"text": "aaj havaaman khup chaan aahe", "display": "आज हवामान खूप छान आहे"},
        {"text": "majhya ghara baddal mala prem aahe", "display": "माझ्या घराबद्दल मला प्रेम आहे"},
        {"text": "kaashtakar mahnat karto", "display": "कष्टकरी माणूस मेहनत करतो"},
    ],
    "bn": [
        {"text": "aaj aabohawa khub sundor", "display": "আজ আবহাওয়া খুব সুন্দর"},
        {"text": "amar paribarkke ami bhalobashi", "display": "আমার পরিবারকে আমি ভালোবাসি"},
    ],
    "gu": [
        {"text": "aaje havaman khub saras chhe", "display": "આજ હવામાન ખૂબ સારું છે"},
        {"text": "mane mara parivar par prem chhe", "display": "મને મારા પરિવાર પર પ્રેમ છે"},
    ],
}

# Sarvam language codes (for TTS API)
SARVAM_LANG_CODE = {
    "hi": "hi-IN",
    "en": "en-IN",
    "ta": "ta-IN",
    "te": "te-IN",
    "kn": "kn-IN",
    "ml": "ml-IN",
    "mr": "mr-IN",
    "bn": "bn-IN",
    "gu": "gu-IN",
}


def get_challenge_phrase(language: str, exclude_texts: list = None) -> dict:
    """
    Pick a random challenge phrase for the given language.

    Args:
        language:      Language code (hi, en, ta, etc.)
        exclude_texts: List of phrase texts already used — avoids repeating the same phrase
                       during multi-sample enrollment.

    Returns:
        Dict with "text" (romanised, for STT comparison) and "display" (native script, for TTS)
    """
    phrases = CHALLENGE_PHRASES.get(language, CHALLENGE_PHRASES["hi"])

    if exclude_texts:
        candidates = [p for p in phrases if p["text"] not in exclude_texts]
        if not candidates:
            candidates = phrases  # if we've used all, repeat

        return random.choice(candidates)

    return random.choice(phrases)


def get_enrollment_phrases(language: str, count: int = 3) -> list:
    """
    Pick `count` distinct phrases for enrollment.
    Returns a list of dicts with "text" and "display" keys.
    """
    phrases = CHALLENGE_PHRASES.get(language, CHALLENGE_PHRASES["hi"])
    count = min(count, len(phrases))
    return random.sample(phrases, count)
