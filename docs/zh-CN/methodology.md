# BorderMargin V5.3 Research Benchmark Notes

V5.3 was designed around recurring patterns in commercial product-research and global-trade intelligence tools while keeping BorderMargin source-driven and auditable.

## Product / marketplace research patterns

### Helium 10 Market Tracker / Product Research
Useful patterns:
- custom market definitions rather than one fixed category view
- market size, competitor monitoring and historical movement
- comparing products/competitors within a defined research set

Reference:
- https://www.helium10.com/tools/analytics/market-tracker/
- https://www.helium10.com/tools/product-research/

### Jungle Scout Opportunity Finder
Useful patterns:
- filter-first exploration
- demand, competition and seasonality viewed together
- opportunity discovery followed by validation rather than a single final score

Reference:
- https://www.junglescout.com/features/opportunity-finder/

## Trade / supply intelligence patterns

### Descartes Global Trade Intelligence / Datamyne
Useful patterns:
- demand and supplier-side research together
- supplier / buyer intelligence
- tariff and trade-compliance context
- supply-chain decisions tied to market expansion

Reference:
- https://www.descartes.com/solutions/global-trade-intelligence

### ImportYeti
Useful patterns:
- supplier discovery from observed shipment records
- supplier concentration and shipment history
- product-to-supplier search

Reference:
- https://www.importyeti.com/
- https://data.importyeti.com/

## Official tariff research architecture

### WTO Tariff & Trade Data
The WTO IDB provides applied and preferential tariffs at national tariff-line level where notified. The ADB provides HS6 analytical tariff/trade data and fills gaps from multiple sources.

Reference:
- https://ttd.wto.org/
- https://data.wto.org/dataset/wto_idb
- https://data.wto.org/dataset/wto_ttd

### UNCTAD TRAINS / WITS
Used as the global HS6 analytical reference layer. It supports MFN and applied / preferential tariff analysis by reporter, partner and product.

Reference:
- https://wits.worldbank.org/tariff/trains/country-byhs6product.aspx

## BorderMargin design choices

1. No synthetic market-attractiveness number is required to use the product.
2. Demand and supply evidence are kept as separate observable dimensions.
3. Global HS6 tariff references and legal/current local tariff verification are separated.
4. Missing evidence remains visible.
5. AI interprets structured evidence only.
6. Marketplace test data is blocked from decision-grade pricing benchmarks.
