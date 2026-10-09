"""Products (limits, deductibles) and policy terms (VPP clauses), loaded from data/policies."""

from decimal import Decimal
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from claimpilot_core.domain import Coverage, Product


class CoverageTerms(BaseModel):
    limit: Decimal | None = None
    deductible: Decimal = Decimal(0)
    sublimits: dict[str, Decimal] = Field(default_factory=dict)
    per_item_limit: Decimal | None = None
    valuables_share: Decimal | None = None
    fracture_benefit: Decimal | None = None
    min_hours: int | None = None
    reimbursement_rate: Decimal | None = None
    clauses: list[str] = Field(default_factory=list)


class ProductTerms(BaseModel):
    name: str
    coverages: dict[Coverage, CoverageTerms | None]
    extreme_sports: bool = False

    def coverage(self, coverage: Coverage) -> CoverageTerms | None:
        return self.coverages.get(coverage)


class Exclusion(BaseModel):
    clause: str
    coverages: list[Coverage]
    unless_product_flag: str | None = None


class ProductCatalog(BaseModel):
    insurer: str
    terms_id: str
    products: dict[Product, ProductTerms]
    exclusions: dict[str, Exclusion]
    required_documents: dict[str, list[str]]

    def product(self, product: Product | str) -> ProductTerms:
        return self.products[Product(product)]

    def referenced_clauses(self) -> set[str]:
        refs = {e.clause for e in self.exclusions.values()}
        for p in self.products.values():
            for c in p.coverages.values():
                if c is not None:
                    refs.update(c.clauses)
        return refs


class Clause(BaseModel):
    clause_id: str
    article: int
    paragraph: int
    article_title: str
    text: str


class PolicyTerms(BaseModel):
    terms_id: str
    title: str
    insurer: str
    clauses: list[Clause]

    def clause_ids(self) -> set[str]:
        return {c.clause_id for c in self.clauses}

    def clause(self, clause_id: str) -> Clause:
        for c in self.clauses:
            if c.clause_id == clause_id:
                return c
        raise KeyError(clause_id)

    def display_id(self, clause_id: str) -> str:
        c = self.clause(clause_id)
        return f"čl. {c.article} ods. {c.paragraph}"


def clause_id(article: int, paragraph: int) -> str:
    return f"A{article}.{paragraph}"


def load_products(path: Path) -> ProductCatalog:
    return ProductCatalog.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def load_terms(path: Path) -> PolicyTerms:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    clauses = [
        Clause(
            clause_id=clause_id(a["number"], i),
            article=a["number"],
            paragraph=i,
            article_title=a["title"],
            text=text,
        )
        for a in raw["articles"]
        for i, text in enumerate(a["paragraphs"], start=1)
    ]
    return PolicyTerms(
        terms_id=raw["terms_id"], title=raw["title"], insurer=raw["insurer"], clauses=clauses
    )
