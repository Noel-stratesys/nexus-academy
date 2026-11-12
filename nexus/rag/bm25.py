"""BM25: búsqueda por palabras, sin modelo y siempre con el mismo resultado.

Puntúa cada chunk según cuántas palabras de la pregunta contiene, dando más peso a
las palabras raras en la colección y menos a los chunks muy largos.
"""

import math
import re
import unicodedata
from collections import Counter
from collections.abc import Sequence

STOPWORDS = set(
    "a al algo con de del el en es la las lo los me mi no o para pero por que se si sin "
    "su sus un una uno y ya mas muy hay puedo puede como cual cuando donde esta este esto "
    "the and or of to in is it can i my el la els les i amb per que un una de del".split()
)


def tokenize(text: str) -> list[str]:
    normalized = unicodedata.normalize("NFKD", text.lower())
    plain = "".join(char for char in normalized if not unicodedata.combining(char))
    return [word for word in re.findall(r"[a-z0-9]+", plain) if word not in STOPWORDS]


class BM25:
    def __init__(self, texts: Sequence[str], k1: float = 1.5, b: float = 0.75) -> None:
        self.k1, self.b = k1, b
        self.docs = [Counter(tokenize(text)) for text in texts]
        self.lengths = [sum(doc.values()) for doc in self.docs]
        self.avg_length = sum(self.lengths) / max(len(self.lengths), 1)
        frequencies = Counter(word for doc in self.docs for word in doc)
        total = len(self.docs)
        self.idf = {
            word: math.log(1 + (total - count + 0.5) / (count + 0.5))
            for word, count in frequencies.items()
        }

    def scores(self, query: str) -> list[float]:
        words = tokenize(query)
        results = []
        for doc, length in zip(self.docs, self.lengths, strict=True):
            score = 0.0
            for word in words:
                frequency = doc.get(word, 0)
                if frequency:
                    norm = self.k1 * (1 - self.b + self.b * length / self.avg_length)
                    score += self.idf[word] * frequency * (self.k1 + 1) / (frequency + norm)
            results.append(score)
        return results
