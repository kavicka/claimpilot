"""General terms printed on the second page of SAP invoices. Generic and made up; they give the
parser a dense page of text that is not part of the invoice data."""

TERMS = [
    (
        "ÚVODNÉ USTANOVENIA",
        "Tieto všeobecné obchodné podmienky upravujú práva a povinnosti dodávateľa a odberateľa "
        "pri predaji kozmetických výrobkov. Odchylné dojednania v písomnej zmluve majú prednosť "
        "pred týmito podmienkami.",
    ),
    (
        "OBJEDNÁVKA",
        "Odberateľ objednáva tovar písomne alebo elektronicky. Objednávka je záväzná jej "
        "potvrdením dodávateľom. Dodávateľ nie je povinný dodať všetky druhy tovaru uvedené v "
        "cenníku.",
    ),
    (
        "CENA TOVARU",
        "Cena sa riadi cenníkom platným v deň doručenia objednávky. Zľavy sa uplatňujú podľa "
        "platnej obchodnej politiky a sú uvedené na faktúre pri každej položke.",
    ),
    (
        "PLATOBNÉ PODMIENKY A VÝHRADA VLASTNÍCTVA",
        "Kúpna cena je splatná bankovým prevodom v lehote uvedenej na faktúre. Do úplného "
        "zaplatenia zostáva tovar vo vlastníctve dodávateľa. Pri omeškaní môže dodávateľ účtovať "
        "úrok z omeškania 0,05 % za každý začatý deň.",
    ),
    (
        "DODANIE A PREVZATIE",
        "Tovar sa dodáva na adresu dodania uvedenú v objednávke. Odberateľ je povinný tovar pri "
        "prevzatí skontrolovať a zjavné vady oznámiť do troch pracovných dní.",
    ),
    (
        "REKLAMÁCIE",
        "Reklamáciu skrytých vád uplatní odberateľ písomne bez zbytočného odkladu po ich zistení. "
        "Dodávateľ reklamáciu vybaví dobropisom, výmenou tovaru alebo zľavou z ceny.",
    ),
    (
        "ZÁVEREČNÉ USTANOVENIA",
        "Zmluvné strany sa zaväzujú riešiť spory prednostne zmierom. Tieto podmienky nadobúdajú "
        "účinnosť dňom ich zverejnenia.",
    ),
]
