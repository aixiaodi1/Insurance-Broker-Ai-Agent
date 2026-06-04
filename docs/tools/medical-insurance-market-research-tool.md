# Medical Insurance Market Research Tool

## Purpose

Run a repeatable public-evidence workflow for identifying high-coverage, high-visibility commercial medical insurance products and producing a market research deck.

This tool is for B-side product research. It is not a C-side purchase recommendation workflow.

## Inputs

- `market_scope`: default `中国个人商业百万医疗/互联网医疗险`
- `ranking_goal`: default `公开证据下的热销代理排序`
- `top_n`: default `5`
- `as_of_date`: research date
- `source_policy`: official sources first, reputable business media second, third-party rankings only as weak signals

## Ranking Proxy

Public sources rarely disclose exact single-product sales. The tool therefore uses proxy evidence:

- Public user scale or cumulative served users
- Platform or channel reach
- Recent official product upgrade and continued sale signal
- Official material or insurer/platform page availability
- Evidence strength and reproducibility

The output must label the result as a proxy ranking, not an exact sales leaderboard.

## Workflow

1. Define scope and exclusions.
   - Include personal commercial medical insurance and internet medical insurance.
   - Exclude basic medical insurance and city-customized Huiminbao unless explicitly requested.

2. Collect candidate products.
   - Search official insurer/platform pages.
   - Search official or reputable business-media product announcements.
   - Query local evidence registry when the product is in `insurance_harness`.

3. Score candidates.
   - S1: official product terms or product page.
   - S2: official insurer/platform announcement.
   - S3: reputable business media.
   - S5: third-party ranking or commentary.

4. Select Top N.
   - Prefer products with explicit public user scale.
   - Break ties with platform reach, recent upgrade signal, and official evidence availability.

5. Produce report.
   - Explain why each product is included.
   - Include evidence tier and source links.
   - State limitations and avoid purchase advice.

6. Produce deck.
   - Include methodology, Top N matrix, one slide per product, and source appendix.

## Guardrails

- Do not claim exact sales rank unless exact sales data is cited.
- Do not say a product is "best to buy".
- Do not recommend purchase.
- Do not use third-party commentary as official evidence.
- Always include the scope and limitations on the first or second slide.
