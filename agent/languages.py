"""Supported voice languages shared by speech and answer generation."""

VOICE_LANGUAGES = {
    "en-IN": "English",
    "hi-IN": "Hindi",
    "pa-IN": "Punjabi",
    "bn-IN": "Bengali",
    "gu-IN": "Gujarati",
    "kn-IN": "Kannada",
    "ml-IN": "Malayalam",
    "mr-IN": "Marathi",
    "od-IN": "Odia",
    "ta-IN": "Tamil",
    "te-IN": "Telugu",
}


def spoken_text(text: str) -> str:
    """Replace em dashes, which Chanakya never says or writes, with a comma pause."""
    return text.replace(" — ", ", ").replace("—", ", ")
