"""Vocabulary the templates print: diagnoses, services, shop items, labels. Synthetic and generic."""

from decimal import Decimal

# ICD-10 code -> label per document language. `kind` drives which archetypes use it.
DIAGNOSES: dict[str, dict] = {
    "S52.5": {"kind": "fracture", "sk": "Zlomenina dolného konca vretennej kosti", "de": "Fraktur des distalen Radius", "it": "Frattura dell'estremità distale del radio", "hr": "Prijelom distalnog dijela palčane kosti", "en": "Fracture of the distal radius", "cs": "Zlomenina dolního konce kosti vřetenní"},
    "S82.6": {"kind": "fracture", "sk": "Zlomenina laterálneho členka", "de": "Fraktur des Außenknöchels", "it": "Frattura del malleolo laterale", "hr": "Prijelom lateralnog maleola", "en": "Fracture of the lateral malleolus", "cs": "Zlomenina zevního kotníku"},
    "S42.0": {"kind": "fracture", "sk": "Zlomenina kľúčnej kosti", "de": "Fraktur der Klavikula", "it": "Frattura della clavicola", "hr": "Prijelom ključne kosti", "en": "Fracture of the clavicle", "cs": "Zlomenina klíční kosti"},
    "S93.4": {"kind": "injury", "sk": "Podvrtnutie členkového kĺbu", "de": "Distorsion des oberen Sprunggelenks", "it": "Distorsione della caviglia", "hr": "Uganuće gležnja", "en": "Sprain of the ankle", "cs": "Podvrtnutí hlezenního kloubu"},
    "S06.0": {"kind": "injury", "sk": "Otras mozgu", "de": "Gehirnerschütterung", "it": "Commozione cerebrale", "hr": "Potres mozga", "en": "Concussion", "cs": "Otřes mozku"},
    "J06.9": {"kind": "illness", "sk": "Akútna infekcia horných dýchacích ciest", "de": "Akute Infektion der oberen Atemwege", "it": "Infezione acuta delle vie respiratorie superiori", "hr": "Akutna infekcija gornjih dišnih puteva", "en": "Acute upper respiratory infection", "cs": "Akutní infekce horních cest dýchacích"},
    "A09": {"kind": "illness", "sk": "Akútna gastroenteritída", "de": "Akute Gastroenteritis", "it": "Gastroenterite acuta", "hr": "Akutni gastroenteritis", "en": "Acute gastroenteritis", "cs": "Akutní gastroenteritida"},
    "H66.9": {"kind": "illness", "sk": "Zápal stredného ucha", "de": "Mittelohrentzündung", "it": "Otite media", "hr": "Upala srednjeg uha", "en": "Otitis media", "cs": "Zánět středního ucha"},
    "K04.7": {"kind": "dental", "sk": "Periapikálny absces zuba", "de": "Periapikaler Zahnabszess", "it": "Ascesso periapicale", "hr": "Periapikalni apsces zuba", "en": "Periapical dental abscess", "cs": "Periapikální absces zubu"},
    "K35.8": {"kind": "hospital", "sk": "Akútny zápal slepého čreva", "de": "Akute Appendizitis", "it": "Appendicite acuta", "hr": "Akutna upala crvuljka", "en": "Acute appendicitis", "cs": "Akutní zánět slepého střeva"},
    "J18.9": {"kind": "hospital", "sk": "Zápal pľúc", "de": "Pneumonie", "it": "Polmonite", "hr": "Upala pluća", "en": "Pneumonia", "cs": "Zápal plic"},
    "M51.2": {"kind": "chronic", "sk": "Lumbálna diskopatia L4/L5 s koreňovým dráždením", "de": "Bandscheibenschaden L4/L5", "it": "Discopatia L4/L5", "hr": "Diskopatija L4/L5", "en": "Lumbar disc disorder L4/L5", "cs": "Lumbální diskopatie L4/L5"},
    "I20.0": {"kind": "pre_existing", "sk": "Nestabilná angína pektoris", "de": "Instabile Angina pectoris", "it": "Angina pectoris instabile", "hr": "Nestabilna angina pektoris", "en": "Unstable angina", "cs": "Nestabilní angina pectoris"},
}  # fmt: skip

# Service lines per language: key -> (label, typical EUR price range)
SERVICES: dict[str, dict] = {
    "consultation": {"eur": (55, 160), "de": "Ambulante Untersuchung", "it": "Visita ambulatoriale", "hr": "Ambulantni pregled", "en": "Outpatient consultation", "cs": "Ambulantní vyšetření", "sk": "Ambulantné vyšetrenie"},
    "emergency": {"eur": (120, 340), "de": "Notfallbehandlung", "it": "Pronto soccorso", "hr": "Hitni prijem", "en": "Emergency room treatment", "cs": "Ošetření na pohotovosti", "sk": "Ošetrenie na pohotovosti"},
    "xray": {"eur": (70, 180), "de": "Röntgen", "it": "Radiografia", "hr": "Rendgensko snimanje", "en": "X-ray", "cs": "Rentgen", "sk": "RTG vyšetrenie"},
    "ct": {"eur": (280, 620), "de": "Computertomographie", "it": "TAC", "hr": "CT snimanje", "en": "CT scan", "cs": "CT vyšetření", "sk": "CT vyšetrenie"},
    "ultrasound": {"eur": (80, 190), "de": "Ultraschall", "it": "Ecografia", "hr": "Ultrazvuk", "en": "Ultrasound", "cs": "Ultrazvuk", "sk": "Ultrazvuk"},
    "lab": {"eur": (40, 140), "de": "Laboruntersuchung", "it": "Esami di laboratorio", "hr": "Laboratorijske pretrage", "en": "Laboratory tests", "cs": "Laboratorní vyšetření", "sk": "Laboratórne vyšetrenie"},
    "cast": {"eur": (90, 260), "de": "Gipsverband", "it": "Ingessatura", "hr": "Gipsana imobilizacija", "en": "Plaster cast", "cs": "Sádrová fixace", "sk": "Sadrová fixácia"},
    "infusion": {"eur": (60, 150), "de": "Infusionstherapie", "it": "Terapia infusionale", "hr": "Infuzijska terapija", "en": "IV infusion", "cs": "Infuzní terapie", "sk": "Infúzna terapia"},
    "ecg": {"eur": (45, 110), "de": "EKG", "it": "Elettrocardiogramma", "hr": "EKG", "en": "ECG", "cs": "EKG", "sk": "EKG"},
    "medication": {"eur": (15, 70), "de": "Medikamente", "it": "Farmaci", "hr": "Lijekovi", "en": "Medication", "cs": "Léky", "sk": "Lieky"},
    "dental_treatment": {"eur": (180, 320), "de": "Zahnbehandlung, Wurzelkanal", "it": "Trattamento canalare", "hr": "Liječenje korijenskog kanala", "en": "Root canal treatment", "cs": "Ošetření kořenového kanálku", "sk": "Ošetrenie koreňového kanálika"},
    "dental_xray": {"eur": (40, 90), "de": "Zahnröntgen", "it": "Radiografia dentale", "hr": "Rendgen zuba", "en": "Dental X-ray", "cs": "Rentgen zubu", "sk": "RTG zuba"},
    "hospital_day": {"eur": (520, 1250), "de": "Stationärer Aufenthalt, Pflegetag", "it": "Degenza, giornata", "hr": "Bolnički dan", "en": "Inpatient day", "cs": "Hospitalizace, ošetřovací den", "sk": "Hospitalizácia, ošetrovací deň"},
    "surgery": {"eur": (1800, 4200), "de": "Operation", "it": "Intervento chirurgico", "hr": "Operativni zahvat", "en": "Surgery", "cs": "Operace", "sk": "Operácia"},
    "anesthesia": {"eur": (350, 900), "de": "Anästhesie", "it": "Anestesia", "hr": "Anestezija", "en": "Anesthesia", "cs": "Anestezie", "sk": "Anestézia"},
    "ambulance": {"eur": (180, 650), "de": "Krankentransport", "it": "Trasporto in ambulanza", "hr": "Prijevoz vozilom hitne pomoći", "en": "Ambulance transport", "cs": "Převoz sanitkou", "sk": "Prevoz sanitkou"},
    "physio": {"eur": (40, 95), "de": "Physiotherapie", "it": "Fisioterapia", "hr": "Fizioterapija", "en": "Physiotherapy", "cs": "Fyzioterapie", "sk": "Fyzioterapia"},
}  # fmt: skip

PHARMACY_ITEMS: dict[str, list[tuple[str, tuple[int, int]]]] = {
    "de": [("Ibuprofen 400 mg", (6, 14)), ("Paracetamol 500 mg", (4, 9)), ("Nasenspray", (5, 11)), ("Elastische Binde", (6, 13)), ("Amoxicillin 1 g", (9, 22)), ("Elektrolytlösung", (5, 12))],
    "it": [("Ibuprofene 400 mg", (6, 14)), ("Paracetamolo 500 mg", (4, 9)), ("Spray nasale", (5, 11)), ("Benda elastica", (6, 13)), ("Amoxicillina 1 g", (9, 22)), ("Sali minerali", (5, 12))],
    "hr": [("Ibuprofen 400 mg", (6, 14)), ("Paracetamol 500 mg", (4, 9)), ("Sprej za nos", (5, 11)), ("Elastični zavoj", (6, 13)), ("Amoksicilin 1 g", (9, 22)), ("Oralna rehidracijska otopina", (5, 12))],
    "en": [("Ibuprofen 400mg", (6, 14)), ("Paracetamol 500mg", (4, 9)), ("Nasal spray", (5, 11)), ("Elastic bandage", (6, 13)), ("Amoxicillin 1g", (9, 22)), ("Rehydration salts", (5, 12))],
    "cs": [("Ibuprofen 400 mg", (6, 14)), ("Paralen 500 mg", (4, 9)), ("Nosní sprej", (5, 11)), ("Elastické obinadlo", (6, 13)), ("Amoxicilin 1 g", (9, 22)), ("Rehydratační roztok", (5, 12))],
}  # fmt: skip

# Essentials bought while luggage is delayed (drugstore receipts)
ESSENTIALS: dict[str, list[tuple[str, tuple[int, int]]]] = {
    "de": [("Zahnbürste und Zahnpasta", (4, 9)), ("Duschgel", (3, 7)), ("T-Shirt", (9, 25)), ("Unterwäsche", (8, 22)), ("Ladekabel", (12, 25)), ("Deodorant", (3, 7))],
    "it": [("Spazzolino e dentifricio", (4, 9)), ("Bagnoschiuma", (3, 7)), ("Maglietta", (9, 25)), ("Biancheria intima", (8, 22)), ("Cavo di ricarica", (12, 25)), ("Deodorante", (3, 7))],
    "hr": [("Četkica i pasta za zube", (4, 9)), ("Gel za tuširanje", (3, 7)), ("Majica", (9, 25)), ("Donje rublje", (8, 22)), ("Kabel za punjenje", (12, 25)), ("Dezodorans", (3, 7))],
    "en": [("Toothbrush and toothpaste", (4, 9)), ("Shower gel", (3, 7)), ("T-shirt", (9, 25)), ("Underwear", (8, 22)), ("Charging cable", (12, 25)), ("Deodorant", (3, 7))],
    "cs": [("Zubní kartáček a pasta", (4, 9)), ("Sprchový gel", (3, 7)), ("Tričko", (9, 25)), ("Spodní prádlo", (8, 22)), ("Nabíjecí kabel", (12, 25)), ("Deodorant", (3, 7))],
}  # fmt: skip

# Luggage contents: (sk description, en description, EUR range, valuables)
LUGGAGE_ITEMS: list[tuple[str, str, tuple[int, int], bool]] = [
    ("Cestovný kufor", "Suitcase", (90, 260), False),
    ("Zimná bunda", "Winter jacket", (120, 320), False),
    ("Oblečenie (nohavice, tričká)", "Clothing (trousers, shirts)", (90, 280), False),
    ("Topánky", "Shoes", (60, 180), False),
    ("Kozmetika", "Toiletries", (30, 90), False),
    ("Slnečné okuliare", "Sunglasses", (60, 210), False),
    ("Notebook", "Laptop", (650, 1400), True),
    ("Mobilný telefón", "Mobile phone", (300, 950), True),
    ("Fotoaparát", "Camera", (350, 900), True),
    ("Hodinky", "Wristwatch", (150, 600), True),
    ("Lyžiarske okuliare", "Ski goggles", (60, 160), False),
    ("Kniha a čítačka", "E-reader", (90, 180), True),
]  # fmt: skip

CLAIM_TYPE_LABELS_SK = {
    "medical": "Liečebné náklady",
    "accident": "Úraz",
    "luggage": "Batožina",
    "delay": "Oneskorenie batožiny",
    "cancellation": "Storno cesty",
}

AIRLINES = [
    ("Danubia Air", "DN"),
    ("Tatra Wings", "TW"),
    ("Adria Sky", "AY"),
    ("Carpathia Airways", "CW"),
]
AGENCIES = [
    "CK Slnečné pobrežie, s. r. o.",
    "CK Modrá vlna, s. r. o.",
    "Cestovná kancelária Horizont Tour, s. r. o.",
]

PREMIUM_PER_DAY = {
    "basic": Decimal("1.10"),
    "standard": Decimal("1.90"),
    "premium": Decimal("3.20"),
}
ANNUAL_PREMIUM = {
    "basic": Decimal("49.00"),
    "standard": Decimal("89.00"),
    "premium": Decimal("149.00"),
}

LUGGAGE_I18N: dict[str, dict[str, str]] = {
    "Suitcase": {"de": "Koffer", "it": "Valigia", "hr": "Kofer", "cs": "Kufr", "en": "Suitcase"},
    "Winter jacket": {"de": "Winterjacke", "it": "Giacca invernale", "hr": "Zimska jakna", "cs": "Zimní bunda", "en": "Winter jacket"},
    "Clothing (trousers, shirts)": {"de": "Kleidung (Hosen, Hemden)", "it": "Abbigliamento (pantaloni, camicie)", "hr": "Odjeća (hlače, košulje)", "cs": "Oblečení (kalhoty, trička)", "en": "Clothing (trousers, shirts)"},
    "Shoes": {"de": "Schuhe", "it": "Scarpe", "hr": "Cipele", "cs": "Boty", "en": "Shoes"},
    "Toiletries": {"de": "Kosmetikartikel", "it": "Articoli da toilette", "hr": "Kozmetika", "cs": "Kosmetika", "en": "Toiletries"},
    "Sunglasses": {"de": "Sonnenbrille", "it": "Occhiali da sole", "hr": "Sunčane naočale", "cs": "Sluneční brýle", "en": "Sunglasses"},
    "Laptop": {"de": "Laptop", "it": "Computer portatile", "hr": "Prijenosno računalo", "cs": "Notebook", "en": "Laptop"},
    "Mobile phone": {"de": "Mobiltelefon", "it": "Telefono cellulare", "hr": "Mobitel", "cs": "Mobilní telefon", "en": "Mobile phone"},
    "Camera": {"de": "Fotokamera", "it": "Fotocamera", "hr": "Fotoaparat", "cs": "Fotoaparát", "en": "Camera"},
    "Wristwatch": {"de": "Armbanduhr", "it": "Orologio da polso", "hr": "Ručni sat", "cs": "Náramkové hodinky", "en": "Wristwatch"},
    "Ski goggles": {"de": "Skibrille", "it": "Maschera da sci", "hr": "Skijaške naočale", "cs": "Lyžařské brýle", "en": "Ski goggles"},
    "E-reader": {"de": "E-Book-Reader", "it": "Lettore di e-book", "hr": "E-čitač", "cs": "Čtečka knih", "en": "E-reader"},
}  # fmt: skip

# Sentences the template puts into the anamnesis, so exclusion signals are exact and checkable.
ANAMNESIS: dict[str, dict[str, str]] = {
    "none": {"de": "Keine relevanten Vorerkrankungen. Keine Dauermedikation.", "it": "Nessuna patologia pregressa rilevante. Nessuna terapia cronica.", "hr": "Bez značajnih prethodnih bolesti. Ne uzima stalnu terapiju.", "en": "No relevant previous illnesses. No regular medication.", "cs": "Bez významných předchozích onemocnění. Trvalou medikaci neužívá.", "sk": "Bez významných predchádzajúcich ochorení. Trvalú medikáciu neužíva."},
    "alcohol": {"de": "Patient bei Aufnahme alkoholisiert, Atemalkohol 1,4 Promille.", "it": "Paziente in stato di ebbrezza all'arrivo, alcolemia 1,4 g/l.", "hr": "Pacijent pri prijemu alkoholiziran, alkohol u izdahu 1,4 promila.", "en": "Patient intoxicated on admission, breath alcohol 1.4 per mille.", "cs": "Pacient při příjmu pod vlivem alkoholu, 1,4 promile v dechu."},
    "extreme_sport": {"de": "Unfall beim Paragleiten (Tandemflug), Landung im Gelände.", "it": "Incidente durante un volo in parapendio, atterraggio fuori pista.", "hr": "Ozljeda pri letu paraglajderom, nezgoda pri slijetanju.", "en": "Injury sustained during a paragliding flight, hard landing.", "cs": "Úraz při letu na paraglidu, tvrdé přistání."},
    "pre_existing": {"de": "Bekannte arterielle Hypertonie, seit 2024 in Behandlung; kardiologische Kontrolle vor 2 Monaten wegen Brustschmerzen.", "it": "Ipertensione arteriosa nota, in terapia dal 2024; controllo cardiologico 2 mesi fa per dolore toracico.", "hr": "Poznata arterijska hipertenzija, liječena od 2024.; kardiološki pregled prije 2 mjeseca zbog boli u prsima.", "en": "Known arterial hypertension treated since 2024; cardiology check-up two months ago for chest pain.", "cs": "Známá arteriální hypertenze léčená od roku 2024; kardiologická kontrola před 2 měsíci pro bolest na hrudi."},
    "known_reason": {"sk": "Pacient je dispenzarizovaný pre diskopatiu L4/L5 od marca 2025, opakovane liečený pre bolesti chrbta."},
}  # fmt: skip
