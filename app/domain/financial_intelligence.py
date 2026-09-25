"""Virtual CFO Financial Intelligence Diagnostic Engine.

Based on the 56-page "Virtual CFO Financial Intelligence Flowchart Compendium:
Exhaustive Root-Cause Financial Analysis (40 Financial Metrics | 6-Level Drill-Down | Management Action Points)".

Purpose:
Enable automated, reverse-flow diagnostic reasoning to answer:
1. What changed? (Metric & Formula level)
2. Why did it change? (Components & Sub-components)
3. What caused it? (Operational Drivers & Root Causes)
4. What to investigate? (Specific Additional Data, Logs, Registers, Ledgers)
5. What to ask management? (Management Insights & High-Impact Action Points)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class TerminalDiagnostic:
    name: str
    root_cause: str
    additional_data: list[str]
    management_insight: str


@dataclass(frozen=True)
class DriverNode:
    name: str
    terminals: list[TerminalDiagnostic] = field(default_factory=list)


@dataclass(frozen=True)
class SubComponentNode:
    name: str
    drivers: list[DriverNode] = field(default_factory=list)
    terminals: list[TerminalDiagnostic] = field(default_factory=list)


@dataclass(frozen=True)
class ComponentNode:
    name: str
    sub_components: list[SubComponentNode] = field(default_factory=list)
    terminals: list[TerminalDiagnostic] = field(default_factory=list)


@dataclass(frozen=True)
class MetricDiagnosticTree:
    metric_id: int
    canonical_name: str
    metric_code: str
    formula: str
    category: str
    components: list[ComponentNode] = field(default_factory=list)
    key_management_questions: list[str] = field(default_factory=list)
    investigation_checklist: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# The 40 Diagnostic Trees (1 to 40)
# ---------------------------------------------------------------------------

TREES: list[MetricDiagnosticTree] = [
    # 1. Revenue Growth
    MetricDiagnosticTree(
        metric_id=1,
        canonical_name="Revenue Growth",
        metric_code="revenue_growth_yoy",
        formula="Revenue Growth (%) = (Current Period Revenue - Prior Period Revenue) / Prior Period Revenue * 100",
        category="growth_returns",
        components=[
            ComponentNode(
                name="PRICE COMPONENT",
                sub_components=[
                    SubComponentNode(
                        name="Average Selling Price (ASP)",
                        drivers=[
                            DriverNode(
                                name="Product Mix Shift",
                                terminals=[
                                    TerminalDiagnostic(
                                        name="Product Mix Shift",
                                        root_cause="Higher/lower-margin SKU sales proportion changed",
                                        additional_data=["SKU-wise revenue split", "Margin per SKU", "Customer segment mix"],
                                        management_insight="Investigate if premium SKUs are being discounted or if sales team is pushing easier lower-value deals.",
                                    )
                                ],
                            ),
                            DriverNode(
                                name="Discounting & Schemes",
                                terminals=[
                                    TerminalDiagnostic(
                                        name="Discounting & Schemes",
                                        root_cause="Trade schemes, festive discounts, distributor incentives elevated",
                                        additional_data=["Discount % per invoice", "Scheme-wise cost", "Channel-wise discount policy"],
                                        management_insight="Calculate net realization vs gross billing; review if discounts are driving volume or eroding margin.",
                                    )
                                ],
                            ),
                            DriverNode(
                                name="Price Increases Implemented",
                                terminals=[
                                    TerminalDiagnostic(
                                        name="Price Increases Implemented",
                                        root_cause="Annual price revision, input cost pass-through, regulatory pricing changes",
                                        additional_data=["Price revision dates", "Customer acceptance rate", "Volume impact post-price hike"],
                                        management_insight="Analyze volume elasticity post price hike; monitor competitor response.",
                                    )
                                ],
                            ),
                            DriverNode(
                                name="Currency / FX Impact (Exports)",
                                terminals=[
                                    TerminalDiagnostic(
                                        name="Currency / FX Impact (Exports)",
                                        root_cause="INR depreciation/appreciation vs USD/EUR affecting realized price",
                                        additional_data=["Forex realization rate", "Hedging policy", "Unhedged exposure"],
                                        management_insight="Review forex hedging adequacy; compute constant-currency growth.",
                                    )
                                ],
                            ),
                        ],
                    )
                ],
            ),
            ComponentNode(
                name="VOLUME COMPONENT",
                sub_components=[
                    SubComponentNode(
                        name="New Customer Acquisition",
                        drivers=[
                            DriverNode(
                                name="Lead Conversion Rate",
                                terminals=[
                                    TerminalDiagnostic(
                                        name="Lead Conversion Rate",
                                        root_cause="Sales funnel leakage - leads not converting to orders",
                                        additional_data=["Lead count", "Conversion %", "Average deal size", "Sales cycle days"],
                                        management_insight="Review sales team productivity, pitch quality, product fit vs customer need.",
                                    )
                                ],
                            ),
                            DriverNode(
                                name="Geographic Expansion",
                                terminals=[
                                    TerminalDiagnostic(
                                        name="Geographic Expansion",
                                        root_cause="New territory/city/country opened for sales",
                                        additional_data=["Revenue by geography", "New vs existing geography contribution"],
                                        management_insight="Validate if new geography revenue is profitable after distribution cost.",
                                    )
                                ],
                            ),
                            DriverNode(
                                name="Channel Addition",
                                terminals=[
                                    TerminalDiagnostic(
                                        name="Channel Addition",
                                        root_cause="New distributor, e-commerce, export, institutional channel added",
                                        additional_data=["Channel-wise revenue", "Channel cost (rebates, logistics)", "Channel margin"],
                                        management_insight="Calculate channel ROI; ensure new channel does not cannibalize existing.",
                                    )
                                ],
                            ),
                        ],
                    ),
                    SubComponentNode(
                        name="Existing Customer Retention & Upsell",
                        drivers=[
                            DriverNode(
                                name="Repeat Order Rate",
                                terminals=[
                                    TerminalDiagnostic(
                                        name="Repeat Order Rate",
                                        root_cause="Customer churn - orders not recurring as expected",
                                        additional_data=["Cohort analysis", "Repeat purchase %", "Churn rate by segment"],
                                        management_insight="Identify churned accounts; initiate win-back campaigns; check NPS scores.",
                                    )
                                ],
                            ),
                            DriverNode(
                                name="Wallet Share Expansion",
                                terminals=[
                                    TerminalDiagnostic(
                                        name="Wallet Share Expansion",
                                        root_cause="Customers buying additional product lines or higher quantities",
                                        additional_data=["Cross-sell revenue", "Revenue per account trend", "Top-10 account growth"],
                                        management_insight="Build account plans for top 20% customers driving 80% revenue.",
                                    )
                                ],
                            ),
                            DriverNode(
                                name="Contract Renewal & Rate Revision",
                                terminals=[
                                    TerminalDiagnostic(
                                        name="Contract Renewal & Rate Revision",
                                        root_cause="Annual contract renewed at higher/lower rates",
                                        additional_data=["Contract renewal dates", "Rate change per contract", "Lost contracts"],
                                        management_insight="Track contract expiry pipeline; alert when at-risk contracts approach renewal.",
                                    )
                                ],
                            ),
                        ],
                    ),
                ],
            ),
            ComponentNode(
                name="NEW PRODUCT / SERVICE CONTRIBUTION",
                sub_components=[
                    SubComponentNode(
                        name="New SKU Launch Revenue",
                        terminals=[
                            TerminalDiagnostic(
                                name="New SKU Launch",
                                root_cause="Revenue from products launched in last 12 months contributing to growth",
                                additional_data=["Revenue by product age bucket (<12M, 12-24M, >24M)", "Launch date", "Cannibalisation rate"],
                                management_insight="Assess new product revenue as % of total; track ramp-up vs plan.",
                            )
                        ],
                    ),
                    SubComponentNode(
                        name="Service Revenue Add-on",
                        terminals=[
                            TerminalDiagnostic(
                                name="Service Revenue Add-on",
                                root_cause="Annual maintenance, installation, SaaS subscription, after-sales service revenue growing",
                                additional_data=["Service revenue %", "Gross margin on services", "Contract value"],
                                management_insight="Monitor recurring vs one-time split; services revenue improves predictability.",
                            )
                        ],
                    ),
                ],
            ),
            ComponentNode(
                name="BASE EFFECT / SEASONALITY",
                sub_components=[
                    SubComponentNode(
                        name="High Base Quarter Prior Year",
                        terminals=[
                            TerminalDiagnostic(
                                name="High Base Effect",
                                root_cause="Prior year had one-off large order or festive demand spike making current growth look low",
                                additional_data=["Quarter-wise revenue for 2 years", "One-off revenue items"],
                                management_insight="Adjust for one-offs; compute like-for-like growth.",
                            )
                        ],
                    ),
                    SubComponentNode(
                        name="Seasonality & Calendar Effects",
                        terminals=[
                            TerminalDiagnostic(
                                name="Seasonality Effects",
                                root_cause="Number of working days, festival shifts, government financial year end-effects",
                                additional_data=["Revenue per working day", "Month-wise trend", "Prior 3-year seasonality index"],
                                management_insight="Use seasonally-adjusted revenue for meaningful trend analysis.",
                            )
                        ],
                    ),
                ],
            ),
        ],
        key_management_questions=[
            "Are premium SKUs being discounted or is the sales team pushing lower-value deals to chase volume targets?",
            "What is our net price realization per unit after subtracting all trade schemes and rebates?",
            "What is our customer churn rate and what is the pipeline for at-risk contract renewals?",
            "How much of current period growth is driven by volume expansion vs price increases?",
        ],
        investigation_checklist=[
            "SKU-wise volume and price realization waterfall",
            "Customer cohort churn and repeat purchase trends",
            "Sales funnel lead conversion rates by sales territory",
            "New product launch revenue contribution vs cannibalization of legacy lines",
        ],
    ),

    # 2. Gross Profit Margin
    MetricDiagnosticTree(
        metric_id=2,
        canonical_name="Gross Profit Margin",
        metric_code="gross_profit_pct",
        formula="Gross Profit Margin (%) = (Revenue - COGS) / Revenue * 100",
        category="profitability",
        components=[
            ComponentNode(
                name="REVENUE COMPONENT",
                terminals=[
                    TerminalDiagnostic(
                        name="Selling Price & Realization",
                        root_cause="Discounting schemes increasing, adverse product mix shifts, or inadequate price hikes against input inflation",
                        additional_data=["Invoice discount register", "Product-line gross margin matrix", "Price increase realization audit"],
                        management_insight="Review net realization per SKU; prevent low-margin products from diluting corporate gross margin.",
                    )
                ],
            ),
            ComponentNode(
                name="RAW MATERIAL COST",
                sub_components=[
                    SubComponentNode(
                        name="Purchase Price per Unit",
                        drivers=[
                            DriverNode(
                                name="Commodity & Supplier Inflation",
                                terminals=[
                                    TerminalDiagnostic(
                                        name="Commodity & Supplier Pricing",
                                        root_cause="Global commodity cycle rising, supplier cost pass-through, import tariffs, or INR depreciation",
                                        additional_data=["12-month commodity index", "Supplier price revision logs", "USD/INR landed cost schedules"],
                                        management_insight="Review commodity hedging; dual-source critical materials; negotiate multi-year volume contracts.",
                                    )
                                ],
                            ),
                            DriverNode(
                                name="Freight & Inbound Logistics",
                                terminals=[
                                    TerminalDiagnostic(
                                        name="Freight Surcharges",
                                        root_cause="Shipping container shortages, fuel surcharges, last-mile rate increases",
                                        additional_data=["Freight cost as % of purchase price", "Inbound freight per ton-km"],
                                        management_insight="Negotiate FOB vs CIF terms; consolidate shipments to optimize container utilization.",
                                    )
                                ],
                            ),
                        ],
                    ),
                    SubComponentNode(
                        name="Material Consumption & Efficiency",
                        drivers=[
                            DriverNode(
                                name="Wastage, Scrap & Yield Loss",
                                terminals=[
                                    TerminalDiagnostic(
                                        name="Production Inefficiencies",
                                        root_cause="Machine calibration issues, operator errors, input-output ratio deterioration, or store pilferage",
                                        additional_data=["Daily wastage % logs", "Batch yield production records", "Physical stock variance reports"],
                                        management_insight="Establish wastage KPIs per production line; lock BOM deviations to engineering sign-off.",
                                    )
                                ],
                            )
                        ],
                    ),
                ],
            ),
            ComponentNode(
                name="DIRECT LABOUR COST",
                sub_components=[
                    SubComponentNode(
                        name="Headcount, Wage Rates & Overtime",
                        terminals=[
                            TerminalDiagnostic(
                                name="Direct Labour Variances",
                                root_cause="Over-hiring vs actual output, minimum wage statutory revisions, or excessive overtime due to rush orders",
                                additional_data=["Worker shift logs", "Overtime premium registers", "Labour productivity per unit"],
                                management_insight="Compute labour productivity ratio; model automation ROI; enforce strict overtime authorizations.",
                            )
                        ],
                    )
                ],
            ),
            ComponentNode(
                name="DIRECT MANUFACTURING OVERHEADS",
                sub_components=[
                    SubComponentNode(
                        name="Power, Fuel & Plant Maintenance",
                        terminals=[
                            TerminalDiagnostic(
                                name="Factory Overheads Escalation",
                                root_cause="Electricity tariff hikes, low boiler efficiency, aging machinery breakdown spikes, or tooling wear",
                                additional_data=["Sub-meter kWh consumption logs", "Boiler fuel efficiency ratios", "Breakdown vs preventive maintenance logs"],
                                management_insight="Shift energy-intensive operations to off-peak hours; evaluate captive solar; shift to preventive maintenance.",
                            )
                        ],
                    )
                ],
            ),
        ],
        key_management_questions=[
            "What portion of the gross margin change is due to purchase price variance (PPV) vs material usage variance?",
            "Are we passing input raw material inflation through to customer prices, and what is the lag time?",
            "What is our batch yield loss across primary product lines, and how much scrap is being sold vs recycled?",
            "Why did direct labour overtime hours spike during the period?",
        ],
        investigation_checklist=[
            "Purchase Price Variance (PPV) report comparing actual prices to standard cost",
            "Bill of Materials (BOM) variance audit by batch",
            "Scrap and wastage registers by factory department",
            "Electricity TOD (time-of-day) consumption logs and power factor penalties",
        ],
    ),

    # 3. EBITDA Margin
    MetricDiagnosticTree(
        metric_id=3,
        canonical_name="EBITDA Margin",
        metric_code="ebitda_margin",
        formula="EBITDA Margin (%) = EBITDA / Revenue * 100 | EBITDA = Revenue - COGS - Employee Cost - S&M Expense - Admin Expense + D&A",
        category="profitability",
        components=[
            ComponentNode(name="GROSS MARGIN DRIVERS (Revenue & COGS)", terminals=[
                TerminalDiagnostic(
                    name="Core Margin Spread",
                    root_cause="Gross margin expansion or compression feeding directly into operating profit",
                    additional_data=["Gross profit percentage trend", "Product-level contribution margins"],
                    management_insight="Stabilize gross margin before attempting to fix SG&A overhead issues.",
                )
            ]),
            ComponentNode(name="OPERATING OVERHEADS (SG&A)", sub_components=[
                SubComponentNode(name="Employee Costs & Staffing", terminals=[
                    TerminalDiagnostic(
                        name="Payroll Growth",
                        root_cause="Over-hiring ahead of revenue, annual increment cycles, or sales commission payouts",
                        additional_data=["Headcount by department", "Revenue per employee ratio", "Payroll budget variance"],
                        management_insight="Benchmark revenue-per-employee against peers; restructure CTC with higher variable performance pay.",
                    )
                ]),
                SubComponentNode(name="Selling & Marketing Costs", terminals=[
                    TerminalDiagnostic(
                        name="Customer Acquisition Spend",
                        root_cause="Elevated performance ad spend, distributor trade schemes, or outbound logistics freight hikes",
                        additional_data=["ROAS (Return on Ad Spend)", "Customer acquisition cost (CAC)", "Freight per unit shipped"],
                        management_insight="Kill underperforming digital campaigns weekly; verify whether distributor schemes drive genuine retail pull.",
                    )
                ]),
                SubComponentNode(name="Administrative Expenses", terminals=[
                    TerminalDiagnostic(
                        name="Corporate Overheads",
                        root_cause="Office rent escalations, high consulting fees, software SaaS proliferation, or travel spikes",
                        additional_data=["Office sq.ft. utilization", "Consulting project deliverable audits", "SaaS tool seat inventory"],
                        management_insight="Right-size office space; rationalize software licenses; mandate economy travel policies.",
                    )
                ]),
            ]),
            ComponentNode(name="OPERATING LEVERAGE & ONE-TIMERS", terminals=[
                TerminalDiagnostic(
                    name="Operating Leverage & Exceptional Items",
                    root_cause="Negative operating leverage when fixed costs fail to flex down with sales; inventory write-offs or restructuring provisions",
                    additional_data=["Fixed vs variable cost proportion", "Contribution margin ratio", "One-time provision register"],
                    management_insight="Track normalized recurring EBITDA separate from one-off charges to assess true underlying cash generation.",
                )
            ]),
        ],
        key_management_questions=[
            "What is our fixed vs variable operating cost breakdown, and what is our current breakeven revenue level?",
            "What is the ROAS and customer acquisition cost across active marketing channels?",
            "Are employee headcount additions delivering proportional increases in gross revenue per employee?",
            "Were any non-recurring write-downs, legal settlements, or restructuring costs booked in the period?",
        ],
        investigation_checklist=[
            "Monthly departmental OPEX variance report vs budget",
            "Revenue per employee and payroll-to-revenue ratio trends",
            "Marketing spend attribution and distributor incentive ROI report",
            "Schedule of non-recurring provisions, bad debt write-offs, and exceptional expenses",
        ],
    ),

    # 4. Operating Margin (EBIT Margin)
    MetricDiagnosticTree(
        metric_id=4,
        canonical_name="Operating Margin (EBIT Margin)",
        metric_code="operating_margin",
        formula="Operating Margin (%) = EBIT / Revenue * 100 | EBIT = EBITDA - Depreciation & Amortisation",
        category="profitability",
        components=[
            ComponentNode(name="EBITDA PERFORMANCE", terminals=[
                TerminalDiagnostic(
                    name="Underlying Cash Operating Margin",
                    root_cause="Operating leverage, sales mix, and operational overhead efficiency",
                    additional_data=["EBITDA margin trend", "Contribution margin"],
                    management_insight="Refer to EBITDA diagnostic tree for operating drivers.",
                )
            ]),
            ComponentNode(name="DEPRECIATION & AMORTISATION", sub_components=[
                SubComponentNode(name="Gross Fixed Asset Base & Capex", terminals=[
                    TerminalDiagnostic(
                        name="Asset Additions & Capitalization",
                        root_cause="New plant or machinery capitalized increasing depreciable base; asset retirements causing disposal loss",
                        additional_data=["Capex capitalization schedule", "Asset commissioning dates", "Asset disposal gain/loss register"],
                        management_insight="Ensure capitalized assets are earning productive revenue immediately; avoid idle asset drag.",
                    )
                ]),
                SubComponentNode(name="Depreciation Policy & Useful Life", terminals=[
                    TerminalDiagnostic(
                        name="Accounting Estimates & Mix Shift",
                        root_cause="Policy shift between SLM and WDV; changes in technical asset useful life; mix shift towards short-life IT hardware",
                        additional_data=["Depreciation method notes", "Useful life revision audit", "Category asset schedules"],
                        management_insight="Benchmark asset useful life assumptions against industry peers; ensure disclosures are transparent.",
                    )
                ]),
                SubComponentNode(name="Intangibles Amortisation", terminals=[
                    TerminalDiagnostic(
                        name="Intangibles & Goodwill Impairment",
                        root_cause="Amortisation of capitalized software or customer lists; impairment write-down of acquisition goodwill",
                        additional_data=["Intangible asset schedule", "Cash Generating Unit (CGU) impairment test results"],
                        management_insight="Test goodwill and capitalized intangibles annually; recognize impairment promptly when CGU cash flows slip.",
                    )
                ]),
            ]),
        ],
        key_management_questions=[
            "Are new fixed asset capitalizations generating revenue commensurate with their depreciation burden?",
            "Have there been any changes in accounting estimates for useful asset lives or depreciation methods?",
            "What is our return on newly commissioned capital expenditure projects vs the original business case?",
        ],
        investigation_checklist=[
            "Fixed asset register additions and commissioning date report",
            "Depreciation schedule by asset class (building, plant, IT, vehicles)",
            "Impairment testing documentation for goodwill and intangible assets",
        ],
    ),

    # 5. Net Profit Margin
    MetricDiagnosticTree(
        metric_id=5,
        canonical_name="Net Profit Margin",
        metric_code="net_profit_margin",
        formula="Net Profit Margin (%) = PAT / Revenue * 100 | PAT = EBIT - Finance Cost + Other Income - Tax",
        category="profitability",
        components=[
            ComponentNode(name="OPERATING PROFIT (EBIT)", terminals=[
                TerminalDiagnostic(
                    name="Operating Earnings Power",
                    root_cause="Revenue growth, gross margin spread, and operating overhead control",
                    additional_data=["EBIT trend", "EBIT margin %"],
                    management_insight="Operating performance must be the primary driver of net margin, not non-operating treasury gains.",
                )
            ]),
            ComponentNode(name="OTHER INCOME", terminals=[
                TerminalDiagnostic(
                    name="Non-Operating Revenue",
                    root_cause="Interest income on bank fixed deposits, mutual fund dividends, asset sale profits, or MTM forex gains",
                    additional_data=["Treasury deposit yields", "Investment portfolio register", "Asset disposal proceeds vs book value"],
                    management_insight="Exclude one-off asset sale gains and unrealized forex MTM from operating core profit assessments.",
                )
            ]),
            ComponentNode(name="FINANCE COST", terminals=[
                TerminalDiagnostic(
                    name="Borrowing & Interest Expense",
                    root_cause="Higher debt balances from capex borrowing, benchmark rate hikes (repo/MCLR), or penal interest charges",
                    additional_data=["Loan interest schedules", "Weighted average cost of debt", "Bank penalty charge breakdown"],
                    management_insight="Accelerate debt repayment from surplus operating cash; eliminate penal charges via tighter treasury scheduling.",
                )
            ]),
            ComponentNode(name="TAX EXPENSE", terminals=[
                TerminalDiagnostic(
                    name="Effective Tax Rate (ETR)",
                    root_cause="Changes in taxable profit disallowances, expiry of tax incentives, MAT applicability, or deferred tax adjustments",
                    additional_data=["Tax computation worksheet", "MAT credit entitlement schedule", "DTA/DTL timing difference register"],
                    management_insight="Scrutinize significant divergence between statutory tax rate and ETR; monitor MAT credit utilization.",
                )
            ]),
        ],
        key_management_questions=[
            "How much of net profit is derived from core operations vs non-operating treasury or asset sale income?",
            "What is our weighted average borrowing rate and how sensitive is PAT to a 100 bps rate hike?",
            "Why is the effective tax rate diverging from the statutory tax rate?",
        ],
        investigation_checklist=[
            "Bridge reconciliation from EBIT to PAT (Interest, Other Income, Tax)",
            "Treasury yields on surplus liquidity vs borrowing interest costs",
            "Effective tax rate reconciliation and deferred tax movement schedule",
        ],
    ),

    # 6. Return on Equity (ROE)
    MetricDiagnosticTree(
        metric_id=6,
        canonical_name="Return on Equity (ROE)",
        metric_code="roe",
        formula="ROE (%) = PAT / Average Shareholders Equity * 100 | DuPont: Net Profit Margin * Asset Turnover * Financial Leverage",
        category="growth_returns",
        components=[
            ComponentNode(name="NET PROFIT MARGIN (DuPont Component 1)", terminals=[
                TerminalDiagnostic(
                    name="Earnings Profitability",
                    root_cause="Pricing power, operational cost discipline, tax optimization, and interest burden control",
                    additional_data=["PAT margin trend", "Operating margin conversion"],
                    management_insight="High ROE driven by net margin represents sustainable operational excellence.",
                )
            ]),
            ComponentNode(name="ASSET TURNOVER (DuPont Component 2)", terminals=[
                TerminalDiagnostic(
                    name="Asset Productivity",
                    root_cause="Revenue efficiency per rupee of assets deployed; utilization of plant and working capital",
                    additional_data=["Revenue to total assets", "Capacity utilization rates"],
                    management_insight="Improve asset turnover by monetizing non-core assets and shrinking working capital days.",
                )
            ]),
            ComponentNode(name="FINANCIAL LEVERAGE (DuPont Component 3)", terminals=[
                TerminalDiagnostic(
                    name="Equity Multiplier & Capital Structure",
                    root_cause="Debt-funded balance sheet amplifying returns; equity dilution from fresh share issuance reducing leverage; retained earnings accumulation",
                    additional_data=["Total assets to shareholders equity", "Debt-to-equity ratio", "Dividend payout history"],
                    management_insight="Ensure ROCE exceeds borrowing costs so financial leverage creates shareholder value rather than debt distress.",
                )
            ]),
        ],
        key_management_questions=[
            "Through DuPont decomposition, is our ROE movement driven by profit margin, asset efficiency, or financial gearing?",
            "If ROE is declining despite profit growth, is the retained earnings equity base compounding faster than net income?",
            "Is the return on capital employed comfortably higher than our post-tax cost of debt?",
        ],
        investigation_checklist=[
            "3-way DuPont decomposition trend analysis (Margin x Turnover x Leverage)",
            "Capital additions and dividend payout policy impact on equity base",
            "Return on invested capital (ROIC) vs WACC spread",
        ],
    ),

    # 7. Return on Capital Employed (ROCE)
    MetricDiagnosticTree(
        metric_id=7,
        canonical_name="Return on Capital Employed (ROCE)",
        metric_code="roce",
        formula="ROCE (%) = EBIT / Capital Employed * 100 | Capital Employed = Total Assets - Current Liabilities",
        category="growth_returns",
        components=[
            ComponentNode(name="EBIT (Operating Earnings)", terminals=[
                TerminalDiagnostic(
                    name="Operating Earnings Base",
                    root_cause="Revenue realization, manufacturing cost efficiency, and fixed overhead absorption",
                    additional_data=["EBIT by division", "Operating profit margin"],
                    management_insight="Focus capital allocation toward business units that generate ROCE in excess of 20%.",
                )
            ]),
            ComponentNode(name="FIXED CAPITAL ASSETS", terminals=[
                TerminalDiagnostic(
                    name="Gross Block & CWIP",
                    root_cause="Heavy capex expansion increasing capital employed before generating revenues; old depreciated assets optically inflating ROCE",
                    additional_data=["Capex payback analysis", "Asset age profile", "Capital work in progress (CWIP)"],
                    management_insight="Sweat existing production lines before approving greenfield capex; watch for under-investment in aging machinery.",
                )
            ]),
            ComponentNode(name="WORKING CAPITAL DEPLOYMENT", terminals=[
                TerminalDiagnostic(
                    name="Operating Working Capital Drag",
                    root_cause="Capital trapped in slow-moving inventory and overdue receivables, inflating capital employed",
                    additional_data=["Net working capital days", "Debtor ageing", "Inventory turns"],
                    management_insight="Tighten collection terms and streamline stock levels to release locked-up capital and boost ROCE.",
                )
            ]),
        ],
        key_management_questions=[
            "Which business divisions generate returns above the corporate hurdle rate?",
            "Are uncommissioned capital projects (CWIP) depressing current capital employed returns?",
            "How much capital can be freed up through working capital optimization to improve ROCE?",
        ],
        investigation_checklist=[
            "Division-level ROCE and asset productivity matrix",
            "CWIP schedule and expected project commercialization dates",
            "Net working capital as a percentage of capital employed",
        ],
    ),

    # 8. Return on Assets (ROA)
    MetricDiagnosticTree(
        metric_id=8,
        canonical_name="Return on Assets (ROA)",
        metric_code="roa",
        formula="ROA (%) = PAT / Average Total Assets * 100",
        category="growth_returns",
        components=[
            ComponentNode(name="NET PROFIT (PAT)", terminals=[
                TerminalDiagnostic(
                    name="Bottom-line Conversion",
                    root_cause="Net margin efficiency and overhead burden",
                    additional_data=["PAT trend", "PBT margin"],
                    management_insight="Enhance product pricing and cost structures to boost earnings flow from deployed assets.",
                )
            ]),
            ComponentNode(name="TOTAL ASSET EFFICIENCY", sub_components=[
                SubComponentNode(name="Fixed & Idle Assets", terminals=[
                    TerminalDiagnostic(
                        name="Under-utilized Fixed Assets",
                        root_cause="Over-investment in plant facilities relative to demand; vacant land or mothballed equipment",
                        additional_data=["Capacity utilization report", "List of idle fixed assets"],
                        management_insight="Monetize or lease out surplus non-core assets to reduce denominator drag.",
                    )
                ]),
                SubComponentNode(name="Current Assets & Advances", terminals=[
                    TerminalDiagnostic(
                        name="Working Capital Bloat",
                        root_cause="Excessive customer credit, safety inventory, or large interest-free supplier advances",
                        additional_data=["Receivables schedule", "Supplier advance aging"],
                        management_insight="Rationalize supplier advance arrangements; negotiate credit terms rather than pre-funding vendors.",
                    )
                ]),
                SubComponentNode(name="Strategic Investments & Goodwill", terminals=[
                    TerminalDiagnostic(
                        name="Subsidiary & Acquisition Drag",
                        root_cause="Capital deployed in under-performing associates/subsidiaries earning returns below cost of capital; un-impaired goodwill",
                        additional_data=["Subsidiary financial returns", "Goodwill impairment reviews"],
                        management_insight="Review investment portfolio; exit non-accretive ventures; recognize goodwill impairment if performance lags.",
                    )
                ]),
            ]),
        ],
        key_management_questions=[
            "What proportion of our total balance sheet assets are actively generating operational income?",
            "What are our idle or non-core assets valued at, and can they be liquidated to repay debt?",
            "Are investments in subsidiaries producing returns commensurate with company WACC?",
        ],
        investigation_checklist=[
            "Asset utilization register across all manufacturing and office locations",
            "Non-core asset inventory and potential disposal valuation",
            "Subsidiary investment ROI and dividend yield audit",
        ],
    ),

    # 9. Current Ratio
    MetricDiagnosticTree(
        metric_id=9,
        canonical_name="Current Ratio",
        metric_code="current_ratio",
        formula="Current Ratio = Current Assets / Current Liabilities",
        category="liquidity",
        components=[
            ComponentNode(
                name="CURRENT ASSETS",
                sub_components=[
                    SubComponentNode(name="Liquid Reserves & Receivables", terminals=[
                        TerminalDiagnostic(
                            name="Cash & Debtors Liquidity",
                            root_cause="Cash collections from customer invoices, short-term marketable deposits, and receivable billing",
                            additional_data=["Daily bank balances", "Accounts receivable ledger", "Credit term policies"],
                            management_insight="Ensure receivables represent high-quality collectible balances rather than disputed invoices.",
                        )
                    ]),
                    SubComponentNode(name="Inventory & Advances", terminals=[
                        TerminalDiagnostic(
                            name="Illiquid Current Assets",
                            root_cause="Overstocking raw materials/finished goods, slow inventory turns, large supplier advance payments",
                            additional_data=["Inventory valuation report", "Advance payment schedule", "Inventory turnover days"],
                            management_insight="High current ratio driven by bloated inventory can mask acute operational illiquidity.",
                        )
                    ]),
                ],
            ),
            ComponentNode(
                name="CURRENT LIABILITIES",
                sub_components=[
                    SubComponentNode(name="Payables & Short-Term Debt", terminals=[
                        TerminalDiagnostic(
                            name="Near-Term Obligations",
                            root_cause="Trade payables accumulation, working capital bank overdraft/CC utilization, upcoming term loan maturities (CPLTD)",
                            additional_data=["Creditor aging report", "Bank drawing power registers", "12-month debt maturity profile"],
                            management_insight="Monitor upcoming CPLTD maturities closely; avoid funding long-term assets with short-term bank limits.",
                        )
                    ]),
                    SubComponentNode(name="Statutory Dues & Advances", terminals=[
                        TerminalDiagnostic(
                            name="Customer Advances & Taxes",
                            root_cause="Unearned revenue / customer advance receipts (interest-free funding) and statutory GST/TDS dues",
                            additional_data=["Customer advance register", "Statutory tax payment schedule"],
                            management_insight="Customer advances represent positive non-debt funding; track order fulfillment conversion.",
                        )
                    ]),
                ],
            ),
        ],
        key_management_questions=[
            "Is the current ratio supported by cash and liquid receivables, or artificially inflated by slow-moving inventory?",
            "What is the quantum of Current Portion of Long-Term Debt (CPLTD) maturing over the next 12 months?",
            "Are trade payables being stretched beyond normal commercial credit terms to preserve liquidity?",
        ],
        investigation_checklist=[
            "Current asset composition breakdown (Cash vs Receivables vs Inventory vs Advances)",
            "12-month forward debt maturity schedule (CPLTD + CC renewals)",
            "Overdue trade payables and supplier hold lists",
        ],
    ),

    # 10. Quick Ratio (Acid Test Ratio)
    MetricDiagnosticTree(
        metric_id=10,
        canonical_name="Quick Ratio (Acid Test Ratio)",
        metric_code="quick_ratio",
        formula="Quick Ratio = (Current Assets - Inventory - Prepaid Expenses) / Current Liabilities",
        category="liquidity",
        components=[
            ComponentNode(name="LIQUID CURRENT ASSETS", terminals=[
                TerminalDiagnostic(
                    name="Immediate Cash & Receivables",
                    root_cause="Operational cash balances, marketable treasury securities, and trade receivables collectible within 90 days",
                    additional_data=["30/60/90-day cash forecast", "Overdue receivables >60 days", "Treasury liquidity schedule"],
                    management_insight="Quick ratio is only genuine if debtors are fully collectible; adjust for doubtful debts and customer disputes.",
                )
            ]),
            ComponentNode(name="CURRENT LIABILITIES", terminals=[
                TerminalDiagnostic(
                    name="Immediate Claimants",
                    root_cause="Supplier dues, short-term bank credit lines, statutory obligations, and CPLTD",
                    additional_data=["Supplier payment waterfall", "Bank credit line utilization"],
                    management_insight="Maintain a quick buffer equal to at least 30 days of non-deferrable operating expenditures.",
                )
            ]),
        ],
        key_management_questions=[
            "What percentage of our trade receivables in the quick asset base are overdue beyond 60 days?",
            "Do we have sufficient liquid cash and collectible debtors to cover current liabilities without selling inventory?",
            "Are committed bank overdraft/credit lines available as secondary liquidity backup?",
        ],
        investigation_checklist=[
            "Debtor ageing profile with doubtful debt provisions deducted",
            "Next 90-day cash burn and committed liability disbursement schedule",
            "Available undrawn credit facility limits from consortium lenders",
        ],
    ),

    # 11. Cash Ratio
    MetricDiagnosticTree(
        metric_id=11,
        canonical_name="Cash Ratio",
        metric_code="cash_ratio",
        formula="Cash Ratio = (Cash & Cash Equivalents) / Current Liabilities",
        category="liquidity",
        components=[
            ComponentNode(name="CASH & CASH EQUIVALENTS", terminals=[
                TerminalDiagnostic(
                    name="Ultra-Liquid Holdings",
                    root_cause="Current account balances, bank fixed deposits maturing under 90 days, and overnight/liquid mutual funds",
                    additional_data=["Daily bank balance summary", "Auto-sweep deposit accounts", "Liquid mutual fund portfolios"],
                    management_insight="Implement automated treasury sweeps to earn 6-7% on surplus balances rather than leaving cash in current accounts.",
                )
            ]),
            ComponentNode(name="CURRENT LIABILITIES", terminals=[
                TerminalDiagnostic(
                    name="Immediate Liquidity Exposure",
                    root_cause="Imminent supplier payments, monthly payroll, advance tax installments, and interest dues",
                    additional_data=["30-day cash obligation calendar", "Statutory tax payment deadlines"],
                    management_insight="A cash ratio below 0.2 is common in manufacturing; prioritize adequacy of sanctioned revolving credit lines.",
                )
            ]),
        ],
        key_management_questions=[
            "Do we maintain a minimum liquid cash reserve covering at least 30 to 45 days of fixed overheads and payroll?",
            "Are surplus bank balances placed in automated interest-bearing overnight/liquid sweep facilities?",
            "What is our projected cash position across seasonal tax payment and festival bonus payout dates?",
        ],
        investigation_checklist=[
            "Bank balance sweep agreement details and idle balance reports",
            "30-day rolling daily cash-in vs cash-out calendar",
            "Revolving credit facility unutilized headroom certificate",
        ],
    ),

    # 12. Debt / Equity Ratio
    MetricDiagnosticTree(
        metric_id=12,
        canonical_name="Debt / Equity Ratio",
        metric_code="debt_to_equity",
        formula="D/E Ratio = Total Debt (Short-term + Long-term Borrowings) / Shareholders Equity",
        category="leverage",
        components=[
            ComponentNode(name="TOTAL BORROWINGS", terminals=[
                TerminalDiagnostic(
                    name="Debt Incurrence",
                    root_cause="Capital expenditure term loan drawdowns, working capital loan expansion to fund receivables, or debenture/bond issuances",
                    additional_data=["Loan-wise outstanding register", "Working capital loan utilization", "Repayment amortization schedule"],
                    management_insight="Match debt tenors with asset economic life; avoid using short-term bank debt to finance long-gestation assets.",
                )
            ]),
            ComponentNode(name="SHAREHOLDERS EQUITY", terminals=[
                TerminalDiagnostic(
                    name="Net Worth & Capital Base",
                    root_cause="Consecutive operational losses eroding retained earnings, fresh equity issuance (QIP/rights/PE), or share buybacks",
                    additional_data=["Historical profit retention trend", "Capital restructuring documentation", "Net worth adequacy calculation"],
                    management_insight="Loss-driven equity erosion deteriorates D/E without new debt; monitor bank covenant default thresholds.",
                )
            ]),
        ],
        key_management_questions=[
            "What is the purpose of recent debt additions: productive capacity capex or operational working capital funding?",
            "Are we approaching any bank loan covenant thresholds for maximum debt-to-equity gearing?",
            "What is our planned deleveraging schedule over the next 24 to 36 months?",
        ],
        investigation_checklist=[
            "Lender-wise debt profile including interest rates, tenors, and collateral pledged",
            "Bank covenant compliance certificates and headroom analysis",
            "Equity retained earnings trend over past 3 to 5 years",
        ],
    ),

    # 13. Interest Coverage Ratio (ICR)
    MetricDiagnosticTree(
        metric_id=13,
        canonical_name="Interest Coverage Ratio",
        metric_code="interest_coverage",
        formula="ICR = EBIT / Finance Cost (Interest Expense)",
        category="leverage",
        components=[
            ComponentNode(name="OPERATING EARNINGS (EBIT)", terminals=[
                TerminalDiagnostic(
                    name="Operating Earnings Buffer",
                    root_cause="Volume drops, gross margin compression, or fixed cost deleverage reducing EBIT",
                    additional_data=["EBIT margin trajectory", "Product contribution margins"],
                    management_insight="A drop in EBIT immediately compresses interest coverage even if total debt is unchanged.",
                )
            ]),
            ComponentNode(name="FINANCE COST", terminals=[
                TerminalDiagnostic(
                    name="Interest Expense Drivers",
                    root_cause="Higher total borrowing balance, floating rate loan repricing from central bank repo rate hikes, or penal interest charges",
                    additional_data=["Weighted average interest rate", "Fixed vs floating debt proportion", "Penal interest ledger entries"],
                    management_insight="In a rising interest rate cycle, evaluate interest rate swaps or fix floating debt; penal charges signal treasury failure.",
                )
            ]),
        ],
        key_management_questions=[
            "How much headroom do we have above the bank covenant minimum ICR (typically 2.0x - 2.5x)?",
            "What percentage of our borrowings are on floating interest rates linked to repo/MCLR?",
            "Have any penal interest charges or LC devolution penalties been incurred this period?",
        ],
        investigation_checklist=[
            "Loan interest rate reset dates and spread matrix (MCLR / Repo + Spread)",
            "Interest coverage sensitivity simulation across +/- 100 bps rate shifts and +/- 10% EBIT swings",
            "Bank sanction letter covenant registers",
        ],
    ),

    # 14. Debt Service Coverage Ratio (DSCR)
    MetricDiagnosticTree(
        metric_id=14,
        canonical_name="Debt Service Coverage Ratio",
        metric_code="dscr",
        formula="DSCR = Net Operating Income (EBITDA) / Total Debt Service (Principal + Interest due in period)",
        category="leverage",
        components=[
            ComponentNode(name="OPERATING CASH GENERATION (EBITDA)", terminals=[
                TerminalDiagnostic(
                    name="Operating Cash Generator",
                    root_cause="Operating performance, cash collection efficiency, and operational profitability",
                    additional_data=["EBITDA trend", "Cash generated from operations"],
                    management_insight="If operational EBITDA is less than annual debt service (DSCR < 1.0), the entity is defaulting without external refinancing.",
                )
            ]),
            ComponentNode(name="TOTAL DEBT SERVICE OBLIGATIONS", terminals=[
                TerminalDiagnostic(
                    name="Principal & Interest Outflows",
                    root_cause="Scheduled term loan EMI repayments, bullet maturities, balloon payments, and capitalized lease obligations (Ind AS 116)",
                    additional_data=["12-month debt repayment schedule", "Lease liability payments schedule", "Refinancing arrangements"],
                    management_insight="Build a 13-week cash flow model to forecast DSCR breaches 90 days in advance; engage lenders early for rescheduling.",
                )
            ]),
        ],
        key_management_questions=[
            "Can projected operational cash flows service principal and interest obligations without relying on rollover credit?",
            "What are the upcoming balloon or bullet principal repayment milestones over the next 24 months?",
            "Are operating lease service obligations factored into lender DSCR calculations under Ind AS 116?",
        ],
        investigation_checklist=[
            "Comprehensive 12-month principal and interest repayment schedule",
            "13-week rolling operational cash flow forecast",
            "Lender covenant threshold documentation and compliance testing history",
        ],
    ),

    # 15. Asset Turnover
    MetricDiagnosticTree(
        metric_id=15,
        canonical_name="Asset Turnover",
        metric_code="asset_turnover",
        formula="Asset Turnover = Revenue / Average Total Assets",
        category="growth_returns",
        components=[
            ComponentNode(name="REVENUE GENERATION", terminals=[
                TerminalDiagnostic(
                    name="Top-line Sales Output",
                    root_cause="Pricing realization, market demand, sales channel throughput",
                    additional_data=["Revenue growth rate", "Product volume sold"],
                    management_insight="Push sales volume through established distribution channels to optimize asset sweat.",
                )
            ]),
            ComponentNode(name="ASSET UTILIZATION & DEPLOYMENT", terminals=[
                TerminalDiagnostic(
                    name="Asset Base Productivity",
                    root_cause="Plant capacity underutilization, large uncommissioned CWIP projects, excessive inventory days, or idle non-core real estate",
                    additional_data=["Installed vs actual capacity utilization %", "CWIP commissioning timeline", "Non-core asset register"],
                    management_insight="Monetize idle assets; delay fixed asset capitalization until full commercial operations begin.",
                )
            ]),
        ],
        key_management_questions=[
            "What is our plant capacity utilization percentage across major product lines?",
            "How much capital is currently locked in uncommissioned Capital Work in Progress (CWIP)?",
            "What non-core or legacy assets can be monetized to lighten the balance sheet?",
        ],
        investigation_checklist=[
            "Capacity utilization reports and machine idle-hour logs",
            "CWIP project schedule and revenue conversion projections",
            "Receivables and inventory days trends compared to industry benchmarks",
        ],
    ),

    # 16. Inventory Turnover & Inventory Days
    MetricDiagnosticTree(
        metric_id=16,
        canonical_name="Inventory Turnover",
        metric_code="dio",
        formula="Inventory Turnover = COGS / Average Inventory | Inventory Days (DIO) = 365 / Inventory Turnover",
        category="working_capital",
        components=[
            ComponentNode(name="RAW MATERIAL INVENTORY", terminals=[
                TerminalDiagnostic(
                    name="Raw Material Stocking",
                    root_cause="Conservative safety stock buffers, bulk procurement to avail quantity discounts, or precautionary stockpiling against supply disruptions",
                    additional_data=["Lead time by supplier", "Purchase order history vs consumption", "EOQ calculation models"],
                    management_insight="Calculate Economic Order Quantity (EOQ); balance supplier discounts against carrying costs; qualify local backup suppliers.",
                )
            ]),
            ComponentNode(name="WORK IN PROGRESS (WIP)", terminals=[
                TerminalDiagnostic(
                    name="Manufacturing WIP Cycle",
                    root_cause="Long production cycle times, batch size inefficiencies, or unbalanced production line bottlenecks",
                    additional_data=["Stage-wise WIP inventory", "Cycle time by workstation", "Bottleneck machine logs"],
                    management_insight="Implement Kanban pull systems; reduce batch sizes; apply Theory of Constraints to clear bottleneck stations.",
                )
            ]),
            ComponentNode(name="FINISHED GOODS & CHANNEL STOCK", terminals=[
                TerminalDiagnostic(
                    name="Finished Goods Accumulation",
                    root_cause="Demand forecast inaccuracies, minimum order quantity (MOQ) overproduction, long transit lead times, or channel stuffing at dealers",
                    additional_data=["FG ageing report", "Forecast accuracy (MAPE)", "Secondary sales vs sell-in data"],
                    management_insight="Liquidate or write down non-moving stock; monitor secondary distributor sell-out to avoid channel loading.",
                )
            ]),
        ],
        key_management_questions=[
            "What proportion of total inventory is aged over 90, 180, and 365 days?",
            "Are bulk purchase discounts being outweighed by inventory carrying and warehousing costs?",
            "What is the gap between primary sales to distributors and secondary retail sell-out?",
        ],
        investigation_checklist=[
            "Inventory ageing schedule classified by Raw Material, WIP, Finished Goods, and Spares",
            "Demand forecast variance report by SKU (forecast vs actual demand)",
            "Non-moving and slow-moving stock write-down review register",
        ],
    ),

    # 17. Receivable Turnover / Debtor Days (DSO)
    MetricDiagnosticTree(
        metric_id=17,
        canonical_name="Debtor Days (DSO)",
        metric_code="dso",
        formula="Receivable Turnover = Revenue / Average Trade Receivables | Debtor Days (DSO) = 365 / Receivable Turnover",
        category="working_capital",
        components=[
            ComponentNode(name="CREDIT POLICY & LIMIT MANAGEMENT", terminals=[
                TerminalDiagnostic(
                    name="Credit Terms Policy",
                    root_cause="Overly liberal credit terms vs industry peers, or sales representatives overriding credit limits to close deals",
                    additional_data=["Customer credit terms schedule", "Sales credit override log", "Industry benchmark debtor days"],
                    management_insight="Standardize credit terms; implement hard credit limits in ERP that cannot be overridden by sales reps.",
                )
            ]),
            ComponentNode(name="COLLECTION EFFICIENCY & DISTRESS", terminals=[
                TerminalDiagnostic(
                    name="Collections Execution",
                    root_cause="Lack of structured dunning follow-up, customer financial insolvency, or invoice quality/billing disputes",
                    additional_data=["Collection follow-up call logs", "Customer payment delinquency history", "Disputed invoice register"],
                    management_insight="Establish weekly collection MIS; fast-track dispute resolutions; initiate legal demand notices on >90 day overdue accounts.",
                )
            ]),
            ComponentNode(name="REVENUE RECOGNITION TIMING", terminals=[
                TerminalDiagnostic(
                    name="Cut-off & Recognition Timing",
                    root_cause="Booking revenue on dispatch before delivery acceptance (POD lag) inflating unearned receivables",
                    additional_data=["Proof of delivery (POD) confirmation logs", "Revenue recognition policy under Ind AS 115"],
                    management_insight="Align invoice booking strictly with performance obligations under Ind AS 115 / IFRS 15.",
                )
            ]),
        ],
        key_management_questions=[
            "What percentage of outstanding receivables are overdue beyond 30, 60, and 90 days?",
            "Which top 10 customer accounts represent the highest collection risk or overdue balance?",
            "Are sales commissions tied to cash collections or merely to booked sales invoices?",
        ],
        investigation_checklist=[
            "Accounts receivable ageing analysis broken down by customer category",
            "Customer dispute tracking log with root-cause categorization",
            "Credit limit override logs and bad debt write-off approvals",
        ],
    ),

    # 18. Payable Turnover / Creditor Days (DPO)
    MetricDiagnosticTree(
        metric_id=18,
        canonical_name="Creditor Days (DPO)",
        metric_code="dpo",
        formula="Payable Turnover = Purchases / Average Trade Payables | Creditor Days (DPO) = 365 / Payable Turnover",
        category="working_capital",
        components=[
            ComponentNode(name="SUPPLIER PAYMENT TERMS", terminals=[
                TerminalDiagnostic(
                    name="Negotiated Vendor Terms",
                    root_cause="Weak bargaining power paying too early vs peers, or deliberately taking early-settlement cash discounts",
                    additional_data=["Supplier payment terms master", "Cash discounts earned register", "Industry peer DPO benchmarks"],
                    management_insight="Consolidate procurement volume across fewer vendors to negotiate 60-90 day payment terms; verify early discount ROI.",
                )
            ]),
            ComponentNode(name="PAYMENT PROCESS & CASH STRETCHING", terminals=[
                TerminalDiagnostic(
                    name="Processing Delays & Cash Stretching",
                    root_cause="Slow internal 3-way matching and GRN verification, or deliberate payable stretching to manage cash shortages",
                    additional_data=["Invoice-to-payment cycle days", "Pending Goods Receipt Notes (GRN)", "Vendor hold notices"],
                    management_insight="Automate invoice processing; avoid chronic overdue stretching that endangers supply continuity; use Supply Chain Financing (SCF).",
                )
            ]),
            ComponentNode(name="REGULATORY COMPLIANCE (MSME)", terminals=[
                TerminalDiagnostic(
                    name="MSME Statutory Payment Mandate",
                    root_cause="Legal requirement under MSMED Act to settle registered MSME vendor invoices within 45 days",
                    additional_data=["MSME supplier classification list", "Invoices pending beyond 45 days", "Statutory interest liability"],
                    management_insight="Maintain updated MSME supplier registers; enforce strict 45-day payment compliance to avoid non-deductible penal interest.",
                )
            ]),
        ],
        key_management_questions=[
            "What is our compliance rate for settling registered MSME suppliers within the mandatory 45-day statutory window?",
            "Are we stretching critical vendor payments to the point of risking supply chain disruptions or price surcharges?",
            "Could we implement a bank-sponsored Supply Chain Financing (Reverse Factoring) program to extend payment terms?",
        ],
        investigation_checklist=[
            "Trade payable ageing report classified by MSME and non-MSME vendors",
            "Supplier dispute and pending GRN reconciliation logs",
            "Cash discount utilization vs short-term borrowing cost analysis",
        ],
    ),

    # 19. Cash Conversion Cycle (CCC)
    MetricDiagnosticTree(
        metric_id=19,
        canonical_name="Cash Conversion Cycle (CCC)",
        metric_code="cash_conversion_cycle",
        formula="CCC = Inventory Days (DIO) + Debtor Days (DSO) - Creditor Days (DPO)",
        category="working_capital",
        components=[
            ComponentNode(name="INVENTORY HOLDING PERIOD (DIO)", terminals=[
                TerminalDiagnostic(
                    name="Inventory Cash Drain",
                    root_cause="Capital trapped in raw materials, WIP, and unsold finished goods",
                    additional_data=["DIO trend by inventory category", "Slow-moving inventory analysis"],
                    management_insight="Target each inventory stage (RM, WIP, FG) with specific reduction initiatives (JIT, VMI).",
                )
            ]),
            ComponentNode(name="RECEIVABLES COLLECTION PERIOD (DSO)", terminals=[
                TerminalDiagnostic(
                    name="Receivables Cash Drain",
                    root_cause="Customer credit extensions and delayed collections postponing operational cash receipts",
                    additional_data=["DSO trend by business division", "Overdue accounts"],
                    management_insight="Evaluate invoice factoring or digital bill discounting platforms (TReDS) for faster cash realization.",
                )
            ]),
            ComponentNode(name="PAYABLES FINANCING PERIOD (DPO)", terminals=[
                TerminalDiagnostic(
                    name="Supplier Operational Funding",
                    root_cause="Credit terms extended by suppliers providing interest-free operational working capital",
                    additional_data=["DPO trend by material category", "Vendor terms"],
                    management_insight="Maximize vendor credit within agreed contractual and legal terms to shorten net cash cycle.",
                )
            ]),
        ],
        key_management_questions=[
            "How many net days does it take to convert inventory investments back into operational cash?",
            "Which of the three levers (DIO, DSO, DPO) is the primary contributor to recent CCC deterioration?",
            "What is the total cash release potential from reducing CCC by 15 days?",
        ],
        investigation_checklist=[
            "Quarterly trend comparison of DIO, DSO, DPO, and CCC",
            "Working capital funding gap analysis against bank credit limits",
            "Working capital cash release sensitivity matrix",
        ],
    ),

    # 20. Operating Cash Flow (OCF)
    MetricDiagnosticTree(
        metric_id=20,
        canonical_name="Operating Cash Flow",
        metric_code="ocf_to_pat",
        formula="OCF = PAT + Non-cash Charges (D&A, Provisions) - Working Capital Increase",
        category="working_capital",
        components=[
            ComponentNode(name="NET PROFIT (PAT)", terminals=[
                TerminalDiagnostic(
                    name="Net Accrual Earnings",
                    root_cause="Core operational earnings before cash flow timing adjustments",
                    additional_data=["Income statement PAT", "EBITDA"],
                    management_insight="Net profit provides the baseline starting point for operating cash generation.",
                )
            ]),
            ComponentNode(name="NON-CASH ADD-BACKS", terminals=[
                TerminalDiagnostic(
                    name="Non-Cash Accounting Charges",
                    root_cause="Depreciation and amortisation, bad debt provisions, warranty reserves, and deferred tax accruals",
                    additional_data=["D&A schedule", "Provision movements schedule", "Deferred tax asset/liability changes"],
                    management_insight="Repeatedly high non-cash provision add-backs signal underlying asset quality issues.",
                )
            ]),
            ComponentNode(name="WORKING CAPITAL MOVEMENTS", terminals=[
                TerminalDiagnostic(
                    name="Working Capital Cash Drag / Release",
                    root_cause="Inventory build-up (cash outflow), trade receivables growth (cash outflow), or payables stretching (short-term cash boost)",
                    additional_data=["Balance sheet working capital changes", "Operating cash flow bridge"],
                    management_insight="If revenue growth outpaces cash collections, working capital absorptions will create a severe cash squeeze.",
                )
            ]),
        ],
        key_management_questions=[
            "What is our OCF-to-PAT conversion ratio (sustainable companies convert 80-100%+)?",
            "Is reported profit failing to translate to cash due to working capital expansion?",
            "Has operating cash flow been artificially boosted by stretching trade payables beyond acceptable terms?",
        ],
        investigation_checklist=[
            "Indirect method cash flow statement bridge from PAT to OCF",
            "Working capital delta analysis (Inventory, Receivables, Payables changes)",
            "Quarterly comparison of OCF vs reported PAT",
        ],
    ),

    # 21. Free Cash Flow (FCF)
    MetricDiagnosticTree(
        metric_id=21,
        canonical_name="Free Cash Flow",
        metric_code="free_cash_flow",
        formula="FCF = Operating Cash Flow - Capital Expenditure (Capex)",
        category="working_capital",
        components=[
            ComponentNode(name="OPERATING CASH FLOW", terminals=[
                TerminalDiagnostic(
                    name="Operating Cash Baseline",
                    root_cause="Cash generated from day-to-day business operations net of working capital movements",
                    additional_data=["Operating cash flow statement", "Working capital movements"],
                    management_insight="Ensure operating cash flow is positive and robust before committing to growth capital spending.",
                )
            ]),
            ComponentNode(name="CAPITAL EXPENDITURE (CAPEX)", terminals=[
                TerminalDiagnostic(
                    name="Capital Allocations",
                    root_cause="Maintenance capex to sustain existing capacity vs growth capex for expansion or acquisitions",
                    additional_data=["Maintenance vs growth capex breakdown", "Projected capex commitments schedule"],
                    management_insight="Maintenance capex is mandatory; FCF after maintenance capex represents true discretionary shareholder cash.",
                )
            ]),
            ComponentNode(name="FCF CONVERSION & YIELD", terminals=[
                TerminalDiagnostic(
                    name="Cash Flow Quality",
                    root_cause="FCF-to-PAT conversion ratio and FCF yield relative to market valuation or enterprise value",
                    additional_data=["FCF conversion ratio trend", "Enterprise value"],
                    management_insight="Target consistent FCF conversion of 70-90% of PAT across economic cycles.",
                )
            ]),
        ],
        key_management_questions=[
            "What is the split between mandatory maintenance capex and discretionary growth capex?",
            "What is our FCF conversion ratio (FCF / PAT), and why are reported profits not converting to surplus cash?",
            "Can projected FCF fund upcoming debt principal repayments and dividend distributions without fresh borrowing?",
        ],
        investigation_checklist=[
            "Detailed project-wise capex authorization vs expenditure report",
            "Multi-year FCF bridge and conversion track record",
            "Debt repayment schedule vs projected discretionary free cash flow",
        ],
    ),

    # 22. Working Capital
    MetricDiagnosticTree(
        metric_id=22,
        canonical_name="Working Capital",
        metric_code="working_capital",
        formula="Working Capital = Current Assets - Current Liabilities | Net Working Capital = Inventory + Receivables - Payables",
        category="working_capital",
        components=[
            ComponentNode(name="OPERATIONAL COMPONENTS (Inventory, Receivables, Payables)", terminals=[
                TerminalDiagnostic(
                    name="Operating NWC Spread",
                    root_cause="Commercial credit terms, production cycle holding requirements, and supplier terms",
                    additional_data=["NWC composition breakdown", "Historical working capital as % of sales"],
                    management_insight="Keep net working capital as a percentage of revenue within targeted operational ranges (15-20%).",
                )
            ]),
            ComponentNode(name="WORKING CAPITAL GAP DRIVERS", terminals=[
                TerminalDiagnostic(
                    name="Structural Working Capital Drivers",
                    root_cause="B2B vs B2C business model characteristics, seasonal inventory buildup, and rapid revenue expansion consuming liquidity",
                    additional_data=["B2B credit sales percentage", "Seasonal monthly WC requirements", "Revenue growth vs WC growth correlation"],
                    management_insight="Fast-growing businesses require pre-arranged working capital facilities to avoid liquidity crises.",
                )
            ]),
            ComponentNode(name="WORKING CAPITAL FINANCING", terminals=[
                TerminalDiagnostic(
                    name="Financing Facility Structure",
                    root_cause="Revolving bank Cash Credit / Overdraft lines, trade supplier credit, or receivable discounting / TReDS",
                    additional_data=["Bank CC limit utilization %", "Drawing power certificates", "Supplier credit balances"],
                    management_insight="Maintain bank CC utilization below 80-85% to ensure adequate liquidity headroom during seasonal spikes.",
                )
            ]),
        ],
        key_management_questions=[
            "Is rapid revenue growth absorbing more cash into working capital than our operating profits can generate?",
            "What is our current bank credit facility drawing power and CC limit utilization rate?",
            "What structural changes to customer and supplier credit terms could compress our working capital requirement?",
        ],
        investigation_checklist=[
            "Monthly Working Capital Gap (WCG) analysis",
            "Drawing power calculation sheets and bank hypothecation stock audits",
            "Receivable factoring and reverse factoring availability assessment",
        ],
    ),

    # 23. Inventory
    MetricDiagnosticTree(
        metric_id=23,
        canonical_name="Inventory",
        metric_code="inventory",
        formula="Inventory = Raw Material + Work In Progress + Finished Goods + Packing Material + Consumables + Spares",
        category="working_capital",
        components=[
            ComponentNode(name="RAW MATERIAL & PACKING", terminals=[
                TerminalDiagnostic(
                    name="Procurement & Lead Time",
                    root_cause="Over-procurement vs production schedules, extended import shipping lead times, and single-supplier risks",
                    additional_data=["Purchase plan vs consumption", "Import shipment transit logs", "Vendor lead times"],
                    management_insight="Align purchase orders with dynamic MRP schedules; develop domestic substitute vendors to cut transit holding.",
                )
            ]),
            ComponentNode(name="WORK IN PROGRESS", terminals=[
                TerminalDiagnostic(
                    name="Shopfloor Bottlenecks",
                    root_cause="Multi-stage production complexity, large batch processing, and line imbalance",
                    additional_data=["WIP stage tracking reports", "Batch cycle run times"],
                    management_insight="Adopt lean cellular manufacturing; reduce setup changeover times to enable smaller batch runs.",
                )
            ]),
            ComponentNode(name="FINISHED GOODS & OBSOLESCENCE", terminals=[
                TerminalDiagnostic(
                    name="Finished Goods & Ageing",
                    root_cause="Demand forecast errors leading to unsold stock pile-ups, distribution transit delays, or product design obsolescence",
                    additional_data=["SKU forecast vs actual orders", "Warehouse stock age buckets", "Scrap/write-off log"],
                    management_insight="Perform monthly inventory ageing reviews; discount or liquidate slow-moving SKUs before complete obsolescence.",
                )
            ]),
        ],
        key_management_questions=[
            "What is the valuation of obsolete, damaged, or slow-moving stock that requires provision or liquidation?",
            "Why is work-in-progress inventory accumulating at specific production stations?",
            "What is our forecast accuracy percentage across high-volume SKUs?",
        ],
        investigation_checklist=[
            "Comprehensive physical stock audit report vs perpetual inventory ledger",
            "SKU-level ageing analysis with slow-moving flag indicators",
            "Scrap write-down register and salvage realization history",
        ],
    ),

    # 24. Trade Receivables
    MetricDiagnosticTree(
        metric_id=24,
        canonical_name="Trade Receivables",
        metric_code="trade_receivables",
        formula="Trade Receivables = Sum of Outstanding Customer Invoices not yet Collected (net of provisions)",
        category="working_capital",
        components=[
            ComponentNode(name="GROSS OUTSTANDING INVOICES", terminals=[
                TerminalDiagnostic(
                    name="Billing Volume & Channel Mix",
                    root_cause="Sales growth increasing invoice volumes, and distributor channel terms being longer than direct customer terms",
                    additional_data=["Revenue vs AR growth rates", "Channel-wise receivables breakdown"],
                    management_insight="Monitor distributor channel exposure separately; distributor insolvencies can create catastrophic credit losses.",
                )
            ]),
            ComponentNode(name="OVERDUE AGEING BRACKETS", terminals=[
                TerminalDiagnostic(
                    name="Delinquency Escalation",
                    root_cause="0-30 days (transit processing), 31-60 days (customer cash flow delays), 61-90 days (serious financial distress), >90 days (high default risk)",
                    additional_data=["Detailed ageing buckets (0-30, 31-60, 61-90, >90)", "Customer credit scores", "Legal dispute files"],
                    management_insight="Stop further shipments to accounts exceeding 60 days overdue; initiate formal legal recovery on >90 day balances.",
                )
            ]),
            ComponentNode(name="PROVISIONS & WRITE-OFFS", terminals=[
                TerminalDiagnostic(
                    name="Expected Credit Loss (ECL)",
                    root_cause="Forward-looking ECL provisioning under Ind AS 109 and bad debt write-offs",
                    additional_data=["ECL provisioning matrix", "Write-off approval documents", "Historical default rates"],
                    management_insight="Maintain adequate, conservative bad debt provisions; pursue concurrent legal claims on written-off accounts.",
                )
            ]),
        ],
        key_management_questions=[
            "What is the total value of receivables past due beyond 90 days and what legal recovery steps have been initiated?",
            "Are distributor concentration risks monitored with personal or corporate guarantees?",
            "Is the ECL provisioning matrix aligned with actual historical loss and current sector stress?",
        ],
        investigation_checklist=[
            "Accounts receivable ledger broken into standard aging buckets",
            "Top 20 delinquent customer profiles and collection action logs",
            "ECL provision computation schedules under Ind AS 109",
        ],
    ),

    # 25. Trade Payables
    MetricDiagnosticTree(
        metric_id=25,
        canonical_name="Trade Payables",
        metric_code="trade_payables",
        formula="Trade Payables = Sum of Outstanding Supplier Invoices not yet Paid",
        category="working_capital",
        components=[
            ComponentNode(name="OPERATIONAL & CAPEX PURCHASES", terminals=[
                TerminalDiagnostic(
                    name="Procurement Volumes",
                    root_cause="Production scale-up requiring higher input material purchases; machinery/capital equipment suppliers (capex creditors)",
                    additional_data=["Purchase trends vs production", "Capex creditor schedule"],
                    management_insight="Segregate operational trade creditors from capex creditors in working capital evaluations.",
                )
            ]),
            ComponentNode(name="PAYMENT TERMS & COMPLIANCE", terminals=[
                TerminalDiagnostic(
                    name="Terms Execution & MSME Mandate",
                    root_cause="Contractual credit periods (30/45/60/90 days) and MSMED Act 45-day statutory payment enforcement",
                    additional_data=["Vendor credit agreement master", "MSME compliance report"],
                    management_insight="Pay precisely on due dates -- not before (preserves cash) or after (protects vendor goodwill and avoids MSME penalties).",
                )
            ]),
            ComponentNode(name="OVERDUE LIABILITIES & CONCENTRATION", terminals=[
                TerminalDiagnostic(
                    name="Delinquency & Single-Source Risks",
                    root_cause="Cash shortages causing overdue delays beyond terms, or over-reliance on 1-2 dominant suppliers",
                    additional_data=["Overdue payables schedule", "Top 5 vendor spend concentration %", "Alternative vendor qualification list"],
                    management_insight="Maintain multi-sourcing for all critical inputs; prevent key supplier supply stoppages through structured payment plans.",
                )
            ]),
        ],
        key_management_questions=[
            "Are any key suppliers threatening supply halts or credit holds due to overdue payments?",
            "What is our statutory compliance status regarding payments to registered MSME suppliers?",
            "What percentage of total procurement spend is concentrated in our top 3 suppliers?",
        ],
        investigation_checklist=[
            "Creditor ageing schedule by supplier category and MSME flag",
            "Supplier concentration analysis (Top 10 vendors as % of total purchases)",
            "Disputed vendor invoice log and pending debit notes",
        ],
    ),

    # 26. Revenue from Operations
    MetricDiagnosticTree(
        metric_id=26,
        canonical_name="Revenue from Operations",
        metric_code="revenue",
        formula="Revenue from Operations = Product Sales + Service Revenue + Other Operating Income",
        category="growth_returns",
        components=[
            ComponentNode(name="PRODUCT SALES REVENUE", sub_components=[
                SubComponentNode(name="Domestic Sales (Volume & Price)", terminals=[
                    TerminalDiagnostic(
                        name="Domestic Sales Realization",
                        root_cause="Market demand, price realization, competitor actions, or high sales returns from quality defects",
                        additional_data=["Volume vs price variance analysis", "Return rate % and reason codes", "SKU-wise sales"],
                        management_insight="Separate volume vs price variance; high returns signal acute product defect or delivery problems.",
                    )
                ]),
                SubComponentNode(name="Export Sales & Forex", terminals=[
                    TerminalDiagnostic(
                        name="Export Throughput & Currency",
                        root_cause="Overseas market demand, foreign product standards compliance, exchange rate movements, and export incentive claims",
                        additional_data=["Country-wise export volumes", "Forex realization per invoice", "Export incentive receivables (RoDTEP/PLI)"],
                        management_insight="Track constant-currency export growth; maximize government export incentive realizations.",
                    )
                ]),
            ]),
            ComponentNode(name="SERVICE REVENUE", terminals=[
                TerminalDiagnostic(
                    name="Service & AMC Contracts",
                    root_cause="Annual maintenance contracts (AMC) renewal rates, equipment installation, and post-sales technical services",
                    additional_data=["AMC renewal %", "Service revenue gross margins"],
                    management_insight="Service revenues carry superior margins and predictable cash flows; mandate AMC cross-selling with product sales.",
                )
            ]),
            ComponentNode(name="OTHER OPERATING INCOME", terminals=[
                TerminalDiagnostic(
                    name="Scrap & Government Subsidies",
                    root_cause="Manufacturing scrap sales and production-linked government incentives (PLI, MSME subsidies)",
                    additional_data=["Scrap quantity and market rates", "PLI compliance milestone certificates"],
                    management_insight="Maximize scrap recycling value; maintain rigorous compliance documentation to safeguard PLI subsidies against clawback.",
                )
            ]),
        ],
        key_management_questions=[
            "What is the exact volume vs price variance driving top-line revenue growth?",
            "What are the primary root causes behind customer product returns and credit notes?",
            "What percentage of revenue is recurring contracted service/AMC income vs one-off transaction sales?",
        ],
        investigation_checklist=[
            "Volume-Price-Mix (VPM) variance waterfall breakdown",
            "Sales return and credit note log by customer and product category",
            "AMC contract renewal pipeline and deferred revenue schedule",
        ],
    ),

    # 27. Cost of Goods Sold (COGS)
    MetricDiagnosticTree(
        metric_id=27,
        canonical_name="Cost of Goods Sold (COGS)",
        metric_code="cogs",
        formula="COGS = Opening Inventory + Purchases + Direct Labour + Direct Overheads - Closing Inventory",
        category="profitability",
        components=[
            ComponentNode(name="RAW MATERIAL CONSUMED", terminals=[
                TerminalDiagnostic(
                    name="Purchase Price & Material Usage Variances",
                    root_cause="Market commodity inflation, procurement pricing renegotiations, or material usage exceeding standard engineering BOM",
                    additional_data=["Standard vs actual purchase price per unit", "BOM variance logs", "Daily shopfloor wastage registers"],
                    management_insight="Implement rigorous Purchase Price Variance (PPV) accountability; treat engineering BOM specifications as sacred.",
                )
            ]),
            ComponentNode(name="DIRECT LABOUR & OVERHEADS", terminals=[
                TerminalDiagnostic(
                    name="Direct Manufacturing Inputs",
                    root_cause="Manufacturing payroll, shift overtime, electricity/fuel costs, consumables, and outsourced job-work charges",
                    additional_data=["Overtime premium registers", "Power & fuel consumption logs", "Job-worker rate comparisons"],
                    management_insight="Compare in-house manufacturing costs vs outsourced job-work rates; evaluate captive solar to control power tariffs.",
                )
            ]),
            ComponentNode(name="INVENTORY VALUATION ADJUSTMENTS", terminals=[
                TerminalDiagnostic(
                    name="Stock Movement Impact",
                    root_cause="Inventory accumulation (reduces reported COGS) or stock drawdowns (increases reported COGS); NRV write-down charges",
                    additional_data=["Opening vs closing inventory valuation", "Inventory valuation methodology (FIFO/Weighted Avg)", "NRV assessment reports"],
                    management_insight="Verify that inventory write-downs to Net Realizable Value (NRV) are factored in quarterly rather than deferred to year-end.",
                )
            ]),
        ],
        key_management_questions=[
            "What is our Purchase Price Variance (PPV) and Material Usage Variance across top 5 raw materials?",
            "How much of the COGS movement is driven by physical inventory stock build-up vs drawdown?",
            "Is outsourced job-work cost-effective compared to internal production capacity?",
        ],
        investigation_checklist=[
            "Standard cost vs actual cost variance report (PPV and Usage variance)",
            "Bill of Materials (BOM) consumption audit by batch production run",
            "Monthly opening to closing inventory bridge with NRV adjustments",
        ],
    ),

    # 28. Employee Cost
    MetricDiagnosticTree(
        metric_id=28,
        canonical_name="Employee Cost",
        metric_code="employee_cost",
        formula="Employee Cost = Salaries + Allowances + PF + Gratuity + ESIC + Bonus + ESOPs + Staff Welfare + Recruitment & Training",
        category="cost_structure",
        components=[
            ComponentNode(name="FIXED COMPENSATION", sub_components=[
                SubComponentNode(name="Headcount & Annual Increments", terminals=[
                    TerminalDiagnostic(
                        name="Base Salary & Headcount",
                        root_cause="Hiring ahead of revenue realization, replacement hiring at salary premiums, across-the-board annual salary increments",
                        additional_data=["Departmental headcount vs budget", "Average salary increment %", "Open hiring requisitions"],
                        management_insight="Benchmark revenue per employee against sector leaders; contain salary increments within budgeted payroll limits.",
                    )
                ]),
                SubComponentNode(name="Statutory Employee Contributions", terminals=[
                    TerminalDiagnostic(
                        name="Statutory Social Security",
                        root_cause="Provident fund employer matching (12%), ESIC contributions, and actuarial gratuity liability provisions",
                        additional_data=["PF/ESIC contribution ledgers", "Actuarial valuation report for gratuity"],
                        management_insight="Set up an approved Gratuity Trust to secure tax deduction advantages on gratuity funding.",
                    )
                ]),
            ]),
            ComponentNode(name="VARIABLE INCENTIVES & ESOPS", terminals=[
                TerminalDiagnostic(
                    name="Performance Pay & Stock Compensation",
                    root_cause="Target-linked annual performance bonuses, sales commission payouts, and ESOP fair value vesting charges (Ind AS 102)",
                    additional_data=["Bonus pool achievement metrics", "Sales commission vs margin realization", "ESOP vesting schedule"],
                    management_insight="Align sales commissions with gross margin and cash collection rather than raw invoice booking.",
                )
            ]),
            ComponentNode(name="RECRUITMENT & ATTRITION COSTS", terminals=[
                TerminalDiagnostic(
                    name="Turnover & Search Agency Fees",
                    root_cause="External recruitment agency commissions (8-12% of CTC) and replacement retraining costs from elevated staff turnover",
                    additional_data=["Agency fees per hire", "Departmental attrition rates", "Exit interview diagnostic summaries"],
                    management_insight="High turnover carries an invisible replacement cost of 1-2x annual salary; expand internal employee referral channels.",
                )
            ]),
        ],
        key_management_questions=[
            "What is our revenue per employee trend over the last 8 quarters?",
            "Are sales incentives tied to gross margin realization and cash collections or pure top-line booking?",
            "What is our employee attrition rate in key revenue-generating and technical leadership roles?",
        ],
        investigation_checklist=[
            "Department-wise headcount, payroll cost, and revenue-per-head matrix",
            "Actuarial gratuity and leave encashment valuation report",
            "Sales commission incentive audit vs realized customer collections",
        ],
    ),

    # 29. Selling & Marketing Expense
    MetricDiagnosticTree(
        metric_id=29,
        canonical_name="Selling & Marketing Expense",
        metric_code="sm_expense",
        formula="S&M Expense = Advertising + Promotions + Sales Force Cost + Distribution + Branding + Digital Marketing + Trade Schemes",
        category="cost_structure",
        components=[
            ComponentNode(name="ADVERTISING & PERFORMANCE MARKETING", terminals=[
                TerminalDiagnostic(
                    name="Media & Digital Campaigns",
                    root_cause="Brand awareness campaigns (TV/Print/OOH) and digital performance marketing spend (Google/Meta ads, SEO, SEM)",
                    additional_data=["Media channel spend logs", "ROAS (Return on Ad Spend)", "Customer Acquisition Cost (CAC)"],
                    management_insight="Track ROAS weekly; immediately pause ad sets that fail to achieve targeted contribution margin thresholds.",
                )
            ]),
            ComponentNode(name="TRADE SCHEMES & CONSUMER OFFERS", terminals=[
                TerminalDiagnostic(
                    name="Trade & Consumer Promotions",
                    root_cause="Distributor volume-linked incentive schemes, festival discounts, cashbacks, and buy-one-get-one consumer promotions",
                    additional_data=["Scheme-wise spend report", "Volume uplift per promotion", "Distributor secondary sell-out data"],
                    management_insight="Audit whether distributor trade schemes are driving genuine consumer uptake or simply channel stuffing.",
                )
            ]),
            ComponentNode(name="SALES FORCE & OUTWARD FREIGHT", terminals=[
                TerminalDiagnostic(
                    name="Field Sales & Outward Logistics",
                    root_cause="Field sales salaries, travel conveyance, CRM software licenses, primary factory freight, and secondary last-mile delivery",
                    additional_data=["Revenue per sales representative", "CRM license adoption rate", "Outward freight cost per ton-km"],
                    management_insight="Restructure underperforming sales territories; consolidate logistics carriers and tender freight contracts annually.",
                )
            ]),
        ],
        key_management_questions=[
            "What is our ROAS and Customer Acquisition Cost (CAC) across each paid advertising channel?",
            "Are distributor incentive schemes generating genuine secondary sales or loading inventory?",
            "What is our outward freight cost per unit delivered and can route optimization reduce logistics spend?",
        ],
        investigation_checklist=[
            "Marketing spend attribution report (Spend, CAC, ROAS by channel)",
            "Distributor trade scheme ROI and secondary sell-through verification",
            "Outward freight carrier contracts and rate comparison benchmarks",
        ],
    ),

    # 30. Administrative Expense
    MetricDiagnosticTree(
        metric_id=30,
        canonical_name="Administrative Expense",
        metric_code="admin_expense",
        formula="Admin Expense = Office Rent + Utilities + Communication + Professional Fees + Travel + Corporate Overheads",
        category="cost_structure",
        components=[
            ComponentNode(name="OCCUPANCY & UTILITIES", terminals=[
                TerminalDiagnostic(
                    name="Office Infrastructure",
                    root_cause="Lease rental escalations, unutilized corporate real estate post-hybrid work adoption, electricity, and facility maintenance",
                    additional_data=["Office sq.ft. per employee", "Rent per sq.ft.", "Facility management contract rates"],
                    management_insight="Right-size corporate office footprint; sub-lease surplus floor space; renegotiate leases on expiry.",
                )
            ]),
            ComponentNode(name="PROFESSIONAL & CONSULTING FEES", terminals=[
                TerminalDiagnostic(
                    name="Legal, Audit & Advisory",
                    root_cause="Statutory and internal audit fees, corporate legal litigation and contract retainer fees, strategy consulting engagements",
                    additional_data=["Audit fee vs company turnover", "Legal case settlement probability", "Consultant project deliverable reviews"],
                    management_insight="Challenge high consulting fees lacking tangible ROI; switch legal engagements to retainer/contingency models.",
                )
            ]),
            ComponentNode(name="TRAVEL & CORPORATE IT OVERHEADS", terminals=[
                TerminalDiagnostic(
                    name="Travel & Administrative Support",
                    root_cause="Executive business travel, hotel bookings, vehicle fleet leases, telecom packages, and paper stationery",
                    additional_data=["Travel spend per executive trip", "Video vs in-person meeting ratio", "Fleet vehicle fuel card audits"],
                    management_insight="Mandate advance economy-class travel bookings; shift to paperless digital workflows and e-signatures.",
                )
            ]),
        ],
        key_management_questions=[
            "Are we sub-leasing or consolidating unutilized corporate office space post-WFH adoption?",
            "What tangible business outcomes have been delivered from strategy and IT consulting advisory fees?",
            "Can corporate travel and executive vehicle fleet costs be rationalized?",
        ],
        investigation_checklist=[
            "Corporate lease agreement registers and square-foot utilization benchmarks",
            "Professional fee breakdown (Audit, Legal, Consulting, Tax advisory)",
            "Corporate travel expense audit by department and seniority tier",
        ],
    ),

    # 31. Technology Expense
    MetricDiagnosticTree(
        metric_id=31,
        canonical_name="Technology Expense",
        metric_code="tech_expense",
        formula="Technology Expense = Software Subscriptions + Hardware + IT Infra + IT Payroll + Cybersecurity + Cloud + Outsourced IT",
        category="cost_structure",
        components=[
            ComponentNode(name="SOFTWARE LICENSES & SAAS", terminals=[
                TerminalDiagnostic(
                    name="SaaS & ERP Subscriptions",
                    root_cause="ERP user licensing tiers, SaaS tool proliferation across business departments, unused collaboration tool seats",
                    additional_data=["Active vs provisioned user licenses", "SaaS subscription inventory", "Renewal schedules"],
                    management_insight="Deactivate unused software licenses; centralize software procurement; eliminate overlapping department tools.",
                )
            ]),
            ComponentNode(name="CLOUD INFRASTRUCTURE (AWS/Azure/GCP)", terminals=[
                TerminalDiagnostic(
                    name="Cloud Compute & Storage",
                    root_cause="Over-provisioned cloud compute instances, unoptimized storage tiers, backup disaster recovery compliance requirements",
                    additional_data=["Cloud invoice by service", "On-demand vs reserved instance ratio", "Data backup storage tiering"],
                    management_insight="Implement a FinOps program; commit to reserved instances/savings plans for steady workloads; move old data to cold storage.",
                )
            ]),
            ComponentNode(name="CYBERSECURITY & IT TALENT", terminals=[
                TerminalDiagnostic(
                    name="Security & Engineering Team",
                    root_cause="Cybersecurity tooling (SIEM, endpoint), compliance certifications (SOC 2, ISO 27001), and in-house vs outsourced IT engineers",
                    additional_data=["Security tools portfolio", "Certification audit fees", "IT headcount cost vs managed services SLA"],
                    management_insight="Enforce vendor SLA penalties for IT managed services; treat cybersecurity certifications as enterprise sales enablers.",
                )
            ]),
        ],
        key_management_questions=[
            "What is our cloud infrastructure spend efficiency (FinOps) and what portion of instances are reserved vs on-demand?",
            "How many redundant or underutilized SaaS software subscriptions exist across departments?",
            "Are enterprise cybersecurity and data privacy compliance controls up to audit standards?",
        ],
        investigation_checklist=[
            "Cloud provider detailed billing reports and utilization metrics",
            "Corporate SaaS inventory audit (license count vs active monthly logins)",
            "IT vendor managed service SLA compliance and penalty reports",
        ],
    ),

    # 32. Manufacturing Cost
    MetricDiagnosticTree(
        metric_id=32,
        canonical_name="Manufacturing Cost",
        metric_code="mfg_cost",
        formula="Manufacturing Cost = RM Cost + Direct Labour + Factory Overheads (Power, Maintenance, Insurance, Depreciation)",
        category="cost_structure",
        components=[
            ComponentNode(name="RAW MATERIAL & DIRECT LABOUR", terminals=[
                TerminalDiagnostic(
                    name="Direct Shopfloor Production Costs",
                    root_cause="Input raw materials, production line workers, overtime, and contract labour",
                    additional_data=["Direct material consumption logs", "Worker output per shift"],
                    management_insight="Refer to COGS and Gross Margin diagnostic trees for root causes of direct material and labour variances.",
                )
            ]),
            ComponentNode(name="FACTORY UTILITIES & MAINTENANCE", terminals=[
                TerminalDiagnostic(
                    name="Plant Overheads & Machine Reliability",
                    root_cause="Industrial power tariffs, furnace/boiler fuel, unplanned breakdown maintenance, tooling consumables, and factory insurance",
                    additional_data=["Machine-wise electricity metering", "Breakdown frequency (MTBF/MTTR)", "Tooling life logs"],
                    management_insight="Establish machine-center sub-metering; replace breakdown firefighting with scheduled preventive maintenance.",
                )
            ]),
            ComponentNode(name="OPERATIONAL EFFICIENCY (OEE)", terminals=[
                TerminalDiagnostic(
                    name="Overall Equipment Effectiveness",
                    root_cause="Low availability from equipment breakdowns, speed losses from machine idling, quality defect rejection losses",
                    additional_data=["OEE calculations by production line", "Machine downtime registers", "First-pass quality yield %"],
                    management_insight="An OEE below 65-70% is a critical operational bottleneck; implement Total Productive Maintenance (TPM).",
                )
            ]),
        ],
        key_management_questions=[
            "What is our plant Overall Equipment Effectiveness (OEE) across primary production lines?",
            "What percentage of plant maintenance expenditure is proactive preventive vs reactive breakdown repairs?",
            "What is the cost per unit of production and how does it move with capacity utilization?",
        ],
        investigation_checklist=[
            "OEE dashboard tracking Availability, Performance, and Quality rates",
            "Mean Time Between Failures (MTBF) and Mean Time To Repair (MTTR) reports",
            "Plant energy audit and power sub-meter consumption analysis",
        ],
    ),

    # 33. Finance Cost (Interest & Borrowing Cost)
    MetricDiagnosticTree(
        metric_id=33,
        canonical_name="Finance Cost",
        metric_code="finance_cost",
        formula="Finance Cost = Interest on TL + Interest on WC Loans + Loan Processing Fees (amortised) + Bank Charges + Forex Loss on FCY Debt",
        category="leverage",
        components=[
            ComponentNode(name="TERM LOAN & WORKING CAPITAL INTEREST", terminals=[
                TerminalDiagnostic(
                    name="Loan Principal & Floating Interest Rates",
                    root_cause="Higher total outstanding principal from recent capex, revolving bank Cash Credit drawings, and central bank benchmark rate increases",
                    additional_data=["Loan balances by facility", "Weighted average borrowing cost", "MCLR/repo spread schedules"],
                    management_insight="Prioritize paying down high-cost short-term debt; explore interest rate swaps during rising interest cycles.",
                )
            ]),
            ComponentNode(name="BANK FEES & TRANSACTION CHARGES", terminals=[
                TerminalDiagnostic(
                    name="Financing Fees & Guarantee Costs",
                    root_cause="Upfront loan processing fees amortised under Effective Interest Rate (EIR) method, and Letter of Credit (LC) / Bank Guarantee (BG) charges",
                    additional_data=["Loan fee amortization schedules", "LC/BG commission registers"],
                    management_insight="Negotiate waiver of loan processing fees on refinancing; switch to open-account terms with established suppliers to eliminate LC fees.",
                )
            ]),
            ComponentNode(name="FOREIGN CURRENCY BORROWING LOSSES", terminals=[
                TerminalDiagnostic(
                    name="Forex Loss on Foreign Debt",
                    root_cause="Domestic currency depreciation inflating the rupee value of unhedged USD/EUR foreign borrowings",
                    additional_data=["Foreign currency loan balances", "Derivative hedge contract register", "Forex sensitivity analysis"],
                    management_insight="Unhedged foreign currency debt is speculation; maintain board-approved policy mandating 100% principal and interest hedging.",
                )
            ]),
        ],
        key_management_questions=[
            "What is our weighted average cost of debt across all bank credit facilities?",
            "What proportion of foreign currency debt is fully hedged against currency depreciation?",
            "Are bank processing fees and guarantee commissions being benchmarked and negotiated competitively?",
        ],
        investigation_checklist=[
            "Consolidated facility-wise debt register with interest rates, spreads, and fee structures",
            "Forex open exposure and derivative hedging contract valuation report",
            "Bank charge reconciliation statement including penal interest audits",
        ],
    ),

    # 34. Tax Expense
    MetricDiagnosticTree(
        metric_id=34,
        canonical_name="Tax Expense",
        metric_code="tax_expense",
        formula="Tax Expense = Current Tax + Deferred Tax | Effective Tax Rate = Tax Expense / PBT",
        category="profitability",
        components=[
            ComponentNode(name="CURRENT TAX & DISALLOWANCES", terminals=[
                TerminalDiagnostic(
                    name="Taxable Profit Adjustments",
                    root_cause="PBT statutory disallowances (penalties, CSR spend), investment tax deductions, Section 115JB Minimum Alternate Tax (MAT) rules",
                    additional_data=["Tax computation reconciliation", "Statutory disallowance register", "MAT credit entitlement balance"],
                    management_insight="Maximize legitimate tax deductions; track MAT credit carry-forwards to offset future normal tax liabilities.",
                )
            ]),
            ComponentNode(name="DEFERRED TAX (DTA / DTL)", terminals=[
                TerminalDiagnostic(
                    name="Timing Differences",
                    root_cause="Accelerated tax depreciation exceeding book depreciation (creates DTL) or disallowed provisions deductible only on actual payment (creates DTA)",
                    additional_data=["Deferred tax asset/liability movement schedule", "Reversal timeline projections"],
                    management_insight="A large Deferred Tax Liability (DTL) indicates future cash tax outflows; incorporate into multi-year treasury plans.",
                )
            ]),
            ComponentNode(name="EFFECTIVE TAX RATE (ETR) VOLATILITY", terminals=[
                TerminalDiagnostic(
                    name="ETR Divergence",
                    root_cause="Prior period tax reassessments, differential tax rates on export zones, or overseas subsidiary tax rates",
                    additional_data=["ETR reconciliation statement (Statutory to Effective rate)"],
                    management_insight="An ETR below 20% warrants scrutiny regarding tax exemption longevity; an ETR above 30% indicates missed tax deductions.",
                )
            ]),
        ],
        key_management_questions=[
            "Why is the company's Effective Tax Rate (ETR) diverging from the statutory corporate tax rate?",
            "What is the outstanding balance of MAT credits and when do they expire?",
            "Are advance tax installments estimated accurately to prevent penal interest under Sections 234B/234C?",
        ],
        investigation_checklist=[
            "Statutory corporate income tax computation and PBT reconciliation",
            "Deferred tax timing difference schedule (depreciation, gratuity, bad debts)",
            "Advance tax payment challans and Section 234 interest liability review",
        ],
    ),

    # 35. Capital Expenditure (Capex)
    MetricDiagnosticTree(
        metric_id=35,
        canonical_name="Capital Expenditure (Capex)",
        metric_code="capex",
        formula="Capex = Additions to Gross Fixed Assets + CWIP Additions | FCF = OCF - Capex",
        category="growth_returns",
        components=[
            ComponentNode(name="GROWTH & EXPANSION CAPEX", terminals=[
                TerminalDiagnostic(
                    name="Capacity & Technology Expansion",
                    root_cause="Greenfield factory construction, new manufacturing lines, R&D testing infrastructure, or geographic warehouse expansions",
                    additional_data=["Project business cases", "Project cost estimate vs actual", "Expected project IRR vs hurdle rate"],
                    management_insight="Ensure growth capex IRR comfortably exceeds WACC; lease facilities first to validate demand before purchasing real estate.",
                )
            ]),
            ComponentNode(name="MAINTENANCE CAPEX", terminals=[
                TerminalDiagnostic(
                    name="Sustenance & IT Refresh",
                    root_cause="Replacing end-of-life plant machinery to maintain operating reliability, and corporate IT server/laptop refresh cycles",
                    additional_data=["Machine age vs useful life", "Maintenance capex vs annual depreciation charge"],
                    management_insight="Maintenance capex should approximate annual depreciation; spending less suggests underlying productive assets are deteriorating.",
                )
            ]),
            ComponentNode(name="CAPEX GOVERNANCE & CWIP", terminals=[
                TerminalDiagnostic(
                    name="Project Execution & Cost Overruns",
                    root_cause="Scope creep inflating project budgets, contractor delays, aging Capital Work in Progress (CWIP), and interest during construction (IDC)",
                    additional_data=["Project-wise capex sanction vs committed spend", "CWIP ageing schedule", "Capitalized borrowing cost (IDC)"],
                    management_insight="Aging CWIP is a major red flag; conduct monthly project milestones reviews to prevent cost overruns and commissioning delays.",
                )
            ]),
        ],
        key_management_questions=[
            "What percentage of approved capital expenditure projects are experiencing time or budget overruns?",
            "Does our maintenance capex adequately match our annual depreciation rate to prevent asset degradation?",
            "What is the post-commissioning revenue and EBITDA track record of recent major capex investments?",
        ],
        investigation_checklist=[
            "Project-level capex sanction, incurred, and estimated-at-completion (EAC) report",
            "CWIP ageing analysis and commissioning timeline commitments",
            "Post-completion capital expenditure audit reports comparing actual IRR to business cases",
        ],
    ),

    # 36. Fixed Assets (Gross Block / Net Block)
    MetricDiagnosticTree(
        metric_id=36,
        canonical_name="Fixed Assets",
        metric_code="fixed_assets",
        formula="Net Fixed Assets = Gross Block - Accumulated Depreciation | Net Block = Tangible + Intangible + ROU Assets (Ind AS 116)",
        category="growth_returns",
        components=[
            ComponentNode(name="TANGIBLE FIXED ASSETS", terminals=[
                TerminalDiagnostic(
                    name="Property, Plant & Equipment (PPE)",
                    root_cause="Land and factory buildings, plant and machinery additions, vehicles, and office technology equipment",
                    additional_data=["Fixed asset register", "Net-to-gross block ratio", "Asset physical verification reports"],
                    management_insight="A net-to-gross block ratio below 40% signals an aging machine base requiring replacement capital expenditure.",
                )
            ]),
            ComponentNode(name="INTANGIBLE ASSETS & GOODWILL", terminals=[
                TerminalDiagnostic(
                    name="Intangible Capital",
                    root_cause="Acquisition goodwill premiums paid over net identifiable assets, enterprise software licenses, and acquired brand trademarks",
                    additional_data=["Intangible asset schedules", "Annual goodwill impairment assessment documentation"],
                    management_insight="Internally generated brands cannot be capitalized; test acquired goodwill annually for impairment triggers.",
                )
            ]),
            ComponentNode(name="RIGHT-OF-USE ASSETS (Ind AS 116 / IFRS 16)", terminals=[
                TerminalDiagnostic(
                    name="Lease Capitalization",
                    root_cause="Long-term factory, warehouse, and office lease agreements capitalized as ROU assets alongside lease liabilities",
                    additional_data=["Lease contracts register", "Incremental borrowing discount rate used", "Variable lease terms"],
                    management_insight="Ind AS 116 inflates gross assets and EBITDA while adding depreciation and interest; compute pre/post lease metrics.",
                )
            ]),
        ],
        key_management_questions=[
            "What is our net-to-gross block ratio, and does it indicate urgent machinery replacement requirements?",
            "Are capitalized intangible assets and goodwill supported by current Cash Generating Unit cash flows?",
            "What is the impact of Ind AS 116 lease capitalization on our reported asset base and leverage ratios?",
        ],
        investigation_checklist=[
            "Fixed asset register reconciliation with physical asset tagging audit",
            "Asset age profile and accumulated depreciation percentage by category",
            "Right-of-use asset and lease liability amortization schedules",
        ],
    ),

    # 37. Borrowings
    MetricDiagnosticTree(
        metric_id=37,
        canonical_name="Borrowings",
        metric_code="borrowings",
        formula="Total Borrowings = Long-term Borrowings + Short-term Borrowings + Current Portion of LTD",
        category="leverage",
        components=[
            ComponentNode(name="LONG-TERM DEBT FACILITIES", terminals=[
                TerminalDiagnostic(
                    name="Term Loans & Debentures",
                    root_cause="Bank term loans for capex, external commercial borrowings (ECB), and capital market debentures/bonds",
                    additional_data=["Facility sanction terms", "First charge asset security details", "Loan covenant definitions"],
                    management_insight="Avoid excessive asset collateralization that limits future financing; maintain 20-30% cushion on debt covenants.",
                )
            ]),
            ComponentNode(name="SHORT-TERM WORKING CAPITAL FACILITIES", terminals=[
                TerminalDiagnostic(
                    name="Revolving Bank Credit & Commercial Paper",
                    root_cause="Bank Cash Credit (CC) / Overdraft (OD) drawn against inventory and receivables, and short-tenor commercial paper (CP)",
                    additional_data=["Drawing power calculation statements", "CC utilization percentages", "Commercial paper maturity dates"],
                    management_insight="Maintain bank lines as backup for commercial paper; never rely wholly on volatile short-term money markets.",
                )
            ]),
            ComponentNode(name="FOREIGN CURRENCY & OFF-BALANCE DEBT", terminals=[
                TerminalDiagnostic(
                    name="Forex Debt & Contingent Liabilities",
                    root_cause="Lower foreign benchmark interest rates attracting ECB borrowings, and bank guarantees/letters of credit issued",
                    additional_data=["Foreign currency loan balances", "Hedging contract coverage", "Contingent liability register"],
                    management_insight="Ensure complete hedge cover on foreign currency loans; monitor non-fund contingent liability conversion risks.",
                )
            ]),
        ],
        key_management_questions=[
            "What is our repayment schedule over the next 12, 24, and 36 months?",
            "What assets are pledged to lenders, and what is our unencumbered asset cover?",
            "Are all financial covenants currently compliant with sufficient headroom?",
        ],
        investigation_checklist=[
            "Comprehensive debt master schedule (Lender, Facility, Limit, Outstanding, Rate, Maturity)",
            "Quarterly covenant compliance certificates submitted to banks",
            "Drawing power calculation and hypothecated asset verification statements",
        ],
    ),

    # 38. Shareholders Equity
    MetricDiagnosticTree(
        metric_id=38,
        canonical_name="Shareholders Equity",
        metric_code="shareholders_equity",
        formula="Shareholders Equity = Share Capital + Securities Premium + Retained Earnings + Other Reserves + OCI",
        category="leverage",
        components=[
            ComponentNode(name="PAID-UP SHARE CAPITAL", terminals=[
                TerminalDiagnostic(
                    name="Equity & Preference Capital",
                    root_cause="New equity issues (IPO, rights issue, QIP, preferential allotment, ESOP exercise), or redeemable preference shares",
                    additional_data=["Authorized vs paid-up share capital register", "Preference share redemption clauses"],
                    management_insight="Redeemable preference shares may be classified as financial liabilities rather than equity under Ind AS 32.",
                )
            ]),
            ComponentNode(name="RESERVES & RETAINED EARNINGS", terminals=[
                TerminalDiagnostic(
                    name="Retained Earnings & Statutory Reserves",
                    root_cause="Cumulative net profits retained over company history less dividend distributions; securities premium and capital redemption reserves",
                    additional_data=["Retained earnings movement statement", "Dividend payout history", "Securities premium utilization log"],
                    management_insight="Securities premium can only be used for legally permitted purposes under Section 52 of Companies Act; retained earnings show true compounding.",
                )
            ]),
            ComponentNode(name="OTHER COMPREHENSIVE INCOME (OCI)", terminals=[
                TerminalDiagnostic(
                    name="OCI Remeasurements",
                    root_cause="Actuarial remeasurement gains/losses on employee gratuity/pension schemes, and fair value changes in FVOCI equity investments",
                    additional_data=["Actuarial valuation assumption reports", "FVOCI equity portfolio mark-to-market statements"],
                    management_insight="Declining discount rates increase actuarial gratuity liabilities, producing OCI losses that reduce total reported equity.",
                )
            ]),
        ],
        key_management_questions=[
            "What has been our retained earnings retention ratio vs dividend distribution over the past 5 years?",
            "Are there any accumulated losses eroding the net worth base and threatening solvency covenants?",
            "What is the impact of employee gratuity actuarial remeasurements in OCI on our net worth?",
        ],
        investigation_checklist=[
            "Statement of Changes in Equity (SOCIE) detailing all reserves and surplus movements",
            "Securities premium account utilization audit under Companies Act guidelines",
            "Actuarial assumptions sensitivity analysis for employee benefit plans",
        ],
    ),

    # 39. Cash & Bank Balance
    MetricDiagnosticTree(
        metric_id=39,
        canonical_name="Cash & Bank Balance",
        metric_code="cash_and_bank",
        formula="Cash & Bank = Cash in Hand + Current Account + Savings Account + FDs (< 3M) + Liquid Mutual Funds",
        category="liquidity",
        components=[
            ComponentNode(name="OPERATIONAL CASH INFLOWS", terminals=[
                TerminalDiagnostic(
                    name="Customer Collections & Proceeds",
                    root_cause="Collections from customer invoices, bank loan disbursements, asset disposals, or equity capital injections",
                    additional_data=["Daily customer collection reports", "Collection-to-billing ratio", "Cheque bounce registers"],
                    management_insight="Customer collections are the lifeblood of liquidity; track daily collection efficiency as the primary CFO operational KPI.",
                )
            ]),
            ComponentNode(name="OPERATIONAL CASH OUTFLOWS", terminals=[
                TerminalDiagnostic(
                    name="Disbursements & Debt Service",
                    root_cause="Trade supplier payments, monthly payroll, statutory tax obligations (GST/TDS/Advance Tax), capex disbursements, and loan EMIs",
                    additional_data=["Payment run schedules", "Statutory tax payment deadlines", "Debt repayment schedule"],
                    management_insight="Maintain a strict cash payment priority waterfall: Statutory Taxes > Secured Lenders > Payroll > Critical Vendors.",
                )
            ]),
            ComponentNode(name="CASH CONCENTRATION & TREASURY SWEEPS", terminals=[
                TerminalDiagnostic(
                    name="Liquidity Optimization",
                    root_cause="Cash trapped in regional branch accounts, lack of automated corporate sweeps, idle current account balances earning 0%",
                    additional_data=["Branch account balance list", "Notional pooling structures", "Liquid fund yields"],
                    management_insight="Set up automated sweeps to liquid mutual funds or overnight deposits above a defined operational threshold to earn 6-7%.",
                )
            ]),
        ],
        key_management_questions=[
            "What is our daily collection-to-billing ratio and what are today's cleared bank balances?",
            "Do we maintain an unencumbered liquid buffer equal to at least 90 days of debt service EMIs?",
            "Is cash sitting idle in non-interest-bearing branch bank accounts that could be centralized via notional pooling?",
        ],
        investigation_checklist=[
            "Daily Treasury MIS showing bank balances across all accounts and liquid fund investments",
            "13-week rolling cash inflow and outflow forecast",
            "Bank reconciliation statements (BRS) with aging of uncleared cheques",
        ],
    ),

    # 40. Enterprise Value (EV)
    MetricDiagnosticTree(
        metric_id=40,
        canonical_name="Enterprise Value (EV)",
        metric_code="enterprise_value",
        formula="EV = Market Capitalization + Total Debt + Minority Interest + Preferred Shares - Cash & Cash Equivalents",
        category="growth_returns",
        components=[
            ComponentNode(name="MARKET CAPITALIZATION", terminals=[
                TerminalDiagnostic(
                    name="Market Valuation & Equity Price",
                    root_cause="Equity share price movements driven by market sentiment, P/E multiple expansion/compression, fundamental EPS growth, and share count dilution",
                    additional_data=["Daily share price history", "P/E and EV/EBITDA peer comps", "Promoter share pledge %"],
                    management_insight="Excessive promoter share pledging creates forced-liquidation risks; improve cash earnings quality to command premium multiples.",
                )
            ]),
            ComponentNode(name="NET DEBT & CONTINGENT LIABILITIES", terminals=[
                TerminalDiagnostic(
                    name="Net Debt Adjustment",
                    root_cause="Total funded borrowings less cash reserves; off-balance sheet contingent liabilities and discounted customer bills",
                    additional_data=["Net debt calculation worksheet", "Contingent liability schedule"],
                    management_insight="Sophisticated acquirers adjust EV for unrecorded contingent liabilities; maintain a cash-rich net debt negative balance sheet.",
                )
            ]),
            ComponentNode(name="MINORITY INTEREST & VALUATION MULTIPLES", terminals=[
                TerminalDiagnostic(
                    name="Multiples & Subsidiary Stakes",
                    root_cause="Third-party equity ownership in consolidated subsidiaries, EV/EBITDA sector multiples, and EV/Revenue metrics for pre-profit units",
                    additional_data=["Subsidiary minority equity %", "Sector median EV/EBITDA multiples", "Revenue growth CAGRs"],
                    management_insight="An EV/EBITDA multiple above 15x requires sustained high ROIC and top-quartile earnings growth to be justified.",
                )
            ]),
        ],
        key_management_questions=[
            "What is our current EV/EBITDA multiple compared to publicly traded sector peers?",
            "How much of our Enterprise Value is composed of net debt vs market equity value?",
            "Are there contingent liabilities or off-balance sheet commitments that would impair enterprise valuation in an M&A context?",
        ],
        investigation_checklist=[
            "Comprehensive Enterprise Value bridge (Market Cap + Debt - Cash + Minority Interest)",
            "Peer valuation multiple benchmarking (P/E, EV/EBITDA, EV/Sales)",
            "Promoter shareholding pattern and share pledge disclosure registers",
        ],
    ),
]

_TREES_BY_ID: dict[int, MetricDiagnosticTree] = {t.metric_id: t for t in TREES}
_TREES_BY_CODE: dict[str, MetricDiagnosticTree] = {t.metric_code: t for t in TREES}

# Alias resolution mapping common terms and acronyms to metric IDs (1-40)
_ALIAS_MAP: dict[str, int] = {
    # 1. Revenue Growth
    "revenue_growth": 1, "revenue_growth_yoy": 1, "topline_growth": 1, "sales_growth": 1, "revenue growth": 1,
    # 2. Gross Profit Margin
    "gross_profit_pct": 2, "gross_margin": 2, "gross_profit": 2, "gross profit margin": 2, "gpm": 2,
    # 3. EBITDA Margin
    "ebitda_margin": 3, "ebitda": 3, "ebitda margin": 3, "operating_profitability": 3,
    # 4. Operating Margin (EBIT Margin)
    "operating_margin": 4, "ebit_margin": 4, "ebit": 4, "operating margin": 4, "ebit margin": 4,
    # 5. Net Profit Margin
    "net_profit_margin": 5, "pat_margin": 5, "pat": 5, "net_margin": 5, "net profit margin": 5, "npm": 5,
    # 6. Return on Equity (ROE)
    "roe": 6, "return on equity": 6, "dupont": 6, "return_on_equity": 6,
    # 7. Return on Capital Employed (ROCE)
    "roce": 7, "return on capital employed": 7, "return_on_capital_employed": 7,
    # 8. Return on Assets (ROA)
    "roa": 8, "return on assets": 8, "return_on_assets": 8,
    # 9. Current Ratio
    "current_ratio": 9, "current ratio": 9, "cr": 9,
    # 10. Quick Ratio (Acid Test Ratio)
    "quick_ratio": 10, "quick ratio": 10, "acid_test": 10, "acid test": 10,
    # 11. Cash Ratio
    "cash_ratio": 11, "cash ratio": 11,
    # 12. Debt / Equity Ratio
    "debt_to_equity": 12, "de_ratio": 12, "debt to equity": 12, "d/e": 12, "gearing": 12, "leverage": 12,
    # 13. Interest Coverage Ratio (ICR)
    "interest_coverage": 13, "icr": 13, "interest coverage": 13, "interest coverage ratio": 13,
    # 14. Debt Service Coverage Ratio (DSCR)
    "dscr": 14, "debt service coverage": 14, "debt service coverage ratio": 14,
    # 15. Asset Turnover
    "asset_turnover": 15, "asset turnover": 15,
    # 16. Inventory Turnover & Inventory Days
    "inventory_turnover": 16, "dio": 16, "inventory_days": 16, "inventory days": 16, "inventory turnover": 16,
    # 17. Receivable Turnover / Debtor Days
    "receivable_turnover": 17, "dso": 17, "debtor_days": 17, "debtor days": 17, "receivable turnover": 17,
    # 18. Payable Turnover / Creditor Days
    "payable_turnover": 18, "dpo": 18, "creditor_days": 18, "creditor days": 18, "payable turnover": 18,
    # 19. Cash Conversion Cycle (CCC)
    "cash_conversion_cycle": 19, "ccc": 19, "cash conversion cycle": 19, "working capital cycle": 19,
    # 20. Operating Cash Flow (OCF)
    "operating_cash_flow": 20, "ocf": 20, "ocf_to_pat": 20, "operating cash flow": 20,
    # 21. Free Cash Flow (FCF)
    "free_cash_flow": 21, "fcf": 21, "free cash flow": 21,
    # 22. Working Capital
    "working_capital": 22, "nwc": 22, "net working capital": 22, "working capital": 22,
    # 23. Inventory
    "inventory": 23, "stock": 23, "raw materials": 23, "wip": 23, "finished goods": 23,
    # 24. Trade Receivables
    "trade_receivables": 24, "ar": 24, "accounts receivable": 24, "debtors": 24, "receivables": 24,
    # 25. Trade Payables
    "trade_payables": 25, "ap": 25, "accounts payable": 25, "creditors": 25, "payables": 25,
    # 26. Revenue from Operations
    "revenue_from_operations": 26, "revenue": 26, "sales": 26, "turnover": 26,
    # 27. Cost of Goods Sold (COGS)
    "cogs": 27, "cost of goods sold": 27, "cost of sales": 27,
    # 28. Employee Cost
    "employee_cost": 28, "payroll": 28, "salaries": 28, "staff cost": 28, "employee expense": 28,
    # 29. Selling & Marketing Expense
    "sm_expense": 29, "selling and marketing": 29, "marketing expense": 29, "advertising": 29, "sales force": 29,
    # 30. Administrative Expense
    "admin_expense": 30, "administrative expense": 30, "ga_expense": 30, "office rent": 30, "overhead": 30,
    # 31. Technology Expense
    "tech_expense": 31, "technology expense": 31, "it_cost": 31, "cloud cost": 31, "software licenses": 31,
    # 32. Manufacturing Cost
    "mfg_cost": 32, "manufacturing cost": 32, "factory overheads": 32, "oee": 32,
    # 33. Finance Cost
    "finance_cost": 33, "borrowing cost": 33, "interest expense": 33, "finance charge": 33,
    # 34. Tax Expense
    "tax_expense": 34, "taxation": 34, "income tax": 34, "etr": 34, "mat": 34,
    # 35. Capital Expenditure (Capex)
    "capex": 35, "capital expenditure": 35, "cwip": 35,
    # 36. Fixed Assets
    "fixed_assets": 36, "gross block": 36, "net block": 36, "goodwill": 36, "rou assets": 36,
    # 37. Borrowings
    "borrowings": 37, "total debt": 37, "term loans": 37, "credit lines": 37, "debt": 37,
    # 38. Shareholders Equity
    "shareholders_equity": 38, "equity": 38, "net worth": 38, "retained earnings": 38,
    # 39. Cash & Bank Balance
    "cash_and_bank": 39, "cash balance": 39, "bank balance": 39, "liquidity reserves": 39, "cash": 39,
    # 40. Enterprise Value (EV)
    "enterprise_value": 40, "ev": 40, "market cap": 40, "valuation": 40,
}


def resolve_metric_tree(query_or_key: str | int) -> MetricDiagnosticTree | None:
    """Finds the authoritative diagnostic tree by integer ID (1-40), metric code, or natural query."""
    if isinstance(query_or_key, int):
        return _TREES_BY_ID.get(query_or_key)

    raw_q = str(query_or_key).strip().lower()

    # Direct ID match
    if raw_q.isdigit():
        return _TREES_BY_ID.get(int(raw_q))

    # Exact raw alias or code match
    if raw_q in _ALIAS_MAP:
        return _TREES_BY_ID.get(_ALIAS_MAP[raw_q])
    if raw_q in _TREES_BY_CODE:
        return _TREES_BY_CODE[raw_q]

    # Normalized comparison (spaces instead of punctuation)
    q_norm = re.sub(r"[^a-z0-9\s/]", " ", raw_q)
    q_norm = re.sub(r"\s+", " ", q_norm).strip()

    # Sort aliases by length descending so specific phrases match before short acronyms
    for alias, mid in sorted(_ALIAS_MAP.items(), key=lambda x: len(x[0]), reverse=True):
        alias_norm = alias.replace("_", " ").replace("-", " ")
        if len(alias_norm) <= 4:
            pattern = r"\b" + re.escape(alias_norm) + r"\b"
            if re.search(pattern, q_norm):
                return _TREES_BY_ID.get(mid)
        else:
            if alias_norm in q_norm:
                return _TREES_BY_ID.get(mid)

    # Search canonical names
    for tree in sorted(TREES, key=lambda t: len(t.canonical_name), reverse=True):
        t_name = tree.canonical_name.lower().replace("_", " ").replace("-", " ")
        if t_name in q_norm:
            return tree

    return None


def get_all_diagnostic_trees() -> list[MetricDiagnosticTree]:
    """Returns the complete list of 40 diagnostic trees."""
    return list(TREES)


def get_diagnostic_summary_for_category(category_key: str) -> list[dict[str, Any]]:
    """Returns summarized diagnostic context for all metrics belonging to a report category."""
    out = []
    for tree in TREES:
        if tree.category == category_key:
            out.append({
                "metric_id": tree.metric_id,
                "canonical_name": tree.canonical_name,
                "metric_code": tree.metric_code,
                "formula": tree.formula,
                "components": [c.name for c in tree.components],
                "sample_questions": tree.key_management_questions[:2],
                "sample_investigation": tree.investigation_checklist[:2],
            })
    return out


def build_cfo_diagnostic_trace(
    metric_key: str | int,
    direction: str = "decline",
    context_notes: list[str] | None = None,
) -> dict[str, Any]:
    """Builds an exhaustive 6-level reverse-flow diagnostic response answering:
    1. What changed?
    2. Why did it change?
    3. What caused it?
    4. What to investigate?
    5. What to ask management?
    """
    tree = resolve_metric_tree(metric_key)
    if not tree:
        return {
            "found": False,
            "query": str(metric_key),
            "message": "Metric not found in the 40-metric Virtual CFO Compendium.",
        }

    # Extract all terminal nodes across components, sub-components, and drivers
    root_causes: list[dict[str, Any]] = []
    investigations: set[str] = set(tree.investigation_checklist)
    management_insights: list[str] = []

    for comp in tree.components:
        for t in comp.terminals:
            root_causes.append({"component": comp.name, "name": t.name, "root_cause": t.root_cause})
            investigations.update(t.additional_data)
            management_insights.append(t.management_insight)

        for sub in comp.sub_components:
            for t in sub.terminals:
                root_causes.append({"component": f"{comp.name} > {sub.name}", "name": t.name, "root_cause": t.root_cause})
                investigations.update(t.additional_data)
                management_insights.append(t.management_insight)

            for drv in sub.drivers:
                for t in drv.terminals:
                    root_causes.append({"component": f"{comp.name} > {sub.name} > {drv.name}", "name": t.name, "root_cause": t.root_cause})
                    investigations.update(t.additional_data)
                    management_insights.append(t.management_insight)

    what_changed_summary = (
        f"{tree.canonical_name} exhibited a notable {direction}. "
        f"Under governing formula: {tree.formula}."
    )

    why_did_it_change = [comp.name for comp in tree.components]

    return {
        "found": True,
        "metric_id": tree.metric_id,
        "canonical_name": tree.canonical_name,
        "metric_code": tree.metric_code,
        "formula": tree.formula,
        "direction": direction,
        "what_changed": what_changed_summary,
        "why_did_it_change": why_did_it_change,
        "what_caused_it": root_causes,
        "what_to_investigate": sorted(list(investigations)),
        "what_to_ask_management": tree.key_management_questions,
        "management_insights": management_insights,
    }


def format_diagnostic_trace_markdown(trace: dict[str, Any]) -> str:
    """Formats a diagnostic trace into structured Markdown matching the 6-step Virtual CFO drill-down."""
    if not trace.get("found"):
        return trace.get("message", "No diagnostic available.")

    md = []
    md.append(f"### Virtual CFO Diagnostic Analysis: {trace['canonical_name']}")
    md.append(f"**Mathematical Formula**: `{trace['formula']}`\n")

    md.append("#### 1. What Changed?")
    md.append(f"{trace['what_changed']}\n")

    md.append("#### 2. Why Did It Change? (Governing Components)")
    for comp in trace["why_did_it_change"]:
        md.append(f"- **{comp}**")
    md.append("")

    md.append("#### 3. What Caused It? (Root-Cause Drill-Down)")
    for rc in trace["what_caused_it"][:6]:
        md.append(f"- **{rc['name']}** (*{rc['component']}*): {rc['root_cause']}")
    md.append("")

    md.append("#### 4. What to Investigate (Required Operational & Accounting Data)")
    for inv in trace["what_to_investigate"][:6]:
        md.append(f"- [ ] {inv}")
    md.append("")

    md.append("#### 5. What to Ask Management (High-Impact CFO Action Points)")
    for q in trace["what_to_ask_management"]:
        md.append(f"- ❓ {q}")
    md.append("")

    return "\n".join(md)
