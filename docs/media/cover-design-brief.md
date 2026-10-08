# Cover Image Design Brief

## Specifications
- **File**: `docs/media/cover.png`
- **Dimensions**: 1280 × 720 px (16:9)
- **Format**: PNG, ≥ 96 dpi

## Layout
```
┌─────────────────────────────────────────────────────────────────┐
│  [LEFT PANEL — 40%]          [RIGHT PANEL — 60%]                │
│                                                                   │
│  FinSight                    ┌──────────────────────────────┐    │
│  ──────────────              │  Executive Report Preview    │    │
│  Multi-Agent Financial       │  (screenshot / mockup)       │    │
│  Analysis Platform           │                              │    │
│                              │  KPI Grid + trend chart      │    │
│  • 13 specialised agents     └──────────────────────────────┘    │
│  • Virtual CFO Q&A           ┌─────────┐  ┌─────────────────┐   │
│  • Power BI export           │ Upload  │  │ Virtual CFO     │   │
│  • 40-metric diagnostics     │ UI shot │  │ Chat screenshot │   │
│                              └─────────┘  └─────────────────┘   │
│  [IBM Bob badge]                                                  │
│  [Apache 2.0 badge]                                              │
└─────────────────────────────────────────────────────────────────┘
```

## Colours
- Background: `#0f0f1a` (near-black, professional)
- Accent: `#3b82f6` (blue — matches app accent)
- Text: `#f8fafc` (off-white)
- Card backgrounds: `#1e1e2e` (dark card)

## Typography
- Title "FinSight": 48px bold, `Segoe UI` or `Inter`
- Tagline: 18px regular
- Bullet points: 14px regular

## Tools (suggested)
- Figma (free)
- Canva (use "Presentation 16:9" template)
- Adobe Express

## Screenshots to capture
1. Document upload interface (`http://localhost:8080` — upload panel)
2. Live agent execution trace (pipeline running, showing stage badges)
3. Executive report (rendered HTML — KPI section + first chart)
4. Virtual CFO chat (example Q&A with diagnostic response)

## Notes
- Do NOT include actual client financial data in screenshots
- Use the `seed/data/` demo files so all numbers are synthetic sample data
- Export final PNG at 1280×720 minimum; 2560×1440 (2x) preferred for retina displays
