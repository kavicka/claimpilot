"""Synthetic insured persons. Structured values come from code, never from a model."""

import random
import unicodedata
from datetime import date, timedelta

from faker import Faker

from claimpilot_core.identifiers import generate_rodne_cislo, generate_sk_iban
from claimpilot_datagen.model import Person

EMAIL_DOMAINS = ["posta.example.sk", "mail.example.sk", "example.com"]


def _ascii(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()


class PeopleFactory:
    def __init__(self, rng: random.Random) -> None:
        self.rng = rng
        self.sk = Faker("sk_SK")
        self.cz = Faker("cs_CZ")
        self.sk.seed_instance(rng.randrange(2**31))
        self.cz.seed_instance(rng.randrange(2**31))
        self._used_names: set[str] = set()

    def person(self, *, czech: bool = False, czech_offset: bool = False) -> Person:
        fk = self.cz if czech else self.sk
        rng = self.rng
        female = rng.random() < 0.5
        first = last = ""
        for _ in range(50):
            first = fk.first_name_female() if female else fk.first_name_male()
            last = fk.last_name_female() if female else fk.last_name_male()
            if f"{first} {last}" not in self._used_names:
                break
        self._used_names.add(f"{first} {last}")
        if czech_offset:
            born = date(2004, 1, 1) + timedelta(days=rng.randrange(0, 365 * 3))
        else:
            born = date(1956, 1, 1) + timedelta(days=rng.randrange(0, 365 * 46))
        rc = generate_rodne_cislo(born, female=female, rng=rng, czech_offset=czech_offset)
        city = fk.city()
        postcode = f"{rng.randrange(800, 999)} {rng.randrange(1, 99):02d}"
        phone = (
            f"+421 9{rng.randrange(0, 50):02d} {rng.randrange(100, 999)} {rng.randrange(100, 999)}"
        )
        email = f"{_ascii(first)}.{_ascii(last)}{rng.randrange(1, 99)}@{rng.choice(EMAIL_DOMAINS)}"
        letters = "ABCDEHJKLMNP"
        id_card = f"{rng.choice(letters)}{rng.choice(letters)}{rng.randrange(100000, 999999)}"
        return Person(
            first_name=first,
            last_name=last,
            female=female,
            birth_date=born,
            birth_number=rc,
            street=fk.street_address(),
            city=city,
            postcode=postcode,
            phone=phone,
            email=email,
            iban=generate_sk_iban(rng),
            id_card=id_card,
            czech=czech,
        )

    def local_name(self, faker_locale: str) -> str:
        fk = Faker(faker_locale)
        fk.seed_instance(self.rng.randrange(2**31))
        return f"{fk.first_name()} {fk.last_name()}"
