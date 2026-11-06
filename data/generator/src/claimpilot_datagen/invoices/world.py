"""The fictional world of the invoice set: one pharmacy group, twelve suppliers, a catalogue.

Every name is made up; identifiers pass their check digits and belong to no one (ADR-006).
"""

import random
from dataclasses import dataclass
from decimal import Decimal

from faker import Faker

from claimpilot_core.identifiers import format_iban, generate_sk_iban, iban_from_bban
from claimpilot_core.trade_ids import generate_ean13, generate_ico, generate_sk_dic
from claimpilot_datagen.invoices.model import Layout, Party, Product

CZ_BANK_CODES = ["0100", "0300", "0800", "2010", "2700", "5500", "6100"]

BUYERS = [  # (key, name, street, zip, city)
    ("central", "Lekárne Sever s.r.o.", "Cesta mieru 14", "831 04", "Bratislava"),
    ("retail", "Lekárne Sever Retail s.r.o.", "Hlavná 52", "040 01", "Košice"),
]
DELIVERY_POINTS = [
    "Lekárne Sever – sklad Senec, Logistická 7, 903 01 Senec",
    "Lekárne Sever – sklad Košice, Priemyselná 3, 040 17 Košice",
    "Lekáreň Sever e-shop (hala 4), Logistická 9, 903 01 Senec",
]

# (key, name, country, layout)
SUPPLIERS = [
    ("medika", "Medika Distribúcia a.s.", "SK", Layout.WHOLESALE),
    ("zdravex", "Zdravex Pharma s.r.o.", "SK", Layout.WHOLESALE),
    ("farmont", "Farmont Slovakia a.s.", "SK", Layout.WHOLESALE),
    ("lumina", "Lumina Cosmetics CZ s.r.o.", "CZ", Layout.SAP),
    ("aurelle", "Aurelle Beauty CZ s.r.o.", "CZ", Layout.SAP),
    ("vitalis", "Vitalis Trade s.r.o.", "SK", Layout.TANGRAM),
    ("nutrisk", "NutriSK s.r.o.", "SK", Layout.TANGRAM),
    ("bioflora", "BioFlora s.r.o.", "SK", Layout.POHODA),
    ("herbana", "Herbana Natur s.r.o.", "SK", Layout.POHODA),
    ("rosalia", "Rosalia Kozmetik s.r.o.", "SK", Layout.POHODA),
    ("novamed", "Novamed Pharma CZ s.r.o.", "CZ", Layout.SCAN_EN),
    ("enzymo", "Enzymo Health CZ s.r.o.", "CZ", Layout.SCAN_EN),
]
BANKS = {
    "SK": [("Banka Dunaj a.s.", "DUNASKBX"), ("Hronská banka a.s.", "HRONSKBX")],
    "CZ": [("Vltava banka a.s.", "VLTBCZPP"), ("Bečva banka a.s.", "BECVCZPP")],
}

ORIGIN = {"858": "SK", "859": "CZ", "400": "DE", "380": "BG", "300": "FR", "471": "TW"}
BRANDS = ["Herbana", "DermaVita", "Nutrilek", "Sanovit", "Florea", "Medisan", "Kalmina", "Vivera"]
# (category, VAT rate, origin prefixes, templates with a size)
CATEGORIES = [
    (
        "medicine",
        5,
        ["858", "859"],
        [
            "{b} tablety proti bolesti 500 mg 20 tbl",
            "{b} sirup na kašeľ 100 ml",
            "{b} masť na hojenie rán 30 g",
            "{b} kvapky do nosa 10 ml",
            "{b} kapsuly na trávenie 30 cps",
        ],
    ),
    (
        "herbal",
        19,
        ["858", "859"],
        [
            "{b} - bylinný čaj na trávenie 20x1,5g",
            "{b} - čaj na pokojný spánok 20x2g",
            "{b} - kláštorný čaj na priedušky 20x2g",
            "{b} - cukríky s medom a šalviou 40g",
            "{b} vitamín C 500 mg 60 tbl",
            "{b} detská výživa ovsená kaša 225 g",
        ],
    ),
    (
        "cosmetics",
        23,
        ["400", "380", "300", "859"],
        [
            "{b} pleťový krém na citlivú pleť 50 ml",
            "{b} šampón proti lupinám 250 ml",
            "{b} telové mlieko s ružovým olejom 330 ml",
            "{b} opaľovací krém SPF 50+ 50 ml",
            "{b} sprchový gél s levanduľou 400 ml",
            "{b} krém na ruky s panthenolom 100 ml",
        ],
    ),
    (
        "device",
        23,
        ["858", "400", "471"],
        [
            "{b} náplasť elastická 10 ks",
            "{b} dávkovač liekov týždenný",
            "{b} bandáž členku veľkosť M",
            "{b} manžeta k tlakomeru 22-42 cm",
            "{b} teplomer digitálny",
            "{b} liekovka 300 ml s uzáverom",
        ],
    ),
]


@dataclass
class World:
    buyers: dict[str, Party]
    suppliers: dict[str, Party]
    layout_of: dict[str, Layout]
    catalogue: dict[str, list[Product]]  # supplier key -> products it sells


def make_iban(rng: random.Random, country: str) -> str:
    if country == "SK":
        return format_iban(generate_sk_iban(rng))
    bban = f"{rng.choice(CZ_BANK_CODES)}000000{rng.randrange(10**9, 10**10):010d}"
    return format_iban(iban_from_bban("CZ", bban))


def person_name(rng: random.Random, fk: Faker) -> str:
    if rng.random() < 0.5:
        return f"{fk.first_name_female()} {fk.last_name_female()}"
    return f"{fk.first_name_male()} {fk.last_name_male()}"


def make_party(
    rng: random.Random,
    fk: Faker,
    key: str,
    name: str,
    country: str,
    street: str = "",
    zip_: str = "",
    city: str = "",
) -> Party:
    ico = generate_ico(rng)
    if country == "SK":
        dic = generate_sk_dic(rng)
        vat = f"SK{dic}"
    else:
        dic = vat = f"CZ{ico}"
    bank, swift = rng.choice(BANKS[country])
    domain = name.split()[0].lower().replace("ž", "z").replace("š", "s") + ".example"
    return Party(
        key=key,
        name=name,
        street=street or fk.street_address(),
        zip=zip_
        or (
            f"{rng.randrange(800, 990)} {rng.randrange(10, 99)}"
            if country == "SK"
            else f"{rng.randrange(100, 799)} {rng.randrange(10, 99)}"
        ),
        city=city or fk.city(),
        country=country,
        ico=ico,
        dic=dic,
        vat_id=vat,
        iban=make_iban(rng, country),
        bank=bank,
        swift=swift,
        email=f"fakturacia@{domain}",
        phone=f"+{421 if country == 'SK' else 420} {rng.randrange(900, 999)} "
        f"{rng.randrange(100, 999)} {rng.randrange(100, 999)}",
        contact=person_name(rng, fk),
        register=(
            f"Obchodný register Mestského súdu Bratislava III, oddiel Sro, vložka č. "
            f"{rng.randrange(10000, 99999)}/B"
            if country == "SK"
            else f"Spisová značka C {rng.randrange(10000, 99999)} vedená u Městského soudu v Praze"
        ),
    )


def _supplier_code(rng: random.Random, layout: Layout, i: int) -> str:
    match layout:
        case Layout.SAP:
            return f"{rng.choice(['MB', 'LC', 'AU'])}{rng.randrange(100000, 999999)}"
        case Layout.TANGRAM:
            return f"99{rng.randrange(10000, 99999)}"
        case Layout.POHODA:
            return f"{i + 1:04d}"
        case _:
            return f"{rng.randrange(100000, 999999)}"


def _price(rng: random.Random, category: str, layout: Layout) -> Decimal:
    lo, hi = {
        "medicine": (1.2, 18),
        "herbal": (0.9, 6),
        "cosmetics": (2.5, 22),
        "device": (0.5, 45),
    }[category]
    if layout is Layout.TANGRAM:
        return Decimal(f"{rng.uniform(lo, hi):.3f}")
    if layout is Layout.SCAN_EN:
        return Decimal(f"{rng.uniform(8, 160):.2f}")
    return Decimal(f"{rng.uniform(lo, hi):.2f}")


def build_world(seed: int) -> World:
    rng = random.Random(f"invoices/{seed}/world")
    sk, cz = Faker("sk_SK"), Faker("cs_CZ")
    sk.seed_instance(rng.randrange(2**31))
    cz.seed_instance(rng.randrange(2**31))
    buyers = {
        key: make_party(rng, sk, key, name, "SK", street, zip_, city)
        for key, name, street, zip_, city in BUYERS
    }
    suppliers, layout_of, catalogue = {}, {}, {}
    used_eans: set[str] = set()
    for key, name, country, layout in SUPPLIERS:
        suppliers[key] = make_party(rng, sk if country == "SK" else cz, key, name, country)
        layout_of[key] = layout
        products = []
        allowed = (
            CATEGORIES
            if layout in (Layout.WHOLESALE, Layout.TANGRAM)
            else [c for c in CATEGORIES if c[0] in ("cosmetics", "device", "herbal")]
            if layout is not Layout.SCAN_EN
            else [c for c in CATEGORIES if c[0] in ("medicine", "herbal")]
        )
        for i in range(rng.randrange(30, 45)):
            category, rate, prefixes, templates = rng.choice(allowed)
            product_name = rng.choice(templates).format(b=rng.choice(BRANDS))
            ean = generate_ean13(rng, prefix=rng.choice(prefixes))
            while ean in used_eans:
                ean = generate_ean13(rng, prefix=rng.choice(prefixes))
            used_eans.add(ean)
            products.append(
                Product(
                    ean=ean,
                    supplier_code=_supplier_code(rng, layout, i),
                    name=product_name,
                    vat_rate=rate,
                    list_price=_price(rng, category, layout),
                    sukl=f"S{rng.randrange(10000, 99999)}" if category == "medicine" else None,
                    origin=ORIGIN[ean[:3]],
                    customs=rng.choice(["30049000", "21069098", "33049900"])
                    if layout is Layout.SCAN_EN
                    else None,
                )
            )
        catalogue[key] = products
    return World(buyers, suppliers, layout_of, catalogue)
