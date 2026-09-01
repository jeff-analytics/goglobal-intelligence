from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field, field_validator


class PricingRequest(BaseModel):
    factory_cost: float = Field(ge=0)
    packaging_cost: float = Field(default=0, ge=0)
    freight_cost: float = Field(default=0, ge=0)
    duty_rate: float = Field(default=0, ge=0, le=1)
    tax_rate: float = Field(default=0, ge=0, le=1)
    fulfillment_cost: float = Field(default=0, ge=0)
    platform_fee_rate: float = Field(default=0, ge=0, lt=1)
    target_margin_rate: float = Field(ge=0, lt=1)
    listing_median: float | None = Field(default=None, ge=0)


class PricingResult(BaseModel):
    pre_tax_cost: float
    duty_cost: float
    tax_cost: float
    landed_cost_before_platform: float
    break_even_price: float
    target_price: float
    margin_at_listing_median: float | None
    premium_to_listing_median: float | None
    driver_shares: dict[str, float]


def _clean_code(value: str | None) -> str:
    if value is None:
        return ""
    return "".join(ch for ch in str(value).strip() if ch.isalnum())


class TariffOverrideRequest(BaseModel):
    market: str = Field(min_length=2, max_length=3)
    hs_code: str = Field(min_length=2, max_length=14)
    rate: float = Field(ge=0, le=100)
    reference_year: int | None = Field(default=None, ge=1988, le=2100)
    note: str | None = Field(default=None, max_length=500)

    @field_validator("hs_code")
    @classmethod
    def clean_hs(cls, value: str) -> str:
        return _clean_code(value)


class ProductIdentifyRequest(BaseModel):
    text: str = Field(min_length=2, max_length=1000)


class ProjectCreateRequest(BaseModel):
    product_type_id: str = Field(default="generic", min_length=2, max_length=100)
    title: str = Field(min_length=2, max_length=180)
    description: str = Field(default="", max_length=1200)
    origin: str = Field(default="", max_length=80)
    hs_code: str = Field(default="", max_length=14)
    attributes: dict[str, Any] = Field(default_factory=dict)
    markets: list[str] = Field(default_factory=list)
    assumptions: dict[str, Any] = Field(default_factory=dict)
    status: str = Field(default="draft", max_length=40)

    @field_validator("hs_code")
    @classmethod
    def clean_hs(cls, value: str) -> str:
        return _clean_code(value)


class ProjectUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=180)
    description: str | None = Field(default=None, max_length=1200)
    origin: str | None = Field(default=None, max_length=80)
    hs_code: str | None = Field(default=None, max_length=14)
    product_type_id: str | None = Field(default=None, min_length=2, max_length=100)
    attributes: dict[str, Any] | None = None
    markets: list[str] | None = None
    assumptions: dict[str, Any] | None = None
    status: str | None = Field(default=None, max_length=40)

    @field_validator("hs_code")
    @classmethod
    def clean_hs(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _clean_code(value)


class ReversePricingRequest(BaseModel):
    target_selling_price: float = Field(gt=0)
    packaging_cost: float = Field(default=0, ge=0)
    freight_cost: float = Field(default=0, ge=0)
    fulfillment_cost: float = Field(default=0, ge=0)
    duty_rate: float = Field(default=0, ge=0, le=1)
    tax_rate: float = Field(default=0, ge=0, le=1)
    platform_fee_rate: float = Field(default=0, ge=0, lt=1)
    target_margin_rate: float = Field(default=0, ge=0, lt=1)
    current_factory_cost: float | None = Field(default=None, ge=0)


class TaxOverrideRequest(BaseModel):
    market: str = Field(min_length=2, max_length=3)
    rate: float = Field(ge=0, le=100)
    reference_year: int | None = Field(default=None, ge=1988, le=2100)
    note: str | None = Field(default=None, max_length=500)

class EbayLocalConfigRequest(BaseModel):
    environment: str = Field(default="sandbox", max_length=20)
    client_id: str | None = Field(default=None, max_length=500)
    client_secret: str | None = Field(default=None, max_length=1000)
    marketplace_id: str | None = Field(default=None, max_length=80)

    @field_validator("environment")
    @classmethod
    def validate_environment(cls, value: str) -> str:
        normalized = str(value or "sandbox").strip().lower()
        if normalized not in {"sandbox", "production"}:
            raise ValueError("environment must be sandbox or production")
        return normalized


class ComtradeLocalConfigRequest(BaseModel):
    api_key: str | None = Field(default=None, max_length=1000)




class WebResearchLocalConfigRequest(BaseModel):
    provider: str = Field(default="auto", max_length=40)
    api_key: str | None = Field(default=None, max_length=4000)
    base_url: str | None = Field(default=None, max_length=1000)

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, value: str) -> str:
        normalized = str(value or "auto").strip().lower()
        if normalized not in {"auto", "native", "tavily", "none"}:
            raise ValueError("provider must be auto, native, tavily, or none")
        return normalized


class ModelAPILocalConfigRequest(BaseModel):
    provider: str | None = Field(default=None, max_length=120)
    protocol: str | None = Field(default=None, max_length=40)
    base_url: str | None = Field(default=None, max_length=1000)
    api_key: str | None = Field(default=None, max_length=4000)
    model: str | None = Field(default=None, max_length=240)

    @field_validator("protocol")
    @classmethod
    def validate_protocol(cls, value: str | None) -> str | None:
        if value is None:
            return value
        normalized = str(value).strip().lower()
        if normalized and normalized not in {"openai_compatible", "openai_responses", "anthropic", "gemini"}:
            raise ValueError("protocol must be openai_compatible, openai_responses, anthropic, or gemini")
        return normalized


class ParetoObjectiveRequest(BaseModel):
    key: str = Field(min_length=1, max_length=80)
    direction: str = Field(default="max", max_length=8)

    @field_validator("direction")
    @classmethod
    def validate_direction(cls, value: str) -> str:
        normalized = str(value or "max").lower()
        if normalized not in {"max", "min"}:
            raise ValueError("direction must be max or min")
        return normalized


class ParetoScreenRequest(BaseModel):
    objectives: list[ParetoObjectiveRequest] = Field(default_factory=list)


class UncertaintyVariableRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    distribution: str = Field(default="uniform", max_length=20)
    low: float
    high: float
    mode: float | None = None
    mean: float | None = None
    std: float | None = Field(default=None, gt=0)

    @field_validator("distribution")
    @classmethod
    def validate_distribution(cls, value: str) -> str:
        normalized = str(value or "uniform").lower()
        if normalized not in {"uniform", "triangular", "normal"}:
            raise ValueError("distribution must be uniform, triangular, or normal")
        return normalized


class ProfitSimulationRequest(BaseModel):
    market: str = Field(min_length=2, max_length=3)
    sampling_method: str = Field(default="lhs", max_length=12)
    sample_count: int = Field(default=10000, ge=256, le=100000)
    sobol_base_n: int = Field(default=512, ge=64, le=4096)
    seed: int = Field(default=42, ge=0, le=2_147_483_647)
    variables: list[UncertaintyVariableRequest] = Field(default_factory=list)

    @field_validator("sampling_method")
    @classmethod
    def validate_sampling(cls, value: str) -> str:
        normalized = str(value or "lhs").lower()
        if normalized not in {"lhs", "mc"}:
            raise ValueError("sampling_method must be lhs or mc")
        return normalized


class AllocationOpportunityRequest(BaseModel):
    project_id: int | str
    product: str = Field(default="", max_length=200)
    market: str = Field(min_length=2, max_length=3)
    return_rate: float
    revenue_rate: float = Field(default=1.0, ge=0)
    uncertainty: float = Field(default=0.0, ge=0)
    risk_score: float = Field(default=0.0, ge=0, le=1)
    max_allocation: float | None = Field(default=None, ge=0)
    enabled: bool = True
    mandatory: bool = False
    prohibited: bool = False


class PortfolioOptimizationRequest(BaseModel):
    total_budget: float = Field(gt=0)
    objective: str = Field(default="robust_profit", max_length=40)
    gamma: float = Field(default=2.0, ge=0)
    market_cap_ratio: float = Field(default=0.35, gt=0, le=1)
    product_cap_ratio: float = Field(default=0.45, gt=0, le=1)
    high_risk_cap_ratio: float = Field(default=0.20, ge=0, le=1)
    high_risk_threshold: float = Field(default=0.65, ge=0, le=1)
    min_markets: int = Field(default=1, ge=0, le=100)
    min_allocation: float = Field(default=0.0, ge=0)
    reserve_ratio: float = Field(default=0.0, ge=0, lt=1)
    opportunities: list[AllocationOpportunityRequest] = Field(default_factory=list)

    @field_validator("objective")
    @classmethod
    def validate_objective(cls, value: str) -> str:
        normalized = str(value or "robust_profit").lower()
        if normalized not in {"robust_profit", "nominal_profit", "revenue"}:
            raise ValueError("objective must be robust_profit, nominal_profit, or revenue")
        return normalized


class HSRankingFeedbackRequest(BaseModel):
    project_id: int = Field(default=0, ge=0)
    query_text: str = Field(min_length=1, max_length=2000)
    selected_code: str = Field(min_length=2, max_length=20)
    candidate_codes: list[str] = Field(default_factory=list)
