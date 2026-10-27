"""Indicatifs : trouvés dans un texte décodé ou dans une phrase parlée, et leur pays.

- calls_in_text(texte) : texte CW/RTTY/PSK (« CQ DE F5ABC », « F5ABC DE DL1XYZ »).
- calls_in_speech(texte) : phrase transcrite par Whisper, indicatif épelé en
  alphabet international (Fox, Tango…), ancien alphabet français (Anatole,
  Berthe…) ou lettres et chiffres isolés, en français ou en anglais.
- country(indicatif) : pays (cty.dat de WSJT-X), en français pour les plus courants.
Un indicatif n'est gardé que si son pays est reconnu.
"""

import re
import unicodedata

from ft8_map import Locator

CALL = re.compile(r"^[A-Z0-9]{1,3}[0-9][A-Z0-9]{0,3}[A-Z](/[A-Z0-9]{1,4})?$")
TEXT_CALL = re.compile(r"\b([A-Z0-9]{1,3}[0-9][A-Z0-9]{0,3}[A-Z](?:/[A-Z0-9]{1,4})?)\b")
NOT_CALLS = {"5NN", "599", "73", "88", "TU", "QRZ", "CQ", "DE", "K", "KN", "BK", "SK", "AR"}

PHONETIC = {
    # alphabet international (et variantes entendues)
    "ALPHA": "A", "ALFA": "A", "BRAVO": "B", "CHARLIE": "C", "CHARLY": "C", "DELTA": "D",
    "ECHO": "E", "FOXTROT": "F", "FOX": "F", "GOLF": "G", "HOTEL": "H", "INDIA": "I",
    "JULIET": "J", "JULIETT": "J", "JULIETTE": "J", "KILO": "K", "LIMA": "L", "MIKE": "M",
    "NOVEMBER": "N", "NOVEMBRE": "N", "OSCAR": "O", "PAPA": "P", "QUEBEC": "Q",
    "ROMEO": "R", "SIERRA": "S", "TANGO": "T", "UNIFORM": "U", "UNIFORME": "U",
    "VICTOR": "V", "WHISKEY": "W", "WHISKY": "W", "XRAY": "X", "ZULU": "Z",
    "YANKEE": "Y",
    # ancien alphabet français
    "ANATOLE": "A", "BERTHE": "B", "CELESTIN": "C", "DESIRE": "D", "EUGENE": "E",
    "FRANCOIS": "F", "GASTON": "G", "HENRI": "H", "IRMA": "I", "JOSEPH": "J",
    "KLEBER": "K", "LOUIS": "L", "MARCEL": "M", "NICOLAS": "N", "PIERRE": "P",
    "QUINTAL": "Q", "RAOUL": "R", "SUZANNE": "S", "THERESE": "T", "URSULE": "U",
    "WILLIAM": "W", "XAVIER": "X", "YVONNE": "Y", "ZOE": "Z",
}
DIGITS = {
    "ZERO": "0", "OH": "0", "ONE": "1", "UN": "1", "UNE": "1", "TWO": "2", "DEUX": "2",
    "THREE": "3", "TROIS": "3", "FOUR": "4", "QUATRE": "4", "FIVE": "5", "CINQ": "5",
    "SIX": "6", "SEVEN": "7", "SEPT": "7", "EIGHT": "8", "HUIT": "8", "NINE": "9",
    "NEUF": "9", "NINER": "9",
}
FR_NAMES = {
    "France": "France", "Corsica": "Corse", "Fed. Rep. of Germany": "Allemagne",
    "England": "Angleterre", "Scotland": "Écosse", "Wales": "Pays de Galles",
    "Ireland": "Irlande", "Northern Ireland": "Irlande du Nord", "Spain": "Espagne",
    "Portugal": "Portugal", "Italy": "Italie", "Belgium": "Belgique",
    "Netherlands": "Pays-Bas", "Switzerland": "Suisse", "Luxembourg": "Luxembourg",
    "Austria": "Autriche", "Poland": "Pologne", "Czech Republic": "Tchéquie",
    "Slovak Republic": "Slovaquie", "Hungary": "Hongrie", "Romania": "Roumanie",
    "Bulgaria": "Bulgarie", "Greece": "Grèce", "Croatia": "Croatie", "Slovenia": "Slovénie",
    "Serbia": "Serbie", "European Russia": "Russie", "Asiatic Russia": "Russie (Asie)",
    "Ukraine": "Ukraine", "Belarus": "Biélorussie", "Lithuania": "Lituanie",
    "Latvia": "Lettonie", "Estonia": "Estonie", "Finland": "Finlande", "Sweden": "Suède",
    "Norway": "Norvège", "Denmark": "Danemark", "Iceland": "Islande",
    "Canary Islands": "Canaries", "Balearic Islands": "Baléares", "Sardinia": "Sardaigne",
    "Sicily": "Sicile", "Monaco": "Monaco", "Andorra": "Andorre", "Malta": "Malte",
    "United States": "États-Unis", "Canada": "Canada", "Brazil": "Brésil",
    "Argentina": "Argentine", "Japan": "Japon", "China": "Chine", "Australia": "Australie",
    "New Zealand": "Nouvelle-Zélande", "Israel": "Israël", "Turkey": "Turquie",
    "Morocco": "Maroc", "Algeria": "Algérie", "Tunisia": "Tunisie",
    "Reunion Island": "La Réunion", "Guadeloupe": "Guadeloupe", "Martinique": "Martinique",
    "French Guiana": "Guyane", "Mayotte": "Mayotte", "New Caledonia": "Nouvelle-Calédonie",
    "French Polynesia": "Polynésie française", "St. Pierre & Miquelon": "Saint-Pierre-et-Miquelon",
    "South Africa": "Afrique du Sud", "India": "Inde", "Mexico": "Mexique",
}

_LOC = None


def _locator():
    global _LOC
    if _LOC is None:
        _LOC = Locator()
    return _LOC


def country(call):
    """Pays de l'indicatif (en français si connu), ou None."""
    name = _locator().country(call.upper())
    return FR_NAMES.get(name, name) if name else None


def valid(call):
    call = call.upper()
    return bool(CALL.match(call)) and call not in NOT_CALLS and country(call) is not None


def calls_in_text(text):
    """Indicatifs d'un texte décodé : celui après « DE » en premier (l'émetteur)."""
    up = text.upper()
    found = []
    for m in re.finditer(r"\bDE\s+([A-Z0-9/]{3,12})", up):
        if valid(m.group(1)) and m.group(1) not in found:
            found.append(m.group(1))
    for call in TEXT_CALL.findall(up):
        if valid(call) and call not in found:
            found.append(call)
    return found


def _plain(text):
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c)).upper()
    return re.sub(r"X[- ]RAY", "XRAY", text)


def calls_in_speech(text):
    """Indicatifs épelés dans une phrase transcrite (« Fox 4 Tango X-ray Romeo »,
    « F4TXR », « effe quatre… »). Le plus long indicatif valide de chaque suite."""
    out = []
    for chunk in re.split(r"[,.;:!?]", _plain(text)):     # la ponctuation coupe un épellement
        for call in _spoken_chunk(re.findall(r"[A-Z0-9]+", chunk)):
            if call not in out:
                out.append(call)
    return out


SHORT_WORDS = {"A", "Y", "I", "O", "E"}  # « à », « il y a », « I »… : lettre seulement si épelée


def _spelled(w):
    return w in PHONETIC or w in DIGITS or (len(w) == 1 and w not in SHORT_WORDS) \
        or (w.isdigit() and len(w) <= 2)


def _spoken_chunk(words):
    out = []
    run = []                            # suite de lettres/chiffres épelés

    def flush():
        s = "".join(run)
        run.clear()
        best = None
        for i in range(len(s)):
            for j in range(len(s), i + 2, -1):
                if valid(s[i:j]) and (best is None or j - i > len(best)):
                    best = s[i:j]
        if best and best not in out:
            out.append(best)

    for k, w in enumerate(words):
        nxt = words[k + 1] if k + 1 < len(words) else ""
        if w in PHONETIC:
            run.append(PHONETIC[w])
        elif w in DIGITS:
            run.append(DIGITS[w])
        elif len(w) == 1 and (w not in SHORT_WORDS or (run and _spelled(nxt))):
            run.append(w)               # lettre ou chiffre dit seul
        elif CALL.match(w) and valid(w):
            flush()
            if w not in out:
                out.append(w)
        elif w.isdigit() and len(w) <= 2:
            run.append(w)
        else:
            flush()
    flush()
    return out


if __name__ == "__main__":
    for t in ("CQ CQ DE F5ABC F5ABC K", "DL1XYZ DE EA8ABC 599 TU",
              "Ici Fox 4 Tango X-ray Romeo, à vous", "this is Kilo One Alpha Bravo Charlie",
              "F six Anatole Berthe Célestin de F4TXR", "bonjour Marcel, il fait beau"):
        print(t, "→", calls_in_text(t) or calls_in_speech(t),
              [country(c) for c in (calls_in_text(t) or calls_in_speech(t))])
